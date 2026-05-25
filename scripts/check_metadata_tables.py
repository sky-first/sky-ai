import asyncio
import json
from sqlalchemy import text
from db.base import SessionLocal


async def check_tables():
    async with SessionLocal() as db:
        result = await db.execute(
            text(
                "SELECT tables FROM connection_metadata WHERE connection_id = CAST(:cid AS uuid)"
            ),
            {"cid": "4e96c724-b1a1-47a8-9f8c-60af9deaeb89"},
        )
        row = result.first()
        if row:
            tables = row[0]
            for t in tables:
                print(f"Logical: {t.get('logical_name') or t.get('name')}")
                print(f"Physical: {t.get('schema')}.{t.get('name')}")
                # print(f"Columns: {[c.get('name') for c in t.get('columns', [])]}")
                print("-" * 20)
        else:
            print("No metadata found")


if __name__ == "__main__":
    asyncio.run(check_tables())
