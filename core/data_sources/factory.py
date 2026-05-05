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
from core.dialects import Dialect
from core.data_sources.api_source import APISource

class DataSourceFactory:
    """
    Fábrica agnóstica de fontes de dados.
    A partir de um DataConnection (Postgres) monta o objeto BaseDataSource correto.

    Suporta:
    - type = "bigquery"  -> BigQueryDataSource
    - type = "postgres"  -> SQLAlchemyDataSource
    - type = "api"       -> APISource
    """

    @staticmethod
    def build_from_dataconnection(conn: DataConnection) -> BaseDataSource:
        """
        Lê DataConnection.config e monta o DataSource adequado.
        """
        cfg_dict = conn.config or {}

        # Handle variations: Model has connector_id, but some code expects .type
        ds_type = getattr(conn, "type", None) or getattr(conn, "connector_id", None) or ""
        ds_type = ds_type.lower()

        if ds_type == "bigquery":
            # Espera em config:
            # {
            #   "project_id": "data-mesh-gcp",
            #   "dataset": "project.dataset",
            #   "credentials_path": "/caminho/gcp-key.json",
            #   "service_account_json": "{...json...}" (opcional; preferível quando configurado via frontend)
            #   "location": "US"  (opcional)
            # }
            project_id = cfg_dict.get("project_id")
            dataset = cfg_dict.get("dataset")  # ex: "project.dataset"
            credentials_path = cfg_dict.get("credentials_path")
            service_account_json = cfg_dict.get("service_account_json") or cfg_dict.get("credentials_json")
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
                    "has_service_account_json": bool(service_account_json),
                },
            )

            return BigQueryDataSource(
                project_id=project_id,
                dataset=dataset,
                location=location,
                credentials_path=credentials_path,
                credentials_json=service_account_json,
                label=f"bigquery:{conn.id}",
            )

        elif ds_type == "api":
            # API REST/GraphQL
            ds_cfg = DataSourceConfig(
                id=conn.id,
                type="api",
                default_schema=None,
                extra=cfg_dict
            )
            log_event(
                "build_api_datasource",
                {"connection_id": conn.id}
            )
            return APISource(ds_cfg, label=f"api:{conn.id}")

        elif ds_type in ["postgres", "postgresql"]:
            # Espera em config:
            # { "dsn": "postgresql+psycopg2://user:pass@host:port/dbname" }
            # Fallback: BE seeds connections as host/port/database/username/password —
            # build the DSN from those when `dsn` isn't explicitly stored.
            dsn = cfg_dict.get("dsn")
            if not dsn:
                host = cfg_dict.get("host")
                user = cfg_dict.get("username") or cfg_dict.get("user")
                pwd = cfg_dict.get("password") or ""
                db = cfg_dict.get("database") or cfg_dict.get("dbname")
                port = cfg_dict.get("port") or 5432
                if host and user and db:
                    from urllib.parse import quote_plus
                    dsn = (
                        f"postgresql+psycopg2://{quote_plus(str(user))}:"
                        f"{quote_plus(str(pwd))}@{host}:{port}/{db}"
                    )
                    ssl_mode = cfg_dict.get("ssl_mode") or cfg_dict.get("sslmode")
                    if ssl_mode:
                        dsn = f"{dsn}?sslmode={ssl_mode}"
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

            # Determine dialect
            dialect = Dialect.POSTGRES
            
            if ds_type == "mysql":
                dialect = Dialect.MYSQL
            elif ds_type == "sqlserver":
                dialect = Dialect.SQLSERVER
            elif ds_type == "sqlite":
                dialect = Dialect.SQLITE
            elif ds_type == "oracle":
                dialect = Dialect.ORACLE
            elif ds_type == "snowflake":
                dialect = Dialect.SNOWFLAKE
            elif ds_type == "databricks":
                dialect = Dialect.DATABRICKS
            elif ds_type == "redshift":
                dialect = Dialect.REDSHIFT
            
            return SQLAlchemyDataSource(engine=engine, dialect=dialect, label=label)

        elif ds_type in ["mysql", "sqlserver", "sqlite", "oracle", "snowflake", "databricks", "redshift"]:
            # Generic handler for other SQL dialects that use SQLAlchemy
            # Similar to postgres block but handles them if they fall through or are explicit
            dsn = cfg_dict.get("dsn")
            if not dsn:
                 raise ValueError(f"DataConnection {conn.id} of type {ds_type} requires config.dsn")
            
            engine = create_engine(dsn, future=True)
            label = f"{ds_type}:{conn.id}"
            
            dialect_map = {
                "mysql": Dialect.MYSQL,
                "sqlserver": Dialect.SQLSERVER,
                "sqlite": Dialect.SQLITE,
                "oracle": Dialect.ORACLE,
                "snowflake": Dialect.SNOWFLAKE,
                "databricks": Dialect.DATABRICKS,
                "redshift": Dialect.REDSHIFT,
            }
            
            return SQLAlchemyDataSource(
                engine=engine, 
                dialect=dialect_map.get(ds_type, Dialect.POSTGRES),
                label=label
            )

        else:
            # Tipo não suportado ainda
            log_event(
                "build_datasource_unsupported_type",
                {"connection_id": conn.id, "type": ds_type},
            )
            raise ValueError(f"Unsupported data source type: {ds_type!r} for connection {conn.id}")
