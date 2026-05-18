"""initial schema

Represents the state of the database after:
  - SQLAlchemy create_all (all tables from db/models.py)
  - 001_create_query_audit_log.sql
  - 002_add_space_id_to_data_connections.sql
  - 003_backfill_space_id_legacy_connections.sql  (fixed in PR #203)

This revision is intentionally a no-op. Its only purpose is to give
existing staging/production databases a revision anchor so that
`alembic upgrade head` can start from here and apply only what's missing
(002 and 003 below), without trying to re-create tables that already
exist.

To stamp an existing database at this baseline:
    alembic stamp 001_initial

Revision ID: 001_initial
Revises: (none — first revision)
Create Date: 2026-05-18
"""

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op: schema already exists in databases that ran create_all
    # and the three SQL migration files above.
    pass


def downgrade() -> None:
    # Downgrading to before the initial schema would mean dropping
    # all tables — too destructive to automate. Do it manually if needed.
    pass
