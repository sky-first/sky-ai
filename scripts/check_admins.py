import asyncio
from db.session import AsyncSessionLocal
from sqlalchemy import text


async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            text("SELECT user_id, crew_id, role FROM crew_members WHERE role = 'admin'")
        )
        print("Admins in crew_members:", res.fetchall())

        res = await db.execute(
            text(
                "SELECT user_id, crew_id, permission FROM user_permissions WHERE permission = 'admin'"
            )
        )
        print("Admins in user_permissions:", res.fetchall())


if __name__ == "__main__":
    asyncio.run(check())
