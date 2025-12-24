# db/base.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dotenv import load_dotenv
import os

# Load env from current dir and project root (dev-friendly)
load_dotenv()
load_dotenv("../.env", override=False)


def _default_database_url() -> str:
    """
    Default to the local Docker Postgres (deploy/5433) for development.
    If DATABASE_URL is explicitly provided, it always wins.
    """
    # If someone provided POSTGRES_* env vars, build a URL (supports special chars via percent-encoding in env).
    pg_user = os.getenv("POSTGRES_USER")
    pg_pass = os.getenv("POSTGRES_PASSWORD")
    pg_host = os.getenv("POSTGRES_HOST")
    pg_port = os.getenv("POSTGRES_PORT")
    pg_db = os.getenv("POSTGRES_DB")
    if pg_user and pg_pass and pg_host and pg_port and pg_db:
        return f"postgresql+psycopg2://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"

    # Fallback: local docker mapping used by this repo (ai_saas_postgres_prod)
    # Local dev default: matches sky-poc-backend docker postgres published port.
    # Override via DATABASE_URL or POSTGRES_* env vars for other environments.
    return "postgresql+psycopg2://postgres:postgres@localhost:5432/ai_saas_db"


DATABASE_URL = os.getenv("DATABASE_URL") or _default_database_url()

engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# importa models para garantir que o metadata seja carregado
from db import models  # noqa: F401


def init_db():
    models.Base.metadata.create_all(bind=engine)
