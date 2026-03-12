# core/ingestion/db_metadata.py
from __future__ import annotations

from typing import Optional, List, Dict
import asyncio
from concurrent.futures import ThreadPoolExecutor

import os
import json
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from google.cloud import bigquery
from google.oauth2 import service_account

from db.models import (
    DataConnection,
    TableMetadata,
    Space,
)
from core.logging_utils import log_event


# ThreadPool para operações BigQuery (bloqueantes)
_executor = ThreadPoolExecutor(max_workers=4)


# ========== HELPERS BIGQUERY ==========

def _create_bq_client(config: dict) -> bigquery.Client:
    """
    Cria um cliente BigQuery a partir do config da DataConnection.
    Usa:
      - config["project_id"] se existir
      - senão, GCP_PROJECT_ID do ambiente
    """
    project_id = config.get("project_id") or os.getenv("GCP_PROJECT_ID")
    if not project_id:
        raise ValueError("project_id not found in DataConnection.config nor GCP_PROJECT_ID env var")

    # Prefer explicit credentials from config/env to avoid relying on ADC.
    credentials_path = (
        (config.get("credentials_path") or "").strip()
        or os.getenv("GCP_CREDENTIALS_PATH")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    )

    service_account_json = config.get("service_account_json")

    if credentials_path:
        creds = service_account.Credentials.from_service_account_file(credentials_path)
        client = bigquery.Client(project=project_id, credentials=creds)
    elif service_account_json:
        # Support JSON stored by the frontend (do NOT require a filesystem path).
        try:
            info = (
                json.loads(service_account_json)
                if isinstance(service_account_json, str)
                else service_account_json
            )
        except Exception as e:
            # Not a not-found condition; treat as internal/config error.
            raise RuntimeError(f"Invalid service_account_json: {e}")
        creds = service_account.Credentials.from_service_account_info(info)
        client = bigquery.Client(project=project_id, credentials=creds)
    else:
        # Fallback: Application Default Credentials (may not be available in all environments)
        client = bigquery.Client(project=project_id)

    return client


def _infer_dataset_from_config(config: dict) -> str:
    """
    Tenta inferir o dataset default da DataConnection.
    Exemplos de possíveis campos:
      - config["dataset"]
      - config["default_schema"] no formato "project.dataset"
    """
    if "dataset" in config:
        return config["dataset"]

    default_schema = config.get("default_schema")
    if default_schema and "." in default_schema:
        # project.dataset
        return default_schema.split(".")[1]

    raise ValueError("Dataset not found in DataConnection.config (expected 'dataset' or 'default_schema').")


def _run_bq_query_sync(client: bigquery.Client, query: str) -> List[dict]:
    """Executa query BigQuery de forma síncrona."""
    job = client.query(query)
    rows = list(job.result())
    return [
        {
            "table_name": row.table_name,
            "column_name": row.column_name,
            "data_type": row.data_type,
            "is_nullable": row.is_nullable,
        }
        for row in rows
    ]


async def ingest_bigquery_metadata_for_connection(
    db: AsyncSession,
    data_connection: DataConnection,
    space: Space,
    crew_id: Optional[str] = None,
) -> int:
    """
    Lê INFORMATION_SCHEMA de um dataset BigQuery e grava em table_metadata.
    NUNCA lê dados de negócio, apenas schema (tabelas/colunas).

    Fluxo:
      1) Descobre project_id + dataset
      2) SELECT em INFORMATION_SCHEMA.COLUMNS
      3) Apaga metadados antigos dessa conexão/space/crew
      4) Insere novos registros em TableMetadata
      5) Retorna quantos registros foram inseridos
    """
    config = data_connection.config or {}

    client = _create_bq_client(config)
    dataset = _infer_dataset_from_config(config)

    # Monta caminho do INFORMATION_SCHEMA
    project_id = client.project
    
    # Se o dataset já contém o projeto (formato "project.dataset"), usar direto
    if "." in dataset and not dataset.startswith(f"{project_id}."):
        # Dataset já tem projeto diferente, usar como está
        full_dataset = dataset
    elif "." in dataset and dataset.startswith(f"{project_id}."):
        # Dataset já tem o mesmo projeto, remover duplicação
        full_dataset = dataset
    else:
        # Dataset sem projeto, adicionar
        full_dataset = f"{project_id}.{dataset}"

    query = f"""
    SELECT
      table_name,
      column_name,
      data_type,
      is_nullable
    FROM `{full_dataset}.INFORMATION_SCHEMA.COLUMNS`
    ORDER BY table_name, ordinal_position
    """

    log_event(
        "ingest_bq_metadata_start",
        {"connection_id": data_connection.id, "space_id": space.id, "dataset": full_dataset},
    )

    # Executa query no INFORMATION_SCHEMA (em thread separada)
    loop = asyncio.get_event_loop()
    rows = await loop.run_in_executor(_executor, _run_bq_query_sync, client, query)

    # Remove metadados antigos dessa conexão + space + crew (se houver)
    # PRIMEIRO deletar embeddings (filhos) para evitar FK Violation
    from db.models import EmbeddingRecord
    
    # Subquery para IDs que serão deletados
    subquery_tm_bq = select(TableMetadata.id).where(
        TableMetadata.data_connection_id == data_connection.id,
        TableMetadata.space_id == space.id
    )
    if crew_id:
        subquery_tm_bq = subquery_tm_bq.where(TableMetadata.crew_id == crew_id)
    else:
        subquery_tm_bq = subquery_tm_bq.where(TableMetadata.crew_id.is_(None))

    delete_embeddings_bq = delete(EmbeddingRecord).where(
        EmbeddingRecord.table_metadata_id.in_(subquery_tm_bq)
    )
    await db.execute(delete_embeddings_bq)
    
    delete_stmt = delete(TableMetadata).where(
        TableMetadata.data_connection_id == data_connection.id,
        TableMetadata.space_id == space.id,
    )
    if crew_id:
        delete_stmt = delete_stmt.where(TableMetadata.crew_id == crew_id)
    else:
        delete_stmt = delete_stmt.where(TableMetadata.crew_id.is_(None))

    result = await db.execute(delete_stmt)
    deleted = result.rowcount

    inserted = 0
    now = datetime.utcnow()
    
    # Agrupar colunas por tabela para detectar PKs (geralmente "id" ou similar)
    table_columns: Dict[str, List[str]] = {}
    for row in rows:
        if row["table_name"] not in table_columns:
            table_columns[row["table_name"]] = []
        table_columns[row["table_name"]].append(row["column_name"])

    for row in rows:
        # Detectar se é PK (geralmente coluna "id" ou similar)
        is_pk = False
        table_name_lower = row["table_name"].lower()
        col_name_lower = row["column_name"].lower()
        
        # Normalizar nome da tabela (remover prefixos/sufixos comuns)
        normalized_table = table_name_lower
        if normalized_table.startswith("silver_"):
            normalized_table = normalized_table[7:]
        if normalized_table.endswith("_enriquecido"):
            normalized_table = normalized_table[:-12]
        
        # PK: coluna "id" ou coluna que termina com "_id" e corresponde ao nome da tabela normalizado
        # Ex: silver_customers_enriquecido -> customers, customer_id -> customers (match!)
        if col_name_lower == "id":
            is_pk = True
        elif col_name_lower.endswith("_id"):
            base_col = col_name_lower[:-3]  # remove "_id"
            # Verifica se o base da coluna corresponde ao nome da tabela normalizado
            # Ex: customer_id -> customer, customers -> customers (match via pluralização)
            if base_col == normalized_table or f"{base_col}s" == normalized_table or base_col == normalized_table.rstrip("s"):
                is_pk = True
        
        # Detectar se é FK (coluna que termina com "_id" mas não é PK)
        is_fk = False
        if col_name_lower.endswith("_id") and not is_pk:
            # Remover sufixo "_id" e tentar encontrar tabela correspondente
            base_name = col_name_lower[:-3]  # remove "_id"
            plural = f"{base_name}s"
            
            # Verificar match direto
            if base_name in table_columns or plural in table_columns:
                is_fk = True
            else:
                # Verificar match com prefixos/sufixos comuns (silver_*, *_enriquecido)
                for existing_table in table_columns.keys():
                    normalized = existing_table.lower()
                    # Remove prefixos comuns
                    if normalized.startswith("silver_"):
                        normalized = normalized[7:]
                    if normalized.endswith("_enriquecido"):
                        normalized = normalized[:-12]
                    
                    # Verifica se corresponde ao base_name ou plural
                    if normalized == base_name or normalized == plural or normalized.startswith(base_name) or normalized.startswith(plural):
                        is_fk = True
                        break
        
        extra = {}
        if is_pk:
            extra["is_primary_key"] = True
        if is_fk:
            extra["is_foreign_key"] = True
        
        tm = TableMetadata(
            data_connection_id=data_connection.id,
            space_id=space.id,
            crew_id=crew_id,
            table_name=row["table_name"],
            column_name=row["column_name"],
            data_type=row["data_type"],
            is_nullable=(row["is_nullable"] == "YES"),
            description=None,
            extra=extra if extra else None,
            created_at=now,
        )
        db.add(tm)
        inserted += 1

    await db.commit()

    log_event(
        "ingest_bq_metadata_done",
        {
            "connection_id": data_connection.id,
            "space_id": space.id,
            "crew_id": crew_id,
            "dataset": full_dataset,
            "num_rows": len(rows),
            "deleted": deleted,
            "inserted": inserted,
        },
    )

    return inserted


async def ingest_from_connection_metadata_cache(
    db: AsyncSession,
    data_connection: DataConnection,
    space: Optional[Space] = None,
    crew_id: Optional[str] = None,
    table_names: Optional[List[str]] = None,
) -> int:
    """
    Normaliza os dados já existentes em `connection_metadata` para `table_metadata`.
    Isso permite que a AI use o schema já descoberto pelo Backend Principal.
    """
    from sqlalchemy import text
    import uuid

    # 1. Buscar JSON em connection_metadata
    result = await db.execute(
        text("SELECT tables FROM connection_metadata WHERE connection_id = :conn_id"),
        {"conn_id": data_connection.id}
    )
    tables_json = result.scalar_one_or_none()

    if not tables_json:
        log_event(
            "ingest_cache_metadata_failed",
            {"connection_id": data_connection.id, "reason": "no_metadata_found"}
        )
        return 0

    # 2. Apagar metadados antigos
    # PRIMEIRO deletar embeddings (filhos) para evitar ForeignKeyViolationError
    from db.models import EmbeddingRecord
    
    # Subquery para identificar IDs de TableMetadata que serão deletados
    subquery_tm = select(TableMetadata.id).where(
        TableMetadata.data_connection_id == data_connection.id
    )
    
    if space:
        subquery_tm = subquery_tm.where(TableMetadata.space_id == space.id)
    else:
        subquery_tm = subquery_tm.where(TableMetadata.space_id.is_(None))

    if crew_id:
        subquery_tm = subquery_tm.where(TableMetadata.crew_id == crew_id)
    else:
        subquery_tm = subquery_tm.where(TableMetadata.crew_id.is_(None))
        
    if table_names:
        subquery_tm = subquery_tm.where(TableMetadata.table_name.in_(table_names))
        
    delete_embeddings_stmt = delete(EmbeddingRecord).where(
        EmbeddingRecord.table_metadata_id.in_(subquery_tm)
    )
    await db.execute(delete_embeddings_stmt)

    delete_stmt = delete(TableMetadata).where(
        TableMetadata.data_connection_id == data_connection.id,
    )
    
    if space:
        delete_stmt = delete_stmt.where(TableMetadata.space_id == space.id)
    else:
        delete_stmt = delete_stmt.where(TableMetadata.space_id.is_(None))

    if crew_id:
        delete_stmt = delete_stmt.where(TableMetadata.crew_id == crew_id)
    else:
        delete_stmt = delete_stmt.where(TableMetadata.crew_id.is_(None))

    if table_names:
        delete_stmt = delete_stmt.where(TableMetadata.table_name.in_(table_names))

    await db.execute(delete_stmt)

    # 3. Normalizar e Inserir
    inserted = 0
    now = datetime.utcnow()
    
    # Handle both list and dict formats
    if isinstance(tables_json, list):
        iterator = tables_json
    elif isinstance(tables_json, dict):
        iterator = tables_json.items()
    else:
        log_event("ingest_cache_metadata_error", {"reason": "invalid_json_format", "type": str(type(tables_json))})
        return 0

    for item in iterator:
        # Extract table name and info based on structure
        if isinstance(tables_json, list):
            table_name = item.get('table_name') or item.get('name')
            table_info = item
        else:
            table_name = item[0]
            table_info = item[1]
            
        # ✅ UX FIX: Clean up table name (remove project.dataset prefix)
        original_table_name = table_name
        if table_name and "." in table_name:
            table_name = table_name.split(".")[-1]
            
        # Granular filter: skip if table_names is provided and this table is not in it
        if table_names and table_name not in table_names and original_table_name not in table_names:
            continue
            
        columns = table_info.get('columns', [])
        
        for col in columns:
            # Handle column structure (dict or string)
            if isinstance(col, dict):
                col_name = col.get('name')
                col_type = col.get('type', 'UNKNOWN')
                is_nullable = col.get('nullable', True)
            else:
                col_name = col
                col_type = 'UNKNOWN'
                is_nullable = True
                
            if not col_name:
                continue

            tm = TableMetadata(
                data_connection_id=data_connection.id,
                space_id=space.id if space else None,
                crew_id=crew_id,
                table_name=table_name,
                column_name=col_name,
                data_type=col_type,
                is_nullable=is_nullable,
                description=None,
                extra={"original_name": original_table_name},
                created_at=now,
            )
            db.add(tm)
            inserted += 1

    await db.commit()
    
    log_event(
        "ingest_cache_metadata_done",
        {
            "connection_id": data_connection.id,
            "space_id": space.id if space else None,
            "inserted": inserted
        }
    )
    
    return inserted


# ========== ENTRYPOINT GENÉRICO ==========

async def ingest_metadata_for_connection(
    db: AsyncSession,
    data_connection: DataConnection,
    space: Space,
    crew_id: Optional[str] = None,
) -> int:
    """
    Função genérica que decide qual implementação usar baseado em data_connection.type

    - "bigquery" -> usa ingest_bigquery_metadata_for_connection
    - no futuro: "postgres", "mysql", "sqlserver", "databricks", etc.
    """
    t = (data_connection.type or "").lower()

    if t == "bigquery":
        return await ingest_bigquery_metadata_for_connection(db, data_connection, space, crew_id)

    # TODO: implementar outros tipos
    # elif t == "postgres":
    #     ...
    # elif t == "mysql":
    #     ...

    raise ValueError(f"Metadata ingestion not implemented for data_connection.type='{data_connection.type}'")
