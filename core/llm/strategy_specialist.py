"""
Strategy Specialist Node for the multi-agent LangGraph pipeline.

Answers questions about OKRs, goals, pillars, initiatives, key results,
and strategic progress — without generating SQL. Calls the backend's
strategy API and uses the LLM to synthesize a natural language answer.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from core.logging_utils import log_event

logger = logging.getLogger("dataassistant")


STRATEGY_SYSTEM_PROMPT = """You are a strategic intelligence analyst for an enterprise platform.
You have access to the company's strategic data: pillars, objectives, OKRs, key results, initiatives, and assumptions.

Your job is to answer the user's question about strategy using ONLY the data provided below.
Be specific, cite numbers (progress %, targets, deadlines), and highlight items that are at risk or off track.

If the data doesn't contain enough information to answer the question, say so clearly.

Respond in the same language as the user's question.

## Strategy Data
{strategy_json}

## Strategy Health Summary
{health_json}
"""


def _format_strategy_for_prompt(tree: Dict[str, Any]) -> str:
    """Convert the strategy tree to a readable text format for the LLM."""
    if not tree:
        return "(No strategy data available)"

    lines: List[str] = []

    # Pillars
    pillars = tree.get("pillars") or []
    if pillars:
        lines.append(f"### Strategic Pillars ({len(pillars)})")
        for p in pillars:
            status = p.get("status", "unknown")
            lines.append(f"- **{p.get('name', 'Unnamed')}** [{status}]: {p.get('description', '')}")

    # Objectives
    objectives = tree.get("objectives") or []
    if objectives:
        lines.append(f"\n### Objectives ({len(objectives)})")
        for o in objectives:
            obj_type = o.get("type", "")
            lines.append(f"- [{obj_type}] **{o.get('name', '')}**: {o.get('description', '')}")

    # OKRs
    okrs = tree.get("okrs") or []
    if okrs:
        lines.append(f"\n### OKRs ({len(okrs)})")
        for okr in okrs:
            progress = okr.get("progress", 0)
            target = okr.get("target_value", "")
            baseline = okr.get("baseline_value", "")
            deadline = okr.get("deadline", "")
            lines.append(
                f"- **{okr.get('title', '')}**: {okr.get('description', '')} "
                f"| Progress: {progress}% | Target: {target} | Baseline: {baseline} | Deadline: {deadline}"
            )

    # Key Results
    key_results = tree.get("key_results") or []
    if key_results:
        lines.append(f"\n### Key Results ({len(key_results)})")
        for kr in key_results:
            progress = kr.get("progress", 0)
            lines.append(f"- **{kr.get('title', '')}**: {kr.get('description', '')} | Progress: {progress}%")

    # Initiatives
    initiatives = tree.get("initiatives") or []
    if initiatives:
        lines.append(f"\n### Initiatives ({len(initiatives)})")
        for ini in initiatives:
            status = ini.get("status", "unknown")
            lines.append(f"- [{status}] **{ini.get('name', '')}**: {ini.get('description', '')}")

    # Assumptions
    assumptions = tree.get("assumptions") or []
    if assumptions:
        lines.append(f"\n### Assumptions ({len(assumptions)})")
        for a in assumptions:
            risk = a.get("risk_level", "unknown")
            lines.append(f"- [{risk}] **{a.get('title', '')}**: {a.get('description', '')}")

    # Cycles
    cycles = tree.get("cycles") or []
    if cycles:
        lines.append(f"\n### Active Cycles ({len(cycles)})")
        for c in cycles:
            lines.append(f"- **{c.get('name', '')}**: {c.get('start_date', '')} → {c.get('end_date', '')}")

    return "\n".join(lines) if lines else "(Strategy tree is empty)"


def _format_health_for_prompt(health: Dict[str, Any]) -> str:
    """Convert health metrics to text."""
    if not health:
        return "(No health data available)"
    try:
        return json.dumps(health, indent=2, default=str)
    except Exception:
        return str(health)


def run_strategy_specialist(
    state: Dict[str, Any],
    llm: Any,
    backend_client: Any,
) -> Dict[str, Any]:
    """
    Strategy specialist LangGraph node.

    1. Calls backend GET /strategy/tree
    2. Calls backend GET /strategy/health
    3. Builds prompt with strategy data
    4. LLM synthesizes answer
    5. Returns updated state with answer + strategy_data
    """
    question = state.get("question", "")
    space_id = state.get("space_id")

    log_event("strategy_specialist_start", {
        "question": question[:100],
        "space_id": space_id,
    })

    # Fetch strategy data from backend
    tree = backend_client.get_strategy_tree(space_id)
    health = backend_client.get_strategy_health(space_id)

    strategy_text = _format_strategy_for_prompt(tree)
    health_text = _format_health_for_prompt(health)

    # Check if we have any data
    has_data = bool(tree and any(tree.get(k) for k in ["pillars", "objectives", "okrs", "initiatives", "key_results"]))

    if not has_data:
        log_event("strategy_specialist_no_data", {"space_id": space_id})
        state["answer"] = (
            "No strategy data has been configured yet for this context. "
            "You can add OKRs, pillars, and objectives in the Strategy section of Settings."
        )
        state["strategy_data"] = {}
        return state

    # Build prompt
    system_prompt = STRATEGY_SYSTEM_PROMPT.format(
        strategy_json=strategy_text,
        health_json=health_text,
    )

    # Phase 4.1: inject Context-Layer evidence retrieved by the graph's
    # brain_retrieval_node. No-op when the brain is empty.
    from core.llm._brain_prompt import prepend_brain_context

    user_content = prepend_brain_context(question, state)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    # Call LLM
    try:
        response = llm.invoke(messages)
        answer = response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        logger.error(f"Strategy specialist LLM error: {e}")
        answer = f"I found strategy data but encountered an error analyzing it: {e}"

    log_event("strategy_specialist_done", {
        "question": question[:100],
        "answer_preview": answer[:200] if answer else "",
        "num_pillars": len(tree.get("pillars", [])),
        "num_okrs": len(tree.get("okrs", [])),
    })

    state["answer"] = answer
    state["strategy_data"] = tree
    state["data"] = []  # No tabular data for strategy questions
    state["sql"] = None
    state["generated_title"] = f"Strategy: {question[:60]}"
    state["chosen_tables"] = []
    state["chosen_tables_physical"] = []

    return state
