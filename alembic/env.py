"""Alembic environment — sky-poc-ai.

URL resolution order:
  1. POSTGRES_* individual env vars (preferred in k8s — avoids encoding issues)
  2. DATABASE_URL env var (local dev / docker-compose)
  3. Hardcoded local default (fallback for bare dev machines)

Uses the sync psycopg2 driver because Alembic's runner is synchronous.
The FastAPI app uses asyncpg at runtime — that's fine, both drivers talk
to the same Postgres instance.

pgvector type registration: the Vector column type is not natively known
to Alembic's autogenerate. We register it as a UserDefinedType so that
future `alembic revision --autogenerate` commands don't produce spurious
ALTER TABLE statements for embedding columns.
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from urllib.parse import quote_plus

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── Logging ──────────────────────────────────────────────────────────────
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Models ───────────────────────────────────────────────────────────────
# Import Base and all models so Alembic's autogenerate can diff them.
from db.models import (
    Base,
)  # noqa: E402  — also registers all mappers via import side-effect

target_metadata = Base.metadata

# ── pgvector ─────────────────────────────────────────────────────────────
# Tell SQLAlchemy's reflection layer about the "vector" type so Alembic
# doesn't flag Vector columns as unknown during autogenerate.
try:
    from pgvector.sqlalchemy import Vector  # noqa: F401
except ImportError:
    pass


# ── URL resolution ────────────────────────────────────────────────────────
def _build_sync_url() -> str:
    pg_user = os.getenv("POSTGRES_USER")
    pg_pass = os.getenv("POSTGRES_PASSWORD")
    pg_host = os.getenv("POSTGRES_HOST")
    pg_port = os.getenv("POSTGRES_PORT", "5432")
    pg_db = os.getenv("POSTGRES_DB")

    if pg_user and pg_pass and pg_host and pg_db:
        return (
            f"postgresql://{pg_user}:{quote_plus(pg_pass)}"
            f"@{pg_host}:{pg_port}/{pg_db}"
        )

    raw = os.getenv("DATABASE_URL", "")
    if raw:
        return raw.replace("postgresql+asyncpg://", "postgresql://").replace(
            "postgresql+psycopg2://", "postgresql://"
        )

    return "postgresql://postgres:postgres@localhost:5432/ai_saas_db"


def run_migrations_offline() -> None:
    context.configure(
        url=_build_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # sky-ai shares the platform DB with sky-be. Each app tracks its
        # own alembic head in a dedicated version table so cross-app
        # revisions never collide. sky-be → alembic_version_be.
        version_table="alembic_version_ai",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _build_sync_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # See note in run_migrations_offline().
            version_table="alembic_version_ai",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
