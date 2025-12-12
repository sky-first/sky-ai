# core/data_sources/base.py
from __future__ import annotations

from typing import List, Dict, Any, Protocol
from dataclasses import dataclass

from sqlalchemy.engine import Engine
from sqlalchemy.sql import text

from core.logging_utils import log_event


# 🔹 Config genérica de uma fonte de dados
@dataclass
class DataSourceConfig:
    """
    Configuração abstrata de uma fonte de dados.
    - id: id da DataConnection (no banco)
    - type: "bigquery", "postgres", "mysql", etc.
    - default_schema: nome do schema/base principal (ex: "project.dataset" ou "public")
    - extra: dict com configs específicas (project_id, credentials_path, host, etc.)
    """
    id: str
    type: str
    default_schema: str | None = None
    extra: Dict[str, Any] | None = None


class BaseDataSource(Protocol):
    """
    Interface genérica de fonte de dados.
    A ideia é poder ter implementações para:
    - Postgres / MySQL / SQL Server via SQLAlchemy
    - BigQuery
    - Databricks
    - etc.

    O specialist NUNCA sabe se está falando com BigQuery ou Postgres.
    Ele só chama run_query(sql) e recebe uma lista de dicts.
    """
    def run_query(self, sql: str) -> List[Dict[str, Any]]:
        ...


class SQLAlchemyDataSource:
    """
    Implementação básica de BaseDataSource usando um Engine do SQLAlchemy.
    Serve para Postgres, MySQL, SQL Server, MariaDB, Redshift (via driver compatível).
    """
    def __init__(self, engine: Engine, label: str = "default_sqlalchemy") -> None:
        self.engine = engine
        self.label = label

    def run_query(self, sql: str) -> List[Dict[str, Any]]:
        log_event(
            "datasource_query_start",
            {
                "datasource": self.label,
                "sql_preview": sql[:500],
            },
        )
        rows: List[Dict[str, Any]] = []
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(sql))
                for row in result:
                    rows.append(dict(row._mapping))

            log_event(
                "datasource_query_success",
                {
                    "datasource": self.label,
                    "num_rows": len(rows),
                    "max_rows": 10_000,
                    "timeout": 90,
                },
            )
            return rows
        except Exception as e:
            log_event(
                "datasource_query_error",
                {
                    "datasource": self.label,
                    "error": str(e)[:500],
                },
            )
            raise
