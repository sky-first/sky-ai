
import asyncio
from db.session import AsyncSessionLocal
from sqlalchemy import text

async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT permission, crew_id FROM user_permissions WHERE user_id = 'ae1a8640-f868-4d2a-9dea-9aa4e21b5dfc'"))
        rows = res.fetchall()
        print(f'Permissions for test user ({len(rows)}):')
        for r in rows:
            print(f"Role: {r[0]} | Crew: {r[1]}")

if __name__ == "__main__":
    asyncio.run(check())
