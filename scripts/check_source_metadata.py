import asyncio
import os
import sys
from sqlalchemy import text
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from db.base import SessionLocal

TEST_CONNECTION_ID = (
    os.getenv("TEST_CONNECTION_ID") or "1fd6fee8-bf03-4e82-9c85-419a228ef726"
)


async def check_metadata():
    async with SessionLocal() as db:
        print(f"Checking ALL entries in connection_metadata...")
        try:
            result = await db.execute(
                text("SELECT connection_id, tables FROM connection_metadata")
            )
            rows = result.fetchall()
            if rows:
                print(f"✅ Found {len(rows)} connections with metadata:")
                for r in rows:
                    conn_id = r[0]
                    tables = r[1]
                    count = len(tables) if isinstance(tables, list) else 0
                    print(f"   - Connection ID: {conn_id} | Tables: {count}")
            else:
                print(f"❌ No metadata found in connection_metadata (table is empty)")
        except Exception as e:
            print(f"❌ Error querying database: {e}")


if __name__ == "__main__":
    asyncio.run(check_metadata())
