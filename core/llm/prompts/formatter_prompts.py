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
    has_data: bool = True,
    is_impossible: bool = False,
    impossible_reason: str = ""
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Build formatter prompt optimized for phi3:mini on CPU.
    
    Goal: Convert SQL results into conversational natural language.
    
    Optimizations for small models:
    - Clear tone guidance
    - Structured output expectations
    - Minimal context (data speaks for itself)
    
    Args:
        context_bundle: Structured context (minimal for formatter)
        question: User's original question
        sql: SQL query that was executed
        data_preview: Preview of query results
        has_data: Whether query returned data
        is_impossible: Whether query was impossible
        impossible_reason: Reason if impossible
        
    Returns:
        Tuple of (system_msg, user_msg) dicts
    """
    
    # Serialize minimal context (formatter doesn't need full context)
    context_text = serialize_for_prompt(context_bundle, "formatter")
    
    # Detect intent for tone guidance
    intent = context_bundle.query.intent
    tone_guidance = ""
    if intent == "analytical":
        tone_guidance = "Provide insights and highlight trends."
    elif intent == "comparative":
        tone_guidance = "Emphasize comparisons and differences."
    elif intent == "operational":
        tone_guidance = "Be concise and focus on current status."
    else:
        tone_guidance = "Be clear and conversational."
    
    # SYSTEM PROMPT: Behavior definition
    system_msg = {
        "role": "system",
        "content": (
            "RESPONSE FORMATTER (phi3:mini)\n\n"
            "TASK: Convert SQL results into natural language.\n\n"
            "RULES:\n"
            "1. Answer in English (always)\n"
            "2. Be conversational but professional\n"
            "3. Reference actual numbers from data\n"
            "4. DO NOT hallucinate (only use provided data)\n"
            "5. If no data: explain why (don't apologize excessively)\n"
            "6. Keep response concise (2-4 sentences)\n\n"
            f"TONE: {tone_guidance}\n\n"
            "OUTPUT FORMAT:\n"
            "Natural language response\n"
        )
    }
    
    # USER PROMPT: Question + data
    if is_impossible:
        user_msg = {
            "role": "user",
            "content": (
                f"{context_text}\n\n"
                f"QUESTION: {question}\n\n"
                f"STATUS: Query was not possible\n"
                f"REASON: {impossible_reason}\n\n"
                "Explain to the user why this cannot be answered "
                "(in friendly language, without technical jargon)."
            )
        }
    elif not has_data:
        user_msg = {
            "role": "user",
            "content": (
                f"{context_text}\n\n"
                f"QUESTION: {question}\n\n"
                f"SQL: {sql}\n\n"
                f"RESULT: No data found\n\n"
                "Explain that no data matches the query criteria. "
                "Suggest the user try a broader search or different time range."
            )
        }
    else:
        user_msg = {
            "role": "user",
            "content": (
                f"{context_text}\n\n"
                f"QUESTION: {question}\n\n"
                f"SQL: {sql}\n\n"
                f"DATA:\n{data_preview}\n\n"
                "Answer the question using the data above. "
                "Reference specific numbers and be conversational."
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
