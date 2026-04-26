"""Isolated async DB session for non-FastAPI loops.

The global engine in db/session.py and db/base.py is bound to whatever
event loop first uses it (typically the FastAPI request loop). When a
sync LangGraph node, a Celery worker, or any code that wraps
``asyncio.run(...)`` opens a session against that pool, the underlying
asyncpg connection's Future ends up attached to a loop different from
the one currently driving it.

Symptoms in the AI service log:
  - asyncpg.exceptions._base.InternalClientError:
      got result for unknown protocol state 3
  - RuntimeError: Future attached to a different loop

Mitigation: build a brand-new engine *inside the caller's loop* with
``NullPool`` so the connection is created and torn down without ever
crossing loop boundaries. Slightly more expensive per call, but these
sites are rare (one per LangGraph invocation, one per audit flush).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from db.session import DATABASE_URL


@asynccontextmanager
async def isolated_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool, echo=False)
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
