
import asyncio
from db.session import AsyncSessionLocal
from sqlalchemy import text

async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT count(*) FROM connection_metadata WHERE connection_id = '4e96c724-b1a1-47a8-9f8c-60af9deaeb89'"))
        count = res.scalar()
        print(f'Rows in connection_metadata for 4e96...: {count}')
        
        if count > 0:
            res = await db.execute(text("SELECT tables FROM connection_metadata WHERE connection_id = '4e96c724-b1a1-47a8-9f8c-60af9deaeb89'"))
            tables = res.scalar()
            print(f'Tables JSON type: {type(tables)}')
            if tables:
                print(f'Num tables in JSON: {len(tables)}')

if __name__ == "__main__":
    asyncio.run(check())
