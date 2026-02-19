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
    
    # 1. USER CONTEXT
    user_ctx = UserContext(
        user_id=state.get("user_id", ""),
        platform_role=state.get("platform_role", "user"),
        crew_role=state.get("crew_role", "guest"),
        role_label=state.get("role_label"), # New field for display roles like CFO
        locale=state.get("locale", "en"),
        permissions=state.get("permissions", [])
    )
    
    # 2. CREW CONTEXT
    crew_ctx = CrewContext(
        crew_ids=state.get("crew_ids", []),
        allowed_datasets=[t.logical_name for t in agent_config.tables],
        restricted_domains=[]  # TODO: Implement domain restrictions
    )
    
    # 3. QUERY CONTEXT
    query_ctx = QueryContext(
        intent=_detect_intent(question),
        entities=_extract_entities(question),
        metrics=_extract_metrics(question),
        time_range=_extract_time_range(question),
        requires_aggregation=_detect_aggregation_need(question),
        requires_joins=_detect_join_need(question, agent_config)
    )
    
    # 4. DATA CONTEXT
    data_ctx = DataContext(
        tables=agent_config.tables,
        relationships=detect_relationships(agent_config.tables),
        total_tables=len(agent_config.tables),
        context_freshness="live"
    )
    
    # 5. HISTORICAL CONTEXT (Multi-layer RAG — execução PARALELA)
    try:
        from core.rag.multi_layer import retrieve_all_layers_sync

        # Get embedding provider from state if available
        embedding_provider = state.get("_embedding_provider")
        space_id = state.get("space_id")

        if embedding_provider:
            # Executa as 5 camadas em paralelo via asyncio.gather
            rag_results = retrieve_all_layers_sync(
                question=question,
                tables=agent_config.tables,
                embedding_provider=embedding_provider,
                db=db,
                space_id=space_id,
            )
        else:
            rag_results = {
                "schema_rag": [],
                "metrics_rag": [],
                "questions_rag": [],
                "comments_rag": [],
                "glossary_rag": [],
            }

        historical_ctx = HistoricalContext(
            schema_rag=rag_results["schema_rag"],
            metrics_rag=rag_results["metrics_rag"],
            questions_rag=rag_results["questions_rag"],
            comments_rag=rag_results["comments_rag"],
            glossary_rag=rag_results["glossary_rag"],
            chat_history=state.get("chat_history", [])[-4:]  # Last 4 messages only
        )

        log_event(
            "multi_layer_rag_retrieved",
            {
                "schema_chunks": len(historical_ctx.schema_rag),
                "metrics_chunks": len(historical_ctx.metrics_rag),
                "questions_chunks": len(historical_ctx.questions_rag),
                "comments_chunks": len(historical_ctx.comments_rag),
                "glossary_chunks": len(historical_ctx.glossary_rag),
                "total_chunks": historical_ctx.total_chunks(),
            }
        )
    except Exception as e:
        # Fallback to simple retrieval context
        log_event(
            "multi_layer_rag_error",
            {"error": str(e)[:300]}
        )
        retrieval_chunks = state.get("retrieval_context", [])
        historical_ctx = HistoricalContext(
            schema_rag=retrieval_chunks[:3] if retrieval_chunks else [],
            chat_history=state.get("chat_history", [])[-4:]
        )
    
    # Create bundle
    bundle = ContextBundle(
        user=user_ctx,
        crew=crew_ctx,
        query=query_ctx,
        data=data_ctx,
        historical=historical_ctx
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
            }
        }
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
        "performance", "metric", "trend", "analysis", "kpi",
        "total", "sum", "average", "count", "calculate"
    ]
    if any(kw in q_lower for kw in analytical_keywords):
        return "analytical"
    
    # Comparative patterns
    comparative_keywords = [
        "compare", "vs", "versus", "difference", "better", "worse",
        "month-over-month", "year-over-year", "increase", "decrease"
    ]
    if any(kw in q_lower for kw in comparative_keywords):
        return "comparative"
    
    # Operational patterns
    operational_keywords = [
        "status", "current", "now", "today", "latest", "recent",
        "active", "pending", "failed"
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
        "total", "sum", "count", "average", "avg", "max", "min",
        "performance", "metric", "per", "by",
        "distribution", "breakdown", "each", "monthly", "yearly"
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
        1 for table in agent_config.tables
        if table.logical_name.lower() in q_lower
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
    # Start with glossary (lowest priority)
    if bundle.historical.glossary_rag and tokens_to_remove > 0:
        removed = len(bundle.historical.glossary_rag)
        bundle.historical.glossary_rag = []
        tokens_to_remove -= removed * 50  # Assume ~50 tokens per chunk
        truncation_details["glossary_rag"] = f"removed {removed} chunks"
    
    # Comments
    if bundle.historical.comments_rag and tokens_to_remove > 0:
        removed = len(bundle.historical.comments_rag)
        bundle.historical.comments_rag = []
        tokens_to_remove -= removed * 40
        truncation_details["comments_rag"] = f"removed {removed} chunks"
    
    # Metrics (keep top 1)
    if len(bundle.historical.metrics_rag) > 1 and tokens_to_remove > 0:
        removed = len(bundle.historical.metrics_rag) - 1
        bundle.historical.metrics_rag = bundle.historical.metrics_rag[:1]
        tokens_to_remove -= removed * 60
        truncation_details["metrics_rag"] = f"kept 1/{removed + 1} chunks"
    
    # Questions (keep top 2)
    if len(bundle.historical.questions_rag) > 2 and tokens_to_remove > 0:
        removed = len(bundle.historical.questions_rag) - 2
        bundle.historical.questions_rag = bundle.historical.questions_rag[:2]
        tokens_to_remove -= removed * 70
        truncation_details["questions_rag"] = f"kept 2/{removed + 2} chunks"
    
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
        }
    )
    
    return bundle
