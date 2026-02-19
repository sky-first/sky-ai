import sys
import os
import asyncio

# Add repository root to path
sys.path.append(os.getcwd())

from db.base import SessionLocal
from sqlalchemy import text

async def check_columns():
    async with SessionLocal() as db:
        # Using connection_id from the error log: 70b0fbf5-195d-426a-b96e-78fc8ee32c38
        result = await db.execute(
            text("SELECT tables FROM connection_metadata WHERE connection_id = '70b0fbf5-195d-426a-b96e-78fc8ee32c38'")
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
