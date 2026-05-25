# scripts/bootstrap_test_env.py
from __future__ import annotations

import os
from uuid import uuid4
from datetime import datetime

from sqlalchemy.orm import Session

from dotenv import load_dotenv

from db.base import SessionLocal
from db.models import Space, DataConnection, TableMetadata
from core.data_sources.factory import DataSourceFactory
from core.rag.embeddings import (
    OpenAIEmbeddingProvider,
    create_embeddings_for_table_metadata,
)
from core.logging_utils import log_event

# 📝 PARAMETROS DE TESTE – PODE MUDAR AQUI
SPACE_ID = "space-test"
SPACE_NAME = "Space de Teste IA"

CONNECTION_ID = "conn-test-bq"
CONNECTION_NAME = "Conexao BigQuery de Teste"

# Esses 3 valores devem bater com seu ambiente real
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "data-mesh-gcp")
DATASET = "data-mesh-gcp.billing_silver"  # ex: "project.dataset"
CREDENTIALS_PATH = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS",
    "/Users/thedatafirst/ia-poc-final/config/gcp/gcp-key.json",
)


def ensure_space(db: Session) -> Space:
    space = db.query(Space).filter(Space.id == SPACE_ID).first()
    if space:
        print(f"[SPACE] Já existe → {space.id} / {space.name}")
        return space

    space = Space(
        id=SPACE_ID,
        name=SPACE_NAME,
        created_at=datetime.utcnow(),
    )
    db.add(space)
    db.commit()
    print(f"[SPACE] Criado → {space.id} / {space.name}")
    return space


def ensure_dataconnection(db: Session, space: Space) -> DataConnection:
    conn = db.query(DataConnection).filter(DataConnection.id == CONNECTION_ID).first()
    if conn:
        print(f"[DATACONNECTION] Já existe → {conn.id} / {conn.name}")
        return conn

    config = {
        "project_id": PROJECT_ID,
        "dataset": DATASET,  # formato "project.dataset"
        "credentials_path": CREDENTIALS_PATH,
    }

    conn = DataConnection(
        id=CONNECTION_ID,
        space_id=space.id,
        name=CONNECTION_NAME,
        type="bigquery",
        config=config,
        created_at=datetime.utcnow(),
    )
    db.add(conn)
    db.commit()
    print(f"[DATACONNECTION] Criada → {conn.id} / {conn.name}")
    return conn


def ingest_table_metadata(db: Session, conn: DataConnection, space: Space) -> int:
    """
    Usa o DataSourceFactory para ler INFORMATION_SCHEMA do BigQuery
    e insere registros em table_metadata.
    """
    ds = DataSourceFactory.build_from_dataconnection(conn)
    meta_rows = ds.fetch_table_metadata()

    print(f"[METADATA] Encontradas {len(meta_rows)} colunas no BigQuery.")

    # Opcional: limpar metadados antigos dessa conexão/space
    db.query(TableMetadata).filter(
        TableMetadata.space_id == space.id,
        TableMetadata.data_connection_id == conn.id,
    ).delete()
    db.commit()

    created = 0
    for col in meta_rows:
        tm = TableMetadata(
            id=str(uuid4()),
            data_connection_id=conn.id,
            space_id=space.id,
            crew_id=None,  # metadados gerais do space
            table_name=col["table_name"],
            column_name=col["column_name"],
            data_type=col["data_type"],
            is_nullable=(str(col["is_nullable"]).upper() in ("YES", "TRUE")),
            created_at=datetime.utcnow(),
        )
        db.add(tm)
        created += 1

    db.commit()
    print(f"[METADATA] Inseridos {created} registros em table_metadata.")
    return created


def create_metadata_embeddings(db: Session, space: Space, conn: DataConnection) -> int:
    """
    Gera embeddings de metadados de tabela (TableMetadata) no pgvector.
    """
    provider = OpenAIEmbeddingProvider(model="text-embedding-3-large")

    num = create_embeddings_for_table_metadata(
        db=db,
        embedding_provider=provider,
        space_id=space.id,
        crew_id=None,  # metadado geral do Space
        data_connection_id=conn.id,  # só dessa conexão
        limit=None,  # ou um número se quiser limitar
    )

    print(f"[EMBEDDINGS] Criados {num} embeddings para metadados.")
    return num


def main():
    load_dotenv()
    db: Session = SessionLocal()

    print("=== BOOTSTRAP TEST ENV ===")

    # 1) Space
    space = ensure_space(db)

    # 2) DataConnection (BigQuery)
    conn = ensure_dataconnection(db, space)

    # 3) Ingest TableMetadata
    ingest_table_metadata(db, conn, space)

    # 4) Criar embeddings de metadados no pgvector
    create_metadata_embeddings(db, space, conn)

    print("\n✅ Ambiente de teste pronto!")
    print(f"- SPACE_ID: {space.id}")
    print(f"- CONNECTION_ID: {conn.id}")
    print("\nAgora você pode rodar: python -m scripts.test_full_pipeline")


if __name__ == "__main__":
    main()
