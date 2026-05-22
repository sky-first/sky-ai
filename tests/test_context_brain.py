"""Tests for the context-brain retrieval — Phase 2.5.

Exercises the ranking and RBAC layer with an in-memory searcher. The
actual Postgres + pgvector + bm25 hybrid query path is covered by the
Phase 2.7 E2E test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.rag.context_brain import (
    CandidateDoc,
    INTENT_WEIGHTS,
    RankedDoc,
    Scope,
    format_evidence,
    retrieve_context,
)


def _doc(
    id: str,
    kind: str,
    *,
    visibility: str = "space",
    space_id: str | None = "s-1",
    crew_id: str | None = None,
    owner_user_id: str | None = None,
    cosine: float = 0.5,
    bm25: float = 0.3,
    age_days: float = 5.0,
    title: str | None = None,
    body: str = "body",
    pii_flags: list[str] | None = None,
) -> CandidateDoc:
    return CandidateDoc(
        id=id,
        kind=kind,
        source_table=f"{kind}s",
        source_id=id,
        title=title or f"{kind}-{id}",
        body=body,
        metadata={},
        space_id=space_id,
        crew_id=crew_id,
        owner_user_id=owner_user_id,
        visibility=visibility,
        pii_flags=pii_flags or [],
        updated_at=datetime.now(timezone.utc) - timedelta(days=age_days),
        cosine=cosine,
        bm25=bm25,
    )


def _make_searcher(pool: list[CandidateDoc]):
    async def _searcher(query, embedding, kinds, k):
        if kinds:
            return [d for d in pool if d.kind in set(kinds)]
        return list(pool)

    return _searcher


async def _null_embedder(_q):
    return None


# ─── R1 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_rbac_space_scope_excludes_other_spaces():
    pool = [
        _doc("a", "goal", space_id="s-1", cosine=0.9),
        _doc("b", "goal", space_id="s-2", cosine=0.99),  # different space
    ]
    result = await retrieve_context(
        "goals",
        Scope(space_id="s-1"),
        searcher=_make_searcher(pool),
        query_embedder=_null_embedder,
        intent="strategy",
    )
    assert [r.doc.id for r in result] == ["a"], "s-2 doc must be filtered"


# ─── R2 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_rbac_crew_scope_excludes_foreign_crews():
    pool = [
        _doc(
            "a", "widget", visibility="crew", space_id="s-1", crew_id="c-1", cosine=0.9
        ),
        _doc(
            "b", "widget", visibility="crew", space_id="s-1", crew_id="c-2", cosine=0.99
        ),
    ]
    result = await retrieve_context(
        "dashboard",
        Scope(space_id="s-1", crew_ids=["c-1"]),
        searcher=_make_searcher(pool),
        query_embedder=_null_embedder,
    )
    assert [r.doc.id for r in result] == ["a"]


# ─── R3 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_public_docs_always_visible():
    pool = [
        _doc("public1", "glossary", visibility="public", space_id=None, cosine=0.8),
    ]
    # Even with empty scope, public docs pass.
    result = await retrieve_context(
        "term",
        Scope(),
        searcher=_make_searcher(pool),
        query_embedder=_null_embedder,
    )
    assert len(result) == 1


# ─── R4 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_intent_weights_boost_relevant_kinds():
    # Two equally-strong candidates by cosine, but goal should win on
    # "strategy" intent because of the intent bonus.
    pool = [
        _doc("goal", "goal", cosine=0.60, bm25=0.10, age_days=10),
        _doc("widget", "widget", cosine=0.60, bm25=0.10, age_days=10),
    ]
    result = await retrieve_context(
        "okrs",
        Scope(space_id="s-1"),
        searcher=_make_searcher(pool),
        query_embedder=_null_embedder,
        intent="strategy",
    )
    assert result[0].doc.kind == "goal"
    assert result[0].components["intent_bonus"] == INTENT_WEIGHTS["strategy"]["goal"]


# ─── R5 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_recency_nudges_ranking_when_cosine_tied():
    pool = [
        _doc("fresh", "goal", cosine=0.5, bm25=0.3, age_days=1),
        _doc("stale", "goal", cosine=0.5, bm25=0.3, age_days=120),
    ]
    result = await retrieve_context(
        "goals",
        Scope(space_id="s-1"),
        searcher=_make_searcher(pool),
        query_embedder=_null_embedder,
        intent="strategy",
    )
    assert result[0].doc.id == "fresh"


# ─── R6 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_top_k_respected():
    pool = [_doc(f"d{i}", "goal", cosine=0.9 - i * 0.01) for i in range(30)]
    result = await retrieve_context(
        "x",
        Scope(space_id="s-1"),
        searcher=_make_searcher(pool),
        query_embedder=_null_embedder,
        k=5,
    )
    assert len(result) == 5


# ─── R7 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_kinds_filter_passes_through():
    calls: list = []

    async def tracking(query, embedding, kinds, k):
        calls.append(list(kinds) if kinds else None)
        return []

    await retrieve_context(
        "x",
        Scope(space_id="s-1"),
        searcher=tracking,
        query_embedder=_null_embedder,
        kinds=["goal", "okr"],
    )
    assert calls == [["goal", "okr"]]


# ─── R8 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_query_embedder_failure_still_returns_results():
    async def bad_embedder(_):
        raise RuntimeError("provider down")

    pool = [_doc("a", "goal", cosine=0.8)]
    result = await retrieve_context(
        "x",
        Scope(space_id="s-1"),
        searcher=_make_searcher(pool),
        query_embedder=bad_embedder,
        intent="strategy",
    )
    assert len(result) == 1


# ─── R9 ───────────────────────────────────────────────────────────────────
def test_format_evidence_prefixes_each_block_with_kind():
    docs = [
        RankedDoc(
            doc=_doc("a", "goal", title="Grow ARR", body="target: +20%"),
            score=0.9,
            components={},
        ),
        RankedDoc(
            doc=_doc("b", "table", title="orders", body="120k rows"),
            score=0.7,
            components={},
        ),
    ]
    formatted = format_evidence(docs)
    assert "[goal] Grow ARR" in formatted
    assert "[table] orders" in formatted


# ─── R10 ──────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_personal_docs_only_visible_to_owner():
    pool = [
        _doc(
            "a",
            "pin",
            visibility="user",
            space_id=None,
            owner_user_id="u-1",
            cosine=0.9,
        ),
        _doc(
            "b",
            "pin",
            visibility="user",
            space_id=None,
            owner_user_id="u-2",
            cosine=0.9,
        ),
    ]
    result = await retrieve_context(
        "pins",
        Scope(user_id="u-1"),
        searcher=_make_searcher(pool),
        query_embedder=_null_embedder,
    )
    assert [r.doc.id for r in result] == ["a"]
