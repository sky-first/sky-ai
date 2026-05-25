import asyncio
from db.session import AsyncSessionLocal
from sqlalchemy import text


async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'crew_members'"
            )
        )
        print("Columns in crew_members:", [r[0] for r in res])

        res = await db.execute(
            text(
                "SELECT * FROM crew_members WHERE user_id = 'ae1a8640-f868-4d2a-9dea-9aa4e21b5dfc'"
            )
        )
        row = res.fetchone()
        print("Data for test user:", row)


if __name__ == "__main__":
    asyncio.run(check())
