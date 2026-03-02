"""
Context Serializers for Prompt Generation

Converts ContextBundle into text blocks for LLM prompts.
Different serialization strategies per agent type (orchestrator, specialist, formatter).
"""
from __future__ import annotations

from typing import Dict, List
from core.llm.context.models import ContextBundle

# Token budget allocations per agent type
TOKEN_BUDGETS: Dict[str, Dict[str, int]] = {
    "orchestrator": {
        "system_prompt": 500,
        "schema_rag": 400,
        "metrics_rag": 300,
        "questions_rag": 300,
        "comments_rag": 100,
        "glossary_rag": 100,
        "user_question": 200,
        "table_list": 400,
        "total_limit": 2400
    },
    "specialist": {
        "system_prompt": 600,
        "schema_rag": 600,  # Most important for SQL generation
        "metrics_rag": 400,
        "questions_rag": 400,
        "comments_rag": 200,
        "glossary_rag": 100,
        "user_question": 200,
        "table_schema": 800,
        "total_limit": 3300
    },
    "formatter": {
        "system_prompt": 300,
        "user_question": 200,
        "data_preview": 800,
        "total_limit": 1500
    }
}


def serialize_for_prompt(bundle: ContextBundle, agent_type: str) -> str:
    """
    Serialize context bundle into prompt text.
    
    Args:
        bundle: ContextBundle to serialize
        agent_type: Type of agent (orchestrator, specialist, formatter)
        
    Returns:
        Formatted context text ready to inject into prompt
        
    Different strategies per agent:
        - orchestrator: Focus on tables, relationships, and query intent
        - specialist: Focus on schema details, past SQL queries, metrics
        - formatter: Minimal context (just query intent)
    """
    if agent_type == "orchestrator":
        return _serialize_for_orchestrator(bundle)
    elif agent_type == "specialist":
        return _serialize_for_specialist(bundle)
    elif agent_type == "formatter":
        return _serialize_for_formatter(bundle)
    else:
        # Default: full serialization
        return _serialize_full(bundle)


def _serialize_for_orchestrator(bundle: ContextBundle) -> str:
    """
    Serialize for orchestrator (table routing).
    
    Needs:
    - Query intent and characteristics
    - Available tables and relationships
    - Schema-level RAG for table semantics
    - Past similar questions
    """
    parts = []
    
    # User role context (affects table selection - admins might prefer financial tables)
    if bundle.user.platform_role == "admin":
        parts.append("[USER ROLE: Executive/Admin - prioritize strategic metrics]")
    elif bundle.user.crew_role == "commander":
        parts.append("[USER ROLE: Commander - prioritize analytical insights]")
    
    # Query characteristics
    intent_line = f"[INTENT: {bundle.query.intent.upper()}]"
    if bundle.query.requires_aggregation:
        intent_line += " [AGGREGATION REQUIRED]"
    if bundle.query.requires_joins:
        intent_line += " [MULTI-TABLE QUERY]"
    parts.append(intent_line)
    
    # Detected entities/metrics (helps choose tables)
    if bundle.query.entities:
        parts.append(f"[ENTITIES: {', '.join(bundle.query.entities)}]")
    if bundle.query.metrics:
        parts.append(f"[METRICS: {', '.join(bundle.query.metrics)}]")
        
    # SÓ INJETA SE TIVER DADO RELEVANTE!
    
    # Strategy RAG (High-Level Intent/Objectives)
    if bundle.historical.strategy_rag:
        parts.append("\n[BUSINESS OBJECTIVES & OKRs]")
        for chunk in bundle.historical.strategy_rag[:1]:
            parts.append(f"- {chunk}")

    # Governance (Access limits, compliance)
    if bundle.historical.governance_rag:
        parts.append("\n[GOVERNANCE & COMPLIANCE WARNING]")
        for chunk in bundle.historical.governance_rag[:1]:
            parts.append(f"- {chunk}")

    # Signals (Macro Events)
    if bundle.historical.signals_rag:
        parts.append("\n[MARKET SIGNALS & EVENTS]")
        for chunk in bundle.historical.signals_rag[:1]:
            parts.append(f"- {chunk}")
    
    # Schema RAG (table semantics)
    if bundle.historical.schema_rag:
        parts.append("\n[SCHEMA CONTEXT]")
        for chunk in bundle.historical.schema_rag[:3]:  # Top 3
            parts.append(f"- {chunk}")
    
    # Questions RAG (similar routing decisions)
    if bundle.historical.questions_rag:
        parts.append("\n[SIMILAR PAST QUERIES]")
        for chunk in bundle.historical.questions_rag[:2]:  # Top 2
            parts.append(f"- {chunk}")
    
    # Relationship hints
    if bundle.data.relationships and len(bundle.data.tables) > 1:
        parts.append(f"\n[AVAILABLE: {len(bundle.data.relationships)} table relationships for JOINs]")
    
    return "\n".join(parts)


def _serialize_for_specialist(bundle: ContextBundle) -> str:
    """
    Serialize for specialist (SQL generation).
    
    Needs:
    - Query intent (aggregation, joins)
    - Schema RAG (column semantics, data types)
    - Metrics RAG (calculation formulas)
    - Questions RAG (similar SQL patterns)
    - Comments RAG (user corrections about column usage)
    """
    parts = []
    
    # Minimal user context (specialist doesn't need full role details)
    parts.append(f"[USER ROLE: {bundle.user.platform_role}]")
    
    # Query characteristics (critical for SQL generation)
    if bundle.query.requires_aggregation:
        parts.append("[AGGREGATION REQUIRED: Use GROUP BY with SUM/COUNT/AVG]")
    if bundle.query.requires_joins:
        parts.append("[MULTI-TABLE: Use JOINs to combine data]")
    if bundle.query.time_range:
        parts.append(f"[TIME RANGE: {bundle.query.time_range}]")
        
    # Analytics / Lineage RAG (Data quality warnings)
    if bundle.historical.analytics_rag:
        parts.append("\n[DATA QUALITY & LINEAGE WARNING]")
        for chunk in bundle.historical.analytics_rag[:1]:
            parts.append(f"- ATENÇÃO: {chunk}")
            
    # Enterprise Graph (Systemic dependencies)
    if bundle.historical.enterprise_rag:
        parts.append("\n[SYSTEMIC DEPENDENCIES]")
        for chunk in bundle.historical.enterprise_rag[:1]:
            parts.append(f"- {chunk}")

    # Governance & Permissions (CRITICAL FOR SQL GENERATION)
    if bundle.historical.governance_rag:
        parts.append("\n[SECURITY & GOVERNANCE POLICIES]")
        for chunk in bundle.historical.governance_rag: # Injeta TODAS as políticas de gov retidas
            parts.append(f"- {chunk}")

    # Catalog RAG (Connection issues/infra context)
    if bundle.historical.catalog_rag:
        parts.append("\n[DATA CATALOG & INFRASTRUCTURE]")
        for chunk in bundle.historical.catalog_rag[:1]:
            parts.append(f"- {chunk}")
    
    # Schema RAG (most important for SQL)
    if bundle.historical.schema_rag:
        parts.append("\n[SCHEMA SEMANTICS]")
        for chunk in bundle.historical.schema_rag[:3]:
            parts.append(f"- {chunk}")
    
    # Metrics RAG (calculation formulas)
    if bundle.historical.metrics_rag:
        parts.append("\n[BUSINESS METRICS]")
        for chunk in bundle.historical.metrics_rag[:2]:
            parts.append(f"- {chunk}")
    
    # Questions RAG (SQL patterns)
    if bundle.historical.questions_rag:
        parts.append("\n[SIMILAR SQL PATTERNS]")
        for chunk in bundle.historical.questions_rag[:2]:
            parts.append(f"- {chunk}")
    
    # Comments RAG (critical corrections)
    if bundle.historical.comments_rag:
        parts.append("\n[USER CLARIFICATIONS]")
        for chunk in bundle.historical.comments_rag[:1]:
            parts.append(f"- {chunk}")
    
    # Glossary RAG (terminology)
    if bundle.historical.glossary_rag:
        parts.append("\n[TERMINOLOGY]")
        for chunk in bundle.historical.glossary_rag[:2]:
            parts.append(f"- {chunk}")
    
    return "\n".join(parts)


def _serialize_for_formatter(bundle: ContextBundle) -> str:
    """
    Serialize for formatter (natural language generation).
    
    Needs:
    - Minimal context (just query intent)
    - User language preference
    - Formatter focuses on data, not context
    """
    parts = []
    
    # User locale for language
    if bundle.user.locale != "en":
        parts.append(f"[LANGUAGE: {bundle.user.locale}]")
    
    # Query intent (affects tone)
    if bundle.query.intent == "comparative":
        parts.append("[FORMAT: Highlight comparisons and differences]")
    elif bundle.query.intent == "analytical":
        parts.append("[FORMAT: Provide insights and trends]")
    
    return "\n".join(parts) if parts else ""


def _serialize_full(bundle: ContextBundle) -> str:
    """
    Full serialization (for debugging or future use).
    
    Includes all context layers.
    """
    parts = []
    
    # User context
    parts.append(f"[USER: {bundle.user.user_id} | Role: {bundle.user.platform_role}/{bundle.user.crew_role}]")
    
    # Crew context
    if bundle.crew.crew_ids:
        parts.append(f"[CREW: {', '.join(bundle.crew.crew_ids)}]")
    parts.append(f"[ALLOWED DATASETS: {', '.join(bundle.crew.allowed_datasets)}]")
    
    # Query context
    parts.append(f"\n[QUERY ANALYSIS]")
    parts.append(f"- Intent: {bundle.query.intent}")
    parts.append(f"- Entities: {', '.join(bundle.query.entities) if bundle.query.entities else 'none'}")
    parts.append(f"- Metrics: {', '.join(bundle.query.metrics) if bundle.query.metrics else 'none'}")
    parts.append(f"- Time Range: {bundle.query.time_range or 'none'}")
    parts.append(f"- Requires Aggregation: {bundle.query.requires_aggregation}")
    parts.append(f"- Requires Joins: {bundle.query.requires_joins}")
    
    # Data context
    parts.append(f"\n[DATA CONTEXT]")
    parts.append(f"- Tables: {bundle.data.total_tables}")
    parts.append(f"- Relationships: {len(bundle.data.relationships)}")
    parts.append(f"- Freshness: {bundle.data.context_freshness}")
    
    # Historical context
    parts.append(f"\n[HISTORICAL CONTEXT]")
    parts.append(f"- Schema RAG: {len(bundle.historical.schema_rag)} chunks")
    parts.append(f"- Metrics RAG: {len(bundle.historical.metrics_rag)} chunks")
    parts.append(f"- Questions RAG: {len(bundle.historical.questions_rag)} chunks")
    parts.append(f"- Comments RAG: {len(bundle.historical.comments_rag)} chunks")
    parts.append(f"- Glossary RAG: {len(bundle.historical.glossary_rag)} chunks")
    parts.append(f"- Catalog RAG: {len(bundle.historical.catalog_rag)} chunks")
    parts.append(f"- Analytics RAG: {len(bundle.historical.analytics_rag)} chunks")
    parts.append(f"- Strategy RAG: {len(bundle.historical.strategy_rag)} chunks")
    parts.append(f"- Governance RAG: {len(bundle.historical.governance_rag)} chunks")
    parts.append(f"- Enterprise RAG: {len(bundle.historical.enterprise_rag)} chunks")
    parts.append(f"- Signals RAG: {len(bundle.historical.signals_rag)} chunks")
    parts.append(f"- Chat History: {len(bundle.historical.chat_history)} messages")
    
    # Token info
    parts.append(f"\n[METADATA]")
    parts.append(f"- Estimated Tokens: {bundle.total_tokens_estimate}")
    parts.append(f"- Truncated: {bundle.is_truncated}")
    if bundle.truncation_details:
        parts.append(f"- Truncation Details: {bundle.truncation_details}")
    
    return "\n".join(parts)


def get_token_budget(agent_type: str) -> Dict[str, int]:
    """
    Get token budget configuration for a specific agent type.
    
    Args:
        agent_type: Type of agent (orchestrator, specialist, formatter)
        
    Returns:
        Dictionary with token allocations per component
    """
    return TOKEN_BUDGETS.get(agent_type, TOKEN_BUDGETS["specialist"])


def estimate_serialized_tokens(text: str) -> int:
    """
    Estimate token count for serialized text.
    
    Uses simple heuristic: 1 token ≈ 4 characters.
    More accurate tokenization would require tiktoken library.
    """
    return len(text) // 4
