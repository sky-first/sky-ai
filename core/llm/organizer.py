"""
Organizer — merges results from multiple specialists into a unified answer.

After the Interpreter dispatches sub-queries to specialists and they return
partial results, the Organizer combines everything into a coherent narrative
with source attribution and confidence.
"""

from __future__ import annotations
import json
import logging
from typing import Any, Dict, List
from core.logging_utils import log_event

logger = logging.getLogger("dataassistant")


ORGANIZER_SYSTEM_PROMPT = """You are the Organizer for a Collective Intelligence platform.
Multiple specialist agents have analyzed different aspects of the user's question.
Your job is to merge their findings into ONE coherent, unified answer.

Rules:
1. Combine insights from all specialists into a flowing narrative — not a list of separate sections.
2. When comparing targets vs actuals, calculate percentages and highlight gaps.
3. When specialists disagree or data conflicts, note the discrepancy with confidence levels.
4. Attribute key facts to their source: "According to the strategy data..." / "The database shows..."
5. End with actionable recommendations if the data suggests them.
6. Respond in the same language as the user's question.

Merge strategy for this question: **{merge_strategy}**
- "compare": Focus on target vs actual comparisons, highlight gaps and progress
- "aggregate": Combine all facts into a comprehensive overview
- "narrative": Tell a story connecting the different data points

## User's Original Question
{question}

## Specialist Results
{results_text}
"""


def _format_results(results: Dict[str, Dict[str, Any]]) -> str:
    """Format specialist results for the LLM prompt."""
    lines = []
    for specialist, result in results.items():
        answer = result.get("answer", "No answer")
        data = result.get("data")
        error = result.get("error")

        lines.append(f"\n### {specialist.upper()} Specialist")
        if error:
            lines.append(f"  (Error: {error})")
        lines.append(f"  Answer: {answer}")
        if data and isinstance(data, list) and len(data) > 0:
            preview = json.dumps(data[:5], default=str)[:500]
            lines.append(f"  Data preview: {preview}")

    return "\n".join(lines)


def run_organizer(
    question: str,
    specialist_results: Dict[str, Dict[str, Any]],
    merge_strategy: str,
    llm: Any,
) -> str:
    """
    Merge results from multiple specialists into a unified answer.

    Args:
        question: The original user question
        specialist_results: Dict mapping specialist name -> {"answer": str, "data": list, "error": str}
        merge_strategy: "compare", "aggregate", or "narrative"
        llm: LLM provider

    Returns:
        Unified answer string
    """
    log_event("organizer_start", {
        "question": question[:100],
        "specialists": list(specialist_results.keys()),
        "merge_strategy": merge_strategy,
    })

    # Filter out empty/error-only results
    valid_results = {
        k: v for k, v in specialist_results.items()
        if v.get("answer") and not v["answer"].startswith("No ") and "not available" not in v.get("answer", "").lower()
    }

    if not valid_results:
        # All specialists returned empty — return best effort
        all_answers = [v.get("answer", "") for v in specialist_results.values() if v.get("answer")]
        if all_answers:
            return all_answers[0]
        return "I couldn't find relevant information across any of the available data sources."

    # If only one specialist returned useful data, just use its answer directly
    if len(valid_results) == 1:
        only_result = list(valid_results.values())[0]
        log_event("organizer_single_source", {"specialist": list(valid_results.keys())[0]})
        return only_result["answer"]

    # Multiple results — ask LLM to merge
    results_text = _format_results(valid_results)
    prompt = ORGANIZER_SYSTEM_PROMPT.format(
        question=question,
        merge_strategy=merge_strategy,
        results_text=results_text,
    )

    try:
        response = llm.invoke([
            {"role": "system", "content": prompt},
            {"role": "user", "content": question},
        ])
        answer = response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        logger.error(f"Organizer LLM error: {e}")
        # Fallback: concatenate specialist answers
        parts = []
        for name, result in valid_results.items():
            parts.append(f"**{name.title()}**: {result['answer']}")
        answer = "\n\n".join(parts)

    log_event("organizer_done", {
        "question": question[:100],
        "num_sources": len(valid_results),
        "answer_preview": answer[:200] if answer else "",
    })

    return answer
