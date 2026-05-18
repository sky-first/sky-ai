"""fix embedding dims to 1024 and add semantic_cache.user_id

Applies two corrections that were written as historical migrations (002, 003)
but were never physically applied because the DB was stamped directly at
003b (agent_finding_viz_kind) without running the chain.

Changes:
  1. semantic_cache.user_id TEXT NULL (cache isolation per user, personal mode)
  2. embeddings.embedding: vector(768) → vector(1024) + TRUNCATE
  3. semantic_cache.embedding: vector(768) → vector(1024) + TRUNCATE
  4. knowledge_file_chunks.embedding: vector(768) → vector(1024) + TRUNCATE

Why truncate: existing 768-dim vectors are incompatible with 1024-dim queries.
The seed task repopulates embeddings lazily on first /spaces/{id}/seed-embeddings
call (or on first /semantic/map). Semantic cache rebuilds naturally from queries.

Safe to re-run: each step is guarded with IF NOT EXISTS / current-dim checks.

Revision ID: 005_fix_embedding_dims_and_cache
Revises: agent_finding_viz_kind_20260515
Create Date: 2026-05-18
"""

from alembic import op

revision = "005_fix_embedding_dims_and_cache"
down_revision = "agent_finding_viz_kind_20260515"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add user_id to semantic_cache (personal-mode cache isolation)
    op.execute("""
        ALTER TABLE semantic_cache
            ADD COLUMN IF NOT EXISTS user_id TEXT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_semantic_cache_user_id
            ON semantic_cache(user_id)
    """)

    # 2. Migrate vector columns from 768 → 1024
    _TABLES = [
        ("embeddings",            "embedding", True),   # NOT NULL
        ("semantic_cache",        "embedding", True),   # NOT NULL
        ("knowledge_file_chunks", "embedding", False),  # nullable
    ]
    for table, column, not_null in _TABLES:
        exists = conn.execute(
            "SELECT 1 FROM pg_class WHERE relname = %s", (table,)
        ).fetchone()
        if not exists:
            continue

        row = conn.execute(
            """SELECT format_type(atttypid, atttypmod)
               FROM pg_attribute
               WHERE attrelid = %s::regclass AND attname = %s""",
            (table, column),
        ).fetchone()
        current_dim = row[0] if row else None
        if current_dim == "vector(1024)":
            continue  # already migrated

        op.execute(f"TRUNCATE TABLE {table} CASCADE")
        op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        null_clause = "NOT NULL" if not_null else ""
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} vector(1024) {null_clause}"
        )


def downgrade() -> None:
    # Intentionally a no-op: reverting to 768 would invalidate all 1024-dim
    # vectors and there is no way to recover the truncated 768-dim data.
    pass
