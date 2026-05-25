# core/agents/checkpoint_manager.py
from __future__ import annotations

import logging
from typing import Optional
from contextlib import contextmanager

try:
    from psycopg_pool import ConnectionPool
    from psycopg.rows import dict_row
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    HAS_POSTGRES_CHECKPOINTER = True
except ImportError:
    HAS_POSTGRES_CHECKPOINTER = False
    ConnectionPool = None
    PostgresSaver = None
    dict_row = None
    JsonPlusSerializer = None

if HAS_POSTGRES_CHECKPOINTER:
    import decimal
    import datetime
    import json as _json

    def _sanitize_for_json(obj):
        """
        Recursively converts non-JSON-serializable types (Decimal, date, datetime,
        bytes, sets) to JSON-safe equivalents so LangGraph checkpoints never fail.
        """
        if isinstance(obj, dict):
            return {k: _sanitize_for_json(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_sanitize_for_json(i) for i in obj]
        if isinstance(obj, decimal.Decimal):
            # Convert to float; use str for lossless if you prefer: str(obj)
            return float(obj)
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        if isinstance(obj, set):
            return list(obj)
        return obj

    class ForceJsonSerializer(JsonPlusSerializer):
        def dumps_typed(self, obj) -> tuple[str, bytes]:
            # Sanitize before serialising so Decimal / date values never crash
            sanitized = _sanitize_for_json(obj)
            return "json", self.dumps(sanitized)

        def dumps(self, obj) -> bytes:
            sanitized = _sanitize_for_json(obj)
            return super().dumps(sanitized)

    class CustomPostgresSaver(PostgresSaver):
        # Override the class attribute used for metadata serialization
        jsonplus_serde = ForceJsonSerializer()


from config.settings import settings
from core.logging_utils import log_event

from contextlib import contextmanager
from typing import Generator

_pool: Optional[ConnectionPool] = None


def get_connection_pool() -> Optional[ConnectionPool]:
    """
    Returns a singleton connection pool for LangGraph checkpointing.
    Initializes it if not already created.
    """
    global _pool
    if not HAS_POSTGRES_CHECKPOINTER:
        return None

    if _pool is None:
        try:
            db_url = settings.database_url
            # Clean up connection string for psycopg
            sync_db_url = db_url.replace(
                "postgresql+asyncpg://", "postgresql://"
            ).replace("postgresql+psycopg2://", "postgresql://")

            # Initialize pool with dict_row factory (required by LangGraph PostgresSaver)
            # and autocommit=True.
            _pool = ConnectionPool(
                sync_db_url,
                min_size=1,
                max_size=10,
                open=True,
                kwargs={"autocommit": True, "row_factory": dict_row},
            )
            log_event("checkpoint_pool_created", {"conninfo_preview": sync_db_url[:50]})

            # Run setup once to ensure tables exist
            with _pool.connection() as conn:
                # Use CustomPostgresSaver to ensure metadata matches the "json" expectation
                saver = CustomPostgresSaver(conn)
                # setup() creates the checkpoint tables if they don't exist
                saver.setup()
                log_event("checkpoint_tables_ensured", {})

        except Exception as e:
            log_event("checkpoint_pool_init_error", {"error": str(e)})
            if _pool:
                try:
                    _pool.close()
                except:
                    pass
            _pool = None

    return _pool


@contextmanager
def get_checkpointer() -> Generator[Optional[PostgresSaver], None, None]:
    """
    Yields a PostgresSaver instance with a connection from the pool.
    The connection is automatically returned to the pool when the context ends.
    """
    pool = get_connection_pool()
    if not pool:
        yield None
        return

    # Use a simpler context manager pattern to avoid generator issues
    conn = None
    try:
        with pool.connection() as conn:
            # LangGraph PostgresSaver requires autocommit=True to manage its own transactions correctly
            conn.autocommit = True
            # Use CustomPostgresSaver to ensure consistency
            yield CustomPostgresSaver(conn)
    except Exception as e:
        log_event("checkpoint_acquisition_error", {"error": str(e)})
        # Re-raise so the caller knows something went wrong,
        # but only if it's not the yield itself that threw (contextlib handles that)
        raise


def close_pool():
    """Closes the connection pool."""
    global _pool
    if _pool:
        _pool.close()
        _pool = None
        log_event("checkpoint_pool_closed", {})
