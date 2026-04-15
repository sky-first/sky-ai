"""Unit tests for the brain searcher — Phase 2.8.

The production SQL path (context_documents + legacy embeddings) can't
run without Postgres + pgvector, so these tests cover the *adapter*
and *merge* logic via monkeypatching. The E2E of the retrieval +
ranking layer is in test_brain_e2e.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from core.rag.brain_searcher import (
    _legacy_kind,
    _legacy_title,
    _overlap_score,
    _tokenize,
    make_brain_searcher,
)
from core.rag.context_brain import CandidateDoc


def test_tokenize_drops_short_tokens_and_lowercases():
    toks = _tokenize("QUAIS meus OKRs de Q4")
    # 'de', 'q4' drop out (≤2 chars after lower() not-quite; but 'de'
    # is exactly 2 so drops; 'q4' is 2 so drops). 'quais', 'meus', 'okrs'.
    assert "quais" in toks and "meus" in toks and "okrs" in toks
    assert "de" not in toks


def test_overlap_score_zero_when_no_tokens_match():
    score = _overlap_score(_tokenize("financial revenue"), "goals and okrs", "quarterly growth")
    assert score == 0.0


def test_overlap_score_caps_at_one_when_all_tokens_match():
    q = _tokenize("revenue quarterly growth")
    score = _overlap_score(q, "Revenue report", "Quarterly growth summary")
    assert score == pytest.approx(1.0)


def test_legacy_kind_maps_table_and_column_metadata():
    assert _legacy_kind({"type": "table_metadata"}) == "table"
    assert _legacy_kind({"type": "column_metadata"}) == "column"
    assert _legacy_kind({"kind": "business_context"}) == "glossary"
    assert _legacy_kind({"type": "connection"}) == "connection"
    # Unknown defaults to 'table' — legacy rows are overwhelmingly table-shaped.
    assert _legacy_kind({"type": "random"}) == "table"
    assert _legacy_kind({}) == "table"


def test_legacy_title_prefers_table_name_then_column_name():
    assert _legacy_title({"table_name": "orders"}) == "orders"
    assert _legacy_title({"column_name": "revenue"}) == "revenue"
    # Name fallback.
    assert _legacy_title({"name": "custom"}) == "custom"
    # Ultimate fallback uses the kind string.
    assert _legacy_title({"type": "table_metadata"}) == "table metadata"


@pytest.mark.asyncio
async def test_searcher_merges_and_deduplicates_both_stores(monkeypatch):
    """When both stores return the same (source_table, source_id), the
    newer store wins. That's important because renders from
    `core.rag.render` are canonical and the old table's body is a raw
    description."""

    same_id = "orders"
    new_doc = CandidateDoc(
        id="new-1",
        kind="table",
        source_table="table_metadata",
        source_id=same_id,
        title="Orders (new render)",
        body="Rich template body from core.rag.render.table",
        metadata={"row_count": 120_000},
        space_id="s-1",
        crew_id=None,
        owner_user_id=None,
        visibility="space",
        pii_flags=[],
        updated_at=datetime.now(timezone.utc),
        cosine=0.8,
        bm25=0.2,
    )
    legacy_doc = CandidateDoc(
        id="legacy-1",
        kind="table",
        source_table="table_metadata",
        source_id=same_id,
        title="orders (raw)",
        body="raw description from old path",
        metadata={},
        space_id="s-1",
        crew_id=None,
        owner_user_id=None,
        visibility="space",
        pii_flags=[],
        updated_at=datetime.now(timezone.utc),
        cosine=0.5,
        bm25=0.1,
    )

    from core.rag import brain_searcher

    async def fake_new(*args, **kwargs):
        return [new_doc]

    async def fake_legacy(*args, **kwargs):
        return [legacy_doc]

    monkeypatch.setattr(brain_searcher, "_search_context_documents", fake_new)
    monkeypatch.setattr(brain_searcher, "_search_legacy_embeddings", fake_legacy)

    searcher = make_brain_searcher(
        db=AsyncMock(),
        embedding_provider=AsyncMock(),
        space_id="s-1",
    )
    results = await searcher("show me orders", None, None, 10)

    assert len(results) == 1
    # The NEW doc wins the dedup.
    assert results[0].title == "Orders (new render)"
    assert results[0].id == "new-1"


@pytest.mark.asyncio
async def test_searcher_skips_legacy_when_kinds_exclude_legacy_kinds(monkeypatch):
    """Only ``connection`` / ``table`` / ``column`` are served by the
    legacy store. If the caller asks only for strategy kinds, we must
    not waste a query on the legacy table."""

    from core.rag import brain_searcher

    legacy_calls = 0

    async def fake_new(*args, **kwargs):
        return []

    async def fake_legacy(*args, **kwargs):
        nonlocal legacy_calls
        legacy_calls += 1
        return []

    monkeypatch.setattr(brain_searcher, "_search_context_documents", fake_new)
    monkeypatch.setattr(brain_searcher, "_search_legacy_embeddings", fake_legacy)

    searcher = make_brain_searcher(
        db=AsyncMock(),
        embedding_provider=AsyncMock(),
        space_id="s-1",
    )
    await searcher("okrs", None, ["goal", "okr"], 10)
    assert legacy_calls == 0, "must not query legacy when kinds are strategy-only"

    await searcher("tables", None, ["table", "column"], 10)
    assert legacy_calls == 1
