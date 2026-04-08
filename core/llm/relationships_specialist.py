"""
Relationships Specialist — answers about cross-space/department connections.

"How does Marketing affect Sales?" / "What are the relationships between departments?"
Reads enterprise relationships (drives, impacts, correlates) from the backend.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List
from core.logging_utils import log_event

logger = logging.getLogger("dataassistant")

SYSTEM_PROMPT = """You are an enterprise relationship analyst.
You have access to the semantic relationships between departments, spaces, and business domains.
Relationships have types like "drives", "impacts", "correlates_with", "depends_on".

Answer the user's question using ONLY the relationship data below.
Explain how entities are connected and what the implications are.
If the question asks about cause-and-effect, trace the relationship chain.

Respond in the same language as the user's question.

## Enterprise Relationships
{relationships_text}

## Spaces / Departments
{spaces_text}
"""


def _format_relationships(rels: List[Dict[str, Any]]) -> str:
    if not rels:
        return "(No relationships configured)"
    lines = []
    for r in rels:
        src = r.get("source_name") or r.get("source", "?")
        tgt = r.get("target_name") or r.get("target", "?")
        rel_type = r.get("type") or r.get("relationship_type", "relates_to")
        desc = r.get("description", "")
        line = f"- {src} --[{rel_type}]--> {tgt}"
        if desc:
            line += f" ({desc})"
        lines.append(line)
    return "\n".join(lines)


def _format_spaces(spaces: List[Dict[str, Any]]) -> str:
    if not spaces:
        return "(No spaces available)"
    return "\n".join(f"- **{s.get('name', '?')}**: {s.get('description', '')}" for s in spaces)


def run_relationships_specialist(state: Dict[str, Any], llm: Any, backend_client: Any) -> Dict[str, Any]:
    question = state.get("question", "")
    log_event("relationships_specialist_start", {"question": question[:100]})

    rels = backend_client.get_enterprise_relationships()
    spaces = backend_client.get_spaces()

    if not rels and not spaces:
        state["answer"] = "No enterprise relationships or spaces have been configured yet."
        return state

    prompt = SYSTEM_PROMPT.format(
        relationships_text=_format_relationships(rels),
        spaces_text=_format_spaces(spaces),
    )

    try:
        response = llm.invoke([{"role": "system", "content": prompt}, {"role": "user", "content": question}])
        state["answer"] = response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        logger.error(f"Relationships specialist error: {e}")
        state["answer"] = f"I found relationship data but encountered an error: {e}"

    state["data"] = []
    state["sql"] = None
    state["generated_title"] = f"Relationships: {question[:50]}"
    log_event("relationships_specialist_done", {"num_rels": len(rels), "num_spaces": len(spaces)})
    return state
