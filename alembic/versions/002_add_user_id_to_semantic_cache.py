"""add user_id to semantic_cache

Isolates Personal-mode cache rows per user. Without this column, user A's
cached answer could be served to user B when both hit the same connection_id
— a cross-user data leak.

Nullable: existing Space/Crew rows keep NULL; new Personal-mode rows
receive the caller's user_id. The lookup in connection_query.py reads
this column to scope cache hits correctly.

Replaces: db/migrations/004_add_user_id_to_semantic_cache.sql

Revision ID: 002_semantic_cache_user_id
Revises: 001_initial
Create Date: 2026-05-18
"""

from alembic import op
import sqlalchemy as sa

revision = "002_semantic_cache_user_id"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE semantic_cache
            ADD COLUMN IF NOT EXISTS user_id TEXT NULL
    """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_semantic_cache_user_id
            ON semantic_cache(user_id)
    """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_semantic_cache_user_id")
    op.execute("ALTER TABLE semantic_cache DROP COLUMN IF EXISTS user_id")
