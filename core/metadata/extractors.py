# core/metadata/extractors.py
from __future__ import annotations

from typing import List, Dict, Any, Protocol, Optional

from sqlalchemy.engine import Engine
from sqlalchemy.sql import text

from core.logging_utils import log_event


class SQLMetadataExtractor(Protocol):
    """
    Interface para extratores de metadados de bancos SQL.
    A ideia é ter implementações para:
    - Postgres
    - MySQL / MariaDB
    - SQL Server
    - Redshift
    - Databricks (via driver compatível)
    - etc.
    """

    def extract_table_metadata(
        self,
        engine: Engine,
        schema: Optional[str] = None,
        include_tables: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]: ...


class InformationSchemaExtractor:
    """
    Implementação genérica baseada em INFORMATION_SCHEMA.
    Funciona bem para Postgres, MySQL, MariaDB, SQL Server, Redshift
    (ajustando detalhes se necessário).
    """

    def __init__(self, label: str = "generic_information_schema") -> None:
        self.label = label

    def extract_table_metadata(
        self,
        engine: Engine,
        schema: Optional[str] = None,
        include_tables: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retorna uma lista de dicts com metadados de colunas, ex:
        {
            "table_name": "invoices",
            "column_name": "id",
            "data_type": "integer",
            "is_nullable": True,
            "column_default": "...",
        }
        """
        params: Dict[str, Any] = {}
        filters = ["table_type = 'BASE TABLE'"]

        if schema:
            filters.append("table_schema = :schema")
            params["schema"] = schema

        if include_tables:
            filters.append("table_name = ANY(:tables)")
            params["tables"] = include_tables

        where_clause = " AND ".join(filters)

        sql = f"""
        SELECT
            table_schema,
            table_name,
            column_name,
            data_type,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE {where_clause}
        ORDER BY table_schema, table_name, ordinal_position
        """

        rows: List[Dict[str, Any]] = []

        log_event(
            "metadata_extract_start",
            {
                "label": self.label,
                "schema": schema,
                "include_tables": include_tables,
            },
        )

        with engine.connect() as conn:
            result = conn.execute(text(sql), params)
            for row in result:
                rows.append(dict(row._mapping))

        log_event(
            "metadata_extract_done",
            {
                "label": self.label,
                "schema": schema,
                "include_tables": include_tables,
                "num_rows": len(rows),
            },
        )

        return rows
