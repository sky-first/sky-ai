# core/ingestion/service.py
from __future__ import annotations

import logging
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text as _text

logger = logging.getLogger(__name__)

from db.models import DataConnection, EmbeddingRecord, Space, TableMetadata
from core.ingestion.db_metadata import ingest_metadata_for_connection
from core.rag.embeddings import (
    EmbeddingProvider,
    OllamaEmbeddingProvider,
    create_embeddings_for_table_metadata,
    get_embedding_provider,
)
from core.logging_utils import log_event


# ---------------------------------------------------------------------------
# Demo-connection helpers
# ---------------------------------------------------------------------------


def _demo_connection_ids() -> set:
    """Return the set of demo connection UUIDs (lowercased) from settings.

    Demo connections (NovaTech sandbox) are shared across ALL demo users in
    staging and production. Their TableMetadata and EmbeddingRecord rows are
    stored with space_id=NULL so every new demo visitor can query them
    without triggering a per-user re-seed.
    """
    from config.settings import settings

    raw = getattr(settings, "demo_dataset_connection_ids", "") or ""
    if isinstance(raw, (list, set, tuple)):
        return {str(x).strip().lower() for x in raw if str(x).strip()}
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def _is_demo_connection(connection_id) -> bool:
    return str(connection_id).lower() in _demo_connection_ids()


async def _demo_table_metadata_exists(db: AsyncSession, connection_id) -> bool:
    """True if global (space_id=NULL) TableMetadata already exists for this
    demo connection. Used as the early-exit guard to prevent a second demo
    user from deleting and re-inserting the shared rows — which would break
    the FK references held by EmbeddingRecord.table_metadata_id.
    """
    result = await db.execute(
        select(TableMetadata)
        .where(
            TableMetadata.data_connection_id == connection_id,
            TableMetadata.space_id.is_(None),
        )
        .limit(1)
    )
    return result.first() is not None


async def _demo_embeddings_exist(db: AsyncSession, connection_id) -> bool:
    """True if global (space_id=NULL) EmbeddingRecord rows already exist for
    this demo connection. Prevents re-embedding the same NovaTech schema
    for every new demo signup.
    """
    result = await db.execute(
        select(EmbeddingRecord)
        .join(TableMetadata, EmbeddingRecord.table_metadata_id == TableMetadata.id)
        .where(
            EmbeddingRecord.space_id.is_(None),
            TableMetadata.data_connection_id == connection_id,
        )
        .limit(1)
    )
    return result.first() is not None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ConnectionNotFoundError(Exception):
    pass


class SpaceNotFoundError(Exception):
    pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_connection_and_space(
    db: AsyncSession, connection_id: str, space_id: Optional[str] = None
) -> tuple[DataConnection, Optional[Space]]:
    from db.models import SpaceConnection

    if not space_id:
        # Global mode: just fetch connection
        result = await db.execute(
            select(DataConnection).where(DataConnection.id == connection_id)
        )
        dc = result.scalar_one_or_none()
        if not dc:
            raise ConnectionNotFoundError(f"DataConnection {connection_id} not found")
        return dc, None

    # Space-specific mode
    stmt = (
        select(DataConnection, Space)
        .join(SpaceConnection, SpaceConnection.connection_id == DataConnection.id)
        .join(Space, Space.id == SpaceConnection.space_id)
        .where(
            DataConnection.id == connection_id,
            Space.id == space_id,
        )
    )

    result = await db.execute(stmt)
    row = result.first()

    if not row:
        dc_check = await db.get(DataConnection, connection_id)
        space_check = await db.get(Space, space_id)
        if not dc_check:
            raise ConnectionNotFoundError(f"DataConnection {connection_id} not found")
        if not space_check:
            raise SpaceNotFoundError(f"Space {space_id} not found")
        raise ConnectionNotFoundError(
            f"DataConnection {connection_id} not found linked to space {space_id}"
        )

    return row[0], row[1]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_metadata_ingestion(
    db: AsyncSession,
    connection_id: str,
    space_id: Optional[str] = None,
    crew_id: Optional[str] = None,
    table_names: Optional[List[str]] = None,
) -> int:
    """Ingests table metadata (INFORMATION_SCHEMA → TableMetadata).

    For demo connections: stores rows with space_id=NULL (shared across all
    demo users). If global rows already exist the function returns 0 without
    touching the DB — this prevents the ingestion pipeline's DELETE+INSERT
    cycle from breaking the FK references held by shared EmbeddingRecord rows.
    """
    dc, space = await _get_connection_and_space(db, connection_id, space_id)

    if _is_demo_connection(connection_id):
        if await _demo_table_metadata_exists(db, dc.id):
            log_event(
                "demo_table_metadata_already_shared",
                {"connection_id": connection_id},
            )
            return 0
        # First user ever — seed globally (space=None → space_id=NULL in DB)
        effective_space = None
    else:
        effective_space = space

    from core.ingestion.db_metadata import ingest_from_connection_metadata_cache

    # ALWAYS use cached metadata from backend (connection_metadata).
    # This ensures backend and AI share the same schema source of truth.
    inserted = await ingest_from_connection_metadata_cache(
        db=db,
        data_connection=dc,
        space=effective_space,
        crew_id=crew_id,
        table_names=table_names,
    )

    log_event(
        "ingestion_run_metadata",
        {
            "space_id": space_id,
            "connection_id": connection_id,
            "crew_id": crew_id,
            "inserted": inserted,
        },
    )

    # ✅ PATCH: Update backend timestamp to prevent immediate staleness (infinite loop fix)
    from sqlalchemy import text

    await db.execute(
        text(
            "UPDATE connection_metadata SET last_metadata_update = NOW() WHERE connection_id = :cid"
        ),
        {"cid": connection_id},
    )
    await db.commit()

    return inserted


async def run_metadata_embeddings(
    db: AsyncSession,
    connection_id: str,
    space_id: Optional[str] = None,
    crew_id: Optional[str] = None,
    embedding_provider: Optional[EmbeddingProvider] = None,
    table_names: Optional[List[str]] = None,
) -> int:
    """Creates EmbeddingRecord rows from TableMetadata for a connection.

    For demo connections: embeddings are stored with space_id=NULL and seeded
    only once — subsequent demo signups find the shared rows and return 0
    immediately, saving embedding API calls.
    """
    dc, space = await _get_connection_and_space(db, connection_id, space_id)

    if embedding_provider is None:
        embedding_provider = get_embedding_provider()

    if _is_demo_connection(connection_id):
        if await _demo_embeddings_exist(db, dc.id):
            log_event(
                "demo_embeddings_already_shared",
                {"connection_id": connection_id},
            )
            return 0
        effective_space_id = None
    else:
        effective_space_id = space.id if space else None

    created = await create_embeddings_for_table_metadata(
        db=db,
        embedding_provider=embedding_provider,
        space_id=effective_space_id,
        crew_id=crew_id,
        data_connection_id=dc.id,
        table_names=table_names,
    )

    log_event(
        "ingestion_run_embeddings",
        {
            "space_id": space_id,
            "connection_id": connection_id,
            "crew_id": crew_id,
            "created": created,
        },
    )

    return created


async def run_dataset_description_embeddings(
    db: AsyncSession,
    connection_id: str,
    space_id: Optional[str] = None,
    embedding_provider: Optional[EmbeddingProvider] = None,
) -> int:
    """Generate one EmbeddingRecord per table using table-level description + column names.

    Reads from `connection_metadata.tables` (backend source of truth) so descriptions
    captured by the backend UI are always picked up — even when column-level metadata
    has no description yet.

    Records are stored with extra_metadata.kind = 'dataset_description' and used by
    DatasetPriorityScorer (item 17) for cosine OKR→dataset relevance scoring.

    Safe to call repeatedly — deletes existing dataset_description records for this
    connection+space before inserting, acting as an upsert.
    """
    from sqlalchemy import text as _text
    from uuid import UUID as _UUID, uuid4

    if embedding_provider is None:
        embedding_provider = get_embedding_provider()

    # Load table catalog from connection_metadata (source of truth)
    try:
        result = await db.execute(
            _text(
                "SELECT tables FROM connection_metadata "
                "WHERE connection_id = CAST(:cid AS uuid) LIMIT 1"
            ),
            {"cid": connection_id},
        )
        tables_json = result.scalar_one_or_none()
    except Exception as exc:
        log_event(
            "dataset_description_embed_load_error",
            {"connection_id": connection_id, "error": str(exc)[:300]},
        )
        return 0

    if not tables_json or not isinstance(tables_json, list):
        return 0

    space_uuid: Optional[_UUID] = None
    if space_id:
        try:
            space_uuid = _UUID(space_id)
        except Exception:
            pass

    # Delete stale dataset_description embeddings for this connection+space
    try:
        if space_uuid:
            await db.execute(
                _text(
                    "DELETE FROM embeddings "
                    "WHERE space_id = CAST(:sid AS uuid) "
                    "AND metadata->>'kind' = 'dataset_description' "
                    "AND metadata->>'data_connection_id' = :cid"
                ),
                {"sid": str(space_uuid), "cid": connection_id},
            )
        else:
            await db.execute(
                _text(
                    "DELETE FROM embeddings "
                    "WHERE space_id IS NULL "
                    "AND metadata->>'kind' = 'dataset_description' "
                    "AND metadata->>'data_connection_id' = :cid"
                ),
                {"cid": connection_id},
            )
    except Exception as exc:
        log_event(
            "dataset_description_embed_delete_error",
            {"connection_id": connection_id, "error": str(exc)[:300]},
        )
        try:
            await db.rollback()
        except Exception:
            pass
        return 0

    # Build one text blob per table
    items = []
    for table in tables_json:
        if not isinstance(table, dict):
            continue
        table_name = table.get("name") or table.get("table_name")
        if not table_name:
            continue
        schema = table.get("schema") or ""
        logical_name = f"{schema}.{table_name}" if schema else table_name
        description = table.get("description") or table.get("desc") or ""
        columns = table.get("columns") or []
        col_names = [
            (c.get("name") if isinstance(c, dict) else str(c)) for c in columns if c
        ]

        text_parts = [f"Dataset: {logical_name}"]
        if description:
            text_parts.append(f"Description: {description}")
        if col_names:
            text_parts.append(f"Columns: {', '.join(col_names[:30])}")
        text = " | ".join(text_parts)

        items.append(
            {
                "logical_name": logical_name,
                "table_name": table_name,
                "text": text,
            }
        )

    if not items:
        return 0

    # Embed all texts in one call
    try:
        vectors = await embedding_provider.embed_async([item["text"] for item in items])
    except Exception as exc:
        log_event(
            "dataset_description_embed_error",
            {"connection_id": connection_id, "error": str(exc)[:300]},
        )
        return 0

    created = 0
    for item, vec in zip(items, vectors):
        db.add(
            EmbeddingRecord(
                id=uuid4(),
                space_id=space_uuid,
                user_id=None,
                crew_id=None,
                table_metadata_id=None,
                embedding=vec,
                text=item["text"],
                extra_metadata={
                    "kind": "dataset_description",
                    "data_connection_id": connection_id,
                    "table_name": item["table_name"],
                    "logical_name": item["logical_name"],
                },
            )
        )
        created += 1

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        log_event(
            "dataset_description_embed_commit_error",
            {"connection_id": connection_id, "error": str(exc)[:300]},
        )
        return 0

    log_event(
        "dataset_description_embeddings_created",
        {
            "connection_id": connection_id,
            "space_id": space_id,
            "created": created,
        },
    )
    return created


async def run_full_refresh_for_connection(
    db: AsyncSession,
    connection_id: str,
    space_id: Optional[str] = None,
    crew_id: Optional[str] = None,
    embedding_provider: Optional[EmbeddingProvider] = None,
) -> dict:
    """Full pipeline: metadata ingestion → embedding generation.

    For demo connections both steps are no-ops after the first seed, so
    calling this function on every demo signup costs nothing after user #1.
    """
    if embedding_provider is None:
        embedding_provider = get_embedding_provider()

    inserted = await run_metadata_ingestion(
        db=db,
        space_id=space_id,
        connection_id=connection_id,
        crew_id=crew_id,
    )
    created = await run_metadata_embeddings(
        db=db,
        space_id=space_id,
        connection_id=connection_id,
        crew_id=crew_id,
        embedding_provider=embedding_provider,
    )

    dataset_emb = await run_dataset_description_embeddings(
        db=db,
        connection_id=connection_id,
        space_id=space_id,
        embedding_provider=embedding_provider,
    )

    summary = {
        "metadata_rows_inserted": inserted,
        "embeddings_created": created,
        "dataset_embeddings_created": dataset_emb,
    }

    log_event(
        "ingestion_run_full_refresh",
        {
            "space_id": space_id,
            "connection_id": connection_id,
            "crew_id": crew_id,
            **summary,
        },
    )
    return summary


async def refresh_dataset_embeddings_for_space(space_id: str) -> int:
    """Regenerate dataset_description embeddings for every connection in a space.

    Creates its own DB session so it can be launched as a fire-and-forget
    asyncio task (e.g. after a new OKR/KPI is added to the brain — item 19).

    Returns the total number of EmbeddingRecords created across all connections.
    """
    from db.session import AsyncSessionLocal

    embedding_provider = get_embedding_provider()
    total_created = 0

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                _text(
                    "SELECT connection_id FROM space_connections "
                    "WHERE space_id = CAST(:sid AS uuid)"
                ),
                {"sid": space_id},
            )
            connection_ids = [str(row[0]) for row in result.fetchall()]

        if not connection_ids:
            logger.debug(
                "refresh_dataset_embeddings_for_space: no connections for space %s",
                space_id,
            )
            return 0

        for conn_id in connection_ids:
            async with AsyncSessionLocal() as db:
                created = await run_dataset_description_embeddings(
                    db=db,
                    connection_id=conn_id,
                    space_id=space_id,
                    embedding_provider=embedding_provider,
                )
                total_created += created

        log_event(
            "dataset_embeddings_refreshed_on_okr_change",
            {
                "space_id": space_id,
                "connections_refreshed": len(connection_ids),
                "total_embeddings_created": total_created,
            },
        )
    except Exception as exc:
        logger.warning(
            "refresh_dataset_embeddings_for_space failed for space %s: %s",
            space_id,
            exc,
        )

    return total_created
