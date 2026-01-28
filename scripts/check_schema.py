
import asyncio
from db.session import AsyncSessionLocal
from sqlalchemy import text

async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'connection_metadata'"))
        print('Columns in connection_metadata:', [r[0] for r in res])
        
        res = await db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'table_metadata'"))
        print('Columns in table_metadata:', [r[0] for r in res])

if __name__ == "__main__":
    asyncio.run(check())
