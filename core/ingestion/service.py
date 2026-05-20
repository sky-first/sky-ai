# core/ingestion/service.py
from __future__ import annotations

from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

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
        text("UPDATE connection_metadata SET last_metadata_update = NOW() WHERE connection_id = :cid"),
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

    summary = {
        "metadata_rows_inserted": inserted,
        "embeddings_created": created,
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
