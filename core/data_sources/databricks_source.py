# core/data_sources/databricks_source.py
"""
Databricks data source.

The factory builds Databricks connections via SQLAlchemyDataSource directly
(using the databricks+connector:// driver), so this module exists as a
convenience re-export and thin wrapper for callers that import DatabricksSource
explicitly.
"""
from __future__ import annotations

from sqlalchemy import create_engine

from core.data_sources.base import SQLAlchemyDataSource
from core.dialects import Dialect
from core.logging_utils import log_event


class DatabricksSource(SQLAlchemyDataSource):
    """
    Databricks data source backed by SQLAlchemy (databricks+connector driver).

    Usage:
        source = DatabricksSource(
            server_hostname="adb-xxx.azuredatabricks.net",
            http_path="/sql/1.0/warehouses/yyy",
            access_token="dapiXXX",
            catalog="hive_metastore",
            label="databricks:my-conn",
        )
        rows = source.run_query("SELECT 1 AS n")

    Alternatively pass a full ``dsn`` to skip auto-construction.
    """

    def __init__(
        self,
        server_hostname: str = "",
        http_path: str = "",
        access_token: str = "",
        catalog: str = "hive_metastore",
        dsn: str = "",
        label: str = "databricks",
    ) -> None:
        if not dsn:
            if not (server_hostname and http_path and access_token):
                raise ValueError(
                    "DatabricksSource requires server_hostname, http_path, and access_token "
                    "(or an explicit dsn)"
                )
            from urllib.parse import quote_plus
            dsn = (
                f"databricks+connector://token:{quote_plus(str(access_token))}"
                f"@{server_hostname}:443/{catalog}"
                f"?http_path={quote_plus(str(http_path))}"
            )
        engine = create_engine(dsn, future=True)
        log_event("build_databricks_datasource", {"label": label, "dsn_preview": dsn[:80]})
        super().__init__(engine=engine, dialect=Dialect.DATABRICKS, label=label)
