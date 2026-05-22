"""Generic SQLAlchemy data source implementation."""

from typing import List, Dict, Any, Optional
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from core.data_sources.base import BaseDataSource, DataSourceConfig


class SQLAlchemySource(BaseDataSource):
    """Generic SQLAlchemy-based data source (Postgres, MySQL, SQL Server, etc.)."""

    def __init__(self, config: DataSourceConfig):
        super().__init__(config)
        connection_string = self.config.config.get("connection_string")
        if not connection_string:
            raise ValueError("connection_string is required in config")

        self.engine = create_engine(connection_string, pool_pre_ping=True)

    def execute_query(
        self, query: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Execute a SQL query using SQLAlchemy with timeout protection."""
        if limit:
            # Try to add LIMIT clause if not present
            query_upper = query.upper().strip()
            if "LIMIT" not in query_upper:
                query = f"{query} LIMIT {limit}"

        import time
        from concurrent.futures import (
            ThreadPoolExecutor,
            TimeoutError as FutureTimeoutError,
        )
        from core.logging_utils import log_event

        def _execute_sync():
            with self.engine.connect() as conn:
                # Set statement timeout for PostgreSQL (60 seconds)
                try:
                    conn.execute(text("SET statement_timeout = '60s'"))
                except Exception:
                    pass  # Not all databases support this

                result = conn.execute(text(query))
                rows = result.fetchall()

                # Convert to list of dicts
                columns = result.keys()
                return [dict(zip(columns, row)) for row in rows]

        # Execute with 60-second timeout
        start = time.time()
        try:
            with ThreadPoolExecutor() as executor:
                future = executor.submit(_execute_sync)
                result = future.result(timeout=60.0)

                elapsed = time.time() - start
                log_event(
                    "sqlalchemy_query_success",
                    {"rows": len(result), "elapsed_sec": round(elapsed, 2)},
                )
                return result
        except (FutureTimeoutError, TimeoutError):
            log_event("sqlalchemy_query_timeout", {"query": query[:200]})
            raise TimeoutError(
                "Query is taking too long. Try filtering your data or asking a simpler question."
            )
        except Exception as e:
            log_event("sqlalchemy_query_error", {"error": str(e)[:200]})
            raise

    def get_table_schema(
        self, schema_name: Optional[str], table_name: str
    ) -> Dict[str, Any]:
        """Get table schema using SQLAlchemy inspector."""
        inspector = inspect(self.engine)

        columns = []
        for column in inspector.get_columns(table_name, schema=schema_name):
            columns.append(
                {
                    "name": column["name"],
                    "type": str(column["type"]),
                    "nullable": column["nullable"],
                    "default": str(column.get("default", "")),
                }
            )

        # Get primary keys
        primary_keys = inspector.get_primary_keys(table_name, schema=schema_name)

        # Get foreign keys
        foreign_keys = []
        for fk in inspector.get_foreign_keys(table_name, schema=schema_name):
            foreign_keys.append(
                {
                    "name": fk.get("name"),
                    "constrained_columns": fk.get("constrained_columns"),
                    "referred_table": fk.get("referred_table"),
                    "referred_columns": fk.get("referred_columns"),
                }
            )

        return {
            "table_name": table_name,
            "schema_name": schema_name,
            "columns": columns,
            "primary_keys": primary_keys,
            "foreign_keys": foreign_keys,
        }

    def list_tables(self, schema_name: Optional[str] = None) -> List[str]:
        """List tables using SQLAlchemy inspector."""
        inspector = inspect(self.engine)
        return inspector.get_table_names(schema=schema_name)

    def test_connection(self) -> bool:
        """Test database connection."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
