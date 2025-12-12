# core/data_sources/factory.py
from __future__ import annotations

from typing import Optional

from sqlalchemy import create_engine

from db.models import DataConnection
from core.data_sources.base import (
    BaseDataSource,
    DataSourceConfig,
    SQLAlchemyDataSource,
)
from core.data_sources.bigquery_source import BigQueryDataSource
from core.logging_utils import log_event


class DataSourceFactory:
    """
    Fábrica agnóstica de fontes de dados.
    A partir de um DataConnection (Postgres) monta o objeto BaseDataSource correto.

    Suporta:
    - type = "bigquery"  -> BigQueryDataSource
    - type = "postgres"  -> SQLAlchemyDataSource
    - (no futuro: mysql, sqlserver, databricks, redshift, bigquery, etc.)
    """

    @staticmethod
    def build_from_dataconnection(conn: DataConnection) -> BaseDataSource:
        """
        Lê DataConnection.config e monta o DataSource adequado.
        """
        cfg_dict = conn.config or {}

        ds_type = (conn.type or "").lower()

        if ds_type == "bigquery":
            # Espera em config:
            # {
            #   "project_id": "data-mesh-gcp",
            #   "dataset": "project.dataset",
            #   "credentials_path": "/caminho/gcp-key.json",
            #   "location": "US"  (opcional)
            # }
            project_id = cfg_dict.get("project_id")
            dataset = cfg_dict.get("dataset")  # ex: "project.dataset"
            credentials_path = cfg_dict.get("credentials_path")
            location = cfg_dict.get("location")

            ds_cfg = DataSourceConfig(
                id=conn.id,
                type="bigquery",
                default_schema=dataset,
                extra={
                    "project_id": project_id,
                    "credentials_path": credentials_path,
                    "location": location,
                },
            )

            log_event(
                "build_bigquery_datasource",
                {
                    "connection_id": conn.id,
                    "project_id": project_id,
                    "dataset": dataset,
                    "location": location,
                    "credentials_path": credentials_path,
                },
            )

            return BigQueryDataSource(
                project_id=project_id,
                dataset=dataset,
                location=location,
                credentials_path=credentials_path,
                label=f"bigquery:{conn.id}",
            )

        elif ds_type == "postgres":
            # Espera em config:
            # { "dsn": "postgresql+psycopg2://user:pass@host:port/dbname" }
            dsn = cfg_dict.get("dsn")
            if not dsn:
                raise ValueError(f"DataConnection {conn.id} do tipo postgres precisa de config.dsn")

            engine = create_engine(dsn, future=True)
            label = f"postgres:{conn.id}"

            log_event(
                "build_postgres_datasource",
                {
                    "connection_id": conn.id,
                    "dsn_preview": dsn[:80],
                },
            )

            return SQLAlchemyDataSource(engine=engine, label=label)

        else:
            # Tipo não suportado ainda
            log_event(
                "build_datasource_unsupported_type",
                {"connection_id": conn.id, "type": ds_type},
            )
            raise ValueError(f"Unsupported data source type: {ds_type!r} for connection {conn.id}")
