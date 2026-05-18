"""add security and role columns to query_audit_log

Adds columns that were previously expected to be created by
_ensure_audit_table_async() at runtime — but were never applied because
a CREATE INDEX on a non-existent column aborted the try block before
the ALTER TABLEs could execute.

Root cause: _ensure_audit_table_async tried to create idx_audit_pii_blocked
before pii_blocked existed in the table (old DBs were created without it).
PostgreSQL aborted the whole block; the subsequent ALTER TABLE ADD COLUMN
statements were never reached.

Revision ID: 004_audit_security_columns
Revises: 003_embeddings_1024
Create Date: 2026-05-18
"""

from alembic import op

revision = "004_audit_security_columns"
down_revision = "003_embeddings_1024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Role columns
    op.execute("ALTER TABLE query_audit_log ADD COLUMN IF NOT EXISTS platform_role VARCHAR(50)")
    op.execute("ALTER TABLE query_audit_log ADD COLUMN IF NOT EXISTS crew_role VARCHAR(50)")
    # PII detection columns
    op.execute("ALTER TABLE query_audit_log ADD COLUMN IF NOT EXISTS pii_detected_in_prompt BOOLEAN DEFAULT FALSE")
    op.execute("ALTER TABLE query_audit_log ADD COLUMN IF NOT EXISTS pii_detected_in_response BOOLEAN DEFAULT FALSE")
    op.execute("ALTER TABLE query_audit_log ADD COLUMN IF NOT EXISTS pii_types TEXT[]")
    op.execute("ALTER TABLE query_audit_log ADD COLUMN IF NOT EXISTS pii_severity VARCHAR(10)")
    op.execute("ALTER TABLE query_audit_log ADD COLUMN IF NOT EXISTS pii_patterns_matched TEXT[]")
    op.execute("ALTER TABLE query_audit_log ADD COLUMN IF NOT EXISTS pii_blocked BOOLEAN DEFAULT FALSE")
    # Indexes (safe to create now — columns exist)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_pii_blocked "
        "ON query_audit_log(pii_blocked) WHERE pii_blocked = TRUE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_pii_detected "
        "ON query_audit_log(pii_detected_in_prompt, pii_detected_in_response) "
        "WHERE pii_detected_in_prompt = TRUE OR pii_detected_in_response = TRUE"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_audit_pii_detected")
    op.execute("DROP INDEX IF EXISTS idx_audit_pii_blocked")
    op.execute("ALTER TABLE query_audit_log DROP COLUMN IF EXISTS pii_blocked")
    op.execute("ALTER TABLE query_audit_log DROP COLUMN IF EXISTS pii_patterns_matched")
    op.execute("ALTER TABLE query_audit_log DROP COLUMN IF EXISTS pii_severity")
    op.execute("ALTER TABLE query_audit_log DROP COLUMN IF EXISTS pii_types")
    op.execute("ALTER TABLE query_audit_log DROP COLUMN IF EXISTS pii_detected_in_response")
    op.execute("ALTER TABLE query_audit_log DROP COLUMN IF EXISTS pii_detected_in_prompt")
    op.execute("ALTER TABLE query_audit_log DROP COLUMN IF EXISTS crew_role")
    op.execute("ALTER TABLE query_audit_log DROP COLUMN IF EXISTS platform_role")
