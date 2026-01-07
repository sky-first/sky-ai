# db/base.py
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker

from dotenv import load_dotenv
import os

# Load env from current dir and project root (dev-friendly)
load_dotenv()
load_dotenv("../.env", override=False)


def _default_database_url_async() -> str:
    """
    Default to the local Docker Postgres for development (async).
    """
    pg_user = os.getenv("POSTGRES_USER")
    pg_pass = os.getenv("POSTGRES_PASSWORD")
    pg_host = os.getenv("POSTGRES_HOST")
    pg_port = os.getenv("POSTGRES_PORT")
    pg_db = os.getenv("POSTGRES_DB")
    if pg_user and pg_pass and pg_host and pg_port and pg_db:
        return f"postgresql+asyncpg://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"
    return "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db"


def _default_database_url_sync() -> str:
    """
    Default to the local Docker Postgres for development (sync).
    """
    pg_user = os.getenv("POSTGRES_USER")
    pg_pass = os.getenv("POSTGRES_PASSWORD")
    pg_host = os.getenv("POSTGRES_HOST")
    pg_port = os.getenv("POSTGRES_PORT")
    pg_db = os.getenv("POSTGRES_DB")
    if pg_user and pg_pass and pg_host and pg_port and pg_db:
        return f"postgresql+psycopg2://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"
    return "postgresql+psycopg2://postgres:postgres@localhost:5432/ai_saas_db"


# URLs para async e sync
_raw_url = os.getenv("DATABASE_URL") or ""

# Async URL (para FastAPI routes)
if _raw_url:
    DATABASE_URL = _raw_url
    if DATABASE_URL.startswith("postgresql+psycopg2://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    elif DATABASE_URL.startswith("postgresql://") and "+" not in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
else:
    DATABASE_URL = _default_database_url_async()

# Sync URL (para LangGraph e operações síncronas)
if _raw_url:
    DATABASE_URL_SYNC = _raw_url
    if DATABASE_URL_SYNC.startswith("postgresql+asyncpg://"):
        DATABASE_URL_SYNC = DATABASE_URL_SYNC.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    elif DATABASE_URL_SYNC.startswith("postgresql://") and "+" not in DATABASE_URL_SYNC:
        DATABASE_URL_SYNC = DATABASE_URL_SYNC.replace("postgresql://", "postgresql+psycopg2://")
else:
    DATABASE_URL_SYNC = _default_database_url_sync()

# Async engine e session (para FastAPI)
engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

# Sync engine e session (para LangGraph e operações síncronas)
sync_engine = create_engine(
    DATABASE_URL_SYNC,
    pool_pre_ping=True,
    echo=False,
)

SyncSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=sync_engine,
)

# importa models para garantir que o metadata seja carregado
from db import models  # noqa: F401


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
