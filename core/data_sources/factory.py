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
from core.security.config_decryption import decrypt_config


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
        # Backend stores config as {"__encrypted": "<fernet>"}; some callers
        # decrypt before passing in, others don't. decrypt_config is idempotent
        # (passes plaintext through), so calling here covers both paths.
        cfg_dict = decrypt_config(conn.config or {})

        # Handle variations: Model has connector_id, but some code expects .type
        ds_type = (
            getattr(conn, "type", None) or getattr(conn, "connector_id", None) or ""
        )
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
            service_account_json = cfg_dict.get("service_account_json") or cfg_dict.get(
                "credentials_json"
            )
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
                id=conn.id, type="api", default_schema=None, extra=cfg_dict
            )
            log_event("build_api_datasource", {"connection_id": conn.id})
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
                raise ValueError(
                    f"DataConnection {conn.id} do tipo postgres precisa de config.dsn"
                )

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

        elif ds_type == "redshift":
            dsn = cfg_dict.get("dsn")
            if not dsn:
                host = cfg_dict.get("host")
                user = cfg_dict.get("username") or cfg_dict.get("user")
                pwd = cfg_dict.get("password") or ""
                db = cfg_dict.get("database") or cfg_dict.get("dbname")
                port = cfg_dict.get("port") or 5439
                if host and user and db:
                    from urllib.parse import quote_plus

                    dsn = f"redshift+redshift_connector://{quote_plus(str(user))}:{quote_plus(str(pwd))}@{host}:{port}/{db}"
            if not dsn:
                raise ValueError(
                    f"Redshift connection {conn.id} needs host/user/database or dsn in config"
                )
            engine = create_engine(dsn, future=True)
            log_event(
                "build_redshift_datasource",
                {"connection_id": conn.id, "dsn_preview": dsn[:80]},
            )
            return SQLAlchemyDataSource(
                engine=engine, dialect=Dialect.REDSHIFT, label=f"redshift:{conn.id}"
            )

        elif ds_type == "databricks":
            dsn = cfg_dict.get("dsn")
            if not dsn:
                host = cfg_dict.get("server_hostname") or cfg_dict.get("host")
                http_path = cfg_dict.get("http_path")
                token = cfg_dict.get("access_token") or cfg_dict.get("token")
                catalog = cfg_dict.get("catalog") or "hive_metastore"
                if host and http_path and token:
                    from urllib.parse import quote_plus

                    dsn = (
                        f"databricks+connector://token:{quote_plus(str(token))}"
                        f"@{host}:443/{catalog}"
                        f"?http_path={quote_plus(str(http_path))}"
                    )
            if not dsn:
                raise ValueError(
                    f"Databricks connection {conn.id} needs server_hostname/http_path/access_token or dsn in config"
                )
            engine = create_engine(dsn, future=True)
            log_event(
                "build_databricks_datasource",
                {"connection_id": conn.id, "dsn_preview": dsn[:80]},
            )
            return SQLAlchemyDataSource(
                engine=engine, dialect=Dialect.DATABRICKS, label=f"databricks:{conn.id}"
            )

        elif ds_type == "mongodb":
            from core.data_sources.mongodb_source import MongoDBSource

            uri = cfg_dict.get("uri") or cfg_dict.get("connection_string")
            database = cfg_dict.get("database")
            collection = (
                cfg_dict.get("collection")
                or cfg_dict.get("default_collection")
                or "default"
            )
            if not uri or not database:
                raise ValueError(
                    f"MongoDB connection {conn.id} needs uri and database in config"
                )
            log_event(
                "build_mongodb_datasource",
                {
                    "connection_id": conn.id,
                    "database": database,
                    "collection": collection,
                },
            )
            return MongoDBSource(
                uri=uri,
                database=database,
                collection=collection,
                label=f"mongodb:{conn.id}",
            )

        elif ds_type == "dynamodb":
            from core.data_sources.dynamodb_source import DynamoDBSource

            region = cfg_dict.get("region") or "us-east-1"
            table_name = (
                cfg_dict.get("table_name") or cfg_dict.get("table") or "default"
            )
            access_key = (
                cfg_dict.get("access_key_id") or cfg_dict.get("access_key") or ""
            )
            secret_key = (
                cfg_dict.get("secret_access_key") or cfg_dict.get("secret_key") or ""
            )
            log_event(
                "build_dynamodb_datasource",
                {"connection_id": conn.id, "region": region, "table_name": table_name},
            )
            return DynamoDBSource(
                region=region,
                table_name=table_name,
                access_key=access_key,
                secret_key=secret_key,
                label=f"dynamodb:{conn.id}",
            )

        elif ds_type == "elasticsearch":
            from core.data_sources.elasticsearch_source import ElasticsearchSource

            hosts = cfg_dict.get("hosts") or [
                cfg_dict.get("host", "http://localhost:9200")
            ]
            if isinstance(hosts, str):
                hosts = [hosts]
            index = cfg_dict.get("index") or cfg_dict.get("default_index") or "*"
            api_key = cfg_dict.get("api_key") or ""
            log_event(
                "build_elasticsearch_datasource",
                {"connection_id": conn.id, "index": index},
            )
            return ElasticsearchSource(
                hosts=hosts,
                index=index,
                api_key=api_key,
                label=f"elasticsearch:{conn.id}",
            )

        elif ds_type in ["mysql", "sqlserver", "sqlite", "oracle", "snowflake"]:
            # Generic handler for remaining SQL dialects that use SQLAlchemy
            dsn = cfg_dict.get("dsn")
            if not dsn:
                raise ValueError(
                    f"DataConnection {conn.id} of type {ds_type} requires config.dsn"
                )

            engine = create_engine(dsn, future=True)
            label = f"{ds_type}:{conn.id}"

            dialect_map = {
                "mysql": Dialect.MYSQL,
                "sqlserver": Dialect.SQLSERVER,
                "sqlite": Dialect.SQLITE,
                "oracle": Dialect.ORACLE,
                "snowflake": Dialect.SNOWFLAKE,
            }

            return SQLAlchemyDataSource(
                engine=engine,
                dialect=dialect_map.get(ds_type, Dialect.POSTGRES),
                label=label,
            )

        else:
            # Tipo não suportado ainda
            log_event(
                "build_datasource_unsupported_type",
                {"connection_id": conn.id, "type": ds_type},
            )
            raise ValueError(
                f"Unsupported data source type: {ds_type!r} for connection {conn.id}"
            )
