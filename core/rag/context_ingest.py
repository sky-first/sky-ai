"""Context ingest pipeline — Phase 2.4.

Consumes events from the ``context:ingest`` Redis stream (produced by
sky-poc-backend) and upserts corresponding ``context_documents`` rows.

Scope of this iteration:
  - The *pure* per-event pipeline: event + row + embedder + writer
    → render → embed → upsert / soft-delete.
  - Backend-client glue and Celery task wrapper live in
    ``worker/context_ingest_worker.py`` and are thin shims over the
    pure function here. That separation keeps the logic testable
    without Redis or the backend.

The AI service writes directly to the same Postgres instance as the
backend (they share a database). Writes are narrow — INSERT ON
CONFLICT DO UPDATE on ``(source_table, source_id)`` — because only
this worker ever touches the embedding column on ``context_documents``.
Backend writes (from ``ContextDocumentRepository.upsert``) always clear
``indexed_at`` so this worker will re-embed on next pass, which
guarantees eventual consistency.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.rag.render import RenderedDoc, has_template, render

logger = logging.getLogger(__name__)


# ───────────────────────────── types ──────────────────────────────────────
@dataclass(frozen=True)
class ContextEvent:
    """Mirror of the JSON payload pushed by the backend.

    The backend's `ContextEvent.to_json()` is authoritative — this is the
    read side. If the backend schema changes, bump the stream version
    explicitly (not yet needed; format is v1).
    """

    action: str  # 'upsert' | 'delete'
    kind: str
    source_table: str
    source_id: str
    space_id: Optional[str] = None
    crew_id: Optional[str] = None
    owner_user_id: Optional[str] = None
    visibility: str = "space"
    meta: dict[str, Any] | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | str) -> "ContextEvent":
        if isinstance(payload, str):
            payload = json.loads(payload)
        return cls(
            action=payload.get("action", "upsert"),
            kind=payload.get("kind", ""),
            source_table=payload.get("source_table", ""),
            source_id=payload.get("source_id", ""),
            space_id=payload.get("space_id"),
            crew_id=payload.get("crew_id"),
            owner_user_id=payload.get("owner_user_id"),
            visibility=payload.get("visibility", "space"),
            meta=payload.get("meta"),
        )


RowFetcher = Callable[[ContextEvent], Awaitable[dict[str, Any] | None]]
Embedder = Callable[[str], Awaitable[Sequence[float]] | None]
Writer = Callable[
    ["UpsertSpec"],
    Awaitable[None],
]


@dataclass
class UpsertSpec:
    """The final shape handed to the database writer."""

    kind: str
    source_table: str
    source_id: str
    title: str
    body: str
    metadata: dict[str, Any]
    space_id: Optional[str]
    crew_id: Optional[str]
    owner_user_id: Optional[str]
    visibility: str
    pii_flags: list[str]
    language: str
    embedding: Optional[Sequence[float]]
    indexed_at: datetime


# ─────────────────────────── pure pipeline ────────────────────────────────
async def process_event(
    event: ContextEvent,
    *,
    fetch_row: RowFetcher,
    embed: Embedder,
    upsert: Writer,
    soft_delete: Callable[[str, str], Awaitable[bool]],
) -> str:
    """Process ONE context event end-to-end.

    Returns a short status string for logging / metrics:
      'deleted'             — soft delete path
      'skipped_no_template' — kind has no renderer in core.rag.render
      'skipped_no_row'      — fetch_row returned None (row was gone)
      'skipped_bad_event'   — missing source_table / source_id
      'upserted'            — happy path

    Never raises on known-bad events; raises on genuinely unexpected
    errors so Celery retries do something useful.
    """
    if not event.source_table or not event.source_id:
        logger.warning("bad context event without source (%s)", event)
        return "skipped_bad_event"

    if event.action == "delete":
        ok = await soft_delete(event.source_table, event.source_id)
        return "deleted" if ok else "skipped_no_row"

    if not has_template(event.kind):
        logger.warning(
            "no render template for kind=%r — skipping %s", event.kind, event.source_id
        )
        return "skipped_no_template"

    row = await fetch_row(event)
    if row is None:
        # The row was deleted between emission and fetch. Soft-delete any
        # existing document so retrieval stops returning it.
        await soft_delete(event.source_table, event.source_id)
        return "skipped_no_row"

    doc = render(event.kind, row)

    # Embedding is best-effort: if the embedder returns None (dimension
    # mismatch, provider down, etc.) we still upsert the text — retrieval
    # falls back to full-text ranking until the next ingest pass.
    vector: Optional[Sequence[float]] = None
    try:
        vector = await embed(f"{doc.title}\n{doc.body}")
    except Exception:
        logger.exception(
            "embedding failed for %s/%s — upserting without vector",
            event.source_table,
            event.source_id,
        )

    spec = UpsertSpec(
        kind=event.kind,
        source_table=event.source_table,
        source_id=event.source_id,
        title=doc.title,
        body=doc.body,
        metadata=_merge_meta(event.meta, doc.metadata),
        space_id=event.space_id,
        crew_id=event.crew_id,
        owner_user_id=event.owner_user_id,
        visibility=event.visibility,
        pii_flags=doc.pii_flags,
        language=doc.language,
        embedding=list(vector) if vector is not None else None,
        indexed_at=datetime.now(timezone.utc),
    )
    await upsert(spec)
    return "upserted"


def _merge_meta(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if a:
        merged.update(a)
    if b:
        merged.update(b)
    return merged


# ─────────────────────── default Postgres writer ──────────────────────────
# The worker wires this in as `upsert`. Kept here so the sync-context
# tests can opt into the real SQL path against a real DB if they want.


async def postgres_upsert(db: AsyncSession, spec: UpsertSpec) -> None:
    """Insert-or-update one row of ``context_documents``.

    Uses raw SQL with ON CONFLICT because the AI service doesn't own
    the SQLAlchemy mapping for this table (the backend does) and we want
    this worker to be robust to the backend's schema drift in
    non-observed columns.
    """
    params = {
        "kind": spec.kind,
        "source_table": spec.source_table,
        "source_id": spec.source_id,
        "title": spec.title,
        "body": spec.body,
        "metadata": json.dumps(spec.metadata),
        "space_id": spec.space_id,
        "crew_id": spec.crew_id,
        "owner_user_id": spec.owner_user_id,
        "visibility": spec.visibility,
        "pii_flags": spec.pii_flags,
        "language": spec.language,
        "embedding": spec.embedding,
        "indexed_at": spec.indexed_at,
    }
    sql = text(
        """
        INSERT INTO context_documents
            (id, kind, source_table, source_id, title, body, metadata_jsonb,
             space_id, crew_id, owner_user_id, visibility, pii_flags,
             language, embedding, indexed_at, created_at, updated_at)
        VALUES
            (gen_random_uuid(), :kind, :source_table, :source_id, :title,
             :body, CAST(:metadata AS JSONB), :space_id, :crew_id,
             :owner_user_id, :visibility, :pii_flags, :language,
             :embedding, :indexed_at, NOW(), NOW())
        ON CONFLICT (source_table, source_id) DO UPDATE SET
            kind = EXCLUDED.kind,
            title = EXCLUDED.title,
            body = EXCLUDED.body,
            metadata_jsonb = EXCLUDED.metadata_jsonb,
            space_id = EXCLUDED.space_id,
            crew_id = EXCLUDED.crew_id,
            owner_user_id = EXCLUDED.owner_user_id,
            visibility = EXCLUDED.visibility,
            pii_flags = EXCLUDED.pii_flags,
            language = EXCLUDED.language,
            embedding = EXCLUDED.embedding,
            indexed_at = EXCLUDED.indexed_at,
            updated_at = NOW(),
            deleted_at = NULL
        """
    )
    await db.execute(sql, params)


async def postgres_soft_delete(
    db: AsyncSession, source_table: str, source_id: str
) -> bool:
    sql = text(
        """
        UPDATE context_documents
        SET deleted_at = NOW(), updated_at = NOW()
        WHERE source_table = :source_table
          AND source_id = :source_id
          AND deleted_at IS NULL
        """
    )
    result = await db.execute(
        sql, {"source_table": source_table, "source_id": source_id}
    )
    return bool(result.rowcount)
