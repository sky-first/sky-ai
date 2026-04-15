"""Regression test: orchestrator weaves brain_context into its prompt.

Phase 4.3. The orchestrator picks tables for a data question; it
already reads `retrieval_context` and now also reads `brain_context`
from AgentState. The contract is load-bearing — if a refactor drops
the brain section, the business context (goals / OKRs / relationships)
stops influencing table choice and the Phase-2 investment loses
half its value. Pin it at the source level so CI catches silent
removals.
"""

from __future__ import annotations

import inspect


def test_orchestrator_prompt_mentions_business_context_from_brain():
    from core.llm import orchestrator

    src = inspect.getsource(orchestrator)
    # The brain-context weaving adds a BUSINESS CONTEXT section that
    # cites the retrieval kinds. If that section disappears, we've
    # silently stopped influencing table selection.
    assert 'state.get("brain_context")' in src, (
        "orchestrator no longer reads brain_context — Phase-2 brain "
        "retrieval is not flowing into table selection."
    )
    assert "BUSINESS CONTEXT (strategy / goals" in src, (
        "orchestrator no longer emits the BUSINESS CONTEXT preamble "
        "that tells the LLM to weight tables against goals/OKRs."
    )
