"""Scan schedule management — item 24 of the proactive intelligence roadmap.

Stores per-space scan configuration in the embeddings table with
kind='scan_schedule'. One record per space (upsert via document_id).

Fields stored in extra_metadata:
  kind:            'scan_schedule'
  space_id:        str UUID
  interval_hours:  int  (1, 6, 12, 24)
  enabled:         bool
  last_scan_at:    ISO-8601 UTC string or null
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Sentinel document_id prefix so we can upsert cleanly.
_DOC_ID_PREFIX = "scan_schedule:"


def _doc_id(space_id: str) -> str:
    return f"{_DOC_ID_PREFIX}{space_id}"


# ─── Public API ───────────────────────────────────────────────────────────────


async def get_scan_schedule(db: AsyncSession, space_id: str) -> Optional[dict]:
    """Return the scan schedule config for a space, or None if not configured."""
    try:
        result = await db.execute(
            text(
                "SELECT metadata FROM embeddings "
                "WHERE document_id = :doc_id LIMIT 1"
            ),
            {"doc_id": _doc_id(space_id)},
        )
        row = result.fetchone()
        if row:
            return row[0]
        return None
    except Exception as exc:
        logger.warning("get_scan_schedule failed for space %s: %s", space_id, exc)
        return None


async def set_scan_schedule(
    db: AsyncSession,
    space_id: str,
    interval_hours: int,
    enabled: bool = True,
) -> None:
    """Upsert the scan schedule for a space.

    interval_hours must be one of: 1, 6, 12, 24 (hourly, every 6h, twice-daily, daily).
    Raises ValueError for invalid intervals.
    """
    valid = {1, 6, 12, 24}
    if interval_hours not in valid:
        raise ValueError(f"interval_hours must be one of {sorted(valid)}, got {interval_hours}")

    from uuid import uuid4, UUID as _UUID
    from db.models import EmbeddingRecord

    doc_id = _doc_id(space_id)

    # Load existing to preserve last_scan_at
    existing = await get_scan_schedule(db, space_id)
    last_scan_at = (existing or {}).get("last_scan_at")

    space_uuid: Optional[_UUID] = None
    try:
        space_uuid = _UUID(space_id)
    except Exception:
        pass

    # Delete old record
    await db.execute(
        text("DELETE FROM embeddings WHERE document_id = :doc_id"),
        {"doc_id": doc_id},
    )

    dummy_embedding = [0.0] * 1024
    db.add(EmbeddingRecord(
        id=uuid4(),
        space_id=space_uuid,
        user_id=None,
        document_id=doc_id,
        embedding=dummy_embedding,
        text=f"scan_schedule for space {space_id}",
        extra_metadata={
            "kind": "scan_schedule",
            "space_id": space_id,
            "interval_hours": interval_hours,
            "enabled": enabled,
            "last_scan_at": last_scan_at,
        },
    ))
    await db.flush()
    logger.info(
        "set_scan_schedule: space=%s interval_hours=%d enabled=%s",
        space_id, interval_hours, enabled,
    )


async def update_last_scan_at(db: AsyncSession, space_id: str) -> None:
    """Record the current time as last_scan_at after a scan completes."""
    try:
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        await db.execute(
            text(
                "UPDATE embeddings "
                "SET metadata = jsonb_set(metadata, '{last_scan_at}', to_jsonb(:ts::text)) "
                "WHERE document_id = :doc_id"
            ),
            {"ts": now_iso, "doc_id": _doc_id(space_id)},
        )
        await db.flush()
    except Exception as exc:
        logger.warning("update_last_scan_at failed for space %s: %s", space_id, exc)


async def get_spaces_due_for_scan(db: AsyncSession) -> List[dict]:
    """Return all enabled spaces whose next scan is overdue.

    Returns list of dicts: [{space_id, interval_hours, connection_id}]
    where connection_id is the first active connection for the space.
    """
    try:
        result = await db.execute(
            text(
                "SELECT "
                "  e.metadata->>'space_id' AS space_id, "
                "  CAST(e.metadata->>'interval_hours' AS INTEGER) AS interval_hours, "
                "  e.metadata->>'last_scan_at' AS last_scan_at, "
                "  sc.connection_id::text AS connection_id "
                "FROM embeddings e "
                "JOIN space_connections sc ON sc.space_id = CAST(e.metadata->>'space_id' AS uuid) "
                "WHERE e.metadata->>'kind' = 'scan_schedule' "
                "AND e.metadata->>'enabled' = 'true' "
                "ORDER BY e.metadata->>'last_scan_at' ASC NULLS FIRST"
            )
        )
        rows = result.fetchall()

        now = datetime.now(tz=timezone.utc)
        due: dict = {}  # space_id → first connection

        for space_id, interval_hours, last_scan_at_str, connection_id in rows:
            if space_id in due:
                continue  # already picked a connection for this space

            if last_scan_at_str:
                try:
                    last = datetime.fromisoformat(last_scan_at_str)
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    next_scan = last + timedelta(hours=interval_hours)
                    if now < next_scan:
                        continue  # not due yet
                except Exception:
                    pass  # parse error → treat as due

            due[space_id] = {
                "space_id": space_id,
                "interval_hours": interval_hours,
                "connection_id": connection_id,
            }

        return list(due.values())

    except Exception as exc:
        logger.warning("get_spaces_due_for_scan failed: %s", exc)
        return []
