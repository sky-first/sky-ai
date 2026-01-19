import asyncio
import os
import sys

# Ensure src is in path
sys.path.append(os.getcwd())

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from src.repositories.planet import PlanetRepository


async def test_create_planet():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL missing")
        return

    if "postgresql+asyncpg" not in database_url:
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = create_async_engine(database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Get user
        result = await session.execute(
            text("SELECT id FROM users WHERE email = 'test@example.com'")
        )
        user_id = result.scalar()
        print(f"User ID: {user_id}")

        if not user_id:
            print("User not found!")
            return

        repo = PlanetRepository(session)
        try:
            planet = await repo.create(
                name="Test Planet",
                description="Debug planet",
                type="personal",
                color="#000000",
                owner_id=user_id,
                is_active=True,
            )
            print(f"Created planet: {planet.id}")
            await session.commit()
        except Exception as e:
            print(f"Error creating planet: {e}")
            import traceback

            traceback.print_exc()

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(test_create_planet())
