"""Tests for the full-context scan agent — Phase 5.1."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.agents.full_context_scan import (
    DEFAULT_K,
    FullContextResult,
    LLMResponse,
    run_full_context_scan,
)
from core.rag.context_brain import CandidateDoc, RankedDoc


def _doc(id_: str, kind: str, title: str, body: str = "body") -> RankedDoc:
    return RankedDoc(
        doc=CandidateDoc(
            id=id_, kind=kind, source_table=f"{kind}s", source_id=id_,
            title=title, body=body, metadata={},
            space_id=None, crew_id=None, owner_user_id=None, visibility="space",
            pii_flags=[], updated_at=datetime.now(timezone.utc),
            cosine=0.5, bm25=0.2,
        ),
        score=0.8, components={},
    )


class _LLM:
    def __init__(self, content: str, tokens_in=200, tokens_out=100, cost=0.004):
        self.content = content
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.cost = cost
        self.calls: list[list[dict[str, str]]] = []

    async def __call__(self, messages):
        self.calls.append(messages)
        return LLMResponse(
            content=self.content,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            cost_usd=self.cost,
        )


# ─── happy path ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_produces_narrative_followups_and_citations():
    async def retrieve(query, **kwargs):
        return [
            _doc("d1", "okr", "Grow ARR 20%"),
            _doc("d2", "event_external", "USD surge"),
            _doc("d3", "table", "orders"),
        ]

    llm = _LLM(
        '{"narrative": ["ARR is behind plan.", "Macro risk from USD."], '
        '"follow_ups": ["How is ARR trending vs. Q4 target?"], '
        '"cited_doc_ids": ["d1", "d2"]}'
    )

    r = await run_full_context_scan(question="What should I know?", retrieve=retrieve, llm=llm)
    assert r.narrative == ["ARR is behind plan.", "Macro risk from USD."]
    assert r.follow_ups == ["How is ARR trending vs. Q4 target?"]
    assert r.cited_doc_ids == ["d1", "d2"]
    assert set(r.retrieved_doc_ids) == {"d1", "d2", "d3"}
    assert r.retrieved_kinds == ["event_external", "okr", "table"]
    assert r.tokens_used == 300
    assert r.cost_usd == pytest.approx(0.004)


@pytest.mark.asyncio
async def test_default_k_and_no_kind_filter_are_passed_to_retriever():
    captured: dict = {}

    async def retrieve(query, **kwargs):
        captured.update(kwargs)
        return []

    await run_full_context_scan(question="anything", retrieve=retrieve, llm=_LLM("{}"))
    assert captured["k"] == DEFAULT_K
    assert captured["kinds"] is None


# ─── citations are restricted to retrieved docs ─────────────────────────
@pytest.mark.asyncio
async def test_invented_citations_are_dropped():
    async def retrieve(q, **kw):
        return [_doc("real-1", "okr", "Real")]

    llm = _LLM(
        '{"narrative": ["x"], "follow_ups": [], '
        '"cited_doc_ids": ["real-1", "made-up"]}'
    )
    r = await run_full_context_scan(question="q", retrieve=retrieve, llm=llm)
    assert r.cited_doc_ids == ["real-1"]


# ─── empty retrieval ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_empty_retrieval_returns_placeholder_without_llm():
    called = False

    async def retrieve(q, **kw):
        return []

    class _NoLLM:
        async def __call__(self, messages):
            nonlocal called
            called = True
            return LLMResponse(content="{}")

    r = await run_full_context_scan(question="q", retrieve=retrieve, llm=_NoLLM())
    assert r.narrative == ["No context available for this scope yet."]
    assert r.follow_ups == []
    assert r.retrieved_doc_ids == []
    assert called is False, "empty retrieval must short-circuit the LLM"


# ─── failure degradation ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_retriever_exception_yields_fallback_narrative():
    async def retrieve(q, **kw):
        raise RuntimeError("db down")

    r = await run_full_context_scan(question="q", retrieve=retrieve, llm=_LLM("{}"))
    assert r.fallback_reason and "retrieval_error" in r.fallback_reason
    assert "retrieval layer" in " ".join(r.narrative).lower()
    assert r.retrieved_doc_ids == []


@pytest.mark.asyncio
async def test_llm_exception_yields_fallback_narrative_but_preserves_retrieval():
    async def retrieve(q, **kw):
        return [_doc("d1", "okr", "x")]

    class _Boom:
        async def __call__(self, messages):
            raise RuntimeError("provider down")

    r = await run_full_context_scan(question="q", retrieve=retrieve, llm=_Boom())
    assert r.fallback_reason and "llm_error" in r.fallback_reason
    # Retrieval trail preserved so the UI still shows what was seen
    # even when synthesis failed.
    assert r.retrieved_doc_ids == ["d1"]
    assert r.retrieved_kinds == ["okr"]


@pytest.mark.asyncio
async def test_unparseable_llm_response_yields_fallback():
    async def retrieve(q, **kw):
        return [_doc("d1", "okr", "x")]

    r = await run_full_context_scan(
        question="q", retrieve=retrieve,
        llm=_LLM("not json at all"),
    )
    assert r.fallback_reason == "unparseable_json"
    assert r.tokens_used == 300  # tokens still counted


@pytest.mark.asyncio
async def test_llm_missing_narrative_field_is_unparseable():
    """A JSON object without a narrative array should be treated as
    unparseable rather than published as an empty scan."""
    async def retrieve(q, **kw):
        return [_doc("d1", "okr", "x")]

    r = await run_full_context_scan(
        question="q", retrieve=retrieve,
        llm=_LLM('{"follow_ups": ["q"], "cited_doc_ids": []}'),
    )
    assert r.fallback_reason == "unparseable_json"


# ─── JSON quirks ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_tolerates_markdown_code_fences():
    async def retrieve(q, **kw):
        return [_doc("d1", "okr", "x")]

    r = await run_full_context_scan(
        question="q", retrieve=retrieve,
        llm=_LLM('```json\n{"narrative": ["ok"], "follow_ups": [], "cited_doc_ids": []}\n```'),
    )
    assert r.narrative == ["ok"]


@pytest.mark.asyncio
async def test_tolerates_preamble_text_before_json():
    async def retrieve(q, **kw):
        return [_doc("d1", "okr", "x")]

    r = await run_full_context_scan(
        question="q", retrieve=retrieve,
        llm=_LLM('Here is my take:\n{"narrative": ["ok"], "follow_ups": [], "cited_doc_ids": []}'),
    )
    assert r.narrative == ["ok"]


# ─── output clamping ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_narrative_and_followups_are_clamped():
    async def retrieve(q, **kw):
        return [_doc("d1", "okr", "x")]

    big_list = [f"item {i}" for i in range(30)]
    import json as _json

    r = await run_full_context_scan(
        question="q", retrieve=retrieve,
        llm=_LLM(_json.dumps({
            "narrative": big_list,
            "follow_ups": big_list,
            "cited_doc_ids": ["d1"],
        })),
    )
    assert len(r.narrative) == 10
    assert len(r.follow_ups) == 10


@pytest.mark.asyncio
async def test_retrieved_blocks_budget_truncates_when_over_limit():
    async def retrieve(q, **kw):
        return [_doc(f"d{i}", "okr", f"title-{i}", body="x" * 1000) for i in range(50)]

    captured = {}

    class _Capturing:
        async def __call__(self, messages):
            captured["prompt"] = messages[1]["content"]
            return LLMResponse(
                content='{"narrative": ["ok"], "follow_ups": [], "cited_doc_ids": []}'
            )

    await run_full_context_scan(
        question="q", retrieve=retrieve, llm=_Capturing(),
        max_chars_for_llm=5000,
    )
    assert "truncated" in captured["prompt"]
    # Prompt length is bounded — hard check.
    assert len(captured["prompt"]) < 7000  # budget + ~2k header tolerance


# ─── to_result_payload ───────────────────────────────────────────────────
def test_to_result_payload_has_expected_keys():
    r = FullContextResult(
        narrative=["a"], follow_ups=["b"], cited_doc_ids=["d1"],
        retrieved_doc_ids=["d1", "d2"], retrieved_kinds=["okr", "goal"],
    )
    p = r.to_result_payload()
    assert p["mode"] == "context"
    assert p["narrative"] == ["a"]
    assert p["follow_ups"] == ["b"]
    assert p["cited_doc_ids"] == ["d1"]
    assert p["retrieved_kinds"] == ["okr", "goal"]
    assert p["retrieved_doc_count"] == 2
