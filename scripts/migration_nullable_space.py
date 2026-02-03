#!/usr/bin/env python3
import os
import sys
import asyncio
from dotenv import load_dotenv
load_dotenv()

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from db.base import SessionLocal
from sqlalchemy import text

async def migrate():
    async with SessionLocal() as db:
        print("Migrating schema to allow nullable space_id...")
        try:
            # Alter table_metadata
            await db.execute(text("ALTER TABLE table_metadata ALTER COLUMN space_id DROP NOT NULL;"))
            print("Altered table_metadata.")
            
            # Alter embeddings
            await db.execute(text("ALTER TABLE embeddings ALTER COLUMN space_id DROP NOT NULL;"))
            print("Altered embeddings.")
            
            await db.commit()
            print("Migration successful.")
        except Exception as e:
            await db.rollback()
            print(f"Migration failed: {e}")

if __name__ == "__main__":
    asyncio.run(migrate())
