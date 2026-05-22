"""Smoke tests for db.isolated.isolated_session.

The contract we care about: every call must build a fresh engine and
dispose it on exit. That is the whole point of this helper — it
guarantees the asyncpg connection is born and dies inside the caller's
loop, sidestepping the "Future attached to a different loop" bug we
hit when LangGraph sync nodes wrap an asyncio.run().
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, AsyncMock, patch

import pytest


def test_isolated_session_creates_fresh_engine_and_disposes_it():
    """Each entry into isolated_session() must build a NEW engine and
    call .dispose() on it before returning, regardless of whether the
    body raised."""
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()

    fake_factory = MagicMock()
    fake_factory.return_value.__aenter__ = AsyncMock(return_value="session-stub")
    fake_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "db.isolated.create_async_engine", return_value=fake_engine
    ) as eng_ctor, patch("db.isolated.async_sessionmaker", return_value=fake_factory):
        from db.isolated import isolated_session

        async def _use_it():
            async with isolated_session() as db:
                assert db == "session-stub"

        asyncio.run(_use_it())

        # NullPool must be passed so each call is isolated
        from sqlalchemy.pool import NullPool

        eng_ctor.assert_called_once()
        kwargs = eng_ctor.call_args.kwargs
        assert kwargs.get("poolclass") is NullPool

        fake_engine.dispose.assert_awaited_once()


def test_isolated_session_disposes_engine_even_when_body_raises():
    """If the caller's body raises, the engine must still be disposed.
    Otherwise we leak a connection per failed brain_retrieval node."""
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()

    fake_factory = MagicMock()
    fake_factory.return_value.__aenter__ = AsyncMock(return_value="session-stub")
    fake_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("db.isolated.create_async_engine", return_value=fake_engine), patch(
        "db.isolated.async_sessionmaker", return_value=fake_factory
    ):
        from db.isolated import isolated_session

        async def _use_it():
            async with isolated_session():
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(_use_it())

        fake_engine.dispose.assert_awaited_once()


def test_isolated_session_independent_engines_across_calls():
    """Two consecutive calls must build TWO engines. Sharing one
    engine across asyncio.run() boundaries is exactly the bug this
    helper exists to prevent."""
    engines = [MagicMock(dispose=AsyncMock()) for _ in range(2)]

    fake_factory = MagicMock()
    fake_factory.return_value.__aenter__ = AsyncMock(return_value="stub")
    fake_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "db.isolated.create_async_engine", side_effect=engines
    ) as eng_ctor, patch("db.isolated.async_sessionmaker", return_value=fake_factory):
        from db.isolated import isolated_session

        async def _once():
            async with isolated_session():
                pass

        asyncio.run(_once())
        asyncio.run(_once())

        assert eng_ctor.call_count == 2
        for eng in engines:
            eng.dispose.assert_awaited_once()
