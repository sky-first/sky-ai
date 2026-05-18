"""migrate embeddings to vector(1024)

Migrates all pgvector columns from vector(768) to vector(1024).

1024 dims matches Bedrock Titan v2, Cohere v3 and Ollama mxbai-embed-large,
removing the dependency on OpenAI text-embedding-3-large (which was the only
model that accepted the dimensions=768 truncation parameter, and which 404'd
against the bedrock-mantle proxy used in staging).

Switching embedding models always invalidates existing vectors — a Titan
vector is meaningless compared to an OpenAI vector. This migration truncates
the affected tables; the lazy seed in the BE re-populates each Space on the
first /semantic/map call after deploy.

Each table is guarded by a dimension check so this is safe to re-run on
databases that are already at vector(1024) (e.g. freshly provisioned envs
where create_all already produced the right dimension).

Replaces: db/migrations/005_migrate_embeddings_to_1024.sql

Revision ID: 003_embeddings_1024
Revises: 002_semantic_cache_user_id
Create Date: 2026-05-18
"""

from alembic import op

revision = "003_embeddings_1024"
down_revision = "002_semantic_cache_user_id"
branch_labels = None
depends_on = None

_TABLES = [
    ("embeddings", "embedding", True),            # NOT NULL
    ("semantic_cache", "embedding", True),         # NOT NULL
    ("knowledge_file_chunks", "embedding", False), # nullable
]


def _current_dim(conn, table: str, column: str) -> str:
    row = conn.execute(
        """
        SELECT format_type(atttypid, atttypmod)
        FROM pg_attribute
        WHERE attrelid = %s::regclass
          AND attname = %s
        """,
        (table, column),
    ).fetchone()
    return row[0] if row else None


def upgrade() -> None:
    conn = op.get_bind()
    for table, column, not_null in _TABLES:
        # Skip if table doesn't exist yet (fresh DB already has 1024 via create_all)
        exists = conn.execute(
            "SELECT 1 FROM pg_class WHERE relname = %s", (table,)
        ).fetchone()
        if not exists:
            continue

        dim = _current_dim(conn, table, column)
        if dim == "vector(1024)":
            continue

        op.execute(f"TRUNCATE TABLE {table} CASCADE")
        op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        null_clause = "NOT NULL" if not_null else ""
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} vector(1024) {null_clause}"
        )


def downgrade() -> None:
    conn = op.get_bind()
    for table, column, not_null in _TABLES:
        exists = conn.execute(
            "SELECT 1 FROM pg_class WHERE relname = %s", (table,)
        ).fetchone()
        if not exists:
            continue

        dim = _current_dim(conn, table, column)
        if dim == "vector(768)":
            continue

        op.execute(f"TRUNCATE TABLE {table} CASCADE")
        op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        null_clause = "NOT NULL" if not_null else ""
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} vector(768) {null_clause}"
        )
