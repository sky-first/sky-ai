# core/data_sources/redshift_source.py
"""
Redshift data source.

The factory builds Redshift connections via SQLAlchemyDataSource directly
(using the redshift+redshift_connector:// driver), so this module exists as a
convenience re-export and thin wrapper for callers that import RedshiftSource
explicitly.
"""

from __future__ import annotations

from typing import List, Dict, Any

from sqlalchemy import create_engine

from core.data_sources.base import SQLAlchemyDataSource
from core.dialects import Dialect
from core.logging_utils import log_event


class RedshiftSource(SQLAlchemyDataSource):
    """
    Redshift data source backed by SQLAlchemy (redshift+redshift_connector driver).

    Usage:
        source = RedshiftSource(
            host="my-cluster.abc.us-east-1.redshift.amazonaws.com",
            database="dev",
            user="admin",
            password="secret",
            port=5439,
            label="redshift:my-conn",
        )
        rows = source.run_query("SELECT 1 AS n")

    Alternatively pass a full ``dsn`` to skip auto-construction.
    """

    def __init__(
        self,
        host: str = "",
        database: str = "",
        user: str = "",
        password: str = "",
        port: int = 5439,
        dsn: str = "",
        label: str = "redshift",
    ) -> None:
        if not dsn:
            if not (host and user and database):
                raise ValueError(
                    "RedshiftSource requires host, user, and database (or an explicit dsn)"
                )
            from urllib.parse import quote_plus

            dsn = (
                f"redshift+redshift_connector://{quote_plus(str(user))}"
                f":{quote_plus(str(password))}"
                f"@{host}:{port}/{database}"
            )
        engine = create_engine(dsn, future=True)
        log_event(
            "build_redshift_datasource", {"label": label, "dsn_preview": dsn[:80]}
        )
        super().__init__(engine=engine, dialect=Dialect.REDSHIFT, label=label)
