"""
Migration: Add crew_id column to semantic_cache table.

FIX 2 — Semantic cache crew isolation.
Previously, semantic_cache only filtered by connection_id + space_id, which
could return a cached answer generated with Crew A's data to a user in Crew B.

Run: python scripts/migrate_semantic_cache_crew_id.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from db.session import engine


async def migrate():
    async with engine.begin() as conn:
        # 1. Add crew_id column (nullable — NULL means personal mode / no restriction)
        await conn.execute(
            text("""
                ALTER TABLE semantic_cache
                ADD COLUMN IF NOT EXISTS crew_id VARCHAR(36) DEFAULT NULL;
            """)
        )

        # 2. Create index for faster lookup filtering by crew_id
        await conn.execute(
            text("""
                CREATE INDEX IF NOT EXISTS idx_semantic_cache_crew_id
                ON semantic_cache (crew_id);
            """)
        )

        print("[OK] semantic_cache.crew_id column and index created successfully.")


if __name__ == "__main__":
    asyncio.run(migrate())
