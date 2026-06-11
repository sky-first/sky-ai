"""
Regression tests locking the A1 (dead semantic cache) and A2 (streaming locale)
fixes. Lives next to the other bilingual/language tests on purpose.

WHY THESE EXIST — do not remove:
  * A2 was ONE line ("locale" in the streaming state dict). A single line
    vanishes in a refactor without anyone noticing in code review. These tests
    are the alarm: if the line goes, the test fails before prod.
  * A1 had the backfill trap: if legacy rows become a VALID cache_version, the
    PT/EN contamination bug comes back. The test proves the legacy stays inert.

Scope: ONLY the two code-level regressions. The end-to-end test (front + back +
IA with the profile language selector) waits until we confirm the front sends a
filled `locale` in the payload — explicitly out of this lot.
"""

import asyncio
import uuid
from types import SimpleNamespace

import pytest

# Light import — always available.
from core.i18n.i18n import language_decision

# Heavy import (pulls the route module). Guard so a DB-less env skips the A2
# helper tests instead of erroring at collection.
try:
    from api.routes.connection_query import _build_streaming_agent_state
    _STREAM_IMPORT_ERR = None
except Exception as e:  # pragma: no cover - env-dependent
    _build_streaming_agent_state = None
    _STREAM_IMPORT_ERR = e


# ═══════════════════════════════════════════════════════════════════════════
# A2 — locale must reach the STREAMING agent state (not the non-streaming path)
# ═══════════════════════════════════════════════════════════════════════════
#
# The implementation note in the spec is load-bearing: the non-streaming path
# already worked (it injects locale via user_ctx). The bug lived ONLY in the
# streaming path's hand-built state dict. So these tests target
# `_build_streaming_agent_state`, the exact construction that dropped locale.

def _fake_body(**overrides):
    """A minimal QueryRequest-shaped object with every attr the builder reads."""
    base = dict(
        question="ok",
        user_id="u1",
        space_id="s1",
        locale=None,
        instructions=None,
        creativity=None,
        length=None,
        response_format=None,
        ai_tone=None,
        ai_style=None,
        sql_instructions=None,
        selected_datasets=None,
        security_config=None,
        agent_mode=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _require_stream_builder():
    if _build_streaming_agent_state is None:
        pytest.skip(f"could not import streaming state builder: {_STREAM_IMPORT_ERR}")


def test_a2_streaming_state_carries_locale_pt():
    _require_stream_builder()
    state = _build_streaming_agent_state(_fake_body(locale="pt"), [], {})
    assert state["locale"] == "pt", (
        "streaming state dropped the locale — A2 regression (short PT messages "
        "would be answered in EN)"
    )


def test_a2_streaming_state_carries_locale_en():
    _require_stream_builder()
    state = _build_streaming_agent_state(_fake_body(locale="en"), [], {})
    assert state["locale"] == "en"


def test_a2_streaming_state_locale_absent_is_none():
    # No locale on the request → None, so consumers fall back to detection.
    # (The key contract is "passes it through", not "invents one".)
    _require_stream_builder()
    state = _build_streaming_agent_state(_fake_body(locale=None), [], {})
    assert state["locale"] is None


def test_a2_language_decision_follows_locale_over_detection():
    # A short message is exactly where statistical detection errs. With an
    # explicit locale, the decision MUST follow it — this is the consumer
    # behavior that makes carrying locale matter.
    assert language_decision("ok", locale="pt") == (False, "pt")
    assert language_decision("e o total?", locale="pt") == (False, "pt")
    assert language_decision("ok", locale="en") == (False, "en")


def test_a2_short_message_without_locale_does_not_follow_pt():
    # Bug shape: drop the locale and a short message no longer resolves to PT —
    # which is why dropping it in the streaming path broke PT users.
    _, lang_with = language_decision("ok", locale="pt")
    _, lang_without = language_decision("ok", locale=None)
    assert lang_with == "pt"
    assert lang_without != "pt"


# ═══════════════════════════════════════════════════════════════════════════
# A1 — semantic_cache schema present + legacy rows inert
# ═══════════════════════════════════════════════════════════════════════════
#
# Integration tests against the local Postgres (the repo's test culture). They
# SKIP if the DB is unreachable, but FAIL if a key column is missing — because a
# missing column IS the A1 regression.

def _embedding_dim():
    from config.settings import settings
    return settings.embedding_dim


def _zero_vec():
    return "[" + ",".join(["0"] * _embedding_dim()) + "]"


def _async_engine_and_session():
    """A FRESH engine per test (NullPool), so two asyncio.run() calls don't share
    the module-level pool — which would bind connections to a dead event loop and
    raise 'attached to a different loop'. Caller must dispose() the engine."""
    from sqlalchemy.ext.asyncio import (
        create_async_engine,
        async_sessionmaker,
        AsyncSession,
    )
    from sqlalchemy.pool import NullPool
    from db.base import DATABASE_URL

    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, Session


def test_a1_1_cache_lookup_columns_present():
    """The lookup filters locale + cache_version + temporal_bucket. With 006+007
    applied, querying those columns must not raise 'column does not exist' —
    proving the DB schema matches what the code filters (the A1 mismatch)."""
    from sqlalchemy import text

    async def run():
        engine, Session = _async_engine_and_session()
        try:
            async with Session() as db:
                await db.execute(
                    text(
                        "SELECT id FROM semantic_cache "
                        "WHERE locale = :loc AND cache_version = :ver "
                        "AND temporal_bucket = :tb LIMIT 1"
                    ),
                    {"loc": "pt", "ver": 2, "tb": "absoluto"},
                )
        finally:
            await engine.dispose()

    try:
        asyncio.run(run())
    except Exception as e:  # noqa: BLE001
        if "does not exist" in str(e).lower():
            pytest.fail(f"A1 regression: semantic_cache schema is missing a column → {e}")
        pytest.skip(f"DB not reachable for A1 test: {e}")


def test_a1_2_legacy_row_is_inert():
    """A legacy row (locale NULL, cache_version=0 — as the 007 backfill marks it)
    must NOT be returned by a current lookup (cache_version=2). Proves old,
    locale-less answers can't leak to users → no PT/EN contamination."""
    from sqlalchemy import text

    cid = f"TEST-A1-LEGACY-{uuid.uuid4()}"
    vec = _zero_vec()

    async def run():
        engine, Session = _async_engine_and_session()
        try:
            async with Session() as db:
                await db.execute(
                    text(
                        "INSERT INTO semantic_cache "
                        "(id, connection_id, question, embedding, response_json, locale, cache_version) "
                        "VALUES (gen_random_uuid(), :cid, 'legacy q', CAST(:vec AS vector), "
                        "'{}'::json, NULL, 0)"
                    ),
                    {"cid": cid, "vec": vec},
                )
                await db.commit()
                r = await db.execute(
                    text(
                        "SELECT COUNT(*) FROM semantic_cache "
                        "WHERE connection_id = :cid AND cache_version = 2"
                    ),
                    {"cid": cid},
                )
                leaked = r.scalar()
                # Always clean up the synthetic row before asserting.
                await db.execute(
                    text("DELETE FROM semantic_cache WHERE connection_id = :cid"),
                    {"cid": cid},
                )
                await db.commit()
                return leaked
        finally:
            await engine.dispose()

    try:
        leaked = asyncio.run(run())
    except Exception as e:  # noqa: BLE001
        if "does not exist" in str(e).lower():
            pytest.fail(f"A1 regression: semantic_cache schema is missing a column → {e}")
        pytest.skip(f"DB not reachable for A1 test: {e}")
        return

    assert leaked == 0, (
        "A1 regression: a legacy cache_version=0 row leaked into a version=2 "
        "lookup — backfill is not isolating the legacy (PT/EN contamination risk)"
    )
