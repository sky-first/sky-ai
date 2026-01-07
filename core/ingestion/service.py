# core/ingestion/service.py
from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import DataConnection, Space
from core.ingestion.db_metadata import ingest_metadata_for_connection
from core.rag.embeddings import (
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
    create_embeddings_for_table_metadata,
)
from core.logging_utils import log_event


class ConnectionNotFoundError(Exception):
    pass


class SpaceNotFoundError(Exception):
    pass


async def _get_connection_and_space(
    db: AsyncSession, connection_id: str, space_id: str
) -> tuple[DataConnection, Space]:
    result = await db.execute(
        select(DataConnection).filter(
            DataConnection.id == connection_id,
            DataConnection.space_id == space_id,
        )
    )
    dc = result.scalar_one_or_none()
    if not dc:
        raise ConnectionNotFoundError(f"DataConnection {connection_id} not found in space {space_id}")

    result = await db.execute(select(Space).filter(Space.id == space_id))
    space = result.scalar_one_or_none()
    if not space:
        raise SpaceNotFoundError(f"Space {space_id} not found")

    return dc, space


async def run_metadata_ingestion(
    db: AsyncSession,
    space_id: str,
    connection_id: str,
    crew_id: Optional[str] = None,
) -> int:
    """
    Executa apenas a ingestão de metadados (INFORMATION_SCHEMA -> TableMetadata)
    para uma conexão específica.
    """
    dc, space = await _get_connection_and_space(db, connection_id, space_id)

    inserted = await ingest_metadata_for_connection(
        db=db,
        data_connection=dc,
        space=space,
        crew_id=crew_id,
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
    return inserted


async def run_metadata_embeddings(
    db: AsyncSession,
    space_id: str,
    connection_id: str,
    crew_id: Optional[str] = None,
    embedding_provider: Optional[EmbeddingProvider] = None,
) -> int:
    """
    Cria embeddings de metadados (TableMetadata -> EmbeddingRecord) para uma conexão específica.
    """
    dc, space = await _get_connection_and_space(db, connection_id, space_id)

    if embedding_provider is None:
        embedding_provider = OpenAIEmbeddingProvider()

    created = await create_embeddings_for_table_metadata(
        db=db,
        embedding_provider=embedding_provider,
        space_id=space.id,
        crew_id=crew_id,
        data_connection_id=dc.id,
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
    space_id: str,
    connection_id: str,
    crew_id: Optional[str] = None,
    embedding_provider: Optional[EmbeddingProvider] = None,
) -> dict:
    """
    Faz o fluxo completo:
      1) Ingestão de metadados (TableMetadata)
      2) Geração de embeddings (EmbeddingRecord)
    Retorna um resumo com contagens.
    """
    if embedding_provider is None:
        embedding_provider = OpenAIEmbeddingProvider()

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
