"""
Widgets & History Specialist — answers about existing dashboards, widgets, past insights.

"What dashboards do we have?" / "What questions have been asked about revenue?"
Reads dashboards, widgets, and AI history from the backend.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List
from core.llm._brain_prompt import prepend_brain_context
from core.logging_utils import log_event

logger = logging.getLogger("dataassistant")

SYSTEM_PROMPT = """You are a dashboard and analytics historian.
You have access to the company's existing dashboards, widgets (charts, tables, KPIs),
and the history of AI questions and answers.

Answer the user's question using ONLY the data below.
Reference specific widget titles, dashboard names, and past insights.
If the user asks about something that was already analyzed, point to the existing widget.

Respond in the same language as the user's question.

## Dashboards
{dashboards_text}

## Widgets
{widgets_text}

## Recent AI Questions & Answers
{history_text}
"""


def _format_dashboards(dashboards: List[Dict[str, Any]]) -> str:
    if not dashboards:
        return "(No dashboards)"
    return "\n".join(
        f"- **{d.get('name', d.get('title', 'Untitled'))}** ({len(d.get('widgets', []))} widgets)"
        for d in dashboards
    )


def _format_widgets(widgets: List[Dict[str, Any]]) -> str:
    if not widgets:
        return "(No widgets)"
    lines = []
    for w in widgets[:30]:
        wtype = w.get("type", "unknown")
        title = w.get("title", "Untitled")
        data = w.get("data") or w.get("config") or {}
        question = data.get("question", "") if isinstance(data, dict) else ""
        line = f"- [{wtype}] **{title}**"
        if question:
            line += f" (from: \"{question[:60]}\")"
        lines.append(line)
    return "\n".join(lines)


def _format_history(history: List[Dict[str, Any]]) -> str:
    if not history:
        return "(No AI history)"
    lines = []
    for h in history[:25]:
        q = h.get("question", h.get("content", ""))[:80]
        a = h.get("answer", "")[:80] if h.get("answer") else ""
        date = (h.get("created_at", "") or "")[:10]
        line = f"- [{date}] Q: \"{q}\""
        if a:
            line += f" -> A: \"{a}...\""
        lines.append(line)
    return "\n".join(lines)


def run_widgets_specialist(state: Dict[str, Any], llm: Any, backend_client: Any) -> Dict[str, Any]:
    question = state.get("question", "")
    space_id = state.get("space_id")
    log_event("widgets_specialist_start", {"question": question[:100]})

    dashboards = backend_client.get_dashboards()
    all_widgets: List[Dict[str, Any]] = []
    for d in dashboards[:10]:
        did = d.get("id")
        if did:
            all_widgets.extend(backend_client.get_widgets(did))
    history = backend_client.get_ai_history(space_id, limit=30)

    if not dashboards and not history:
        state["answer"] = "No dashboards or AI history available yet. Start asking questions to build your analytics history."
        return state

    prompt = SYSTEM_PROMPT.format(
        dashboards_text=_format_dashboards(dashboards),
        widgets_text=_format_widgets(all_widgets),
        history_text=_format_history(history),
    )

    try:
        response = llm.invoke([
            {"role": "system", "content": prompt},
            {"role": "user", "content": prepend_brain_context(question, state)},
        ])
        state["answer"] = response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        logger.error(f"Widgets specialist error: {e}")
        state["answer"] = f"Error analyzing dashboard data: {e}"

    state["data"] = []
    state["sql"] = None
    state["generated_title"] = f"Analytics: {question[:50]}"
    log_event("widgets_specialist_done", {"num_dashboards": len(dashboards), "num_widgets": len(all_widgets)})
    return state
