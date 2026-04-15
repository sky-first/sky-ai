"""Tests for delta detection — Phase 3.6."""

from __future__ import annotations

import pytest

from core.agents.delta_detector import (
    DeltaResult,
    HashDeltaStrategy,
    LLMDeltaStrategy,
    LLMResponse,
    compute_result_hash,
)


# ─── hash stability ──────────────────────────────────────────────────────
def test_hash_is_stable_across_key_order():
    a = {"b": 2, "a": 1, "rows": [{"x": 1, "y": 2}]}
    b = {"a": 1, "rows": [{"y": 2, "x": 1}], "b": 2}
    assert compute_result_hash(a) == compute_result_hash(b)


def test_hash_ignores_cosmetic_whitespace_in_strings():
    a = {"label": "North  region"}
    b = {"label": "North region"}
    assert compute_result_hash(a) == compute_result_hash(b)


def test_hash_distinguishes_real_value_change():
    a = {"rows": [{"revenue": 100}]}
    b = {"rows": [{"revenue": 101}]}
    assert compute_result_hash(a) != compute_result_hash(b)


# ─── hash strategy ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_hash_first_run():
    r = await HashDeltaStrategy().classify(
        current_payload={"rows": []}, previous_hash=None
    )
    assert r.kind == "first_run"
    assert r.result_hash


@pytest.mark.asyncio
async def test_hash_none_on_match():
    payload = {"rows": [{"a": 1}]}
    h = compute_result_hash(payload)
    r = await HashDeltaStrategy().classify(current_payload=payload, previous_hash=h)
    assert r.kind == "none"


@pytest.mark.asyncio
async def test_hash_material_on_mismatch():
    r = await HashDeltaStrategy().classify(
        current_payload={"rows": [{"a": 2}]}, previous_hash="deadbeef",
    )
    assert r.kind == "material"


# ─── LLM strategy — happy path ──────────────────────────────────────────
class _FakeLLM:
    def __init__(self, response_text: str, tokens_in=50, tokens_out=20, cost=0.0002):
        self.response_text = response_text
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.cost = cost
        self.calls: list[list[dict[str, str]]] = []

    async def __call__(self, messages):
        self.calls.append(messages)
        return LLMResponse(
            content=self.response_text,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            cost_usd=self.cost,
        )


@pytest.mark.asyncio
async def test_llm_classifies_material_with_summary():
    llm = _FakeLLM(
        '{"kind": "material", "summary": "Revenue dropped 12% vs. last run."}'
    )
    r = await LLMDeltaStrategy(llm).classify(
        current_payload={"revenue": 88}, previous_hash="x",
        previous_payload={"revenue": 100},
    )
    assert r.kind == "material"
    assert "12%" in r.summary
    assert r.tokens_used == 70
    assert r.cost_usd == pytest.approx(0.0002)


@pytest.mark.asyncio
async def test_llm_classifies_trivial():
    llm = _FakeLLM('{"kind": "trivial", "summary": "Row count +1."}')
    r = await LLMDeltaStrategy(llm).classify(
        current_payload={"n": 101}, previous_hash="x",
    )
    assert r.kind == "trivial"


@pytest.mark.asyncio
async def test_llm_skipped_on_unchanged_hash():
    payload = {"rows": [{"a": 1}]}
    h = compute_result_hash(payload)
    llm = _FakeLLM('{"kind":"material","summary":"should not be called"}')
    r = await LLMDeltaStrategy(llm).classify(
        current_payload=payload, previous_hash=h,
    )
    assert r.kind == "none"
    assert llm.calls == [], "LLM must not be called when hash matches"


@pytest.mark.asyncio
async def test_llm_first_run_short_circuits():
    llm = _FakeLLM('{"kind":"material","summary":"x"}')
    r = await LLMDeltaStrategy(llm).classify(
        current_payload={"rows": []}, previous_hash=None,
    )
    assert r.kind == "first_run"
    assert llm.calls == []


# ─── LLM strategy — failure modes ───────────────────────────────────────
@pytest.mark.asyncio
async def test_llm_exception_degrades_to_material_not_none():
    """Suppressing a change is worse than paging too eagerly."""
    class Boom:
        async def __call__(self, messages):
            raise RuntimeError("provider down")

    r = await LLMDeltaStrategy(Boom()).classify(
        current_payload={"a": 2}, previous_hash="x",
    )
    assert r.kind == "material"
    assert r.fallback_reason and "llm_error" in r.fallback_reason
    assert r.summary


@pytest.mark.asyncio
async def test_llm_unparseable_response_degrades_to_material():
    llm = _FakeLLM("here is my take: something changed a bit")
    r = await LLMDeltaStrategy(llm).classify(
        current_payload={"a": 2}, previous_hash="x",
    )
    assert r.kind == "material"
    assert r.fallback_reason == "unparseable_json"


@pytest.mark.asyncio
async def test_llm_tolerates_markdown_code_fences():
    llm = _FakeLLM(
        '```json\n{"kind": "material", "summary": "X dropped"}\n```'
    )
    r = await LLMDeltaStrategy(llm).classify(
        current_payload={"a": 2}, previous_hash="x",
    )
    assert r.kind == "material"
    assert r.summary == "X dropped"


@pytest.mark.asyncio
async def test_llm_clamps_overlong_summary():
    llm = _FakeLLM(
        '{"kind":"material","summary":"' + ("long " * 60) + '"}'
    )
    r = await LLMDeltaStrategy(llm).classify(
        current_payload={"a": 2}, previous_hash="x",
    )
    assert len(r.summary) <= 200


@pytest.mark.asyncio
async def test_llm_rejects_unknown_kind_values():
    llm = _FakeLLM('{"kind": "catastrophic", "summary": "boom"}')
    r = await LLMDeltaStrategy(llm).classify(
        current_payload={"a": 2}, previous_hash="x",
    )
    # Not in the canonical set → treated as unparseable.
    assert r.kind == "material"
    assert r.fallback_reason == "unparseable_json"


# ─── payload size budget ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_llm_truncates_large_payloads():
    llm = _FakeLLM('{"kind":"trivial","summary":"ok"}')
    # Big payload on both sides.
    big = {"rows": [{"i": i, "v": "x" * 50} for i in range(1000)]}
    await LLMDeltaStrategy(llm, max_chars_per_side=2000).classify(
        current_payload=big, previous_hash="x", previous_payload=big,
    )
    # User message should never exceed roughly 2× budget + prompt overhead.
    user_msg = llm.calls[0][1]["content"]
    assert len(user_msg) < 6000
    assert "truncated" in user_msg
