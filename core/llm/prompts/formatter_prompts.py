"""
Formatter Prompt Builder

Creates prompts for natural language response generation (phi3:mini).
Optimized for fast, conversational output (~1-2s on CPU).
"""
from __future__ import annotations

from typing import Dict, List, Tuple
from core.llm.context.models import ContextBundle
from core.llm.context.serializers import serialize_for_prompt


def build_formatter_prompt(
    context_bundle: ContextBundle,
    question: str,
    sql: str,
    data_preview: str,
    stats_summary: Optional[str] = None,
    has_data: bool = True,
    is_impossible: bool = False,
    impossible_reason: str = "",
    response_format: Optional[str] = None,
    length_guidance: Optional[str] = None,
    extra_instructions: Optional[str] = None
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Build formatter prompt optimized for both OpenAI and local models.
    
    Goal: Convert SQL results into conversational natural language.
    
    Args:
        context_bundle: Structured context
        question: User's original question
        sql: SQL query that was executed
        data_preview: Preview of query results
        has_data: Whether query returned data
        is_impossible: Whether query was impossible
        impossible_reason: Reason if impossible
        response_format: Optional forced format (e.g., 'markdown', 'json')
        length_guidance: Optional guidance on response length
        extra_instructions: Optional additional instructions
        
    Returns:
        Tuple of (system_msg, user_msg) dicts
    """
    
    # Serialize context
    context_text = serialize_for_prompt(context_bundle, "formatter")
    
    # Role-Based Style Guidance
    platform_role = context_bundle.user.platform_role
    crew_role = context_bundle.user.crew_role
    role_label = context_bundle.user.role_label
    
    # Custom Tone & Focus based on role
    role_style = "Be clear and conversational."
    if platform_role == "cfo" or (role_label and "CFO" in role_label.upper()):
        role_style = "Apply strict financial audit logic (Platinum Auditor). Focus on accuracy and net impact."
    elif platform_role == "admin":
        role_style = "Provide executive summaries with key financial metrics and strategic insights."
    elif crew_role == "commander":
        role_style = "Focus on team metrics, performance indicators, and management insights."
    elif crew_role == "guest":
        role_style = "Provide minimal necessary information."
    
    # Format Guidance
    format_guidance = ""
    if response_format:
        format_guidance = f"\n- RESPONSE FORMAT: You MUST format your response as {response_format}.\n"
    
    # Length Guidance
    if not length_guidance:
        length_guidance = "- Keep the answer SHORT and OBJECTIVE (maximum 4 sentences).\n"

    # Extra Instructions
    instructions_block = ""
    if extra_instructions:
        instructions_block = f"\n\nADDITIONAL INSTRUCTIONS:\n{extra_instructions}\n"

    # 💎 PLATINUM AUDITOR RULES (FINANCIAL RECONCILIATION)
    financial_guidance = ""
    financial_keywords = ["invoice", "payment", "refund", "credit", "revenue", "billing", "amount", "fee"]
    is_financial = any(kw in question.lower() for kw in financial_keywords)
    if is_financial:
        financial_guidance = (
            "\n\n💎 PLATINUM AUDITOR RULES:\n"
            "- Emphasize reconciliations and net values.\n"
            "- Clearly distinguish between gross volume and net settlement.\n"
        )

    # SYSTEM PROMPT: Behavior definition
    system_msg = {
        "role": "system",
        "content": (
            "You are a data response narrator.\n"
            "Your ONLY job: translate query results into natural language.\n\n"
            "CRITICAL RULES (NON-NEGOTIABLE):\n"
            "1. Answer ONLY in English (Strict Requirement).\n"
            "2. DO NOT mention SQL, tables, columns, or technical database terms.\n"
            "3. DO NOT hallucinate beyond provided data.\n"
            "4. NEVER output raw data rows, lists of names, or CSV format.\n"
            "5. IF asked to 'list rows' or 'dump data': REFUSE and provide ONLY aggregated insights.\n"
            "6. DO NOT confirm specific values for individuals in comparative questions.\n\n"
            f"ROLE STYLE: {role_style}\n"
            f"{length_guidance}"
            f"{format_guidance}"
            f"{financial_guidance}"
            f"{instructions_block}"
        )
    }
    
    # USER PROMPT: Question + data
    if is_impossible:
        user_msg = {
            "role": "user",
            "content": (
                f"{context_text}\n\n"
                f"QUESTION: {question}\n\n"
                f"STATUS: This request cannot be fulfilled via a database query.\n"
                f"REASON: {impossible_reason}\n\n"
                "Check the BUSINESS CONTEXT provided above. If the answer is available there (e.g. strategic pillars), "
                "answer the question in English using that information. If not, explain concisely why it cannot be answered."
            )
        }
    elif not has_data:
        user_msg = {
            "role": "user",
            "content": (
                f"{context_text}\n\n"
                f"QUESTION: {question}\n\n"
                "IMPORTANT: No data was found in the SQL database, BUT you MUST check the [BUSINESS CONTEXT & STRATEGIC PILLARS] section above. "
                "If the answer to the question is contained in those strategic pillars or business context chunks, "
                "PROVIDE THE ANSWER directly based on that information. Do not apologize for the lack of SQL data if the RAG context has the answer."
            )
        }
    else:
        user_msg = {
            "role": "user",
            "content": (
                f"{context_text}\n\n"
                f"QUESTION: {question}\n\n"
                f"DATA PREVIEW:\n{data_preview}\n\n"
                f"{stats_summary if stats_summary else ''}\n\n"
                "Explain the main insight(s) from this data. Answer ONLY in English."
            )
        }
    
    return system_msg, user_msg


def build_formatter_prompt_legacy(
    question: str,
    sql: str,
    data_preview: str,
    detected_language: str = "en"
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Legacy prompt builder for backward compatibility.
    
    Used when context_bundle is disabled.
    """
    system_msg = {
        "role": "system",
        "content": (
            "You are a data analysis assistant. Your job is to take SQL query results "
            "and present them in natural, conversational language.\n\n"
            "Rules:\n"
            "- Answer ONLY in English (even if the question is in another language)\n"
            "- Be professional but friendly\n"
            "- Reference actual numbers from the data\n"
            "- Do not hallucinate or make up information\n"
            "- If there's no data, explain why clearly\n"
            "- Keep responses concise (2-4 sentences typically)\n"
        )
    }
    
    user_msg = {
        "role": "user",
        "content": (
            f"User question: {question}\n\n"
            f"SQL query executed: {sql}\n\n"
            f"Query results:\n{data_preview}\n\n"
            "Please answer the user's question based on this data. "
            "Provide a clear, conversational response in English."
        )
    }
    
    return system_msg, user_msg
