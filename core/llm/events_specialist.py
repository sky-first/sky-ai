"""
Events Specialist Node for the multi-agent LangGraph pipeline.

Answers questions about market signals, internal events, trends,
regulatory changes, competitor moves, and business context events
-- without generating SQL. Calls the backend's signal-events API.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from core.llm._brain_prompt import prepend_brain_context
from core.logging_utils import log_event
from core.llm.lingua_da_resposta import lingua_de_quem_fala, nome_da_lingua

logger = logging.getLogger("dataassistant")


EVENTS_SYSTEM_PROMPT = """You are an intelligence analyst for an enterprise platform.
You have access to the company's event and signal data: internal events, external market signals, trends, and hypotheses.

Your job is to answer the user's question using ONLY the events/signals provided below.
Be specific, cite dates, confidence levels, and categories.
Highlight high-confidence signals and recent events first.
If relevant, mention potential business impact.

If the data doesn't contain enough information to answer, say so clearly.

Answer ONLY in {lingua}. This is not a preference — the reader may not read English.

## Events & Signals Data
{events_text}
"""

CATEGORY_LABELS = {
    "INTERNAL": "Internal",
    "EXTERNAL": "External / Market",
    "TRENDS": "Trends & Hypotheses",
}

NATURE_LABELS = {
    "EVENT": "Confirmed Event",
    "SIGNAL": "Signal",
    "HYPOTHESIS": "Hypothesis",
}


def _format_events_for_prompt(events: List[Dict[str, Any]]) -> str:
    """Convert events list to readable text for the LLM."""
    if not events:
        return "(No events or signals available)"

    lines: List[str] = []

    # Group by category
    by_category: Dict[str, List[Dict[str, Any]]] = {}
    for e in events:
        cat = e.get("category", "UNKNOWN")
        by_category.setdefault(cat, []).append(e)

    for category in ["INTERNAL", "EXTERNAL", "TRENDS"]:
        cat_events = by_category.get(category, [])
        if not cat_events:
            continue

        label = CATEGORY_LABELS.get(category, category)
        lines.append(f"\n### {label} ({len(cat_events)})")

        for e in cat_events:
            nature = NATURE_LABELS.get(e.get("nature", ""), e.get("nature", ""))
            confidence = e.get("confidence", "UNKNOWN")
            sub_type = e.get("sub_type", "")
            desc = e.get("description", "")
            date = (e.get("start_date") or "")[:10]
            impact_date = e.get("impact_date")

            line = f"- [{nature}] [{confidence}] **{sub_type}** ({date}): {desc}"
            if impact_date:
                line += f" | Impact expected: {impact_date[:10]}"

            relations = e.get("relations")
            if relations and isinstance(relations, dict):
                rel_str = ", ".join(f"{k}: {v}" for k, v in relations.items() if v)
                if rel_str:
                    line += f" | Related: {rel_str}"

            lines.append(line)

    return "\n".join(lines) if lines else "(No events found)"


def run_events_specialist(
    state: Dict[str, Any],
    llm: Any,
    backend_client: Any,
) -> Dict[str, Any]:
    """
    Events specialist LangGraph node.

    1. Calls backend GET /signal-events/
    2. Builds prompt with categorized events
    3. LLM synthesizes answer about signals, events, trends
    4. Returns updated state
    """
    question = state.get("question", "")
    space_id = state.get("space_id")

    log_event(
        "events_specialist_start",
        {
            "question": question[:100],
            "space_id": space_id,
        },
    )

    # Fetch events from backend
    events = backend_client.get_signal_events(space_id)

    has_data = bool(events)

    if not has_data:
        log_event("events_specialist_no_data", {"space_id": space_id})
        state["answer"] = (
            "No events or signals have been registered yet for this context. "
            "You can add events in the Signals section of Universe Intelligence."
        )
        state["signals_data"] = []
        return state

    # Build prompt
    events_text = _format_events_for_prompt(events)
    system_prompt = EVENTS_SYSTEM_PROMPT.format(
        events_text=events_text,
        lingua=nome_da_lingua(lingua_de_quem_fala(state, question)),
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prepend_brain_context(question, state)},
    ]

    # Call LLM
    try:
        response = llm.invoke(messages)
        answer = response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        logger.error(f"Events specialist LLM error: {e}")
        answer = f"I found event data but encountered an error analyzing it: {e}"

    log_event(
        "events_specialist_done",
        {
            "question": question[:100],
            "answer_preview": answer[:200] if answer else "",
            "num_events": len(events),
            "categories": list(set(e.get("category", "") for e in events)),
        },
    )

    state["answer"] = answer
    state["signals_data"] = events
    state["data"] = []
    state["sql"] = None
    state["generated_title"] = f"Events: {question[:60]}"
    state["chosen_tables"] = []
    state["chosen_tables_physical"] = []

    return state
