"""
People & Activity Specialist — answers about teams, users, crew membership, and user activity.

"Who is in the Finance team?" / "Which crews are most active?"
Reads spaces, crews, users, and AI history from the backend.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List
from core.llm._brain_prompt import prepend_brain_context
from core.logging_utils import log_event
from core.llm.lingua_da_resposta import lingua_de_quem_fala, nome_da_lingua

logger = logging.getLogger("dataassistant")

SYSTEM_PROMPT = """You are an organizational intelligence analyst.
You have access to the company's organizational structure: spaces (departments), crews (teams),
users (people), and their recent AI activity (questions they've asked).

Answer the user's question using ONLY the data below.
Be specific about team membership, activity levels, and organizational context.
Do NOT reveal sensitive personal information — focus on roles and activity patterns.

Answer ONLY in {lingua}. This is not a preference — the reader may not read English.

## Spaces (Departments)
{spaces_text}

## Crews (Teams)
{crews_text}

## Users
{users_text}

## Recent AI Activity (what people are asking)
{activity_text}
"""


def _format_spaces(spaces: List[Dict[str, Any]]) -> str:
    if not spaces:
        return "(No spaces)"
    return "\n".join(
        f"- **{s.get('name', '?')}** (id: {s.get('id', '?')[:8]}): {s.get('description', 'No description')}"
        for s in spaces
    )


def _format_crews(crews: List[Dict[str, Any]]) -> str:
    if not crews:
        return "(No crews)"
    lines = []
    for c in crews:
        members = c.get("members", [])
        member_count = len(members) if isinstance(members, list) else "?"
        lines.append(
            f"- **{c.get('name', '?')}** (space: {c.get('space_id', '?')[:8]}): {member_count} members"
        )
    return "\n".join(lines)


def _format_users(users: List[Dict[str, Any]]) -> str:
    if not users:
        return "(No users)"
    return "\n".join(
        f"- {u.get('name', u.get('email', '?'))} ({u.get('role', 'user')})"
        for u in users[:30]
    )


def _format_activity(history: List[Dict[str, Any]]) -> str:
    if not history:
        return "(No recent activity)"
    lines = []
    for h in history[:20]:
        q = h.get("question", h.get("content", ""))[:80]
        user = h.get("user_name", h.get("user_id", "?"))
        date = (h.get("created_at", "") or "")[:10]
        lines.append(f'- [{date}] {user}: "{q}"')
    return "\n".join(lines)


def run_people_specialist(
    state: Dict[str, Any], llm: Any, backend_client: Any
) -> Dict[str, Any]:
    question = state.get("question", "")
    space_id = state.get("space_id")
    log_event("people_specialist_start", {"question": question[:100]})

    spaces = backend_client.get_spaces()
    crews = backend_client.get_crews(space_id)
    users = backend_client.get_users()
    history = backend_client.get_ai_history(space_id, limit=30)

    if not spaces and not crews and not users:
        state["answer"] = "No organizational data available yet."
        return state

    prompt = SYSTEM_PROMPT.format(
        lingua=nome_da_lingua(lingua_de_quem_fala(state, question)),
        spaces_text=_format_spaces(spaces),
        crews_text=_format_crews(crews),
        users_text=_format_users(users),
        activity_text=_format_activity(history),
    )

    try:
        response = llm.invoke(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": prepend_brain_context(question, state)},
            ]
        )
        state["answer"] = (
            response.content if hasattr(response, "content") else str(response)
        )
    except Exception as e:
        logger.error(f"People specialist error: {e}")
        state["answer"] = f"I found organizational data but encountered an error: {e}"

    state["data"] = []
    state["sql"] = None
    state["generated_title"] = f"People: {question[:50]}"
    log_event(
        "people_specialist_done",
        {"num_spaces": len(spaces), "num_crews": len(crews), "num_users": len(users)},
    )
    return state
