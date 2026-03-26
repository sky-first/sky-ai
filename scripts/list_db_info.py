import asyncio
import sys
import os

sys.path.append(os.getcwd())

async def list_unique_tables():
    from db.session import AsyncSessionLocal
    from sqlalchemy import text
    
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT DISTINCT table_name FROM table_metadata WHERE data_connection_id = 'c9207911-8f8d-4fcd-86a8-1fe77aa2ed25'"))
        rows = res.all()
        print(f"Total de tabelas únicas: {len(rows)}")
        for r in rows[:15]:
            print(f"Table: {r[0]}")

if __name__ == "__main__":
    asyncio.run(list_unique_tables())
