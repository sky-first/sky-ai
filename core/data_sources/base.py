# core/data_sources/base.py
from __future__ import annotations

from typing import List, Dict, Any, Protocol
from dataclasses import dataclass

from sqlalchemy.engine import Engine
from sqlalchemy.sql import text

from core.logging_utils import log_event
from core.dialects import Dialect


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
    dialect: Dialect  # Every data source must declare its dialect

    def run_query(self, sql: str) -> List[Dict[str, Any]]:
        ...

    def run_query_arrow(self, sql: str) -> Any:
        """
        Executa query e retorna pyarrow.Table.
        Implementações devem sobrescrever para otimização nativa se possível.
        Retorna Any para evitar dependência dura de pyarrow no type hint se não instalado,
        mas runtime deve garantir retorno de pyarrow.Table.
        """
        ...


class SQLAlchemyDataSource:
    """
    Implementação básica de BaseDataSource usando um Engine do SQLAlchemy.
    Serve para Postgres, MySQL, SQL Server, MariaDB, Redshift (via driver compatível).
    """
    def __init__(self, engine: Engine, dialect: Dialect, label: str = "default_sqlalchemy") -> None:
        self.engine = engine
        self.dialect = dialect
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

    def run_query_arrow(self, sql: str) -> Any:
        """
        Implementação fallback: roda query normal e converte para Arrow.
        Útil para padronização.
        """
        import pyarrow as pa
        
        # 1. Obter dados como lista de dicts
        data = self.run_query(sql)

        # 1.5 Convert UUIDs to strings to avoid Arrow errors
        import uuid
        if data:
            for row in data:
                for k, v in row.items():
                    if isinstance(v, uuid.UUID):
                        row[k] = str(v)
        
        # 2. Converter para Arrow Table
        # Se data estiver vazio, precisamos cuidar do schema, mas pyarrow lida bem com lista vazia se inferir
        if not data:
             return pa.Table.from_pylist([])
             
        return pa.Table.from_pylist(data)

    def sample_table_rows(self, table_name: str, limit: int = 3) -> List[Dict[str, Any]]:
        """
        Retorna amostra de dados para preview no prompt.
        """
        try:
            return self.run_query(f"SELECT * FROM {table_name} LIMIT {limit}")
        except Exception:
            return []
