
import asyncio
from db.base import SessionLocal
from sqlalchemy import text

async def check_columns():
    async with SessionLocal() as db:
        result = await db.execute(
            text("SELECT tables FROM connection_metadata WHERE connection_id = '4e96c724-b1a1-47a8-9f8c-60af9deaeb89'")
        )
        row = result.first()
        if row:
            for t in row[0]:
                name = t.get('name', '')
                if 'invoices' in name or 'items' in name:
                    print(f"Table: {name}")
                    cols = [c.get('name') for c in t.get('columns', [])]
                    print(f"Columns: {cols}")
                    print("-" * 20)

if __name__ == "__main__":
    asyncio.run(check_columns())
