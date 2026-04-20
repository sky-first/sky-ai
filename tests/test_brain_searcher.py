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


# ──────────── hidden-column filter (sky-poc-backend#190) ─────────────────

def _column_doc(conn_id: str, table: str, column: str, space_id: str = "s-1") -> CandidateDoc:
    return CandidateDoc(
        id=f"col-{column}",
        kind="column",
        source_table="column_metadata",
        source_id=column,
        title=f"Column: {table}.{column}",
        body=f"Column {table}.{column}",
        metadata={
            "connection_id": conn_id,
            "table_name": table,
            "column_name": column,
        },
        space_id=space_id,
        crew_id=None,
        owner_user_id=None,
        visibility="space",
        pii_flags=[],
        updated_at=datetime.now(timezone.utc),
        cosine=0.7,
        bm25=0.1,
    )


@pytest.mark.asyncio
async def test_hidden_column_filter_drops_matching_columns(monkeypatch):
    from core.rag import brain_searcher

    connection_id = str(uuid4())
    visible = _column_doc(connection_id, "customers", "name")
    hidden_email = _column_doc(connection_id, "customers", "email")
    hidden_ssn = _column_doc(connection_id, "customers", "ssn")

    async def fake_new(*args, **kwargs):
        return [visible, hidden_email, hidden_ssn]

    async def fake_legacy(*args, **kwargs):
        return []

    async def fake_fetch_hidden(_db, _space_id):
        return {(connection_id, "customers"): {"email", "ssn"}}

    monkeypatch.setattr(brain_searcher, "_search_context_documents", fake_new)
    monkeypatch.setattr(brain_searcher, "_search_legacy_embeddings", fake_legacy)
    monkeypatch.setattr(brain_searcher, "_fetch_hidden_columns_map", fake_fetch_hidden)

    searcher = make_brain_searcher(
        db=AsyncMock(),
        embedding_provider=AsyncMock(),
        space_id="s-1",
    )
    results = await searcher("show me customer data", None, None, 10)

    kept_columns = {d.metadata.get("column_name") for d in results if d.kind == "column"}
    assert kept_columns == {"name"}, (
        f"email+ssn should be filtered out of Space s-1; got {kept_columns}"
    )


@pytest.mark.asyncio
async def test_hidden_column_filter_noop_without_space_id(monkeypatch):
    """No space_id → no filter. Keeps personal/organization queries cheap."""
    from core.rag import brain_searcher

    col = _column_doc("c-1", "customers", "email", space_id="s-1")

    async def fake_new(*args, **kwargs):
        return [col]

    async def fake_legacy(*args, **kwargs):
        return []

    calls = {"fetch": 0}

    async def fake_fetch_hidden(_db, _space_id):
        calls["fetch"] += 1
        return {}

    monkeypatch.setattr(brain_searcher, "_search_context_documents", fake_new)
    monkeypatch.setattr(brain_searcher, "_search_legacy_embeddings", fake_legacy)
    monkeypatch.setattr(brain_searcher, "_fetch_hidden_columns_map", fake_fetch_hidden)

    searcher = make_brain_searcher(
        db=AsyncMock(),
        embedding_provider=AsyncMock(),
        space_id=None,
    )
    results = await searcher("email", None, None, 10)
    assert len(results) == 1
    assert calls["fetch"] == 0, "must not query space_tables when there is no space"


@pytest.mark.asyncio
async def test_hidden_column_filter_keeps_docs_without_full_triple(monkeypatch):
    """A column doc with incomplete metadata (legacy ingest, pre-fix)
    stays in the result — over-show is safer than silently drop.
    """
    from core.rag import brain_searcher

    incomplete = CandidateDoc(
        id="col-legacy",
        kind="column",
        source_table="column_metadata",
        source_id="legacy",
        title="Column: ?.email",
        body="raw",
        metadata={"column_name": "email"},  # no connection_id/table_name
        space_id="s-1",
        crew_id=None,
        owner_user_id=None,
        visibility="space",
        pii_flags=[],
        updated_at=datetime.now(timezone.utc),
        cosine=0.5,
        bm25=0.1,
    )

    async def fake_new(*args, **kwargs):
        return [incomplete]

    async def fake_legacy(*args, **kwargs):
        return []

    async def fake_fetch_hidden(_db, _space_id):
        return {("c-1", "customers"): {"email"}}

    monkeypatch.setattr(brain_searcher, "_search_context_documents", fake_new)
    monkeypatch.setattr(brain_searcher, "_search_legacy_embeddings", fake_legacy)
    monkeypatch.setattr(brain_searcher, "_fetch_hidden_columns_map", fake_fetch_hidden)

    searcher = make_brain_searcher(
        db=AsyncMock(),
        embedding_provider=AsyncMock(),
        space_id="s-1",
    )
    results = await searcher("email", None, None, 10)
    assert len(results) == 1
    assert results[0].id == "col-legacy"


@pytest.mark.asyncio
async def test_hidden_column_filter_never_touches_non_column_docs(monkeypatch):
    """Table, glossary, widget etc. pass through unchanged."""
    from core.rag import brain_searcher

    table = CandidateDoc(
        id="tbl-1",
        kind="table",
        source_table="table_metadata",
        source_id="customers",
        title="Table: customers",
        body="",
        metadata={"connection_id": "c-1"},
        space_id="s-1",
        crew_id=None,
        owner_user_id=None,
        visibility="space",
        pii_flags=[],
        updated_at=datetime.now(timezone.utc),
        cosine=0.9,
        bm25=0.2,
    )

    async def fake_new(*args, **kwargs):
        return [table]

    async def fake_legacy(*args, **kwargs):
        return []

    async def fake_fetch_hidden(_db, _space_id):
        # Even with hidden columns set, the table doc itself passes.
        return {("c-1", "customers"): {"email"}}

    monkeypatch.setattr(brain_searcher, "_search_context_documents", fake_new)
    monkeypatch.setattr(brain_searcher, "_search_legacy_embeddings", fake_legacy)
    monkeypatch.setattr(brain_searcher, "_fetch_hidden_columns_map", fake_fetch_hidden)

    searcher = make_brain_searcher(
        db=AsyncMock(),
        embedding_provider=AsyncMock(),
        space_id="s-1",
    )
    results = await searcher("customers", None, None, 10)
    assert len(results) == 1
    assert results[0].kind == "table"
