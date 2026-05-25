"""Tests for the surface-level brain access helper — Phase 2.9."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from core.rag import brain_access as ba
from core.rag.brain_access import (
    BrainAccess,
    davinci_context_section,
    fetch_brain_context_for_surface,
    sherlock_context_section,
)
from core.rag.context_brain import CandidateDoc, RankedDoc


def _fake_ranked(kind: str, title: str) -> RankedDoc:
    return RankedDoc(
        doc=CandidateDoc(
            id=f"id-{title}",
            kind=kind,
            source_table=f"{kind}s",
            source_id=title,
            title=title,
            body=f"{title} body",
            metadata={},
            space_id="s-1",
            crew_id=None,
            owner_user_id=None,
            visibility="space",
            pii_flags=[],
            updated_at=datetime.now(timezone.utc),
            cosine=0.8,
            bm25=0.1,
        ),
        score=0.9,
        components={},
    )


# ─── happy path ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_fetch_populates_doc_ids_prompt_block_kinds(monkeypatch):
    async def fake_retrieve(*args, **kwargs):
        return [_fake_ranked("okr", "Grow ARR"), _fake_ranked("table", "orders")]

    monkeypatch.setattr(ba, "retrieve_context", fake_retrieve)

    # make_brain_searcher returns a callable; we don't care here because
    # `retrieve_context` is swapped.
    result = await fetch_brain_context_for_surface(
        surface="chat_query",
        question="quais os okrs?",
        db=AsyncMock(),
        embedding_provider=AsyncMock(),
        space_id="s-1",
    )
    assert result.doc_ids == ["id-Grow ARR", "id-orders"]
    assert result.doc_kinds == ["okr", "table"]
    assert "Grow ARR" in result.prompt_block
    assert "[okr]" in result.prompt_block


# ─── defaults per surface ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_chat_bootstrap_defaults_to_strategic_kinds(monkeypatch):
    captured: dict = {}

    async def fake_retrieve(
        query, scope, *, searcher, query_embedder, intent, kinds, k
    ):
        captured["kinds"] = list(kinds) if kinds else None
        captured["k"] = k
        return []

    monkeypatch.setattr(ba, "retrieve_context", fake_retrieve)

    await fetch_brain_context_for_surface(
        surface="chat_bootstrap",
        question="help me start",
        db=AsyncMock(),
        embedding_provider=AsyncMock(),
        space_id="s-1",
    )
    # chat_bootstrap has a tight k (8) and a strategic-kind filter.
    assert captured["k"] == 8
    assert captured["kinds"] == [
        "pillar",
        "goal",
        "okr",
        "kpi",
        "table",
        "column",
        "connection",
    ]


@pytest.mark.asyncio
async def test_dashboard_plan_has_no_kind_filter(monkeypatch):
    captured: dict = {}

    async def fake_retrieve(*args, **kwargs):
        captured["kinds"] = kwargs.get("kinds")
        captured["k"] = kwargs.get("k")
        return []

    monkeypatch.setattr(ba, "retrieve_context", fake_retrieve)

    await fetch_brain_context_for_surface(
        surface="dashboard_plan",
        question="build me a growth dashboard",
        db=AsyncMock(),
        embedding_provider=AsyncMock(),
        space_id="s-1",
    )
    # dashboard_plan gets the full brain
    assert captured["kinds"] is None
    assert captured["k"] == 30


# ─── failure modes ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_empty_question_short_circuits_without_hitting_brain(monkeypatch):
    called = False

    async def fake_retrieve(*args, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(ba, "retrieve_context", fake_retrieve)

    r = await fetch_brain_context_for_surface(
        surface="chat_query",
        question="   ",
        db=AsyncMock(),
        embedding_provider=AsyncMock(),
        space_id="s-1",
    )
    assert called is False
    assert r.empty is True


@pytest.mark.asyncio
async def test_retrieve_context_exception_returns_empty(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ba, "retrieve_context", boom)

    r = await fetch_brain_context_for_surface(
        surface="agent_run",
        question="weekly check",
        db=AsyncMock(),
        embedding_provider=AsyncMock(),
        space_id="s-1",
    )
    assert r.empty is True


# ─── prompt-section helpers ───────────────────────────────────────────────
def test_sherlock_section_omits_empty_access():
    r = BrainAccess(surface="chat_bootstrap")
    assert sherlock_context_section(r) == ""


def test_sherlock_section_wraps_prompt_block_in_pt_tag():
    r = BrainAccess(
        surface="chat_bootstrap",
        doc_ids=["a"],
        doc_kinds=["okr"],
        prompt_block="[okr] Grow ARR\nbody",
    )
    s = sherlock_context_section(r)
    assert "<contexto_estrategico>" in s
    assert "</contexto_estrategico>" in s
    assert "[okr] Grow ARR" in s


def test_davinci_section_wraps_with_company_tag():
    r = BrainAccess(
        surface="dashboard_plan",
        doc_ids=["a"],
        doc_kinds=["goal"],
        prompt_block="[goal] x",
    )
    s = davinci_context_section(r)
    assert "<contexto_da_empresa>" in s
    assert "[goal] x" in s


def test_davinci_section_omits_empty_access():
    r = BrainAccess(surface="dashboard_plan")
    assert davinci_context_section(r) == ""
