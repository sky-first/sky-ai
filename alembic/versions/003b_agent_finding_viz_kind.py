"""add viz_kind to agent_findings

Stub migration. This revision was applied directly to the staging DB
(outside the repository) before Alembic was introduced. The column
already exists in production; the upgrade is guarded with IF NOT EXISTS
so it is safe to re-run.

The revision ID matches exactly what the DB recorded so that Alembic
can resolve its migration chain.

Revision ID: agent_finding_viz_kind_20260515
Revises: 003_embeddings_1024
Create Date: 2026-05-18
"""

from alembic import op

revision = "agent_finding_viz_kind_20260515"
down_revision = "003_embeddings_1024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Column already exists in staging — ADD COLUMN IF NOT EXISTS is a no-op there.
    # For fresh envs this creates the column so the chain stays consistent.
    op.execute(
        "ALTER TABLE agent_findings ADD COLUMN IF NOT EXISTS viz_kind VARCHAR(50)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE agent_findings DROP COLUMN IF EXISTS viz_kind")
