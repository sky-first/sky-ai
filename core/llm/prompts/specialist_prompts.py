"""
Specialist Prompt Builder

Creates prompts for SQL generation agent (sqlcoder:7b).
Optimized for deterministic SQL output with 8-12s latency on CPU.
"""
from __future__ import annotations

from typing import Dict, List, Tuple, Optional
from core.llm.context.models import ContextBundle
from core.llm.context.serializers import serialize_for_prompt
from core.agents.generic_sql_agent import TableSchema
from core.dialects import Dialect


def build_specialist_prompt(
    context_bundle: ContextBundle,
    table_schema: TableSchema,
    question: str,
    dialect: Dialect = Dialect.POSTGRES,
    max_limit: int = 100,
    max_columns: int = 10,
    use_multiple_tables: bool = False,
    schema_text: str = "",
    join_info: str = ""
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Build specialist prompt optimized for sqlcoder:7b on CPU.
    
    Goal: Generate valid, secure SQL for the user's question.
    
    Optimizations for small models:
    - Extremely explicit security rules (mandatory constraints)
    - Structured output format (SQL or IMPOSSIBLE)
    - Context-aware hints (aggregation, joins, temporal)
    - No ambiguity or narrative
    
    Args:
        context_bundle: Structured context with RAG layers
        table_schema: Primary table schema
        question: User's question
        dialect: SQL dialect (POSTGRES or BIGQUERY)
        max_limit: Maximum LIMIT value
        max_columns: Maximum columns allowed
        use_multiple_tables: Whether query can use JOINs
        schema_text: Detailed schema text (fallback if not in bundle)
        join_info: JOIN relationship information
        
    Returns:
        Tuple of (system_msg, user_msg) dicts
    """
    
    # Serialize context (specialist-specific)
    context_text = serialize_for_prompt(context_bundle, "specialist")
    
    # Detect query characteristics from context
    requires_aggregation = context_bundle.query.requires_aggregation
    requires_joins = use_multiple_tables or context_bundle.query.requires_joins
    
    # Build security rules (CRITICAL for CPU models - be explicit)
    security_rules = (
        "🔴 MANDATORY SECURITY RULES (NON-NEGOTIABLE):\n\n"
        f"1. LIMIT RULE: If the user asks for a specific count (e.g. 'top 5', 'last 3'),\n"
        f"   use exactly that number as the LIMIT. Otherwise end with LIMIT {max_limit}.\n"
        f"   NEVER add a second LIMIT if one is already in the query.\n"
        f"   Example (top 5): SELECT name, SUM(amt) FROM t GROUP BY name ORDER BY 2 DESC LIMIT 5\n"
        f"   Example (no count): SELECT year, SUM(amt) FROM t GROUP BY year LIMIT {max_limit}\n\n"
        f"2. NEVER use SELECT * - specify columns (max {max_columns})\n\n"
        "3. FORBIDDEN:\n"
        "   - UNION / UNION ALL\n"
        "   - Multiple queries (only ONE SELECT)\n"
        "   - Semicolons (except at end)\n"
        "   - Comments (-- or /* */)\n"
        "   - System tables (INFORMATION_SCHEMA, pg_catalog, sys, mysql)\n"
        "   - Write operations (DROP, DELETE, UPDATE, INSERT, ALTER, CREATE)\n\n"
        "4. If you cannot follow these rules, respond:\n"
        "   IMPOSSIBLE: <reason>\n\n"
    )
    
    # Build query guidance based on context
    query_guidance = ""
    if requires_aggregation:
        query_guidance += (
            "📊 AGGREGATION REQUIRED:\n"
            "- Use GROUP BY with SUM/COUNT/AVG/MAX/MIN\n"
            "- DO NOT use SELECT * LIMIT when aggregation is needed\n"
            "- Look for date/time columns to group by temporal ranges\n\n"
        )
    
    if requires_joins:
        query_guidance += (
            "🔗 MULTI-TABLE QUERY:\n"
            "- Use INNER JOIN to combine tables\n"
            "- Follow the provided JOIN relationships\n"
            "- Qualify all columns with table aliases (t1.column)\n\n"
        )
    
    # Temporal filter guidance
    temporal_warning = (
        "⚠️ TEMPORAL FILTERS:\n"
        "- You MAY use WHERE with date filters (CURRENT_DATE, NOW(), INTERVAL, etc.)\n"
        "- For a period: WHERE date_col >= CURRENT_DATE - INTERVAL 'N days'\n"
        "- For aggregation over time: use WHERE for the range + GROUP BY for the breakdown\n"
        "- NEVER mix aggregate functions (SUM/COUNT) with ORDER BY on a non-grouped column\n"
        "  BAD: SELECT SUM(amt) FROM t ORDER BY created_at DESC LIMIT 7  -- GroupingError\n"
        "  GOOD: SELECT SUM(amt) FROM t WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'\n\n"
    )
    
    # Column selection guidance
    column_guidance = (
        "📋 COLUMN SELECTION:\n"
        "- Prefer human-readable columns (*_name, *_label, *_desc) over IDs\n"
        "- For status/category: use descriptive columns, not numeric codes\n\n"
    )
    
    # SYSTEM PROMPT: Behavior definition
    system_msg = {
        "role": "system",
        "content": (
            f"SQL GENERATOR (sqlcoder:7b)\n"
            f"DIALECT: {dialect.value}\n\n"
            f"{security_rules}"
            f"{query_guidance}"
            f"{temporal_warning}"
            f"{column_guidance}"
            "OUTPUT FORMAT:\n"
            "Valid SQL query\n"
            "OR\n"
            "IMPOSSIBLE: <specific reason>\n"
        )
    }
    
    # USER PROMPT: Context + schema + question
    user_msg = {
        "role": "user",
        "content": (
            f"{context_text}\n\n"
            f"SCHEMA:\n{schema_text}\n\n"
            f"{join_info}\n\n" if join_info else ""
            f"QUESTION: {question}\n\n"
            "OUTPUT SQL:"
        )
    }
    
    return system_msg, user_msg


def _build_compact_schema(table_schema: TableSchema, max_columns: int = 15) -> str:
    """
    Build compact schema representation for CPU models.
    
    Limits columns to save tokens while preserving essential info.
    """
    lines = []
    lines.append(f"TABLE: {table_schema.physical_name}")
    lines.append("COLUMNS:")
    
    # Show first N columns
    cols = table_schema.columns[:max_columns] if hasattr(table_schema, 'columns') else []
    for col in cols:
        if isinstance(col, dict):
            name = col.get("name", "")
            col_type = col.get("type", "")
            nullable = " (nullable)" if col.get("nullable") else ""
            lines.append(f"  - {name} {col_type}{nullable}")
        else:
            # Column object
            name = getattr(col, "name", "")
            col_type = getattr(col, "type", "")
            lines.append(f"  - {name} {col_type}")
    
    if len(table_schema.columns) > max_columns:
        lines.append(f"  ... ({len(table_schema.columns) - max_columns} more columns)")
    
    return "\n".join(lines)
