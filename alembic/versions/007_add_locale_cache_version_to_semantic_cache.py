"""add locale and cache_version to semantic_cache (A1: dead-cache fix)

The semantic_cache lookup filters on ``locale`` and ``cache_version`` (and,
since 006, ``temporal_bucket``). Both columns were declared in the ORM
(db/models.py) but NEVER added by any migration (001-005). On a fresh DB
``create_all`` builds the table with every ORM column, so local/CI passes —
but on staging/prod, where ``semantic_cache`` predates the columns, the
lookup hits ``column "locale" does not exist`` and the (previously silent)
except swallowed it. Net effect: the cache has been 100% dead in prod,
every repeated question paying full LLM + SQL cost with no alarm.

This migration adds the two missing columns and, critically, marks the
legacy rows as DEAD so the old locale-less answers can never be served:

  - locale         VARCHAR(10)  NULL  — added without a server default
  - cache_version  INTEGER      NULL  — added without a server default

THE BACKFILL TRAP (why no server default here):
  The ORM declares ``cache_version`` server_default="1". If this migration
  added the column WITH that default, Postgres would backfill every existing
  row to version=1 — making the pre-PR, locale-less rows look VALID and
  reintroducing the PT/EN contamination bug. Instead we add the column with
  NO default (legacy rows → NULL) and then explicitly set them to 0. The
  current lookup filters cache_version=2, so version=0 rows are inert.
  New rows are written by the store path with explicit locale + version=2,
  so they never rely on a column default.

Revision ID: 007_locale_cache_version
Revises: 006_temporal_bucket_cache
Create Date: 2026-06-11
"""

from alembic import op

revision = "007_locale_cache_version"
down_revision = "006_temporal_bucket_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add the two columns the lookup needs — WITHOUT a server default, so
    #    pre-existing rows land at NULL (not the model's default of 1/"en").
    op.execute("ALTER TABLE semantic_cache ADD COLUMN IF NOT EXISTS locale VARCHAR(10) NULL")
    op.execute("ALTER TABLE semantic_cache ADD COLUMN IF NOT EXISTS cache_version INTEGER NULL")

    # 2. Mark the legacy rows as DEAD explicitly. version=0 is ignored by every
    #    lookup (which filters cache_version=2), so locale-less answers from
    #    before this fix can never be served. Do NOT rely on server_default.
    op.execute("UPDATE semantic_cache SET cache_version = 0 WHERE cache_version IS NULL")

    # 3. Index the columns the lookup filters on.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_semantic_cache_locale_version "
        "ON semantic_cache(locale, cache_version)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_semantic_cache_locale_version")
    op.execute("ALTER TABLE semantic_cache DROP COLUMN IF EXISTS cache_version")
    op.execute("ALTER TABLE semantic_cache DROP COLUMN IF EXISTS locale")
