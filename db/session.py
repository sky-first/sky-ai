# db/session.py
from __future__ import annotations

from typing import AsyncGenerator
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from dotenv import load_dotenv

# Load env from current dir and project root (dev-friendly)
load_dotenv()
load_dotenv("../.env", override=False)


def _default_database_url() -> str:
    pg_user = os.getenv("POSTGRES_USER")
    pg_pass = os.getenv("POSTGRES_PASSWORD")
    pg_host = os.getenv("POSTGRES_HOST")
    pg_port = os.getenv("POSTGRES_PORT")
    pg_db = os.getenv("POSTGRES_DB")
    if pg_user and pg_pass and pg_host and pg_port and pg_db:
        # Usar asyncpg ao invés de psycopg2
        return f"postgresql+asyncpg://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"
    # Local dev default: matches sky-poc-backend docker postgres published port.
    # Override via DATABASE_URL or POSTGRES_* env vars for other environments.
    return "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db"


# Ex: postgresql+asyncpg://user:password@localhost:5432/mydb
# Se DATABASE_URL tiver psycopg2, converter para asyncpg
DATABASE_URL = os.getenv("DATABASE_URL") or _default_database_url()
if DATABASE_URL.startswith("postgresql+psycopg2://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
elif DATABASE_URL.startswith("postgresql://") and "+" not in DATABASE_URL:
    # Se for postgresql:// sem driver, adicionar asyncpg
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

import json
from datetime import date, datetime

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False,
    json_serializer=lambda obj: json.dumps(obj, default=json_serial),
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
