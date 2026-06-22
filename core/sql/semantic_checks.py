"""Deterministic semantic checks for generated SQL.

These run *after* the specialist produces SQL and *before* execution. Unlike the
prompt (which only nudges the model), these are deterministic, dialect-aware AST
checks — so the same input always yields the same verdict and each check is unit
testable.

Two structural bugs are covered today:

- FAN_OUT (#3): aggregating across a flat join of two+ base tables inflates the
  result (a row on the "one" side is summed once per matching "many" row). The
  fix is to pre-aggregate each table in its own CTE/subquery, then combine.

- DEGENERATE_GROUP_COUNT (#4): "how many entities satisfy <aggregate
  threshold>" written as ``COUNT(DISTINCT key) ... GROUP BY key HAVING <agg>``
  returns one meaningless row (value 1) per group instead of a useful result.
  We rewrite the projection to ``key, <the HAVING aggregate>`` so the row count
  is correct and the formatter receives meaningful per-entity numbers.

Design: precision over recall. Auto-rewrite/repair only when confident; warn
otherwise so a legitimate query is never broken. Everything is schema-agnostic
(no table/column names hardcoded) — it works on any tenant's schema.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import sqlglot
from sqlglot import exp

from core.logging_utils import log_event


# Severities drive what the caller does with a finding.
REPAIR = "repair"  # high confidence: rewrite or retry before executing
WARN = "warn"  # low confidence: execute but flag possible distortion


@dataclass
class Finding:
    code: str
    severity: str
    message: str
    # Schema-agnostic hint fed back to the specialist on a repair retry.
    fix_hint: str = ""
    # Deterministic rewrite, when the fix is mechanical (preferred over retry).
    rewritten_sql: Optional[str] = None


def _dialect_for(connection_type: Optional[str]) -> Optional[str]:
    """Map a connection type to a sqlglot dialect (None = generic)."""
    t = (connection_type or "").lower()
    if "bigquery" in t:
        return "bigquery"
    if "postgres" in t:
        return "postgres"
    if "mysql" in t:
        return "mysql"
    if "snowflake" in t:
        return "snowflake"
    if "redshift" in t:
        return "redshift"
    if "databricks" in t or "spark" in t:
        return "databricks"
    return None


def _base_tables(select: exp.Select) -> List[exp.Table]:
    """Tables referenced directly in this SELECT's own scope (FROM/JOINs),
    excluding tables that live inside nested subqueries — those belong to a
    different scope. Robust to FROM/JOIN arg quirks across sqlglot versions: a
    table belongs to this scope iff its nearest enclosing SELECT is this one."""
    return [
        tbl
        for tbl in select.find_all(exp.Table)
        if tbl.find_ancestor(exp.Select) is select
    ]


def _norm(identifier: str) -> str:
    """Bare column/table name without qualifier or quoting."""
    return identifier.split(".")[-1].strip('`"[] ')


def _check_degenerate_group_count(select: exp.Select) -> Optional[Finding]:
    """#4 — ``COUNT(DISTINCT key) ... GROUP BY key HAVING <agg>``.

    The projection counts distinct values of the grouping key *within* each
    group, which is always 1. Rewrite the projection to the grouping key plus
    the aggregate used in the HAVING, so the result is meaningful per entity.
    """
    group = select.args.get("group")
    having = select.args.get("having")
    if not group or not having:
        return None

    group_keys = {_norm(g.sql()) for g in group.expressions}
    if not group_keys:
        return None

    # The single projection must be a COUNT over one of the grouping keys.
    projections = [p for p in select.expressions]
    if len(projections) != 1:
        return None
    count_node = projections[0].find(exp.Count)
    if not count_node or not count_node.this:
        return None
    counted = _norm(count_node.this.sql().replace("DISTINCT ", ""))
    if counted not in group_keys:
        return None  # counting something other than the key — not degenerate

    # Reuse the aggregate the model already wrote in HAVING as the real metric.
    having_agg = having.find(exp.AggFunc)
    if not having_agg:
        return None

    # Build: SELECT <group keys...>, <having agg> AS metric  (keep FROM/JOIN/
    # WHERE/GROUP BY/HAVING/ORDER untouched).
    new_select = select.copy()
    metric = having_agg.copy()
    metric_alias = exp.alias_(metric, "metric")
    new_projection = [g.copy() for g in group.expressions] + [metric_alias]
    new_select.set("expressions", new_projection)

    return Finding(
        code="DEGENERATE_GROUP_COUNT",
        severity=REPAIR,
        message=(
            "Projection counts the grouping key itself (always 1 per group); "
            "rewritten to return the key and the HAVING aggregate."
        ),
        rewritten_sql=new_select.sql(dialect=select.meta.get("dialect")),
        fix_hint=(
            "Do NOT count the grouping key itself — that is always 1 per group. "
            "To answer 'how many entities satisfy <aggregate condition>', either "
            "return each entity with its aggregate, or wrap the grouped query: "
            "SELECT COUNT(*) FROM (SELECT key FROM ... GROUP BY key HAVING ...)."
        ),
    )


def _check_aggregate_fanout(select: exp.Select) -> Optional[Finding]:
    """#3 — aggregating across a flat join of two+ base tables.

    High confidence (REPAIR): aggregates reference columns from two or more
    distinct base tables in the same scope — summing across the join product
    almost always inflates the totals.

    Low confidence (WARN): two+ base tables are joined and aggregated, but every
    aggregate reads from a single table. It may still fan out on a 1:N join, but
    without key/cardinality metadata we only warn so a 1:1 join is not "fixed"
    into a wrong answer.
    """
    base = _base_tables(select)
    # Distinct base-table names actually joined in this scope.
    table_aliases = {(_norm(t.alias_or_name)) for t in base if t.alias_or_name}
    if len(table_aliases) < 2:
        return None

    # Only the aggregates this SELECT *projects* matter for fan-out — not those
    # inside HAVING (a filter) or inside CTE/subquery scopes (already grouped).
    proj_aggs = [
        a
        for proj in select.expressions
        for a in proj.find_all(exp.AggFunc)
        if a.find_ancestor(exp.Select) is select
    ]
    if not proj_aggs:
        return None

    # Which base tables do the aggregated columns come from?
    agg_table_quals = set()
    for a in proj_aggs:
        for col in a.find_all(exp.Column):
            if col.table:
                agg_table_quals.add(_norm(col.table))

    schema_agnostic_hint = (
        "Avoid aggregating (SUM/AVG/COUNT) directly over a flat JOIN of tables "
        "at different granularities — it multiplies rows and inflates totals. "
        "Pre-aggregate EACH table in its own CTE first, then combine. Use this "
        "schema-agnostic structure (replace placeholders with the real names):\n"
        "  -- a global ratio across two tables:\n"
        "  WITH a AS (SELECT <AGG>(<col_a>) AS m1 FROM <table_a> [WHERE ...]),\n"
        "       b AS (SELECT <AGG>(<col_b>) AS m2 FROM <table_b> [WHERE ...])\n"
        "  SELECT a.m1 / b.m2 FROM a, b\n"
        "  -- a per-entity metric: add GROUP BY <key> in each CTE and JOIN on it.\n"
        "Never put aggregates of two different base tables in the same SELECT "
        "over a JOIN."
    )

    if len(agg_table_quals) >= 2:
        return Finding(
            code="AGGREGATE_FANOUT",
            severity=REPAIR,
            message=(
                "Aggregates read from multiple joined base tables in one scope; "
                "the join multiplies rows and inflates the result."
            ),
            fix_hint=schema_agnostic_hint,
        )

    # Single-table aggregates grouped by a key (e.g. group by the "one" side,
    # sum the "many" side) are the *correct* 1:N pattern — do not warn. Only a
    # flat aggregate (no GROUP BY) over a multi-table join is suspect.
    if select.args.get("group"):
        return None

    return Finding(
        code="AGGREGATE_FANOUT_POSSIBLE",
        severity=WARN,
        message=(
            "Aggregation over a multi-table join; if the relationship is 1:N "
            "the totals may be inflated by row fan-out."
        ),
        fix_hint=schema_agnostic_hint,
    )


def analyze_sql(sql: str, connection_type: Optional[str] = None) -> List[Finding]:
    """Run all semantic checks on a SQL string. Returns a list of findings
    (possibly empty). Never raises: a parse failure yields no findings so the
    normal validators still apply."""
    if not sql or not sql.strip():
        return []
    dialect = _dialect_for(connection_type)
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception as exc:
        log_event("semantic_check_parse_error", {"error": str(exc)[:160]})
        return []

    findings: List[Finding] = []
    # Check every SELECT scope (top-level and nested) so issues inside a
    # subquery are caught too.
    for select in tree.find_all(exp.Select):
        select.meta["dialect"] = dialect
        for check in (_check_degenerate_group_count, _check_aggregate_fanout):
            try:
                f = check(select)
            except Exception as exc:
                log_event(
                    "semantic_check_error",
                    {"check": check.__name__, "error": str(exc)[:160]},
                )
                f = None
            if f:
                findings.append(f)
    return findings
