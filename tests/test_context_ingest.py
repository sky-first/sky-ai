"""Tests for the context-ingest pipeline — Phase 2.4.

The pure pipeline ``process_event`` is fully unit-tested here with
in-memory fakes for fetch_row / embed / upsert / soft_delete. Redis
and Postgres integration lives in ``worker/context_ingest_worker.py``
and is covered by the E2E test in Phase 2.7.
"""

from __future__ import annotations

import pytest

from core.rag.context_ingest import ContextEvent, UpsertSpec, process_event


def make_event(**kwargs):
    defaults = dict(
        action="upsert",
        kind="goal",
        source_table="strategic_objectives",
        source_id="g-1",
        space_id="s-1",
        crew_id=None,
        owner_user_id=None,
        visibility="space",
        meta=None,
    )
    defaults.update(kwargs)
    return ContextEvent(**defaults)


class FakeStore:
    """Minimal stand-in for the Postgres upsert path."""

    def __init__(self):
        self.upserts: list[UpsertSpec] = []
        self.deletes: list[tuple[str, str]] = []
        self.known_rows: dict[tuple[str, str], bool] = {}

    async def upsert(self, spec: UpsertSpec) -> None:
        self.upserts.append(spec)
        self.known_rows[(spec.source_table, spec.source_id)] = True

    async def soft_delete(self, table: str, sid: str) -> bool:
        existed = self.known_rows.pop((table, sid), False)
        self.deletes.append((table, sid))
        return bool(existed)


async def _ok_embed(text: str):
    # Predictable 4-d vector so assertions stay readable.
    return [0.1, 0.2, 0.3, 0.4]


async def _null_embed(text: str):
    return None


async def _exploding_embed(text: str):
    raise RuntimeError("provider down")


# ─── P1 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_upsert_goal_renders_and_writes():
    store = FakeStore()
    fetched = {"type": "corporate", "title": "Grow ARR 20%", "description": "north star", "status": "on_track"}

    async def fetch(_evt):
        return fetched

    status = await process_event(
        make_event(),
        fetch_row=fetch,
        embed=_ok_embed,
        upsert=store.upsert,
        soft_delete=store.soft_delete,
    )
    assert status == "upserted"
    assert len(store.upserts) == 1
    spec = store.upserts[0]
    assert spec.kind == "goal"
    assert "Grow ARR 20%" in spec.title
    assert "north star" in spec.body
    assert spec.space_id == "s-1"
    assert spec.embedding == [0.1, 0.2, 0.3, 0.4]
    assert spec.indexed_at is not None


# ─── P2 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_delete_event_soft_deletes():
    store = FakeStore()
    store.known_rows[("strategic_objectives", "g-1")] = True

    async def fetch(_):
        raise AssertionError("fetch must not be called on delete")

    status = await process_event(
        make_event(action="delete"),
        fetch_row=fetch,
        embed=_ok_embed,
        upsert=store.upsert,
        soft_delete=store.soft_delete,
    )
    assert status == "deleted"
    assert store.deletes == [("strategic_objectives", "g-1")]
    assert store.upserts == []


# ─── P3 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_delete_for_unknown_row_returns_skipped_no_row():
    store = FakeStore()

    async def fetch(_):
        return None

    status = await process_event(
        make_event(action="delete"),
        fetch_row=fetch,
        embed=_ok_embed,
        upsert=store.upsert,
        soft_delete=store.soft_delete,
    )
    assert status == "skipped_no_row"


# ─── P4 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_no_template_for_kind_is_skipped_not_crashed():
    store = FakeStore()

    async def fetch(_):
        return {"title": "x"}

    status = await process_event(
        make_event(kind="totally_made_up"),
        fetch_row=fetch,
        embed=_ok_embed,
        upsert=store.upsert,
        soft_delete=store.soft_delete,
    )
    assert status == "skipped_no_template"
    assert store.upserts == []


# ─── P5 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_row_gone_between_emit_and_fetch_soft_deletes():
    store = FakeStore()
    store.known_rows[("strategic_objectives", "g-1")] = True

    async def fetch(_):
        return None  # the source row was deleted after the event was queued

    status = await process_event(
        make_event(),
        fetch_row=fetch,
        embed=_ok_embed,
        upsert=store.upsert,
        soft_delete=store.soft_delete,
    )
    assert status == "skipped_no_row"
    assert store.deletes == [("strategic_objectives", "g-1")]


# ─── P6 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_missing_source_fields_rejected_early():
    store = FakeStore()

    async def fetch(_):
        raise AssertionError("must not be called")

    status = await process_event(
        make_event(source_table="", source_id=""),
        fetch_row=fetch,
        embed=_ok_embed,
        upsert=store.upsert,
        soft_delete=store.soft_delete,
    )
    assert status == "skipped_bad_event"


# ─── P7 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_embedder_returning_none_still_upserts_row():
    store = FakeStore()

    async def fetch(_):
        return {"type": "corporate", "title": "x"}

    status = await process_event(
        make_event(),
        fetch_row=fetch,
        embed=_null_embed,
        upsert=store.upsert,
        soft_delete=store.soft_delete,
    )
    assert status == "upserted"
    assert store.upserts[0].embedding is None


# ─── P8 ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_embedder_crashing_still_upserts_row():
    store = FakeStore()

    async def fetch(_):
        return {"type": "corporate", "title": "x"}

    status = await process_event(
        make_event(),
        fetch_row=fetch,
        embed=_exploding_embed,
        upsert=store.upsert,
        soft_delete=store.soft_delete,
    )
    assert status == "upserted"
    assert store.upserts[0].embedding is None


# ─── P9 ───────────────────────────────────────────────────────────────────
def test_from_payload_accepts_string_or_dict():
    raw = '{"action":"upsert","kind":"goal","source_table":"t","source_id":"1"}'
    e1 = ContextEvent.from_payload(raw)
    e2 = ContextEvent.from_payload({"action": "upsert", "kind": "goal", "source_table": "t", "source_id": "1"})
    assert e1 == e2
    assert e1.action == "upsert"
    assert e1.kind == "goal"


# ─── P10 ──────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_upsert_merges_event_meta_with_template_metadata():
    store = FakeStore()

    async def fetch(_):
        return {"type": "corporate", "title": "x", "priority": "P0", "status": "at_risk", "area": "growth"}

    status = await process_event(
        make_event(meta={"source_origin": "backend-api"}),
        fetch_row=fetch,
        embed=_null_embed,
        upsert=store.upsert,
        soft_delete=store.soft_delete,
    )
    assert status == "upserted"
    merged = store.upserts[0].metadata
    assert merged["source_origin"] == "backend-api"  # from event
    assert merged["priority"] == "P0"  # from template
