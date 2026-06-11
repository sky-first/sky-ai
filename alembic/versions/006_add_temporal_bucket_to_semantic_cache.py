"""add temporal_bucket to semantic_cache

Adds a temporal_bucket column so that queries with relative temporal expressions
("este ano", "último mês", "this quarter") are isolated by the absolute period
they resolve to at query time. Without this column, "faturas deste ano" asked in
2023 and 2026 collide on the same cache key and the stale 2023 answer is served.

Changes:
  1. semantic_cache.temporal_bucket TEXT NULL
     "absoluto" for non-temporal / absolute-date questions.
     Period string (e.g. "2026", "2026-Q2", "2026-05") for relative expressions.
     NULL on pre-existing rows — they are version=1 and are not matched by
     version=2 lookups, so they naturally expire without needing a TRUNCATE.

Revision ID: 006_add_temporal_bucket_to_semantic_cache
Revises: 005_fix_embedding_dims_and_cache
Create Date: 2026-06-09
"""

from alembic import op

revision = "006_temporal_bucket_cache"
down_revision = "005_fix_embedding_dims_and_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE semantic_cache
            ADD COLUMN IF NOT EXISTS temporal_bucket TEXT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_semantic_cache_temporal_bucket
            ON semantic_cache(temporal_bucket)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_semantic_cache_temporal_bucket")
    op.execute("ALTER TABLE semantic_cache DROP COLUMN IF EXISTS temporal_bucket")
