"""
Context Bundle Builder

Constructs ContextBundle from AgentState and AgentConfig.
Handles multi-layer RAG retrieval with token-aware truncation.
"""

from __future__ import annotations

from typing import Optional, List
import re

from sqlalchemy.orm import Session

from core.agents.generic_sql_agent import AgentState, AgentConfig
from core.llm.context.models import (
    UserContext,
    CrewContext,
    QueryContext,
    DataContext,
    HistoricalContext,
    ContextBundle,
)
from core.sql.relationships import detect_relationships
from core.logging_utils import log_event


def build_context_bundle(
    state: AgentState,
    agent_config: AgentConfig,
    db: Optional[Session] = None,
) -> ContextBundle:
    """
    Builds context bundle from agent state and configuration.

    This is called ONCE per request at the beginning of orchestrator.
    The bundle is then reused by all agents (orchestrator → specialist → formatter).

    Args:
        state: Current agent state with user question and session data
        agent_config: Agent configuration with tables and settings
        db: Optional database session for RAG retrieval

    Returns:
        ContextBundle with all context layers populated

    CPU Optimization:
        - Limits RAG retrieval to top-3 per layer
        - Truncates chat history to last 4 messages
        - Estimates tokens and marks if truncated
    """
    question = state.get("question", "")

    user_ctx = UserContext(
        user_id=state.get("user_id", ""),
        space_ids=state.get(
            "space_ids", [state.get("space_id")] if state.get("space_id") else []
        ),
        is_personal=state.get("is_personal", False),
        platform_role=state.get("platform_role", "user"),
        crew_role=state.get("crew_role", "guest"),
        locale=state.get("locale") or "en",
        role_label=state.get("role_label"),
    )

    # 2. CREW CONTEXT
    crew_ctx = CrewContext(
        crew_ids=state.get("crew_ids", []),
        allowed_datasets=[t.logical_name for t in agent_config.tables],
        restricted_domains=[],  # TODO: Implement domain restrictions
    )

    # 3. QUERY CONTEXT
    query_ctx = QueryContext(
        intent=_detect_intent(question),
        entities=_extract_entities(question),
        metrics=_extract_metrics(question),
        time_range=_extract_time_range(question),
        requires_aggregation=_detect_aggregation_need(question),
        requires_joins=_detect_join_need(question, agent_config),
    )

    # 4. DATA CONTEXT
    explicit_relationships = state.get(
        "explicit_relationships"
    )  # Definidos pelo cliente
    data_ctx = DataContext(
        tables=agent_config.tables,
        relationships=detect_relationships(
            agent_config.tables,
            explicit_relationships=explicit_relationships,
        ),
        total_tables=len(agent_config.tables),
        context_freshness="live",
    )

    # 5. HISTORICAL CONTEXT (Consome o RAG pré-carregado no state)
    # `.get(k, [])` still returns None when the key exists with an explicit
    # None value (RAG failed / returned nothing) — coalesce so the formatter
    # never crashes on iteration or len() below.
    retrieval_context = state.get("retrieval_context") or []

    rag_results = {
        "schema_rag": [],
        "metrics_rag": [],
        "questions_rag": [],
        "comments_rag": [],
        "glossary_rag": [],
        "strategy_rag": [],
        "governance_rag": [],
    }

    # Distribui os chunks baseados nos prefixos criados pelo _format_records
    for chunk in retrieval_context:
        if "[TABLE METADATA]" in chunk:
            rag_results["schema_rag"].append(chunk)
        elif "[BUSINESS CONTEXT]" in chunk:
            rag_results["strategy_rag"].append(chunk)
        elif "[DOCUMENT]" in chunk:
            rag_results["strategy_rag"].append(
                chunk
            )  # Documentos enriquecem estratégia
        elif "[GLOSSARY]" in chunk:
            rag_results["glossary_rag"].append(chunk)
        else:
            # Fallback para schema se não for reconhecido (comportamento legado)
            rag_results["schema_rag"].append(chunk)

    historical_ctx = HistoricalContext(
        schema_rag=rag_results["schema_rag"],
        metrics_rag=rag_results["metrics_rag"],
        questions_rag=rag_results["questions_rag"],
        comments_rag=rag_results["comments_rag"],
        glossary_rag=rag_results["glossary_rag"],
        strategy_rag=rag_results["strategy_rag"],
        governance_rag=rag_results["governance_rag"],
        chat_history=state.get("chat_history", [])[-4:],  # Last 4 messages only
    )

    log_event(
        "context_rag_processed",
        {
            "total_chunks": len(retrieval_context),
            "strategy_chunks": len(historical_ctx.strategy_rag),
        },
    )

    # Create bundle
    bundle = ContextBundle(
        user=user_ctx,
        crew=crew_ctx,
        query=query_ctx,
        data=data_ctx,
        historical=historical_ctx,
    )

    # Estimate tokens
    bundle.total_tokens_estimate = _estimate_bundle_tokens(bundle)

    # Check if truncation needed (leave room for system prompt + user message)
    MAX_CONTEXT_TOKENS = 3000  # Conservative limit for 4096 context window
    if bundle.total_tokens_estimate > MAX_CONTEXT_TOKENS:
        bundle = _truncate_bundle(bundle, max_tokens=MAX_CONTEXT_TOKENS)
        bundle.is_truncated = True

    log_event(
        "context_bundle_built",
        {
            "agent_id": agent_config.id,
            "total_tokens": bundle.total_tokens_estimate,
            "is_truncated": bundle.is_truncated,
            "rag_layers": {
                "schema": len(historical_ctx.schema_rag),
                "metrics": len(historical_ctx.metrics_rag),
                "questions": len(historical_ctx.questions_rag),
                "comments": len(historical_ctx.comments_rag),
                "glossary": len(historical_ctx.glossary_rag),
                "catalog": len(historical_ctx.catalog_rag),
                "analytics": len(historical_ctx.analytics_rag),
                "strategy": len(historical_ctx.strategy_rag),
                "governance": len(historical_ctx.governance_rag),
                "enterprise": len(historical_ctx.enterprise_rag),
                "signals": len(historical_ctx.signals_rag),
            },
        },
    )

    return bundle


# ============================================================================
# Intent Detection
# ============================================================================


def _detect_intent(question: str) -> str:
    """
    Detect user intent from question.

    Returns:
        - analytical: Metrics, trends, aggregations
        - exploratory: Browsing data, finding patterns
        - comparative: Comparing entities or time periods
        - operational: Status checks, current state
    """
    q_lower = question.lower()

    # Analytical patterns
    analytical_keywords = [
        "performance",
        "metric",
        "trend",
        "analysis",
        "kpi",
        "total",
        "sum",
        "average",
        "count",
        "calculate",
    ]
    if any(kw in q_lower for kw in analytical_keywords):
        return "analytical"

    # Comparative patterns
    comparative_keywords = [
        "compare",
        "vs",
        "versus",
        "difference",
        "better",
        "worse",
        "month-over-month",
        "year-over-year",
        "increase",
        "decrease",
    ]
    if any(kw in q_lower for kw in comparative_keywords):
        return "comparative"

    # Operational patterns
    operational_keywords = [
        "status",
        "current",
        "now",
        "today",
        "latest",
        "recent",
        "active",
        "pending",
        "failed",
    ]
    if any(kw in q_lower for kw in operational_keywords):
        return "operational"

    # Default: exploratory
    return "exploratory"


def _extract_entities(question: str) -> List[str]:
    """
    Extract entity mentions (customers, products, invoices, etc).

    Simple keyword-based extraction. TODO: NER model for better extraction.
    """
    entities = []
    entity_keywords = {
        "customer": ["customer", "client", "user"],
        "product": ["product", "item", "sku"],
        "invoice": ["invoice", "bill", "receipt"],
        "payment": ["payment", "transaction", "charge"],
        "order": ["order", "purchase"],
    }

    q_lower = question.lower()
    for entity_type, keywords in entity_keywords.items():
        if any(kw in q_lower for kw in keywords):
            entities.append(entity_type)

    return entities


def _extract_metrics(question: str) -> List[str]:
    """
    Extract metric mentions (revenue, count, average, etc).
    """
    metrics = []
    metric_keywords = {
        "revenue": ["revenue", "sales", "income"],
        "count": ["count", "number of", "how many"],
        "average": ["average", "mean", "avg"],
        "total": ["total", "sum"],
        "percentage": ["percentage", "percent", "rate"],
    }

    q_lower = question.lower()
    for metric_type, keywords in metric_keywords.items():
        if any(kw in q_lower for kw in keywords):
            metrics.append(metric_type)

    return metrics


def _extract_time_range(question: str) -> Optional[str]:
    """
    Extract time range mentions (monthly, yearly, last quarter, etc).
    """
    q_lower = question.lower()

    time_patterns = {
        "monthly": ["monthly", "per month", "each month", "by month"],
        "yearly": ["yearly", "per year", "annual", "by year"],
        "quarterly": ["quarterly", "per quarter", "by quarter"],
        "weekly": ["weekly", "per week", "by week"],
        "daily": ["daily", "per day", "by day"],
    }

    for time_type, keywords in time_patterns.items():
        if any(kw in q_lower for kw in keywords):
            return time_type

    # Check for specific ranges
    if any(kw in q_lower for kw in ["last month", "this month", "past month"]):
        return "last_month"
    if any(kw in q_lower for kw in ["last year", "this year", "past year"]):
        return "last_year"

    return None


def _detect_aggregation_need(question: str) -> bool:
    """
    Detect if question requires aggregation (GROUP BY, SUM, COUNT, etc).
    """
    q_lower = question.lower()
    aggregation_indicators = [
        "total",
        "sum",
        "count",
        "average",
        "avg",
        "max",
        "min",
        "performance",
        "metric",
        "per",
        "by",
        "distribution",
        "breakdown",
        "each",
        "monthly",
        "yearly",
    ]
    return any(ind in q_lower for ind in aggregation_indicators)


def _detect_join_need(question: str, agent_config: AgentConfig) -> bool:
    """
    Detect if question might require joining tables.

    Heuristic: mentions multiple entity types or relationships.
    """
    q_lower = question.lower()

    # Count how many table names are mentioned
    tables_mentioned = sum(
        1 for table in agent_config.tables if table.logical_name.lower() in q_lower
    )

    # If 2+ tables mentioned, likely needs JOIN
    if tables_mentioned >= 2:
        return True

    # Check for relationship keywords
    relationship_keywords = ["with", "and", "related", "associated", "linked"]
    if any(kw in q_lower for kw in relationship_keywords):
        # And multiple entities mentioned
        entities = _extract_entities(question)
        if len(entities) >= 2:
            return True

    return False


# ============================================================================
# Token Estimation & Truncation
# ============================================================================


def _estimate_bundle_tokens(bundle: ContextBundle) -> int:
    """
    Estimate token count for entire bundle.

    Rough heuristic: 1 token ≈ 4 characters (conservative for CPU models).
    """
    total_chars = 0

    # User context (minimal)
    total_chars += len(bundle.user.platform_role) + len(bundle.user.crew_role)

    # Crew context
    total_chars += sum(len(ds) for ds in bundle.crew.allowed_datasets)

    # Query context
    total_chars += sum(len(e) for e in bundle.query.entities)
    total_chars += sum(len(m) for m in bundle.query.metrics)

    # Data context (table names only, not full schemas)
    total_chars += sum(len(t.logical_name) for t in bundle.data.tables)

    # Historical context (largest component)
    total_chars += sum(len(chunk) for chunk in bundle.historical.schema_rag)
    total_chars += sum(len(chunk) for chunk in bundle.historical.metrics_rag)
    total_chars += sum(len(chunk) for chunk in bundle.historical.questions_rag)
    total_chars += sum(len(chunk) for chunk in bundle.historical.comments_rag)
    total_chars += sum(len(chunk) for chunk in bundle.historical.glossary_rag)
    total_chars += sum(len(chunk) for chunk in bundle.historical.catalog_rag)
    total_chars += sum(len(chunk) for chunk in bundle.historical.analytics_rag)
    total_chars += sum(len(chunk) for chunk in bundle.historical.strategy_rag)
    total_chars += sum(len(chunk) for chunk in bundle.historical.governance_rag)
    total_chars += sum(len(chunk) for chunk in bundle.historical.enterprise_rag)
    total_chars += sum(len(chunk) for chunk in bundle.historical.signals_rag)

    # Chat history
    for msg in bundle.historical.chat_history:
        total_chars += len(msg.get("content", ""))

    # Convert to tokens (1 token ≈ 4 chars)
    estimated_tokens = total_chars // 4

    return estimated_tokens


def _truncate_bundle(bundle: ContextBundle, max_tokens: int) -> ContextBundle:
    """
    Truncate bundle to fit within token budget.

    Priority order:
    1. User/Crew context (never truncate)
    2. Query context (never truncate)
    3. Data context (never truncate table list)
    4. Historical RAG layers (truncate in priority order)

    RAG truncation priority: schema > questions > metrics > comments > glossary
    """
    truncation_details = {}

    # Calculate current tokens
    current_tokens = _estimate_bundle_tokens(bundle)
    tokens_to_remove = current_tokens - max_tokens

    if tokens_to_remove <= 0:
        return bundle

    # Truncate RAG layers in reverse priority order

    # 1. Signals (lowest priority for SQL matching)
    if bundle.historical.signals_rag and tokens_to_remove > 0:
        removed = len(bundle.historical.signals_rag)
        bundle.historical.signals_rag = []
        tokens_to_remove -= removed * 50
        truncation_details["signals_rag"] = f"removed {removed} chunks"

    # 2. Enterprise
    if bundle.historical.enterprise_rag and tokens_to_remove > 0:
        removed = len(bundle.historical.enterprise_rag)
        bundle.historical.enterprise_rag = []
        tokens_to_remove -= removed * 50
        truncation_details["enterprise_rag"] = f"removed {removed} chunks"

    # 3. Catalog
    if bundle.historical.catalog_rag and tokens_to_remove > 0:
        removed = len(bundle.historical.catalog_rag)
        bundle.historical.catalog_rag = []
        tokens_to_remove -= removed * 50
        truncation_details["catalog_rag"] = f"removed {removed} chunks"

    # 4. Glossary
    if bundle.historical.glossary_rag and tokens_to_remove > 0:
        removed = len(bundle.historical.glossary_rag)
        bundle.historical.glossary_rag = []
        tokens_to_remove -= removed * 50  # Assume ~50 tokens per chunk
        truncation_details["glossary_rag"] = f"removed {removed} chunks"

    # 5. Comments
    if bundle.historical.comments_rag and tokens_to_remove > 0:
        removed = len(bundle.historical.comments_rag)
        bundle.historical.comments_rag = []
        tokens_to_remove -= removed * 40
        truncation_details["comments_rag"] = f"removed {removed} chunks"

    # 6. Analytics (Lineage/Quality)
    if bundle.historical.analytics_rag and tokens_to_remove > 0:
        removed = len(bundle.historical.analytics_rag)
        bundle.historical.analytics_rag = []
        tokens_to_remove -= removed * 50
        truncation_details["analytics_rag"] = f"removed {removed} chunks"

    # 7. Metrics (keep top 1)
    if len(bundle.historical.metrics_rag) > 1 and tokens_to_remove > 0:
        removed = len(bundle.historical.metrics_rag) - 1
        bundle.historical.metrics_rag = bundle.historical.metrics_rag[:1]
        tokens_to_remove -= removed * 60
        truncation_details["metrics_rag"] = f"kept 1/{removed + 1} chunks"

    # 8. Questions (keep top 2)
    if len(bundle.historical.questions_rag) > 2 and tokens_to_remove > 0:
        removed = len(bundle.historical.questions_rag) - 2
        bundle.historical.questions_rag = bundle.historical.questions_rag[:2]
        tokens_to_remove -= removed * 70
        truncation_details["questions_rag"] = f"kept 2/{removed + 2} chunks"

    # 9. Strategy (OKRs/Goals)
    if bundle.historical.strategy_rag and tokens_to_remove > 0:
        removed = len(bundle.historical.strategy_rag)
        bundle.historical.strategy_rag = []
        tokens_to_remove -= removed * 50
        truncation_details["strategy_rag"] = f"removed {removed} chunks"

    # 10. Governance (highly sensitive, try to keep)
    if len(bundle.historical.governance_rag) > 1 and tokens_to_remove > 0:
        removed = len(bundle.historical.governance_rag) - 1
        bundle.historical.governance_rag = bundle.historical.governance_rag[:1]
        tokens_to_remove -= removed * 50
        truncation_details["governance_rag"] = f"kept 1/{removed + 1} chunks"

    # Schema (keep top 2) - highest priority, truncate last
    if len(bundle.historical.schema_rag) > 2 and tokens_to_remove > 0:
        removed = len(bundle.historical.schema_rag) - 2
        bundle.historical.schema_rag = bundle.historical.schema_rag[:2]
        tokens_to_remove -= removed * 50
        truncation_details["schema_rag"] = f"kept 2/{removed + 2} chunks"

    # Chat history (keep top 2)
    if len(bundle.historical.chat_history) > 2 and tokens_to_remove > 0:
        removed = len(bundle.historical.chat_history) - 2
        bundle.historical.chat_history = bundle.historical.chat_history[-2:]
        truncation_details["chat_history"] = f"kept 2/{removed + 2} messages"

    bundle.truncation_details = truncation_details
    bundle.total_tokens_estimate = _estimate_bundle_tokens(bundle)

    log_event(
        "context_bundle_truncated",
        {
            "original_tokens": current_tokens,
            "target_tokens": max_tokens,
            "final_tokens": bundle.total_tokens_estimate,
            "truncation_details": truncation_details,
        },
    )

    return bundle
