import asyncio
from db.session import AsyncSessionLocal
from sqlalchemy import text
import json


async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            text(
                "SELECT tables FROM connection_metadata WHERE connection_id = '4e96c724-b1a1-47a8-9f8c-60af9deaeb89'"
            )
        )
        tables = res.scalar()
        if tables:
            print(f"Found {len(tables)} tables.")
            for t in tables:
                print(f"Table: {t.get('name')} | Logical: {t.get('logical_name')}")


if __name__ == "__main__":
    asyncio.run(check())
