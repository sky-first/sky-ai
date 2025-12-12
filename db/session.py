# db/session.py
from __future__ import annotations

from typing import Generator

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Ex: postgresql+psycopg2://user:password@localhost:5432/mydb
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://user:password@localhost:5432/mydb")

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
