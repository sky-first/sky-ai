"""Full Context Agent — Autonomous Proactive Intelligence.

Runs on a schedule (via Celery Beat + agent_worker). Instead of
answering a single question, this agent:

  1. Reconnaissance — inspects available DB tables, active OKRs/goals,
     and recent market signals.
  2. Investigation (ReAct loop) — cross-references data from multiple
     tables against strategy and signals to find meaningful patterns.
  3. Synthesis — decides if there is something worth surfacing. If yes,
     formats a concise insight. If not, stays silent.

Security:
  - All SQL executed through this agent is validated SELECT-only.
  - Scoped to the agent owner's space_id / crew_ids (RBAC inherited).
  - Recursion capped at MAX_REACT_ITERATIONS to prevent runaway cost.

Observability:
  - Every execution is traced in Langfuse when LANGFUSE_ENABLED=true.
  - Tool calls, LLM generations, token counts and cost are all captured.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from langchain_core.messages import HumanMessage

from core.agents.generic_sql_agent import AgentConfig, AgentState
from core.data_sources.base import BaseDataSource
from core.logging_utils import log_event
from core.rag.embeddings import EmbeddingProvider
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MAX_REACT_ITERATIONS = 20
MAX_SQL_ROWS = 100


# ─── Safety guard ─────────────────────────────────────────────────────────

def _is_safe_sql(sql: str) -> bool:
    """Accept only SELECT / WITH (CTE) statements."""
    cleaned = sql.strip().lstrip("-– \n\r\t")
    upper = cleaned.upper()
    return upper.startswith("SELECT") or upper.startswith("WITH")


# ─── Langfuse callback (optional) ─────────────────────────────────────────

def _get_langfuse_callback(agent_id: str, user_id: str, space_id: str) -> Optional[Any]:
    """Build a Langfuse LangChain callback handler if observability is enabled.

    Uses langfuse v2 CallbackHandler which accepts all config directly and
    wraps every LLM call + tool call in a trace automatically.
    """
    try:
        from config.settings import settings
        if not settings.langfuse_enabled:
            return None
        from langfuse.callback import CallbackHandler
        return CallbackHandler(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
            trace_name="full_context_agent",
            user_id=user_id,
            tags=["autonomous", "full_context"],
            metadata={"agent_id": agent_id, "space_id": space_id},
        )
    except Exception:
        logger.debug("Langfuse not available — running without observability")
        return None


# ─── System prompt ────────────────────────────────────────────────────────

_BASE_SYSTEM_PROMPT = """\
You are an Autonomous Data Intelligence Agent for this organisation.

Your mission: proactively investigate the organisation's data and surface \
ONE meaningful insight that leadership or the data owner should know right now.

══════════════════════════════════════════
WHAT COUNTS AS MEANINGFUL (surface these):
══════════════════════════════════════════
  ✓ Goal vs actual GAP   — a metric is >10% above or below a stated target
  ✓ Trend anomaly        — a metric changed >20% compared to the prior period
  ✓ Unexpected pattern   — two metrics moving together in a non-obvious way
  ✓ Imminent risk        — a leading indicator pointing to a near-term problem
  ✓ Dormant opportunity  — an underutilised asset, cohort, or product line

══════════════════════════════════════════
WHAT IS NOISE (stay SILENT for these):
══════════════════════════════════════════
  ✗ Static facts    — "there are 500 records in the table" (no action needed)
  ✗ Normal variation — changes <5% with no strategic context
  ✗ Missing data    — an empty table is not an insight
  ✗ Schema listing  — describing table structure is not an insight

You have 5 tools:
  • list_tables()                      — compact list of all tables (call FIRST, ONCE)
  • get_table_schema(table_name)       — full columns for ONE specific table
  • query_table(sql)                   — run a SELECT and get real data back
  • search_corporate_strategy(query)  — search OKRs, goals, KPIs, strategic pillars
  • search_market_signals(query)      — search recent events, anomalies, market signals

══════════════════════════════════════════
INVESTIGATION PROTOCOL (follow in order):
══════════════════════════════════════════
1. Call list_tables() ONCE — scan for 1–2 tables most likely to hold
   business metrics (revenue, retention, churn, conversions, pipeline, etc.).
2. Call get_table_schema(table_name) for each chosen table — understand the
   exact column names and types BEFORE writing any SQL.
3. Call query_table() with a focused SELECT to get real numbers.
   Use aggregations, date filters, GROUP BY, and LIMIT {max_rows}.
4. Call search_corporate_strategy() ONCE with one relevant query.
   If it returns "No strategic documentation found", accept it and move on.
5. Call search_market_signals() ONCE with one relevant query.
   If it returns "No market signals found", accept it and move on.
6. Synthesise — apply MEANINGFUL vs NOISE criteria. If nothing passes
   the bar, end with exactly: SILENT — nothing to surface.

EFFICIENCY RULES (strictly enforced):
- list_tables() → called AT MOST ONCE.
- get_table_schema() → called AT MOST TWICE (pick your top 2 tables).
- query_table() → called AT MOST THREE times total.
- search_* tools → called AT MOST ONCE each. Do NOT retry on empty results.

SQL RULES:
- Only SELECT statements. Never INSERT, UPDATE, DELETE, or DROP.
- Use the PHYSICAL table name shown after "→" in list_tables output.
  Example: "orders → crm.orders" → write: SELECT … FROM crm.orders …
- NEVER use the logical name in SQL — it will fail with "relation does not exist".
- If a query fails, call get_table_schema() to confirm the physical name,
  then retry ONCE with the corrected name. Do not retry more than once.

OUTPUT FORMAT — use ONLY when you have something meaningful to surface:
## [Insight title — 8 words max]

**What we found:** 2–3 sentences with actual numbers and the time period covered.

**Why it matters:** 1 sentence connecting to a goal, OKR, or risk.

**Suggested next questions:**
- Question 1
- Question 2
- Question 3
""".format(max_rows=MAX_SQL_ROWS)


def _fetch_brain_context_sync(db: Session, space_id: str, crew_ids: list) -> str:
    """Query strategy docs (OKRs, pillars, KPIs) using the sync DB session.

    Fetches EmbeddingRecord rows for the given space/crew scope, filters
    in-Python by kind to avoid JSON-operator portability issues, and formats
    them as a concise text block for prompt injection.
    Returns "" on any error so the caller always gets a safe string.
    """
    try:
        from db.models import EmbeddingRecord
        from sqlalchemy import or_
        from uuid import UUID as _UUID

        strategy_kinds = {
            "pillar", "goal", "okr", "kpi", "metric",
            "objective", "key_result", "target",
        }

        q = db.query(EmbeddingRecord.text, EmbeddingRecord.extra_metadata)

        scope_conditions = []
        if space_id:
            try:
                scope_conditions.append(EmbeddingRecord.space_id == _UUID(space_id))
            except Exception:
                scope_conditions.append(EmbeddingRecord.space_id == space_id)
        if crew_ids:
            try:
                uuid_crew_ids = [_UUID(c) if isinstance(c, str) else c for c in crew_ids]
                scope_conditions.append(EmbeddingRecord.crew_id.in_(uuid_crew_ids))
            except Exception:
                pass

        if scope_conditions:
            q = q.filter(or_(*scope_conditions))

        q = q.filter(EmbeddingRecord.extra_metadata.isnot(None))
        rows = q.order_by(EmbeddingRecord.created_at.desc()).limit(60).all()

        lines = []
        for text_val, meta in rows:
            if not meta:
                continue
            kind = meta.get("type") or meta.get("kind") or ""
            if kind not in strategy_kinds:
                continue
            name = meta.get("name") or ""
            prefix = f"[{kind.upper()}] {name}: " if name else f"[{kind.upper()}] "
            lines.append(prefix + (text_val or "")[:300])
            if len(lines) >= 15:
                break

        return "\n".join(lines)
    except Exception as exc:
        logger.debug("_fetch_brain_context_sync failed: %s", exc)
        return ""


def _build_system_prompt(brain_context: str, briefing: str = "") -> str:
    """Append per-client strategic context and optional scan briefing to the BASE prompt."""
    prompt = _BASE_SYSTEM_PROMPT

    # Inject scan briefing (direction block) before the organisation context
    # so the agent reads its mission before the OKR/KPI details.
    if briefing:
        prompt = prompt + briefing

    if brain_context:
        prompt = (
            prompt
            + "\n══════════════════════════════════════════\n"
            "ORGANISATION CONTEXT (prioritise findings aligned with these):\n"
            "══════════════════════════════════════════\n"
            + brain_context
            + "\n"
        )

    return prompt


# ─── Main entry point ─────────────────────────────────────────────────────

def _find_datasource_for_sql(
    sql: str,
    agent_config: AgentConfig,
    dispatch_map: dict,
) -> Any:
    """Pick the right DataSource from dispatch_map by matching physical table names in SQL."""
    sql_upper = sql.upper()
    for table in agent_config.tables:
        phys = (table.physical_name or "").upper()
        if phys and phys in sql_upper:
            conn_id = str(getattr(table, "data_connection_id", "") or "")
            if conn_id in dispatch_map:
                return dispatch_map[conn_id]
    # fallback: first source in map
    return next(iter(dispatch_map.values()), None)


def run_full_context_agent(
    state: AgentState,
    agent_config: AgentConfig,
    llm: Any,
    db: Session,
    embedding_provider: EmbeddingProvider,
    data_source: Optional[BaseDataSource] = None,
    dispatch_map: Optional[dict] = None,
    briefing: str = "",
) -> AgentState:
    """Execute one full-context investigation cycle.

    Called from the ``full_context_node`` inside the LangGraph graph when
    ``agent_mode == 'scan'``. Returns a mutated copy of ``state`` with
    ``state['answer']`` set to the markdown insight (or a silent signal).
    """
    from langchain_core.tools import tool
    from langgraph.prebuilt import create_react_agent
    from core.llm.tools import ToolFactory

    question = (state.get("question") or "").strip()
    space_id = state.get("space_id") or ""
    crew_ids = list(state.get("crew_ids") or [])
    user_id = state.get("user_id") or ""
    agent_id = str(agent_config.id) if agent_config.id else "unknown"

    log_event("full_context_agent_start", {
        "agent_id": agent_id,
        "space_id": space_id,
        "question": question[:100],
    })

    # ── Chat model check ──────────────────────────────────────────────────
    chat_model = getattr(llm, "_chat", None)
    if chat_model is None or not hasattr(chat_model, "bind_tools"):
        state["answer"] = (
            "Full context mode requires a tool-capable model. "
            "Please configure AI_PROVIDER=openai or bedrock."
        )
        return state

    # ── Build effective dispatch map ──────────────────────────────────────
    # dispatch_map: {connection_id → DataSource}
    # Allows query_table to route SQL to the right database.
    # Backward compat: if only data_source is passed, wrap it in a map.
    if dispatch_map:
        _dispatch = {str(k): v for k, v in dispatch_map.items()}
    elif data_source is not None:
        _dispatch = {"__default__": data_source}
    else:
        _dispatch = {}

    def _active_source(sql: str) -> Any:
        if not _dispatch:
            return None
        if len(_dispatch) == 1:
            return next(iter(_dispatch.values()))
        return _find_datasource_for_sql(sql, agent_config, _dispatch)

    log_event("full_context_agent_dispatch", {
        "agent_id": agent_id,
        "num_sources": len(_dispatch),
        "connection_ids": [k for k in _dispatch if k != "__default__"],
    })

    # ── Build tools ───────────────────────────────────────────────────────

    # Tracks which logical table names were actually queried this run.
    # Populated inside query_table at execution time — more reliable than
    # parsing message objects after the fact.
    _queried_logical_names: list[str] = []

    # Accumulates every SQL string executed successfully — used by the
    # depth tracker in connection_query.py to record (dim × metric) combos
    # without needing async DB access inside this sync tool.
    _sql_executions: list[str] = []

    # Build connection labels for list_tables grouping (only when multi-source)
    _connection_labels: Optional[dict] = None
    if dispatch_map and len(dispatch_map) > 1:
        _connection_labels = {
            str(k): getattr(v, "label", None) or str(k)[:16]
            for k, v in dispatch_map.items()
        }

    list_tables_tool = ToolFactory.create_list_tables_tool(agent_config, _connection_labels)
    get_schema_tool = ToolFactory.create_table_schema_tool(agent_config)
    strategy_tool = ToolFactory.create_strategy_tool(db, embedding_provider, space_id, crew_ids)
    signals_tool = ToolFactory.create_signals_tool(db, embedding_provider, space_id, crew_ids)

    # ── Dynamic system prompt (BASE + scan briefing + per-client OKR/pillar context) ──────
    brain_context = _fetch_brain_context_sync(db, space_id, crew_ids)
    system_prompt = _build_system_prompt(brain_context, briefing=briefing)

    @tool
    def query_table(sql: str) -> str:
        """Execute a SELECT query against the organisation's database.

        Provide a complete, valid SELECT statement. The result will be
        returned as formatted rows. Use LIMIT to avoid huge results.
        Example: SELECT customer_id, mrr FROM billing.subscriptions
                 WHERE status = 'active' ORDER BY mrr DESC LIMIT 20
        """
        if not _is_safe_sql(sql):
            return "ERROR: Only SELECT statements are permitted."

        source = _active_source(sql)
        if source is None:
            return "ERROR: No data source available."

        def _run_and_format(s: Any, q: str) -> str:
            rows = s.run_query(q)
            if not rows:
                return "Query returned 0 rows."
            rows = rows[:MAX_SQL_ROWS]
            header = " | ".join(rows[0].keys())
            lines = [" | ".join(str(v) for v in row.values()) for row in rows[:5]]
            preview = "\n".join([header, "---"] + lines)
            suffix = f"\n... ({len(rows)} rows total)" if len(rows) > 5 else ""
            return preview + suffix

        try:
            result_str = _run_and_format(source, sql)
            # Track which logical tables were actually queried.
            # Check both full physical name ("crm.opportunities") and
            # unqualified name ("opportunities") since the agent may omit schema.
            sql_upper = sql.upper()
            for table in agent_config.tables:
                phys = (table.physical_name or "").upper()
                phys_bare = phys.split(".")[-1]  # "opportunities"
                if phys and (phys in sql_upper or (phys_bare and phys_bare in sql_upper)):
                    if table.logical_name not in _queried_logical_names:
                        _queried_logical_names.append(table.logical_name)
            # Accumulate for depth tracker (item 34 — async flush happens in caller)
            _sql_executions.append(sql)
            return result_str
        except Exception as exc:
            err_str = str(exc)
            if "does not exist" in err_str:
                resolved = _resolve_schema_qualified_sql(sql, source)
                if resolved and resolved != sql:
                    try:
                        result_str = _run_and_format(source, resolved)
                        sql_upper = resolved.upper()
                        for table in agent_config.tables:
                            phys = (table.physical_name or "").upper()
                            if phys and phys in sql_upper:
                                if table.logical_name not in _queried_logical_names:
                                    _queried_logical_names.append(table.logical_name)
                        _sql_executions.append(resolved)
                        return result_str
                    except Exception as exc2:
                        logger.warning("query_table resolved retry failed: %s", exc2)
                        return f"Query failed: {exc2}"
            logger.warning("query_table failed: %s", exc)
            return f"Query failed: {exc}"

    tools = [list_tables_tool, get_schema_tool, strategy_tool, signals_tool, query_table]

    # ── Langfuse callback ─────────────────────────────────────────────────
    langfuse_cb = _get_langfuse_callback(agent_id, user_id, space_id)
    invoke_config: dict[str, Any] = {"recursion_limit": MAX_REACT_ITERATIONS}
    if langfuse_cb:
        invoke_config["callbacks"] = [langfuse_cb]

    # ── Build and run ReAct agent ─────────────────────────────────────────
    user_prompt = (
        f"Agent focus: {question}\n\n"
        "Investigate autonomously and surface one meaningful insight. "
        "Follow the INVESTIGATION PROTOCOL in your instructions."
    ) if question else (
        "Investigate the available data autonomously and surface one "
        "meaningful insight for the data owner. Follow the INVESTIGATION "
        "PROTOCOL in your instructions."
    )

    try:
        react_agent = create_react_agent(
            chat_model,
            tools=tools,
            state_modifier=system_prompt,
        )
        result = react_agent.invoke(
            {"messages": [HumanMessage(content=user_prompt)]},
            config=invoke_config,
        )
        answer = result["messages"][-1].content

        # Count tool calls (ToolMessage = one completed tool invocation)
        tool_calls = sum(
            1 for m in result.get("messages", [])
            if hasattr(m, "type") and getattr(m, "type", "") == "tool"
        )

        # tables_queried and executed_sqls were populated inside query_table
        tables_queried = list(_queried_logical_names)
        executed_sqls = list(_sql_executions)

        log_event("full_context_agent_done", {
            "agent_id": agent_id,
            "tool_calls": tool_calls,
            "answer_len": len(answer),
            "silent": "SILENT" in answer.upper(),
            "tables_queried": tables_queried,
        })

    except Exception as exc:
        logger.exception("full_context_agent failed")
        log_event("full_context_agent_error", {"agent_id": agent_id, "error": str(exc)[:300]})
        state["answer"] = (
            "The autonomous agent encountered an error during investigation. "
            "Please try again later."
        )
        return state

    # Always persist tables_queried and executed_sqls so downstream
    # components (staleness scorer, depth tracker) can consume them
    # even when the agent returns SILENT.
    state["tables_queried"] = tables_queried
    state["executed_sqls"] = executed_sqls

    # ── Silent mode — agent found nothing worth surfacing ─────────────────
    if re.search(r"\bSILENT\b", answer, re.IGNORECASE):
        state["answer"] = None  # caller (agent_worker) interprets None as no-op
        return state

    state["answer"] = answer
    state["generated_title"] = _extract_title(answer) or "Autonomous insight"
    return state


# ─── Helpers ──────────────────────────────────────────────────────────────

def _extract_title(answer: str) -> Optional[str]:
    """Pull the first ## heading from the markdown output as the title."""
    match = re.search(r"^##\s+(.+)$", answer, re.MULTILINE)
    return match.group(1).strip() if match else None


def _resolve_schema_qualified_sql(sql: str, data_source: "BaseDataSource") -> Optional[str]:
    """Replace unqualified table names in SQL with schema-qualified ones.

    Queries information_schema.tables on the data source to find the correct
    schema for each unqualified table name, then does targeted word-boundary
    replacements — only for known table names, never for SQL keywords.
    Returns the rewritten SQL, or None if resolution fails.
    """
    try:
        schema_rows = data_source.run_query(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_type='BASE TABLE' AND table_schema NOT IN "
            "('information_schema','pg_catalog') ORDER BY table_schema, table_name"
        )
        # Build mapping: unqualified_name → schema.table_name (first match wins)
        schema_map: dict[str, str] = {}
        for row in (schema_rows or []):
            vals = list(row.values())
            tschema, tname = str(vals[0]), str(vals[1])
            if tname not in schema_map:
                schema_map[tname] = f"{tschema}.{tname}"

        if not schema_map:
            return None

        rewritten = sql
        for bare_name, qualified_name in schema_map.items():
            # Only replace the bare name when NOT already preceded by a dot
            # (i.e., not already schema-qualified like "crm.opportunities")
            rewritten = re.sub(
                r"(?<!\.)(?<!\w)\b" + re.escape(bare_name) + r"\b",
                qualified_name,
                rewritten,
            )

        return rewritten if rewritten != sql else None
    except Exception as exc:
        logger.debug("_resolve_schema_qualified_sql failed: %s", exc)
        return None
