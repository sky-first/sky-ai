
import asyncio
import os
import sys

from sqlalchemy import text

from db.session import get_db

# Add repository root to path
sys.path.insert(0, os.getcwd())


async def main():
    try:
        db_gen = get_db()
        db = await anext(db_gen)

        print("\n--- Data Connections ---")
        result = await db.execute(text("SELECT id, name FROM data_connections"))
        conns = result.fetchall()
        for c in conns:
            print(f"ID: {c[0]} | Name: {c[1]}")

        print("\n--- Spaces ---")
        result = await db.execute(text("SELECT id, name FROM spaces"))
        spaces = result.fetchall()
        for s in spaces:
            print(f"ID: {s[0]} | Name: {s[1]}")

        print("\n--- Crews ---")
        result = await db.execute(text("SELECT id, name FROM crews"))
        crews = result.fetchall()
        for c in crews:
            print(f"ID: {c[0]} | Name: {c[1]}")

        print("\n--- Users ---")
        result = await db.execute(text("SELECT id, email FROM users"))
        users = result.fetchall()
        for u in users:
            print(f"ID: {u[0]} | Email: {u[1]}")

        await db.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
