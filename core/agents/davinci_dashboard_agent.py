from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.logging_utils import log_event


@dataclass
class DavinciDashboardPlan:
    dashboard_name: str
    description: Optional[str]
    widgets: List[Dict[str, Any]]
    meta: Dict[str, Any]


def _parse_schema_summary(schema_summary: str) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """
    Parse the schema summary produced by `connection_query.dashboards_plan`.

    Expected line format:
      - <logical_table> cols: a, b, c keys: k1, k2
    """
    table_cols: dict[str, list[str]] = {}
    table_keys: dict[str, list[str]] = {}
    for raw in (schema_summary or "").splitlines():
        line = raw.strip()
        if not line.startswith("- "):
            continue
        # "- table cols: ... keys: ..."
        try:
            line = line[2:]
            table = line.split(" cols:", 1)[0].strip()
            rest = line.split(" cols:", 1)[1] if " cols:" in line else ""
            cols_part = rest
            keys_part = ""
            if " keys:" in rest:
                cols_part, keys_part = rest.split(" keys:", 1)
            cols = [c.strip() for c in (cols_part or "").split(",") if c.strip()]
            keys = [k.strip() for k in (keys_part or "").split(",") if k.strip()]
            if table:
                table_cols[table] = cols
                table_keys[table] = keys
        except Exception:
            continue
    return table_cols, table_keys


def _count_tables_mentioned(question: str, logical_tables: list[str]) -> int:
    q = (question or "").lower()
    mentioned: set[str] = set()
    for t in logical_tables:
        tl = (t or "").lower()
        if not tl:
            continue
        # Prefer explicit backtick mentions, but allow plain fallback.
        if f"`{tl}`" in q or tl in q:
            mentioned.add(tl)
    return len(mentioned)


def _pick_join_pairs(table_keys: dict[str, list[str]], logical_tables: list[str]) -> list[tuple[str, str, str]]:
    """
    Pick join pairs based on overlapping key-like columns.
    Returns list of (A, B, key).
    """
    pairs: list[tuple[str, str, str]] = []
    keys_norm: dict[str, set[str]] = {
        t: {k.lower() for k in (table_keys.get(t) or []) if k} for t in logical_tables
    }

    # Prefer overlaps that look like foreign keys.
    def score_key(k: str) -> int:
        if k.endswith("_id") and k != "id":
            return 3
        if "id" in k and k != "id":
            return 2
        return 1

    for i, a in enumerate(logical_tables):
        for b in logical_tables[i + 1 :]:
            overlap = keys_norm.get(a, set()) & keys_norm.get(b, set())
            if not overlap:
                continue
            # Choose best key from overlap.
            best = sorted(overlap, key=lambda k: (-score_key(k), k))[0]
            pairs.append((a, b, best))

    # Deterministic ordering: prefer stronger keys then stable names
    pairs = sorted(pairs, key=lambda p: (-score_key(p[2]), p[0].lower(), p[1].lower(), p[2]))
    return pairs


def _is_fact_table(name: str) -> bool:
    n = (name or "").lower()
    pats = (
        "invoice",
        "order",
        "payment",
        "transaction",
        "event",
        "session",
        "line_item",
        "fact_",
        "billing",
        "refund",
        "shipment",
    )
    return any(p in n for p in pats)


def _is_dim_table(name: str) -> bool:
    n = (name or "").lower()
    pats = (
        "customer",
        "client",
        "user",
        "account",
        "product",
        "vendor",
        "merchant",
        "category",
        "country",
        "region",
        "dim_",
    )
    return any(p in n for p in pats)


def _pick_fact_dim_pairs(
    table_keys: dict[str, list[str]], logical_tables: list[str]
) -> list[tuple[str, str, str]]:
    """
    Choose join pairs where one table is likely a fact and the other a dimension.
    Returns list of (fact, dim, key).
    """
    pairs = _pick_join_pairs(table_keys, logical_tables)
    out: list[tuple[str, str, str]] = []
    for a, b, k in pairs:
        if _is_fact_table(a) and _is_dim_table(b):
            out.append((a, b, k))
        elif _is_fact_table(b) and _is_dim_table(a):
            out.append((b, a, k))
    return out


def _choose_metric_col(cols: list[str]) -> str | None:
    pats = ("amount", "total", "value", "revenue", "price", "cost", "qty", "quantity", "balance", "paid")
    for p in pats:
        hit = next((c for c in cols if p in c.lower()), None)
        if hit:
            return hit
    return None


def _choose_dim_col(cols: list[str]) -> str | None:
    pats = ("name", "category", "type", "status", "method", "segment", "reason", "country", "region")
    for p in pats:
        hit = next((c for c in cols if p in c.lower()), None)
        if hit:
            return hit
    return None


def _choose_date_col(cols: list[str]) -> str | None:
    pats = ("date", "time", "created", "updated", "month", "day")
    for p in pats:
        hit = next((c for c in cols if p in c.lower()), None)
        if hit:
            return hit
    return None


def _enforce_join_mix(
    widgets: list[dict[str, Any]],
    *,
    logical_tables: list[str],
    table_cols: dict[str, list[str]],
    table_keys: dict[str, list[str]],
    max_widgets: int,
) -> list[dict[str, Any]]:
    """
    Ensure at least a minimum number of widgets are explicitly cross-table (JOIN) questions.
    We detect cross-table by number of logical tables mentioned in the question text.
    If insufficient, we rewrite some chart widgets into join-based questions.
    """
    if not widgets or not logical_tables:
        return widgets

    # For N=8, we want a strong cross-table dashboard.
    min_join = min(5, max_widgets)

    join_pairs = _pick_join_pairs(table_keys, logical_tables)
    if not join_pairs:
        return widgets

    def is_join_widget(w: dict[str, Any]) -> bool:
        q = str(w.get("question") or "")
        return _count_tables_mentioned(q, logical_tables) >= 2

    current_join = sum(1 for w in widgets if is_join_widget(w))
    if current_join >= min_join:
        return widgets

    # Prefer rewriting chart widgets first.
    rewrite_idxs = [i for i, w in enumerate(widgets) if str(w.get("type") or "") == "chart"]
    # If still not enough, allow rewriting KPI widgets too.
    if len(rewrite_idxs) < (min_join - current_join):
        rewrite_idxs += [i for i, w in enumerate(widgets) if str(w.get("type") or "") == "kpi"]

    needed = min_join - current_join
    rewrite_idxs = rewrite_idxs[:needed]

    # Create deterministic join templates.
    for n, idx in enumerate(rewrite_idxs):
        a, b, key = join_pairs[n % len(join_pairs)]
        a_cols = table_cols.get(a, [])
        b_cols = table_cols.get(b, [])
        metric = _choose_metric_col(a_cols) or _choose_metric_col(b_cols)
        dim = _choose_dim_col(b_cols) or _choose_dim_col(a_cols)
        dt = _choose_date_col(a_cols) or _choose_date_col(b_cols)

        # Pick a viz type to diversify.
        viz_type = ["bar", "line", "pie", "area", "scatter"][n % 5]

        if viz_type in {"line", "area"} and dt:
            question = (
                f"Using `{a}` JOIN `{b}` on `{key}`, show a monthly trend of "
                f"{('total ' + metric) if metric else 'count of records'} by `{dt}`. "
                "Return a table with two columns: period and value."
            )
            viz = {"type": viz_type, "mapping": {"x": "period", "y": "value"}}
        elif viz_type == "pie" and dim:
            question = (
                f"Using `{a}` JOIN `{b}` on `{key}`, show the distribution of `{dim}` "
                f"by {('total ' + metric) if metric else 'count of records'} (top 8 + other). "
                "Return columns: category and value."
            )
            viz = {"type": "pie", "mapping": {"x": "category", "y": "value"}}
        elif viz_type == "scatter" and metric and dim:
            question = (
                f"Using `{a}` JOIN `{b}` on `{key}`, build a scatter plot of `{metric}` versus `{dim}` "
                "(use numeric dimension if applicable; otherwise pick a suitable numeric column). "
                "Return columns: x, y, and category."
            )
            viz = {"type": "scatter", "mapping": {"x": "x", "y": "y"}}
        else:
            # Default: bar/column style.
            question = (
                f"Using `{a}` JOIN `{b}` on `{key}`, show the top 10 `{dim or b}` by "
                f"{('total ' + metric) if metric else 'count of records'}. "
                "Return columns: category and value."
            )
            viz = {"type": "bar", "mapping": {"x": "category", "y": "value"}}

        widgets[idx] = {
            **widgets[idx],
            "type": "chart",
            "title": widgets[idx].get("title") or f"Cross-table insight {idx+1}",
            "question": question,
            "viz": viz,
        }

    return widgets


def _enforce_distribution_and_fact_dim(
    widgets: list[dict[str, Any]],
    *,
    logical_tables: list[str],
    table_cols: dict[str, list[str]],
    table_keys: dict[str, list[str]],
    max_widgets: int,
) -> list[dict[str, Any]]:
    """
    For the auto "super dashboard" (N=8), enforce:
      - 2 KPI
      - 1 Table
      - 5 Chart
      - >= 3 fact+dimension JOIN widgets (questions explicitly mention 2+ tables)
    """
    if not widgets or not logical_tables:
        return widgets

    # Only enforce strongly for larger dashboards.
    if max_widgets < 6:
        return widgets

    target_kpi = 2 if max_widgets >= 8 else 1
    target_table = 1
    target_chart = max_widgets - target_kpi - target_table

    def wtype(w: dict[str, Any]) -> str:
        return str(w.get("type") or "chart")

    join_pairs = _pick_join_pairs(table_keys, logical_tables)
    fact_dim_pairs = _pick_fact_dim_pairs(table_keys, logical_tables)

    def _rewrite_as_table(i: int, pair: tuple[str, str, str] | None) -> None:
        if pair:
            fact, dim, key = pair
            dim_cols = table_cols.get(dim, [])
            label = _choose_dim_col(dim_cols) or "name"
            question = (
                f"Using `{fact}` JOIN `{dim}` on `{key}`, show the latest 15 records with key fields and `{label}`. "
                "Return a table with <= 15 rows."
            )
            widgets[i] = {
                **widgets[i],
                "type": "table",
                "title": widgets[i].get("title") or "Joined detail view",
                "question": question,
                "viz": {"type": "table"},
            }
        else:
            t = logical_tables[0]
            widgets[i] = {
                **widgets[i],
                "type": "table",
                "title": widgets[i].get("title") or f"Latest rows from {t}",
                "question": f"Show the latest 15 rows from `{t}`. Return a table with <= 15 rows.",
                "viz": {"type": "table"},
            }

    def _rewrite_as_kpi(i: int, pair: tuple[str, str, str] | None) -> None:
        if pair:
            fact, dim, key = pair
            metric = _choose_metric_col(table_cols.get(fact, [])) or _choose_metric_col(table_cols.get(dim, []))
            if metric:
                question = f"Using `{fact}` JOIN `{dim}` on `{key}`, what is the total `{metric}`? Return a single number."
                title = f"Total {metric}"
            else:
                question = f"Using `{fact}` JOIN `{dim}` on `{key}`, how many records are there? Return a single number."
                title = "Total records"
            widgets[i] = {**widgets[i], "type": "kpi", "title": widgets[i].get("title") or title, "question": question, "viz": {"type": "kpi"}}
        else:
            t = logical_tables[0]
            widgets[i] = {
                **widgets[i],
                "type": "kpi",
                "title": widgets[i].get("title") or f"Total rows in {t}",
                "question": f"How many rows are in the `{t}` table? Return a single number.",
                "viz": {"type": "kpi"},
            }

    # Ensure at least one table widget.
    table_idxs = [i for i, w in enumerate(widgets) if wtype(w) == "table"]
    if len(table_idxs) < target_table:
        candidates = [i for i, w in enumerate(widgets) if wtype(w) == "chart"] or list(range(len(widgets)))
        idx = candidates[-1]
        pair = fact_dim_pairs[0] if fact_dim_pairs else (join_pairs[0] if join_pairs else None)
        _rewrite_as_table(idx, pair)

    # Ensure KPI count.
    kpi_idxs = [i for i, w in enumerate(widgets) if wtype(w) == "kpi"]
    while len(kpi_idxs) < target_kpi:
        candidates = [i for i, w in enumerate(widgets) if wtype(w) == "chart"]
        if not candidates:
            candidates = [i for i, w in enumerate(widgets) if wtype(w) != "table"] or [0]
        idx = candidates[0]
        pair = fact_dim_pairs[len(kpi_idxs) % len(fact_dim_pairs)] if fact_dim_pairs else (join_pairs[0] if join_pairs else None)
        _rewrite_as_kpi(idx, pair)
        kpi_idxs = [i for i, w in enumerate(widgets) if wtype(w) == "kpi"]

    # Reduce extras (convert extra tables/kpis back to charts).
    table_idxs = [i for i, w in enumerate(widgets) if wtype(w) == "table"]
    if len(table_idxs) > target_table:
        for idx in table_idxs[target_table:]:
            widgets[idx] = {**widgets[idx], "type": "chart", "viz": {"type": "bar"}}

    kpi_idxs = [i for i, w in enumerate(widgets) if wtype(w) == "kpi"]
    if len(kpi_idxs) > target_kpi:
        for idx in kpi_idxs[target_kpi:]:
            widgets[idx] = {**widgets[idx], "type": "chart", "viz": {"type": "bar"}}

    # Ensure chart count.
    chart_idxs = [i for i, w in enumerate(widgets) if wtype(w) == "chart"]
    if len(chart_idxs) < target_chart:
        for i, w in enumerate(widgets):
            if wtype(w) not in {"chart"} and len(chart_idxs) < target_chart:
                # Keep at least one table.
                if wtype(w) == "table" and sum(1 for ww in widgets if wtype(ww) == "table") <= 1:
                    continue
                widgets[i] = {**widgets[i], "type": "chart", "viz": {"type": "bar"}}
                chart_idxs = [j for j, ww in enumerate(widgets) if wtype(ww) == "chart"]

    # Ensure >=3 fact+dim join widgets by rewriting some charts deterministically.
    if fact_dim_pairs:
        min_fact_dim = min(3, max_widgets)
        for n in range(min_fact_dim):
            fact, dim, key = fact_dim_pairs[n % len(fact_dim_pairs)]
            idx_candidates = [i for i, w in enumerate(widgets) if wtype(w) == "chart"]
            if not idx_candidates:
                break
            idx = idx_candidates[n % len(idx_candidates)]
            metric = _choose_metric_col(table_cols.get(fact, [])) or _choose_metric_col(table_cols.get(dim, []))
            dt = _choose_date_col(table_cols.get(fact, [])) or _choose_date_col(table_cols.get(dim, []))
            if dt:
                question = (
                    f"Using `{fact}` JOIN `{dim}` on `{key}`, show a monthly trend of "
                    f"{('total ' + metric) if metric else 'count of records'} by `{dt}`. Return columns: period, value."
                )
                viz = {"type": "line", "mapping": {"x": "period", "y": "value"}}
                title = f"Trend ({fact} ↔ {dim})"
            else:
                question = (
                    f"Using `{fact}` JOIN `{dim}` on `{key}`, show top 10 `{dim}` by "
                    f"{('total ' + metric) if metric else 'count of records'}. Return columns: category, value."
                )
                viz = {"type": "bar", "mapping": {"x": "category", "y": "value"}}
                title = f"Top {dim} ({fact} ↔ {dim})"
            widgets[idx] = {**widgets[idx], "type": "chart", "title": title, "question": question, "viz": viz}

    return widgets


def _safe_json_loads(text: str) -> Optional[dict]:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        # try extracting first {...} block
        try:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


def _fallback_plan(goal: str, logical_tables: List[str], max_widgets: int, schema_summary: str = "") -> DavinciDashboardPlan:
    """
    Deterministic fallback plan when LLM fails.
    Produces widgets that are safe to execute with small result sets.
    """
    picked = logical_tables[:12]
    widgets: List[Dict[str, Any]] = []

    # Try to build a strong fallback using join/key hints when available.
    table_cols, table_keys = _parse_schema_summary(schema_summary)
    join_pairs = _pick_join_pairs(table_keys, logical_tables) if logical_tables else []
    fact_dim_pairs = _pick_fact_dim_pairs(table_keys, logical_tables) if logical_tables else []

    # If we have no catalog metadata, return a text-only plan explaining the next step.
    if not picked:
        widgets.append(
            {
                "widget_key": "w1",
                "type": "text",
                "title": "Connect data to generate dashboards",
                "question": "N/A",
                "viz": {
                    "type": "text",
                    "content": (
                        "I couldn't find any tables in your data catalog for this connection yet.\n\n"
                        "Next steps:\n"
                        "- Open your connection settings and run **Refresh catalog**\n"
                        "- Ensure your credentials are configured correctly\n\n"
                        "After the catalog is ready, try creating the dashboard again."
                    ),
                },
            }
        )
        # Duplicate to match max_widgets if needed
        while len(widgets) < max_widgets:
            widgets.append({**widgets[-1], "widget_key": f"w{len(widgets)+1}"})
        return DavinciDashboardPlan(
            dashboard_name=goal.strip()[:80] or "Dashboard",
            description="Auto-generated dashboard plan (catalog not ready yet).",
            widgets=widgets[:max_widgets],
            meta={"fallback": True, "reason": "NO_CATALOG_METADATA"},
        )

    # Strong fallback layout for N=8:
    # 2 KPI, 1 Table, 5 Charts with required viz types (bar, line, pie, area, scatter).
    # Prefer fact↔dim join pairs; otherwise any join pairs; otherwise single-table safe widgets.

    def _pick_pair(i: int) -> tuple[str, str, str] | None:
        if fact_dim_pairs:
            return fact_dim_pairs[i % len(fact_dim_pairs)]
        if join_pairs:
            return join_pairs[i % len(join_pairs)]
        return None

    # KPI #1 (prefer join + metric)
    pair0 = _pick_pair(0)
    if pair0:
        fact, dim, key = pair0
        metric = _choose_metric_col(table_cols.get(fact, [])) or _choose_metric_col(table_cols.get(dim, []))
        title = f"Total {metric}" if metric else "Total records"
        question = (
            f"Using `{fact}` JOIN `{dim}` on `{key}`, what is the total `{metric}`? Return a single number."
            if metric
            else f"Using `{fact}` JOIN `{dim}` on `{key}`, how many records are there? Return a single number."
        )
        widgets.append({"widget_key": "w1", "type": "kpi", "title": title, "question": question, "viz": {"type": "kpi"}})
    else:
        widgets.append(
            {
                "widget_key": "w1",
                "type": "kpi",
                "title": f"Total rows in {picked[0]}",
                "question": f"How many rows are in the `{picked[0]}` table? Return a single number.",
                "viz": {"type": "kpi"},
            }
        )

    # KPI #2
    pair1 = _pick_pair(1)
    if pair1:
        fact, dim, key = pair1
        metric = _choose_metric_col(table_cols.get(fact, [])) or _choose_metric_col(table_cols.get(dim, []))
        title = f"Total {metric}" if metric else "Total records"
        question = (
            f"Using `{fact}` JOIN `{dim}` on `{key}`, what is the total `{metric}`? Return a single number."
            if metric
            else f"Using `{fact}` JOIN `{dim}` on `{key}`, how many records are there? Return a single number."
        )
        widgets.append({"widget_key": "w2", "type": "kpi", "title": title, "question": question, "viz": {"type": "kpi"}})
    else:
        t = picked[1] if len(picked) > 1 else picked[0]
        widgets.append(
            {
                "widget_key": "w2",
                "type": "kpi",
                "title": f"Total rows in {t}",
                "question": f"How many rows are in the `{t}` table? Return a single number.",
                "viz": {"type": "kpi"},
            }
        )

    # Table (prefer join detail)
    pair2 = _pick_pair(2)
    if pair2:
        fact, dim, key = pair2
        dim_cols = table_cols.get(dim, [])
        label = _choose_dim_col(dim_cols) or "name"
        widgets.append(
            {
                "widget_key": "w3",
                "type": "table",
                "title": "Joined detail view",
                "question": (
                    f"Using `{fact}` JOIN `{dim}` on `{key}`, show the latest 15 records with key fields and `{label}`. "
                    "Return a table with <= 15 rows."
                ),
                "viz": {"type": "table"},
            }
        )
    else:
        widgets.append(
            {
                "widget_key": "w3",
                "type": "table",
                "title": f"Latest rows from {picked[0]}",
                "question": f"Show the latest 15 rows from `{picked[0]}`.",
                "viz": {"type": "table"},
            }
        )

    # Charts: force required viz set for a "super dashboard"
    required_viz = ["bar", "line", "pie", "area", "scatter"]
    for i, viz_type in enumerate(required_viz, start=4):
        pair = _pick_pair(i)
        if pair:
            a, b, key = pair
            a_cols = table_cols.get(a, [])
            b_cols = table_cols.get(b, [])
            metric = _choose_metric_col(a_cols) or _choose_metric_col(b_cols)
            dim = _choose_dim_col(b_cols) or _choose_dim_col(a_cols)
            dt = _choose_date_col(a_cols) or _choose_date_col(b_cols)

            if viz_type in {"line", "area"} and dt:
                question = (
                    f"Using `{a}` JOIN `{b}` on `{key}`, show a monthly trend of "
                    f"{('total ' + metric) if metric else 'count of records'} by `{dt}`. "
                    "Return columns: period and value."
                )
                viz = {"type": viz_type, "mapping": {"x": "period", "y": "value"}}
                title = f"Trend ({a} ↔ {b})"
            elif viz_type == "pie" and dim:
                question = (
                    f"Using `{a}` JOIN `{b}` on `{key}`, show the distribution of `{dim}` "
                    f"by {('total ' + metric) if metric else 'count of records'} (top 8 + other). "
                    "Return columns: category and value."
                )
                viz = {"type": "pie", "mapping": {"x": "category", "y": "value"}}
                title = f"Distribution by {dim}"
            elif viz_type == "scatter" and metric:
                question = (
                    f"Using `{a}` JOIN `{b}` on `{key}`, build a scatter plot for `{metric}` against another numeric measure. "
                    "Return columns: x, y, and category."
                )
                viz = {"type": "scatter", "mapping": {"x": "x", "y": "y"}}
                title = f"Scatter ({metric})"
            else:
                question = (
                    f"Using `{a}` JOIN `{b}` on `{key}`, show the top 10 `{dim or b}` by "
                    f"{('total ' + metric) if metric else 'count of records'}. "
                    "Return columns: category and value."
                )
                viz = {"type": "bar", "mapping": {"x": "category", "y": "value"}}
                title = f"Top {dim or 'categories'}"

            widgets.append({"widget_key": f"w{i}", "type": "chart", "title": title, "question": question, "viz": viz})
        else:
            # Single-table fallback for charts
            t = picked[(i - 1) % max(1, len(picked))]
            widgets.append(
                {
                    "widget_key": f"w{i}",
                    "type": "chart",
                    "title": f"{viz_type.title()} insight from {t}",
                    "question": f"Show a small aggregated result from `{t}` suitable for a {viz_type} chart (<= 15 rows).",
                    "viz": {"type": viz_type},
                }
            )

    # Trim / pad deterministically
    widgets = widgets[:max_widgets]
    while len(widgets) < max_widgets:
        widgets.append({**widgets[-1], "widget_key": f"w{len(widgets)+1}"})

    return DavinciDashboardPlan(
        dashboard_name=goal.strip()[:80] or "Dashboard",
        description="Auto-generated super dashboard based on your accessible data.",
        widgets=widgets[:max_widgets],
        meta={"fallback": True, "reason": "LLM_FALLBACK"},
    )


def generate_dashboard_plan(
    *,
    llm: Any,
    goal: str,
    language: str,
    max_widgets: int,
    logical_tables: List[str],
    schema_summary: str,
) -> DavinciDashboardPlan:
    """
    Davinci "graph": generate a dashboard plan as STRICT JSON.

    Inputs are already permission-filtered (logical_tables/schema_summary).
    """
    # Keep the request bounded and deterministic-ish.
    # Temporary product decision: cap at 8 widgets for auto dashboard creation.
    max_widgets = max(1, min(8, int(max_widgets)))
    language = (language or "en").lower()
    if language not in {"en", "pt", "es"}:
        language = "en"

    if not logical_tables:
        return _fallback_plan(goal=goal, logical_tables=[], max_widgets=max_widgets, schema_summary=schema_summary)

    table_cols, table_keys = _parse_schema_summary(schema_summary)

    # NOTE: when using `.format(...)`, any `{}` in the prompt becomes a formatting placeholder.
    # We intentionally avoid `.format` here because the JSON schema includes `{}`.
    min_join = min(5, max_widgets)
    system = (
        "You are Davinci, a dashboard planner.\n"
        "You propose a dashboard (name + widgets) based on accessible tables.\n"
        "Rules:\n"
        "- Output STRICT JSON only.\n"
        "- Use ONLY the provided logical table names.\n"
        "- ALWAYS wrap referenced table names in backticks (e.g., `invoices`).\n"
        "- Each widget must have: widget_key, type, title, question, viz.\n"
        "- Widget types allowed: chart, kpi, table, text.\n"
        "- Questions MUST be answerable from the provided tables.\n"
        "- Prefer aggregated queries that return <= 15 rows for charts.\n"
        "- Make the dashboard engaging: mix widget types (KPIs + charts + at least one table when possible).\n"
        "- Prefer a mix of chart viz types (bar/column, line/area, pie/donut, scatter) when applicable.\n"
        "- IMPORTANT: Prefer cross-table insights. When useful, ask questions that require JOINs (e.g., invoice + customer, order + product, payments + invoices) to produce better business metrics.\n"
        "- If keys are provided in the schema sample, use them to suggest joined questions (e.g., *_id and date fields).\n"
        f"- Hard requirement: at least {min_join} of N widgets MUST require JOINs across 2+ tables.\n"
        "- For N=8: enforce a fixed distribution: exactly 2 KPI widgets, exactly 1 Table widget, and exactly 5 Chart widgets.\n"
        "- For N=8: at least 3 of the JOIN widgets MUST be fact+dimension joins (e.g., invoices↔customers, orders↔products).\n"
        f"- Language for titles/questions: {language}\n"
        "- EXACTLY N widgets.\n"
        'JSON schema: {{"dashboard_name": string, "description": string, "widgets": ['
        '{{"widget_key": string, "type": string, "title": string, "question": string, "viz": object}}'
        "]}}.\n"
    )

    user = (
        f"N={max_widgets}\n"
        f"Goal: {goal}\n"
        f"Accessible tables: {', '.join(logical_tables[:20])}\n"
        f"Schema sample:\n{schema_summary}\n"
    )

    try:
        resp = llm.invoke([{"role": "system", "content": system}, {"role": "user", "content": user}])
        parsed = _safe_json_loads(getattr(resp, "content", "") or "")
        if not isinstance(parsed, dict):
            raise ValueError("LLM did not return valid JSON object")

        dashboard_name = str(parsed.get("dashboard_name") or "").strip() or (goal.strip()[:80] or "Dashboard")
        description = str(parsed.get("description") or "").strip() or None
        widgets_raw = parsed.get("widgets") or []
        if not isinstance(widgets_raw, list) or not widgets_raw:
            raise ValueError("LLM returned no widgets")

        widgets: List[Dict[str, Any]] = []
        for i, w in enumerate(widgets_raw[:max_widgets], start=1):
            if not isinstance(w, dict):
                continue
            widget_key = str(w.get("widget_key") or f"w{i}").strip() or f"w{i}"
            wtype = str(w.get("type") or "chart").strip()
            title = str(w.get("title") or "").strip() or f"Widget {i}"
            question = str(w.get("question") or "").strip()
            viz = w.get("viz") if isinstance(w.get("viz"), dict) else {"type": "bar"}
            if not question:
                continue
            widgets.append(
                {
                    "widget_key": widget_key,
                    "type": wtype,
                    "title": title,
                    "question": question,
                    "viz": viz,
                }
            )

        if not widgets:
            raise ValueError("LLM widgets invalid")

        # Normalize count
        widgets = widgets[:max_widgets]
        while len(widgets) < max_widgets:
            widgets.append(widgets[-1])

        # Enforce cross-table join mix if the LLM didn't satisfy it.
        widgets = _enforce_join_mix(
            widgets,
            logical_tables=logical_tables,
            table_cols=table_cols,
            table_keys=table_keys,
            max_widgets=max_widgets,
        )

        widgets = _enforce_distribution_and_fact_dim(
            widgets,
            logical_tables=logical_tables,
            table_cols=table_cols,
            table_keys=table_keys,
            max_widgets=max_widgets,
        )

        log_event(
            "davinci_plan_generated",
            {
                "goal": goal[:200],
                "language": language,
                "num_widgets": len(widgets),
                "join_widgets": sum(1 for w in widgets if _count_tables_mentioned(str(w.get("question") or ""), logical_tables) >= 2),
                "type_counts": {
                    "kpi": sum(1 for w in widgets if str(w.get("type") or "") == "kpi"),
                    "table": sum(1 for w in widgets if str(w.get("type") or "") == "table"),
                    "chart": sum(1 for w in widgets if str(w.get("type") or "") == "chart"),
                    "text": sum(1 for w in widgets if str(w.get("type") or "") == "text"),
                },
                "fallback": False,
            },
        )
        return DavinciDashboardPlan(
            dashboard_name=dashboard_name,
            description=description,
            widgets=widgets,
            meta={"fallback": False, "model": getattr(getattr(llm, "_chat", None), "model_name", None)},
        )
    except Exception as e:
        log_event(
            "davinci_plan_error",
            {"goal": goal[:200], "error": str(e)[:500]},
        )
        return _fallback_plan(goal=goal, logical_tables=logical_tables, max_widgets=max_widgets, schema_summary=schema_summary)

