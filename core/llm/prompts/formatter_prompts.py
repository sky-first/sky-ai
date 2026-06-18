"""
Formatter Prompt Builder

Creates prompts for natural language response generation (phi3:mini).
Optimized for fast, conversational output (~1-2s on CPU).
"""

from __future__ import annotations

from typing import Dict, List, Tuple, Optional
from core.llm.context.models import ContextBundle
from core.llm.context.serializers import serialize_for_prompt

# Maps the tone IDs emitted by the frontend Settings → AI Customization UI
# (see sky-poc-frontend settings/ai-preferences.tsx `toneOptions`) to concrete
# voice instructions for the formatter LLM.
_TONE_DIRECTIVES: Dict[str, str] = {
    "casual": "Write like you'd talk to a smart colleague. Use contractions, plain words, no corporate jargon.",
    "professional": "Use formal, objective business English. No contractions, no slang, no filler.",
    "technical": "Use precise domain terminology. Assume the reader is technically literate; do not over-explain basics.",
    "friendly": "Use a warm, encouraging tone. Acknowledge the reader; phrase findings as helpful insight, not verdict.",
}

# Maps the output-structure IDs from the Settings UI `styleOptions` to concrete
# shape directives. User-selected style takes precedence over the length/
# role-based guidance below when they disagree.
_STYLE_DIRECTIVES: Dict[str, str] = {
    "concise": "Keep the answer to at most 2-3 sentences. Lead with the single most important number or insight.",
    "detailed": "Give a fuller explanation: headline first, then 1-2 sentences of context, and note relevant caveats.",
    "step-by-step": "Structure the answer as numbered steps (1., 2., 3.) that walk through the reasoning in order.",
}


def _build_user_preferences_block(
    ai_tone: Optional[str], ai_style: Optional[str]
) -> str:
    """Render the USER PREFERENCES section, or empty string when not set."""
    tone_directive = _TONE_DIRECTIVES.get(ai_tone) if ai_tone else None
    style_directive = _STYLE_DIRECTIVES.get(ai_style) if ai_style else None
    if not tone_directive and not style_directive:
        return ""
    lines = ["USER PREFERENCES (these take precedence over ROLE STYLE for form/voice):"]
    if tone_directive:
        lines.append(f"- TONE: {tone_directive}")
    if style_directive:
        lines.append(f"- STRUCTURE: {style_directive}")
    return "\n".join(lines) + "\n\n"


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
    extra_instructions: Optional[str] = None,
    ai_tone: Optional[str] = None,
    ai_style: Optional[str] = None,
    detected_language: Optional[str] = None,
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
        role_style = (
            "Focus on team metrics, performance indicators, and management insights."
        )
    elif crew_role == "guest":
        role_style = "Provide minimal necessary information."

    # User Preferences (Settings → AI Customization)
    # Precedence: role defines WHAT to analyze (substance); user preferences
    # define HOW to present (form). When both speak to tone, user wins.
    user_prefs_block = _build_user_preferences_block(ai_tone, ai_style)

    # Format Guidance
    format_guidance = ""
    if response_format:
        format_guidance = f"\n- RESPONSE FORMAT: You MUST format your response as {response_format}.\n"

    # Length Guidance
    if not length_guidance:
        length_guidance = (
            "- Keep the answer SHORT and OBJECTIVE (maximum 4 sentences).\n"
        )

    # Extra Instructions
    instructions_block = ""
    if extra_instructions:
        instructions_block = f"\n\nADDITIONAL INSTRUCTIONS:\n{extra_instructions}\n"

    # 💎 PLATINUM AUDITOR RULES (FINANCIAL RECONCILIATION)
    financial_guidance = ""
    financial_keywords = [
        "invoice",
        "payment",
        "refund",
        "credit",
        "revenue",
        "billing",
        "amount",
        "fee",
    ]
    is_financial = any(kw in question.lower() for kw in financial_keywords)
    if is_financial:
        financial_guidance = (
            "\n\n💎 PLATINUM AUDITOR RULES:\n"
            "- Emphasize reconciliations and net values.\n"
            "- Clearly distinguish between gross volume and net settlement.\n"
        )

    # Resolve response language
    _lang = detected_language if detected_language in ("en", "pt") else "en"
    _lang_name = "Portuguese" if _lang == "pt" else "English"

    # SYSTEM PROMPT: Behavior definition
    # Precedence reminder for the LLM: user prefs (form) > role style (tone),
    # but role still drives substance/focus.
    system_msg = {
        "role": "system",
        "content": (
            "You are a data response narrator.\n"
            "Your ONLY job: translate query results into natural language.\n\n"
            "CRITICAL RULES (NON-NEGOTIABLE):\n"
            f"1. Answer ONLY in {_lang_name} (Strict Requirement).\n"
            "2. DO NOT mention SQL, tables, columns, or technical database terms.\n"
            "3. DO NOT hallucinate beyond provided data.\n"
            "4. NEVER output raw data rows, lists of names, or CSV format.\n"
            "5. IF asked to 'list rows' or 'dump data': REFUSE and provide ONLY aggregated insights.\n"
            "6. DO NOT confirm specific values for individuals in comparative questions.\n"
            "7. The result may be AGGREGATED (COUNT/SUM/AVG) or LIMITED (top-N). A single\n"
            "   aggregated row says NOTHING about how the underlying rows are spread —\n"
            "   NEVER claim values are 'constant', 'uniform', 'do not vary', 'are all equal',\n"
            "   or that 'min, max and average are the same'.\n"
            "8. NEVER infer ABSENCE from a limited/aggregated result: do not say 'there are\n"
            "   no other X', 'nothing else exists', or 'no variation' just because the result\n"
            "   returned one row or one group — more may exist beyond what was returned.\n"
            "9. State ONLY what the returned numbers literally support. Do NOT invent\n"
            "   statistics (min/max/average/trends/variation) that are not present in the data.\n"
            "10. NEVER rescale, multiply, divide or convert a numeric value — report every\n"
            "    number EXACTLY as it appears in the results. A value of 0.75 is 0.75, NOT 75%.\n"
            "    If a value already represents a percentage (e.g. a column meaning a percent),\n"
            "    append '%' WITHOUT changing the digits (0.75 → '0.75%', never '75%').\n\n"
            f"{user_prefs_block}"
            f"ROLE STYLE (substance/focus): {role_style}\n"
            f"{length_guidance}"
            f"{format_guidance}"
            f"{financial_guidance}"
            f"{instructions_block}"
        ),
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
                f"answer the question in {_lang_name} using that information. If not, explain concisely why it cannot be answered."
            ),
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
            ),
        }
    else:
        user_msg = {
            "role": "user",
            "content": (
                f"{context_text}\n\n"
                f"QUESTION: {question}\n\n"
                f"DATA PREVIEW:\n{data_preview}\n\n"
                f"{stats_summary if stats_summary else ''}\n\n"
                "Explain the main insight(s) from this data. The result may be aggregated "
                "or limited to the top rows — describe ONLY what these rows show; do not "
                "infer the full distribution, the variation of the underlying rows, or the "
                f"absence of other values. Answer ONLY in {_lang_name}."
            ),
        }

    return system_msg, user_msg


def build_formatter_prompt_legacy(
    question: str, sql: str, data_preview: str, detected_language: str = "en"
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Legacy prompt builder for backward compatibility.

    Used when context_bundle is disabled.
    """
    _leg_lang = detected_language if detected_language in ("en", "pt") else "en"
    _leg_lang_name = "Portuguese" if _leg_lang == "pt" else "English"

    system_msg = {
        "role": "system",
        "content": (
            "You are a data analysis assistant. Your job is to take SQL query results "
            "and present them in natural, conversational language.\n\n"
            "Rules:\n"
            f"- Answer ONLY in {_leg_lang_name}\n"
            "- Be professional but friendly\n"
            "- Reference actual numbers from the data\n"
            "- Do not hallucinate or make up information\n"
            "- If there's no data, explain why clearly\n"
            "- Keep responses concise (2-4 sentences typically)\n"
        ),
    }

    user_msg = {
        "role": "user",
        "content": (
            f"User question: {question}\n\n"
            f"SQL query executed: {sql}\n\n"
            f"Query results:\n{data_preview}\n\n"
            f"Please answer the user's question based on this data. "
            f"Provide a clear, conversational response in {_leg_lang_name}."
        ),
    }

    return system_msg, user_msg
