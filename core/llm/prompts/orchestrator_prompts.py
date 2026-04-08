"""
Orchestrator Prompt Builder

Creates prompts for table routing agent (phi3:mini).
Optimized for fast CPU inference (~1-2s).
"""
from __future__ import annotations

from typing import Dict, List, Tuple
from core.llm.context.models import ContextBundle
from core.llm.context.serializers import serialize_for_prompt


def build_orchestrator_prompt(
    context_bundle: ContextBundle,
    question: str,
    tables_summary: str,
    relationships_info: str = ""
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Build orchestrator prompt optimized for phi3:mini on CPU.
    
    Goal: Choose the correct table(s) for the user's question.
    
    Optimizations for small models:
    - Clear role definition
    - Explicit bullet-point rules
    - Constrained output format
    - Minimal narrative fluff
    
    Args:
        context_bundle: Structured context with all layers
        question: User's question
        tables_summary: Text summary of available tables
        relationships_info: Optional info about table relationships
        
    Returns:
        Tuple of (system_msg, user_msg) dicts
    """
    
    # Serialize context (agent-specific)
    context_text = serialize_for_prompt(context_bundle, "orchestrator")
    
    # SYSTEM PROMPT: Define behavior (static, explicit)
    system_msg = {
        "role": "system",
        "content": (
            "TABLE ROUTER (phi3:mini)\n\n"
            "TASK: Choose which table(s) to use for the question.\n\n"
            "RULES:\n"
            "1. Output ONLY table name(s)\n"
            "2. For single table: output name (e.g., 'invoices')\n"
            "3. For multiple tables: comma-separated (e.g., 'invoices, customers')\n"
            "4. Use logical names from the list\n"
            "5. If question needs multiple tables, choose 2-3 (not all)\n"
            "6. Prioritize tables mentioned in context or relationships\n\n"
            "OUTPUT FORMAT:\n"
            "table_name\n"
            "OR\n"
            "table1, table2\n"
        )
    }
    
    # USER PROMPT: Inject context + question
    user_msg = {
        "role": "user",
        "content": (
            f"{context_text}\n\n"
            f"AVAILABLE TABLES:\n{tables_summary}\n\n"
            f"{relationships_info}\n\n" if relationships_info else ""
            f"QUESTION: {question}\n\n"
            "OUTPUT:"
        )
    }
    
    return system_msg, user_msg


def build_orchestrator_prompt_legacy(
    question: str,
    tables_summary: str,
    context_block: str = "",
    instructions_block: str = "",
    role_context_block: str = "",
    relationships_info: str = ""
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Legacy prompt builder for backward compatibility.
    
    Used when context_bundle is disabled (settings.use_context_bundle=False).
    This mirrors the old orchestrator.py prompt structure.
    """
    system_msg = {
        "role": "system",
        "content": (
            f"{role_context_block}"
            "You are a routing assistant. Your job is to choose ONE OR MORE logical tables "
            "from the list to answer the user's question.\n\n"
            "Rules:\n"
            "- You can choose ONE or MULTIPLE logical table names from the list.\n"
            "- If the question requires data from multiple tables (e.g., comparing data, "
            "  relating entities, aggregating across tables), choose MULTIPLE tables.\n"
            "- If the question can be answered with a single table, choose ONE table.\n"
            "- Answer with ONLY the logical table name(s), separated by commas if multiple.\n"
            "- Example responses: 'table1' or 'table1, table2' or 'orders, products, categories'\n"
            "- Use the additional semantic context and available relationships to make the best choice.\n"
            f"{relationships_info}\n"
            f"{instructions_block}"
        ),
    }

    user_msg = {
        "role": "user",
        "content": (
            f"User question:\n{question}\n\n"
            f"Available tables:\n{tables_summary}"
            f"{context_block}\n"
            f"{relationships_info}\n"
            "\nRespond with the logical table name(s) needed, separated by commas if multiple "
            "(for example: 'table1' or 'table1, table2' or 'orders, products')."
        ),
    }
    
    return system_msg, user_msg
