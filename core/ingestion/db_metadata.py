# core/ingestion/db_metadata.py
from __future__ import annotations

from typing import Optional, List, Dict

import os
from datetime import datetime

from sqlalchemy.orm import Session

from google.cloud import bigquery

from db.models import (
    DataConnection,
    TableMetadata,
    Space,
)
from core.logging_utils import log_event


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


def ingest_bigquery_metadata_for_connection(
    db: Session,
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

    # Executa query no INFORMATION_SCHEMA
    job = client.query(query)
    rows = list(job.result())

    # Remove metadados antigos dessa conexão + space + crew (se houver)
    delete_q = db.query(TableMetadata).filter(
        TableMetadata.data_connection_id == data_connection.id,
        TableMetadata.space_id == space.id,
    )
    if crew_id:
        delete_q = delete_q.filter(TableMetadata.crew_id == crew_id)
    else:
        delete_q = delete_q.filter(TableMetadata.crew_id.is_(None))

    deleted = delete_q.delete(synchronize_session=False)

    inserted = 0
    now = datetime.utcnow()
    
    # Agrupar colunas por tabela para detectar PKs (geralmente "id" ou similar)
    table_columns: Dict[str, List[str]] = {}
    for row in rows:
        if row.table_name not in table_columns:
            table_columns[row.table_name] = []
        table_columns[row.table_name].append(row.column_name)

    for row in rows:
        # Detectar se é PK (geralmente coluna "id" ou similar)
        is_pk = False
        table_name_lower = row.table_name.lower()
        col_name_lower = row.column_name.lower()
        
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
            table_name=row.table_name,
            column_name=row.column_name,
            data_type=row.data_type,
            is_nullable=(row.is_nullable == "YES"),
            description=None,
            extra=extra if extra else None,
            created_at=now,
        )
        db.add(tm)
        inserted += 1

    db.commit()

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


# ========== ENTRYPOINT GENÉRICO ==========

def ingest_metadata_for_connection(
    db: Session,
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
        return ingest_bigquery_metadata_for_connection(db, data_connection, space, crew_id)

    # TODO: implementar outros tipos
    # elif t == "postgres":
    #     ...
    # elif t == "mysql":
    #     ...

    raise ValueError(f"Metadata ingestion not implemented for data_connection.type='{data_connection.type}'")
