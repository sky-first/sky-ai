"""End-to-end contract test — closes the loop on the context pipeline.

The pipeline has three moving parts across two repos:

1. Backend (sky-poc-backend) mutates a row → emits a `ContextEvent` to
   Redis via `src/core/context_events.py`.
2. Worker reads the event, fetches the row via
   `GET /api/v1/context/rows/{source_table}/{source_id}` (shipped in
   sky-poc-backend#189), passes it through `core.rag.render`.
3. Renderer produces `(title, body, metadata)` → embedded → upserted
   into `context_documents`.

These tests pin the CONTRACT between the backend serializer and the
AI render templates. A new field added to a backend model that a
renderer expects? This suite fails. A backend drops a field a
renderer relied on? This suite fails. Without these tests the only
way to catch a mismatch is to deploy, push an event, and watch the
worker log `skipped_no_row` or `upserted` with a broken body.

We simulate the backend response as a Python dict — the REAL shape
comes from `src/api/v1/context_rows.py:row_to_dict` which serializes
`__table__.columns`. For each kind we craft the dict that matches
that serialization (UUIDs as strings, Enums as .value, datetimes as
ISO), then run the full pipeline and assert invariants.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.rag.context_ingest import ContextEvent, UpsertSpec, process_event


class _Capturer:
    def __init__(self) -> None:
        self.specs: list[UpsertSpec] = []

    async def upsert(self, spec: UpsertSpec) -> None:
        self.specs.append(spec)

    async def soft_delete(self, *_args) -> bool:
        return False


async def _embed(_text: str):
    return [0.0] * 4


async def _run(kind: str, source_table: str, row: dict, **event_kwargs) -> UpsertSpec:
    """Simulate one event end-to-end and return the captured UpsertSpec."""
    store = _Capturer()
    evt = ContextEvent(
        action="upsert",
        kind=kind,
        source_table=source_table,
        source_id="11111111-1111-1111-1111-111111111111",
        space_id=event_kwargs.get("space_id", "22222222-2222-2222-2222-222222222222"),
        crew_id=event_kwargs.get("crew_id"),
        owner_user_id=event_kwargs.get("owner_user_id"),
        visibility="space",
        meta={},
    )

    async def fetch(_):
        return row

    status = await process_event(
        evt,
        fetch_row=fetch,
        embed=_embed,
        upsert=store.upsert,
        soft_delete=store.soft_delete,
    )
    assert status == "upserted", f"pipeline did not upsert — got {status!r}"
    assert len(store.specs) == 1
    return store.specs[0]


# ─── Glossary ────────────────────────────────────────────────────────────
# Fields that `_render_glossary` reads: term, definition.


@pytest.mark.asyncio
async def test_glossary_term_end_to_end():
    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "term": "ARR",
        "definition": "Annual Recurring Revenue — receita recorrente anualizada.",
        "notes": None,
        "space_id": "22222222-2222-2222-2222-222222222222",
        "created_at": datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc).isoformat(),
        "updated_at": datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc).isoformat(),
    }
    spec = await _run("glossary", "glossary_terms", row)

    assert "ARR" in spec.title, "glossary render must surface the term"
    assert "Annual Recurring Revenue" in spec.body
    assert spec.kind == "glossary"
    assert spec.source_table == "glossary_terms"


# ─── Strategy — Pillar ────────────────────────────────────────────────────
# Fields `_render_pillar` reads: title / name, description, owner, status.


@pytest.mark.asyncio
async def test_pillar_end_to_end():
    row = {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "name": "Customer Experience",
        "description": "Lift NPS from 42 to 60 by EOY 2026",
        "color": "#8b5cf6",
        "owner": None,
        "space_id": "22222222-2222-2222-2222-222222222222",
    }
    spec = await _run("pillar", "strategic_pillars", row)
    # Pillar title falls back to `name` when `title` is missing —
    # that's the contract the renderer relies on.
    assert "Customer Experience" in spec.title
    assert "NPS" in spec.body


# ─── Strategy — Goal (StrategicObjective) ─────────────────────────────────
# Fields `_render_goal` reads: title, description, type, status, priority,
# area, owner, kpis, budget, pillar_title.


@pytest.mark.asyncio
async def test_goal_end_to_end_all_fields_render():
    row = {
        "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "title": "Grow ARR by 30%",
        "description": "Corporate objective for FY26",
        "type": "corporate",
        "status": "on_track",
        "priority": "high",
        "area": "Revenue",
        "owner": "Lucas",
        "kpis": ["ARR", "CAC:LTV"],
        "budget": 250000.0,
    }
    spec = await _run("goal", "strategic_objectives", row)
    assert "Grow ARR by 30%" in spec.title
    # The renderer prints budget and kpis into the body — this guards
    # against the backend schema silently dropping those columns.
    assert "Corporate" in spec.body or "corporate" in spec.body
    assert "Revenue" in spec.body
    assert "ARR" in spec.body


# ─── Events ───────────────────────────────────────────────────────────────
# `_render_event_generic("internal")` reads title / sub_type, description,
# start_date, impact_date, nature, confidence, relations.


@pytest.mark.asyncio
async def test_event_internal_end_to_end():
    row = {
        "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "category": "INTERNAL",
        "sub_type": "deploy_failure",
        "nature": "EVENT",
        "confidence": "HIGH",
        "description": "Prod deploy rolled back in 12min.",
        "start_date": datetime(2026, 4, 19, 15, 30, tzinfo=timezone.utc).isoformat(),
        "impact_date": None,
        "relations": None,
        "space_id": "22222222-2222-2222-2222-222222222222",
    }
    spec = await _run("event_internal", "signal_events", row)
    assert "deploy_failure" in spec.title or "Deploy_failure" in spec.title
    assert "rolled back" in spec.body


# ─── Relationships ────────────────────────────────────────────────────────
# `_render_relationship` reads source_label/source_id, target_label/target_id,
# relationship_type/kind, strength, description.


@pytest.mark.asyncio
async def test_relationship_end_to_end():
    row = {
        "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "name": "ARR → MRR",
        "relationship_type": "derives_from",
        "description": "ARR derives from 12× MRR.",
        "source_label": "ARR",
        "target_label": "MRR",
        "strength": 0.95,
    }
    spec = await _run("relationship", "user_enterprise_relationships", row)
    assert "ARR" in spec.title
    assert "MRR" in spec.title


# ─── Connection ───────────────────────────────────────────────────────────
# `_render_connection` reads name, connection_type / type, description,
# tables.


@pytest.mark.asyncio
async def test_connection_end_to_end():
    row = {
        "id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        "name": "Prod Postgres",
        "connector_id": "postgres-primary",
        "type": "database",
        "description": "Primary prod cluster",
        "tables": ["customers", "orders"],
    }
    spec = await _run("connection", "data_connections", row)
    assert "Prod Postgres" in spec.title
    assert "postgres" in spec.body.lower() or "database" in spec.body.lower()


# ─── Column — with hidden_columns filter metadata ─────────────────────────
# Critical for the hidden_columns feature (sky-poc-backend#190 +
# sky-poc-ai#145): the render now stuffs (connection_id, table_name,
# column_name) into metadata so the retrieval filter has the triple it
# needs. If this contract drifts, filtering silently stops working.


@pytest.mark.asyncio
async def test_column_metadata_exposes_triple_for_hidden_columns_filter():
    row = {
        "id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
        "name": "email",
        "table_name": "customers",
        "connection_id": "99999999-9999-9999-9999-999999999999",
        "data_type": "varchar",
        "is_nullable": True,
        "is_pii": True,
        "sample_values": ["jane@example.com"],
    }
    spec = await _run("column", "column_metadata", row)
    assert spec.metadata.get("connection_id") == "99999999-9999-9999-9999-999999999999"
    assert spec.metadata.get("table_name") == "customers"
    assert spec.metadata.get("column_name") == "email"
    # PII flag must propagate so the response filter can mask values.
    assert "email" in spec.pii_flags


# ─── Soft-delete path (404 from context/rows → mark deleted) ─────────────


@pytest.mark.asyncio
async def test_soft_delete_when_fetch_returns_none():
    """Matches the contract: backend returns 404 for deleted rows, the
    ingest worker treats that as None from fetch_row, and the pipeline
    soft-deletes the document instead of trying to upsert garbage.
    """

    class _Sink:
        def __init__(self):
            self.soft_deleted: list[tuple[str, str]] = []
            self.upserts: list[UpsertSpec] = []

        async def upsert(self, spec):
            self.upserts.append(spec)

        async def soft_delete(self, table, sid):
            self.soft_deleted.append((table, sid))
            return True

    sink = _Sink()
    evt = ContextEvent(
        action="upsert",
        kind="glossary",
        source_table="glossary_terms",
        source_id="gone-id",
        space_id=None,
        crew_id=None,
        owner_user_id=None,
        visibility="space",
        meta={},
    )

    async def fetch_returns_none(_):
        return None

    status = await process_event(
        evt,
        fetch_row=fetch_returns_none,
        embed=_embed,
        upsert=sink.upsert,
        soft_delete=sink.soft_delete,
    )
    assert status == "skipped_no_row"
    assert sink.soft_deleted == [("glossary_terms", "gone-id")]
    assert sink.upserts == []
