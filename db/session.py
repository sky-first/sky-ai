# db/session.py
from __future__ import annotations

from typing import Generator

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

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
        return f"postgresql+psycopg2://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"
    return (
        "postgresql+psycopg2://postgres:"
        "IvXyeUdrcPA6gvfp1HzjgojiDj%2B0%2BPDO1Ob4s4PviRM%3D"
        "@localhost:5433/ai_saas_db"
    )


# Ex: postgresql+psycopg2://user:password@localhost:5432/mydb
DATABASE_URL = os.getenv("DATABASE_URL") or _default_database_url()

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
