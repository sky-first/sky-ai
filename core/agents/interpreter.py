"""
Interpreter — the brain of the multi-agent system.

Analyzes a user's question, identifies which context layers are needed,
decomposes into sub-queries for each specialist, and defines execution
order (handling dependencies between specialists).

This replaces the simple intent classifier for "mixed" questions.
"""

from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.logging_utils import log_event

logger = logging.getLogger("dataassistant")

# All available specialists that the Interpreter can dispatch to
AVAILABLE_SPECIALISTS = [
    "strategy",  # OKRs, pillars, goals, KPIs, initiatives
    "events",  # Market signals, internal events, trends
    "relationships",  # Cross-space/department connections
    "people",  # Teams, users, crew membership, activity
    "widgets",  # Existing dashboards, past AI insights
    "data",  # SQL queries against databases
]

INTERPRETER_SYSTEM_PROMPT = """You are the Interpreter for a Collective Intelligence platform.
Your job is to analyze a user's question and create a query plan that determines
which specialist agents should be consulted to build the best answer.

Available specialists:
- **strategy**: Knows about OKRs, pillars, goals, KPIs, initiatives, assumptions, business rules
- **events**: Knows about market signals, internal events, trends, regulatory changes, competitor moves
- **relationships**: Knows how departments/spaces are connected (drives, impacts, correlates)
- **people**: Knows about teams, users, crew membership, who is asking what
- **widgets**: Knows about existing dashboards, past AI questions and answers, analytics history
- **data**: Can query SQL databases for actual numbers (revenue, invoices, customers, etc.)

Rules:
1. Choose the MINIMUM set of specialists needed. Don't add specialists that aren't relevant.
2. If a specialist needs output from another first, mark it as a dependency.
   Example: To compare OKR targets vs actual values, "data" depends on "strategy" (need targets first).
3. Write a focused sub-question for each specialist — not the full original question.
4. Choose a merge_strategy: "compare" (target vs actual), "aggregate" (combine facts), or "narrative" (tell a story).

Respond ONLY with valid JSON in this exact format:
```json
{
    "specialists": [
        {"name": "strategy", "sub_question": "List all KPIs with their targets by department"},
        {"name": "data", "sub_question": "Get current values for revenue, NPS, processing time", "depends_on": ["strategy"]}
    ],
    "merge_strategy": "compare",
    "reasoning": "Brief explanation of why these specialists are needed"
}
```
"""


@dataclass
class SubQuery:
    specialist: str
    sub_question: str
    depends_on: List[str] = field(default_factory=list)
    context_from: Optional[Dict[str, Any]] = None  # Filled after dependencies resolve


@dataclass
class QueryPlan:
    sub_queries: List[SubQuery]
    merge_strategy: str  # "compare", "aggregate", "narrative"
    reasoning: str = ""


def create_query_plan(question: str, llm: Any) -> QueryPlan:
    """
    Use the LLM to decompose a question into a multi-specialist query plan.

    Falls back to a simple plan if the LLM fails.
    """
    log_event("interpreter_start", {"question": question[:100]})

    try:
        response = llm.invoke(
            [
                {"role": "system", "content": INTERPRETER_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ]
        )
        text = response.content if hasattr(response, "content") else str(response)

        # Extract JSON
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        plan_data = json.loads(text)

        sub_queries = []
        for sq in plan_data.get("specialists", []):
            name = sq.get("name", "")
            if name not in AVAILABLE_SPECIALISTS:
                continue
            sub_queries.append(
                SubQuery(
                    specialist=name,
                    sub_question=sq.get("sub_question", question),
                    depends_on=sq.get("depends_on", []),
                )
            )

        if not sub_queries:
            raise ValueError("No valid specialists in plan")

        plan = QueryPlan(
            sub_queries=sub_queries,
            merge_strategy=plan_data.get("merge_strategy", "narrative"),
            reasoning=plan_data.get("reasoning", ""),
        )

        log_event(
            "interpreter_plan_created",
            {
                "question": question[:100],
                "specialists": [sq.specialist for sq in plan.sub_queries],
                "merge_strategy": plan.merge_strategy,
                "reasoning": plan.reasoning[:200],
            },
        )

        return plan

    except Exception as e:
        logger.warning(f"Interpreter LLM failed, using fallback plan: {e}")

        # Fallback: use strategy + data (most common mixed pattern)
        return QueryPlan(
            sub_queries=[
                SubQuery(specialist="strategy", sub_question=question),
                SubQuery(specialist="data", sub_question=question, depends_on=[]),
            ],
            merge_strategy="narrative",
            reasoning=f"Fallback plan (LLM error: {str(e)[:50]})",
        )


def resolve_execution_order(plan: QueryPlan) -> List[List[SubQuery]]:
    """
    Resolve dependencies into execution waves.
    Wave 0: specialists with no dependencies (run in parallel)
    Wave 1: specialists that depend on wave 0 results
    etc.
    """
    remaining = {sq.specialist: sq for sq in plan.sub_queries}
    resolved: set = set()
    waves: List[List[SubQuery]] = []

    max_iterations = 10
    for _ in range(max_iterations):
        if not remaining:
            break

        # Find specialists whose dependencies are all resolved
        wave = []
        for name, sq in list(remaining.items()):
            deps = set(sq.depends_on)
            if deps.issubset(resolved):
                wave.append(sq)

        if not wave:
            # Circular dependency or unresolvable — dump remaining into last wave
            wave = list(remaining.values())
            waves.append(wave)
            break

        waves.append(wave)
        for sq in wave:
            resolved.add(sq.specialist)
            del remaining[sq.specialist]

    log_event(
        "interpreter_execution_order",
        {
            "waves": [[sq.specialist for sq in w] for w in waves],
        },
    )

    return waves
