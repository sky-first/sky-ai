
import asyncio
from sqlalchemy import text
from db.session import AsyncSessionLocal

async def get_conn_id():
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT id FROM data_connections LIMIT 1"))
        row = result.first()
        if row:
            print(row[0])
        else:
            print("None")

if __name__ == "__main__":
    asyncio.run(get_conn_id())
