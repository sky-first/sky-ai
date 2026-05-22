"""
Unit tests for item 33 — Semantic deduplication of scan insights.

Tests:
  - is_semantic_duplicate returns False when no prior insights exist
  - is_semantic_duplicate returns True above threshold
  - is_semantic_duplicate returns False below threshold
  - is_semantic_duplicate returns False for zero/empty vectors (safe fallback)
  - is_semantic_duplicate returns False on pgvector error (safe fallback)
  - save_scan_insight stores real embedding when provided
  - save_scan_insight falls back to zero vector when embedding=None
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_db(fetchone_return=None):
    """Build a minimal async DB mock that replays a fetchone result."""
    db = AsyncMock()
    result = MagicMock()
    result.fetchone.return_value = fetchone_return
    db.execute.return_value = result
    db.rollback = AsyncMock()
    return db


def _make_db_add():
    """Build a minimal async DB mock for add/flush (save_scan_insight)."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.rollback = AsyncMock()
    return db


SPACE_ID = "00000000-0000-0000-0000-000000000001"
EMBED_DIM = 1024
VEC = [0.5] * EMBED_DIM


# ─── is_semantic_duplicate ────────────────────────────────────────────────────


class TestIsSemanticDuplicate:
    @pytest.mark.asyncio
    async def test_no_prior_insights_returns_false(self):
        from core.agents.scan_briefing import is_semantic_duplicate

        db = _make_db(fetchone_return=None)
        result = await is_semantic_duplicate(db, SPACE_ID, VEC, threshold=0.85)
        assert result is False

    @pytest.mark.asyncio
    async def test_high_similarity_returns_true(self):
        from core.agents.scan_briefing import is_semantic_duplicate

        db = _make_db(fetchone_return=(0.95,))  # similarity = 0.95 > 0.85
        result = await is_semantic_duplicate(db, SPACE_ID, VEC, threshold=0.85)
        assert result is True

    @pytest.mark.asyncio
    async def test_exact_threshold_is_duplicate(self):
        from core.agents.scan_briefing import is_semantic_duplicate

        db = _make_db(fetchone_return=(0.85,))
        result = await is_semantic_duplicate(db, SPACE_ID, VEC, threshold=0.85)
        assert result is True

    @pytest.mark.asyncio
    async def test_low_similarity_returns_false(self):
        from core.agents.scan_briefing import is_semantic_duplicate

        db = _make_db(fetchone_return=(0.40,))  # similarity = 0.40 < 0.85
        result = await is_semantic_duplicate(db, SPACE_ID, VEC, threshold=0.85)
        assert result is False

    @pytest.mark.asyncio
    async def test_zero_vector_short_circuits_false(self):
        from core.agents.scan_briefing import is_semantic_duplicate

        db = _make_db()
        result = await is_semantic_duplicate(
            db, SPACE_ID, [0.0] * EMBED_DIM, threshold=0.85
        )
        assert result is False
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_vector_short_circuits_false(self):
        from core.agents.scan_briefing import is_semantic_duplicate

        db = _make_db()
        result = await is_semantic_duplicate(db, SPACE_ID, [], threshold=0.85)
        assert result is False
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_none_similarity_value_returns_false(self):
        from core.agents.scan_briefing import is_semantic_duplicate

        db = _make_db(fetchone_return=(None,))
        result = await is_semantic_duplicate(db, SPACE_ID, VEC, threshold=0.85)
        assert result is False

    @pytest.mark.asyncio
    async def test_pgvector_error_returns_false(self):
        """Any DB error must never crash the caller — return False (safe fallback)."""
        from core.agents.scan_briefing import is_semantic_duplicate

        db = AsyncMock()
        db.execute.side_effect = Exception("pgvector not available")
        db.rollback = AsyncMock()

        result = await is_semantic_duplicate(db, SPACE_ID, VEC, threshold=0.85)
        assert result is False

    @pytest.mark.asyncio
    async def test_custom_threshold_respected(self):
        from core.agents.scan_briefing import is_semantic_duplicate

        db = _make_db(fetchone_return=(0.70,))
        # similarity 0.70 >= 0.65 → duplicate
        assert await is_semantic_duplicate(db, SPACE_ID, VEC, threshold=0.65) is True
        # but with default threshold 0.85 → not duplicate
        db2 = _make_db(fetchone_return=(0.70,))
        assert await is_semantic_duplicate(db2, SPACE_ID, VEC, threshold=0.85) is False

    @pytest.mark.asyncio
    async def test_sql_uses_space_id(self):
        """Confirm the pgvector query filters by space_id."""
        from core.agents.scan_briefing import is_semantic_duplicate

        db = _make_db(fetchone_return=(0.50,))
        await is_semantic_duplicate(db, SPACE_ID, VEC, threshold=0.85)

        assert db.execute.called
        call_args = db.execute.call_args
        # Second positional arg is the params dict
        params = call_args[0][1]
        assert params["sid"] == SPACE_ID


# ─── save_scan_insight with real embedding ────────────────────────────────────


class TestSaveScanInsightEmbedding:
    @pytest.mark.asyncio
    async def test_stores_real_embedding_when_provided(self):
        from core.agents.scan_briefing import save_scan_insight

        real_vec = [0.1] * EMBED_DIM
        db = _make_db_add()

        with patch("db.models.EmbeddingRecord") as MockRecord:
            MockRecord.return_value = MagicMock()
            await save_scan_insight(
                db=db,
                space_id=SPACE_ID,
                user_id=None,
                text_content="Revenue grew 12% MoM driven by enterprise segment.",
                title="Revenue insight",
                tables_queried=["orders"],
                embedding=real_vec,
            )

        kwargs = MockRecord.call_args[1]
        assert kwargs["embedding"] == real_vec

    @pytest.mark.asyncio
    async def test_falls_back_to_zero_when_embedding_none(self):
        from core.agents.scan_briefing import save_scan_insight

        db = _make_db_add()
        with patch("db.models.EmbeddingRecord") as MockRecord:
            MockRecord.return_value = MagicMock()
            await save_scan_insight(
                db=db,
                space_id=SPACE_ID,
                user_id=None,
                text_content="Churn rate spiked 3% in Q2.",
                title="Churn insight",
                embedding=None,
            )

        kwargs = MockRecord.call_args[1]
        assert kwargs["embedding"] == [0.0] * 1024

    @pytest.mark.asyncio
    async def test_metadata_includes_tables_queried(self):
        from core.agents.scan_briefing import save_scan_insight

        db = _make_db_add()
        with patch("db.models.EmbeddingRecord") as MockRecord:
            MockRecord.return_value = MagicMock()
            await save_scan_insight(
                db=db,
                space_id=SPACE_ID,
                user_id=None,
                text_content="Active users declined.",
                title="DAU insight",
                tables_queried=["users", "events"],
                embedding=VEC,
            )

        kwargs = MockRecord.call_args[1]
        assert kwargs["extra_metadata"]["tables_queried"] == ["users", "events"]
        assert kwargs["extra_metadata"]["type"] == "scan_insight"
