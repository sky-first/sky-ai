"""Unit tests for item 19 — OKR ingest hook that refreshes dataset embeddings.

Tests cover:
  - _is_okr_relevant: which entity types trigger a refresh
  - refresh_dataset_embeddings_for_space: loads connections + calls run_dataset_description_embeddings
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

from api.routes.knowledge_graph import _is_okr_relevant, _OKR_ENTITY_TYPES


# ─── _is_okr_relevant ─────────────────────────────────────────────────────────


class TestIsOkrRelevant:
    def test_explicit_okr_types_are_relevant(self):
        for t in ("okr", "pillar", "kpi", "metric", "strategy_okr", "strategic_objective"):
            assert _is_okr_relevant(t), f"{t!r} should be OKR-relevant"

    def test_strategy_prefix_is_relevant(self):
        assert _is_okr_relevant("strategy_anything")
        assert _is_okr_relevant("strategy_goal")
        assert _is_okr_relevant("strategy_kpi")

    def test_strategic_prefix_is_relevant(self):
        assert _is_okr_relevant("strategic_priority")
        assert _is_okr_relevant("strategic_objective")

    def test_enterprise_graph_node_is_not_relevant(self):
        assert not _is_okr_relevant("enterprise_graph_node")

    def test_signal_event_is_not_relevant(self):
        assert not _is_okr_relevant("signal_event")

    def test_dashboard_is_not_relevant(self):
        assert not _is_okr_relevant("dashboard")

    def test_generic_business_context_is_not_relevant(self):
        # "business_context" alone is not in _OKR_ENTITY_TYPES and doesn't match prefixes
        assert not _is_okr_relevant("business_context")


# ─── refresh_dataset_embeddings_for_space ─────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_calls_run_for_each_connection():
    """refresh_dataset_embeddings_for_space should call run_dataset_description_embeddings
    once per connection returned by space_connections."""
    space_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    conn_ids = [
        "11111111-0000-0000-0000-000000000001",
        "22222222-0000-0000-0000-000000000002",
    ]

    # Mock the DB rows returned by the space_connections query
    fake_rows = [(cid,) for cid in conn_ids]
    mock_result = MagicMock()
    mock_result.fetchall.return_value = fake_rows

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_sessionmaker = MagicMock(return_value=mock_session)

    with (
        patch("db.session.AsyncSessionLocal", mock_sessionmaker),
        patch(
            "core.ingestion.service.run_dataset_description_embeddings",
            new_callable=AsyncMock,
            return_value=3,
        ) as mock_run,
        patch("core.ingestion.service.get_embedding_provider", return_value=MagicMock()),
    ):
        from core.ingestion.service import refresh_dataset_embeddings_for_space
        total = await refresh_dataset_embeddings_for_space(space_id)

    # Should have been called once per connection
    assert mock_run.call_count == len(conn_ids)
    assert total == 3 * len(conn_ids)


@pytest.mark.asyncio
async def test_refresh_returns_zero_when_no_connections():
    space_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    mock_result = MagicMock()
    mock_result.fetchall.return_value = []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_sessionmaker = MagicMock(return_value=mock_session)

    with (
        patch("db.session.AsyncSessionLocal", mock_sessionmaker),
        patch(
            "core.ingestion.service.run_dataset_description_embeddings",
            new_callable=AsyncMock,
        ) as mock_run,
        patch("core.ingestion.service.get_embedding_provider", return_value=MagicMock()),
    ):
        from core.ingestion.service import refresh_dataset_embeddings_for_space
        total = await refresh_dataset_embeddings_for_space(space_id)

    assert total == 0
    mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_does_not_raise_on_db_error():
    """A DB failure should be silently swallowed — never crash the caller."""
    space_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=Exception("DB down"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_sessionmaker = MagicMock(return_value=mock_session)

    with (
        patch("db.session.AsyncSessionLocal", mock_sessionmaker),
        patch("core.ingestion.service.get_embedding_provider", return_value=MagicMock()),
    ):
        from core.ingestion.service import refresh_dataset_embeddings_for_space
        total = await refresh_dataset_embeddings_for_space(space_id)  # must not raise

    assert total == 0
