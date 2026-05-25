import asyncio
from db.session import AsyncSessionLocal
from sqlalchemy import text


async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            text(
                "SELECT DISTINCT table_name FROM table_metadata WHERE data_connection_id = '4e96c724-b1a1-47a8-9f8c-60af9deaeb89'"
            )
        )
        table_names = [r[0] for r in res]
        print(f"Tables in table_metadata ({len(table_names)}): {table_names}")


if __name__ == "__main__":
    asyncio.run(check())
