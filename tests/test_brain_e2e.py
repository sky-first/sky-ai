"""End-to-end test of the Phase-2 context brain — Phase 2.7.

Walks the whole pipeline with in-memory fakes for the I/O boundaries:

    backend event  →  process_event  →  render  →  embed  →  upsert  →
    store  →  retrieve_context  →  RBAC  →  rank  →  evidence blob

The claim: when a space is seeded with OKRs + a sales table + an
external market event, a user asking *"quais meus OKRs e como estão
vs o financeiro?"* gets back evidence that cites BOTH an OKR and the
sales table/column — proving the brain blends kinds in one pass.

The Postgres + pgvector path is covered by the worker's production
writers; this test deliberately uses a fake store because CI doesn't
have a vector-capable database available.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from core.rag.context_brain import (
    CandidateDoc,
    RankedDoc,
    Scope,
    format_evidence,
    retrieve_context,
)
from core.rag.context_ingest import (
    ContextEvent,
    UpsertSpec,
    process_event,
)
from core.rag.render import RenderedDoc


# ─────────────────────────── fixtures ─────────────────────────────────────
class FakeStore:
    """Combines writer + searcher used by the brain layer. Keeps rows
    keyed by (source_table, source_id) so upsert semantics match
    production."""

    def __init__(self):
        self.rows: dict[tuple[str, str], CandidateDoc] = {}

    async def upsert(self, spec: UpsertSpec) -> None:
        # Approximate cosine: length-1 deterministic score derived from
        # a hash of the body. The test only needs *some* ordering.
        cosine = 0.5 + (hash(spec.body) % 100) / 1000.0
        self.rows[(spec.source_table, spec.source_id)] = CandidateDoc(
            id=str(uuid4()),
            kind=spec.kind,
            source_table=spec.source_table,
            source_id=spec.source_id,
            title=spec.title,
            body=spec.body,
            metadata=spec.metadata,
            space_id=spec.space_id,
            crew_id=spec.crew_id,
            owner_user_id=spec.owner_user_id,
            visibility=spec.visibility,
            pii_flags=spec.pii_flags,
            updated_at=spec.indexed_at or datetime.now(timezone.utc),
            cosine=cosine,
            bm25=0.1,
        )

    async def soft_delete(self, table: str, sid: str) -> bool:
        removed = self.rows.pop((table, sid), None)
        return removed is not None

    async def search(self, query, embedding, kinds, k):
        # In the real implementation this is hybrid SQL; here we just
        # return every live row and let the ranking layer do its job.
        pool = list(self.rows.values())
        if kinds:
            pool = [d for d in pool if d.kind in set(kinds)]
        return pool


# ─────────────────────────── the E2E itself ───────────────────────────────
@pytest.mark.asyncio
async def test_okrs_vs_finance_question_blends_strategy_and_data():
    """The north-star test — mirrors Paulo's Portuguese prompt exactly."""
    store = FakeStore()
    SPACE = "space-novatech"

    # ── seed: three kinds of evidence the brain should blend.
    seeded = [
        # Strategy
        ContextEvent(
            action="upsert",
            kind="okr",
            source_table="strategy_okrs",
            source_id="okr-arr",
            space_id=SPACE,
            meta=None,
        ),
        ContextEvent(
            action="upsert",
            kind="goal",
            source_table="strategic_objectives",
            source_id="goal-growth",
            space_id=SPACE,
            meta=None,
        ),
        # Data
        ContextEvent(
            action="upsert",
            kind="table",
            source_table="table_metadata",
            source_id="orders-table",
            space_id=SPACE,
            meta=None,
        ),
        ContextEvent(
            action="upsert",
            kind="column",
            source_table="column_metadata",
            source_id="orders-revenue",
            space_id=SPACE,
            meta=None,
        ),
        # Noise from another space — RBAC must reject this.
        ContextEvent(
            action="upsert",
            kind="okr",
            source_table="strategy_okrs",
            source_id="okr-from-other-space",
            space_id="space-other",
            meta=None,
        ),
    ]
    rows_by_id = {
        "okr-arr": {"title": "Grow ARR 20%", "objective_title": "Increase ARR", "baseline": 70, "target": 100, "cycle_title": "Q4"},
        "goal-growth": {"type": "corporate", "title": "Increase ARR 20%", "description": "company north star", "status": "on_track"},
        "orders-table": {"name": "orders", "schema": "public", "connection_name": "finance_pg", "columns": ["id", "revenue", "customer_id"], "row_count": 125000},
        "orders-revenue": {"name": "revenue", "table_name": "orders", "data_type": "numeric", "description": "order revenue"},
        "okr-from-other-space": {"title": "Unreachable OKR", "objective_title": "Secret"},
    }

    async def fetch(evt: ContextEvent):
        return rows_by_id.get(evt.source_id)

    async def embed(text: str):
        # Pretend every body embeds fine — keeps the pipeline wet.
        return [0.0] * 4

    for evt in seeded:
        status = await process_event(
            evt,
            fetch_row=fetch,
            embed=embed,
            upsert=store.upsert,
            soft_delete=store.soft_delete,
        )
        assert status == "upserted", f"seed failure on {evt.source_id}"

    # ── the user asks the north-star question.
    ranked = await retrieve_context(
        "Quais meus OKRs e como estão vs o financeiro?",
        Scope(space_id=SPACE),
        searcher=store.search,
        query_embedder=lambda q: _mock_query_embedding(),
        intent="strategy",
    )

    kinds = [r.doc.kind for r in ranked]
    ids = [r.doc.source_id for r in ranked]

    assert "okr" in kinds, "brain must retrieve at least one OKR"
    assert any(k in kinds for k in ("table", "column")), "brain must retrieve data evidence"
    assert "okr-from-other-space" not in ids, "RBAC must block other-space docs"

    evidence = format_evidence(ranked)
    assert "[okr]" in evidence
    assert any(f"[{k}]" in evidence for k in ("table", "column"))


async def _mock_query_embedding():
    return [0.0, 0.0, 0.0, 0.0]


# ─── Targeted edge cases ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_deletion_flows_through_pipeline_and_hides_from_retrieval():
    store = FakeStore()
    SPACE = "s-1"

    async def fetch(_):
        return {"type": "corporate", "title": "Temporary", "status": "active"}

    async def embed(_):
        return [0.0] * 4

    # Insert, then delete.
    await process_event(
        ContextEvent(
            action="upsert",
            kind="goal",
            source_table="strategic_objectives",
            source_id="g-1",
            space_id=SPACE,
        ),
        fetch_row=fetch,
        embed=embed,
        upsert=store.upsert,
        soft_delete=store.soft_delete,
    )
    assert len(store.rows) == 1

    await process_event(
        ContextEvent(
            action="delete",
            kind="goal",
            source_table="strategic_objectives",
            source_id="g-1",
            space_id=SPACE,
        ),
        fetch_row=fetch,
        embed=embed,
        upsert=store.upsert,
        soft_delete=store.soft_delete,
    )

    ranked = await retrieve_context(
        "growth",
        Scope(space_id=SPACE),
        searcher=store.search,
        query_embedder=_mock_query_embedding,
        intent="strategy",
    )
    assert ranked == []


@pytest.mark.asyncio
async def test_rbac_isolates_crew_docs_across_crews():
    store = FakeStore()
    SPACE = "s-1"

    async def fetch(_):
        return {"title": "private insight"}

    async def embed(_):
        return [0.0] * 4

    await process_event(
        ContextEvent(
            action="upsert",
            kind="widget",
            source_table="widgets",
            source_id="w-crew-a",
            space_id=SPACE,
            crew_id="crew-a",
            visibility="crew",
        ),
        fetch_row=fetch,
        embed=embed,
        upsert=store.upsert,
        soft_delete=store.soft_delete,
    )
    await process_event(
        ContextEvent(
            action="upsert",
            kind="widget",
            source_table="widgets",
            source_id="w-crew-b",
            space_id=SPACE,
            crew_id="crew-b",
            visibility="crew",
        ),
        fetch_row=fetch,
        embed=embed,
        upsert=store.upsert,
        soft_delete=store.soft_delete,
    )

    ranked = await retrieve_context(
        "insights",
        Scope(space_id=SPACE, crew_ids=["crew-a"]),
        searcher=store.search,
        query_embedder=_mock_query_embedding,
    )

    ids = [r.doc.source_id for r in ranked]
    assert "w-crew-a" in ids
    assert "w-crew-b" not in ids
