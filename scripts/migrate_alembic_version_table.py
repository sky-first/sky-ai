"""Migrate sky-ai's alembic head from the legacy shared ``alembic_version``
table to the new dedicated ``alembic_version_ai`` table.

Runs ONCE per environment before the first deploy that ships
``alembic/env.py`` with ``version_table="alembic_version_ai"``.
After this script, sky-ai writes/reads ``alembic_version_ai`` and
sky-be uses ``alembic_version_be`` — see the
``skyfirst-alembic-version-conflict`` memory for the back-story.

Idempotent: re-running is safe — it only inserts the row when
``alembic_version_ai`` is empty.

Usage::

    # local dev
    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db \\
        venv/Scripts/python.exe scripts/migrate_alembic_version_table.py

    # staging (from inside a sky-ai pod with env wired)
    python scripts/migrate_alembic_version_table.py \\
        --expected-heads 004_audit_security_columns,005_fix_embedding_dims_and_cache

The script does:

  1. Confirm the legacy ``alembic_version`` table exists.
  2. Pick rows that match known sky-ai revisions (from the local
     script tree). Sky-be rows are ignored.
  3. CREATE TABLE ``alembic_version_ai`` (if not present) with the
     same schema.
  4. INSERT the picked rows if the new table is empty. Sky-ai has
     two divergent heads (audit_security + fix_embedding_dims), so
     this supports multi-row seeding via comma-separated ``--expected-heads``.
  5. Print a summary.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import List, Optional, Set

sys.path.insert(0, str(Path(__file__).parent.parent))

from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402


def _local_sky_ai_revisions() -> Set[str]:
    """Collect every revision ID known to this checkout."""
    cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    return {rev.revision for rev in script.walk_revisions()}


async def main(expected_heads: Optional[List[str]]) -> int:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL env var required", file=sys.stderr)
        return 2

    engine = create_async_engine(db_url, echo=False)
    sky_ai_revs = _local_sky_ai_revisions()
    print(f"  loaded {len(sky_ai_revs)} sky-ai revisions from script tree")

    async with engine.begin() as conn:
        legacy_exists = (
            await conn.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT FROM information_schema.tables "
                    "WHERE table_name = 'alembic_version')"
                )
            )
        ).scalar()
        if not legacy_exists:
            print("  no legacy alembic_version table present — nothing to migrate")
            # Still create the new table + seed from expected_heads so
            # greenfield envs end up in a consistent state.
            if expected_heads:
                await _create_and_seed(conn, expected_heads)
            await engine.dispose()
            return 0

        rows: List[str] = list(
            (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalars()
        )
        print(f"  legacy alembic_version contains {len(rows)} row(s): {rows}")

        sky_ai_rows = [r for r in rows if r in sky_ai_revs]
        other_rows = [r for r in rows if r not in sky_ai_revs]
        print(f"  classified: {len(sky_ai_rows)} sky-ai · {len(other_rows)} other")

        if not sky_ai_rows:
            print(
                "  no sky-ai revision in legacy table — using ``expected_heads`` "
                "argument if provided"
            )
            if not expected_heads:
                print(
                    "  pass --expected-heads <REV1,REV2,...> to seed the new table",
                    file=sys.stderr,
                )
                await engine.dispose()
                return 1
            picked = expected_heads
        else:
            picked = sky_ai_rows

        if expected_heads and set(picked) != set(expected_heads):
            print(
                f"  WARNING expected_heads={expected_heads} but picking {picked}",
                file=sys.stderr,
            )

        await _create_and_seed(conn, picked)

        if sky_ai_rows:
            await conn.execute(
                text(
                    "DELETE FROM alembic_version "
                    "WHERE version_num = ANY(:revs)"
                ),
                {"revs": sky_ai_rows},
            )
            print(f"  removed {len(sky_ai_rows)} sky-ai row(s) from legacy table")

    await engine.dispose()
    print("done.")
    return 0


async def _create_and_seed(conn, picked: List[str]) -> None:
    """Create alembic_version_ai if missing, seed if empty."""
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS alembic_version_ai ("
            "version_num VARCHAR(32) NOT NULL, "
            "CONSTRAINT alembic_version_ai_pkc PRIMARY KEY (version_num))"
        )
    )
    existing = list(
        (
            await conn.execute(text("SELECT version_num FROM alembic_version_ai"))
        ).scalars()
    )
    if existing:
        print(
            f"  alembic_version_ai already populated with {existing!r} — no-op"
        )
        return
    for rev in picked:
        await conn.execute(
            text("INSERT INTO alembic_version_ai (version_num) VALUES (:v)"),
            {"v": rev},
        )
    print(f"  inserted {picked!r} into alembic_version_ai")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expected-heads",
        default=None,
        help=(
            "Comma-separated revisions to seed alembic_version_ai when "
            "no sky-ai revision is found in the legacy table (greenfield env). "
            "Sky-ai has two divergent heads — pass both."
        ),
    )
    args = parser.parse_args()
    heads = (
        [h.strip() for h in args.expected_heads.split(",") if h.strip()]
        if args.expected_heads
        else None
    )
    sys.exit(asyncio.run(main(heads)))
