# core/rag/pipelines.py
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session
from sqlalchemy.engine import Engine

from db.models import TableMetadata  # seus modelos de metadados
from core.metadata.extractors import InformationSchemaExtractor
from core.rag.embeddings import (
    EmbeddingProvider,
    create_embeddings_for_table_metadata,
)
from core.logging_utils import log_event


def ingest_sql_metadata_for_connection(
    db: Session,
    engine: Engine,
    space_id: str,
    data_connection_id: str,
    crew_id: Optional[str] = None,
    schema: Optional[str] = None,
    include_tables: Optional[List[str]] = None,
) -> int:
    """
    Pipeline simples:
      1) Conecta na base SQL do cliente via SQLAlchemy Engine
      2) Lê INFORMATION_SCHEMA (colunas, tipos, nullability)
      3) Converte em TableMetadata no Postgres do produto
      4) Retorna quantas colunas foram upsertadas

    NÃO lê dados de negócio, apenas schema.
    """
    extractor = InformationSchemaExtractor(label=f"conn_{data_connection_id}")

    metadata_rows = extractor.extract_table_metadata(
        engine=engine,
        schema=schema,
        include_tables=include_tables,
    )

    if not metadata_rows:
        log_event(
            "ingest_sql_metadata_no_rows",
            {
                "space_id": space_id,
                "data_connection_id": data_connection_id,
                "schema": schema,
            },
        )
        return 0

    upserted = 0

    for row in metadata_rows:
        table_name = row["table_name"]
        column_name = row["column_name"]
        data_type = row.get("data_type", "text")
        is_nullable = (row.get("is_nullable", "YES") == "YES")

        # Upsert bem simples: tenta achar a linha, se não tiver cria
        tm = (
            db.query(TableMetadata)
            .filter(
                TableMetadata.space_id == space_id,
                TableMetadata.data_connection_id == data_connection_id,
                TableMetadata.table_name == table_name,
                TableMetadata.column_name == column_name,
                TableMetadata.crew_id == crew_id,
            )
            .one_or_none()
        )

        if tm is None:
            tm = TableMetadata(
                space_id=space_id,
                crew_id=crew_id,
                data_connection_id=data_connection_id,
                table_name=table_name,
                column_name=column_name,
                data_type=data_type,
                is_nullable=is_nullable,
                description=None,
                extra={},
            )
            db.add(tm)
        else:
            # Atualiza tipos / nullability se mudaram
            tm.data_type = data_type
            tm.is_nullable = is_nullable

        upserted += 1

    db.commit()

    log_event(
        "ingest_sql_metadata_done",
        {
            "space_id": space_id,
            "data_connection_id": data_connection_id,
            "schema": schema,
            "crew_id": crew_id,
            "num_columns": upserted,
        },
    )

    return upserted


def ingest_sql_metadata_and_embeddings(
    db: Session,
    engine: Engine,
    embedding_provider: EmbeddingProvider,
    space_id: str,
    data_connection_id: str,
    crew_id: Optional[str] = None,
    schema: Optional[str] = None,
    include_tables: Optional[List[str]] = None,
) -> int:
    """
    Pipeline completo:
      1) Ingestão de metadados de uma conexão SQL
      2) Geração de embeddings em pgvector para TableMetadata

    Retorna quantos embeddings foram criados.
    """
    num_metadata = ingest_sql_metadata_for_connection(
        db=db,
        engine=engine,
        space_id=space_id,
        data_connection_id=data_connection_id,
        crew_id=crew_id,
        schema=schema,
        include_tables=include_tables,
    )

    if num_metadata == 0:
        log_event(
            "ingest_sql_metadata_and_embeddings_no_metadata",
            {
                "space_id": space_id,
                "data_connection_id": data_connection_id,
                "crew_id": crew_id,
            },
        )
        return 0

    num_embeddings = create_embeddings_for_table_metadata(
        db=db,
        embedding_provider=embedding_provider,
        space_id=space_id,
        crew_id=crew_id,
        data_connection_id=data_connection_id,
    )

    log_event(
        "ingest_sql_metadata_and_embeddings_done",
        {
            "space_id": space_id,
            "data_connection_id": data_connection_id,
            "crew_id": crew_id,
            "num_metadata": num_metadata,
            "num_embeddings": num_embeddings,
        },
    )

    return num_embeddings
