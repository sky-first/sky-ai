"""Unit tests for Volatility Tracker (roadmap items 20-22).

Tests cover:
  - _volatility_score: delta calculation from row_count snapshots
  - save_row_count_snapshots: reads connection_metadata, saves EmbeddingRecord per table
  - load_row_count_snapshots_for_scorer: reads last 2 per table, newest first
  - Integration: volatile tables rank higher than static ones
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from core.agents.dataset_priority_scorer import DatasetPriorityScorer

# ─── Stubs ────────────────────────────────────────────────────────────────────


@dataclass
class _Table:
    logical_name: str
    physical_name: str = ""
    description: str = ""
    columns: List[Dict[str, Any]] = field(default_factory=list)
    data_connection_id: Optional[str] = None


# ─── _volatility_score (items 21-22) ──────────────────────────────────────────


class TestVolatilityScore:
    def _scorer(self, snapshots: Dict[str, List[int]]) -> DatasetPriorityScorer:
        return DatasetPriorityScorer(row_count_snapshots=snapshots)

    def test_no_snapshots_returns_neutral(self):
        t = _Table("events")
        assert self._scorer({})._volatility_score(t) == 0.5

    def test_one_snapshot_returns_neutral(self):
        t = _Table("events")
        assert self._scorer({"events": [1000]})._volatility_score(t) == 0.5

    def test_unknown_table_returns_neutral(self):
        t = _Table("events")
        assert self._scorer({"other": [100, 90]})._volatility_score(t) == 0.5

    def test_zero_delta_returns_zero(self):
        t = _Table("users")
        score = self._scorer({"users": [1000, 1000]})._volatility_score(t)
        assert score == 0.0

    def test_10_pct_growth_returns_0_1(self):
        t = _Table("events")
        score = self._scorer({"events": [1100, 1000]})._volatility_score(t)
        assert abs(score - 0.1) < 1e-9

    def test_50_pct_growth_returns_0_5(self):
        t = _Table("events")
        score = self._scorer({"events": [1500, 1000]})._volatility_score(t)
        assert abs(score - 0.5) < 1e-9

    def test_100_pct_growth_returns_1_0(self):
        t = _Table("events")
        score = self._scorer({"events": [2000, 1000]})._volatility_score(t)
        assert score == 1.0

    def test_over_100_pct_capped_at_1_0(self):
        t = _Table("events")
        score = self._scorer({"events": [5000, 1000]})._volatility_score(t)
        assert score == 1.0

    def test_decrease_also_counts(self):
        t = _Table("events")
        score = self._scorer({"events": [900, 1000]})._volatility_score(t)
        assert abs(score - 0.1) < 1e-9

    def test_was_empty_now_has_rows_returns_1_0(self):
        t = _Table("events")
        score = self._scorer({"events": [500, 0]})._volatility_score(t)
        assert score == 1.0

    def test_was_empty_still_empty_returns_neutral(self):
        t = _Table("events")
        score = self._scorer({"events": [0, 0]})._volatility_score(t)
        assert score == 0.5


# ─── Integration: volatile > static in ranking (item 22) ─────────────────────


class TestVolatileTableRanksHigher:
    def test_event_table_beats_static_table(self):
        # Two tables with same staleness and depth.
        # events: 100% row_count growth → volatility=1.0
        # users: 0% change → volatility=0.0
        events = _Table("events")
        users = _Table("users")

        scorer = DatasetPriorityScorer(
            top_k=1,
            row_count_snapshots={
                "events": [2000, 1000],  # 100% growth
                "users": [500, 500],  # no change
            },
        )
        top = scorer.rank([events, users], insights=[])
        assert top[0].logical_name == "events"

    def test_moderate_volatility_beats_static(self):
        events = _Table("events")
        users = _Table("users")

        scorer = DatasetPriorityScorer(
            top_k=1,
            row_count_snapshots={
                "events": [1200, 1000],  # 20% growth
                "users": [500, 500],  # no change
            },
        )
        top = scorer.rank([events, users], insights=[])
        assert top[0].logical_name == "events"


# ─── save_row_count_snapshots (item 20) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_save_row_count_snapshots_creates_one_record_per_table():
    tables = [
        _Table("crm.orders", data_connection_id="conn-1"),
        _Table("crm.users", data_connection_id="conn-1"),
    ]
    space_id = "aaaaaaaa-0000-0000-0000-000000000001"

    # connection_metadata returns two tables with positive row_counts
    catalog_json = [
        {"name": "orders", "schema": "crm", "row_count": 1500, "columns": []},
        {"name": "users", "schema": "crm", "row_count": 800, "columns": []},
    ]

    mock_scalar = MagicMock()
    mock_scalar.scalar_one_or_none = MagicMock(return_value=catalog_json)
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_scalar)
    mock_db.flush = AsyncMock()

    added_records = []
    mock_db.add = lambda r: added_records.append(r)

    from core.agents.dataset_priority_scorer import save_row_count_snapshots

    count = await save_row_count_snapshots(mock_db, space_id, tables)

    assert count == 2
    assert len(added_records) == 2
    names = {r.extra_metadata["logical_name"] for r in added_records}
    assert names == {"crm.orders", "crm.users"}


@pytest.mark.asyncio
async def test_save_row_count_snapshots_skips_negative_row_count():
    tables = [_Table("crm.events", data_connection_id="conn-1")]
    space_id = "aaaaaaaa-0000-0000-0000-000000000001"

    catalog_json = [{"name": "events", "schema": "crm", "row_count": -1, "columns": []}]

    mock_scalar = MagicMock()
    mock_scalar.scalar_one_or_none = MagicMock(return_value=catalog_json)
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_scalar)
    mock_db.flush = AsyncMock()

    added_records = []
    mock_db.add = lambda r: added_records.append(r)

    from core.agents.dataset_priority_scorer import save_row_count_snapshots

    count = await save_row_count_snapshots(mock_db, space_id, tables)

    assert count == 0
    assert len(added_records) == 0


@pytest.mark.asyncio
async def test_save_row_count_snapshots_skips_tables_without_connection_id():
    tables = [_Table("orphan", data_connection_id=None)]
    space_id = "aaaaaaaa-0000-0000-0000-000000000001"

    mock_db = AsyncMock()

    from core.agents.dataset_priority_scorer import save_row_count_snapshots

    count = await save_row_count_snapshots(mock_db, space_id, tables)

    assert count == 0
    mock_db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_save_row_count_snapshots_returns_zero_on_empty_tables():
    mock_db = AsyncMock()
    from core.agents.dataset_priority_scorer import save_row_count_snapshots

    count = await save_row_count_snapshots(mock_db, "any-space-id", [])
    assert count == 0


# ─── load_row_count_snapshots_for_scorer (item 20) ────────────────────────────


@pytest.mark.asyncio
async def test_load_row_count_snapshots_returns_newest_first():
    space_id = "aaaaaaaa-0000-0000-0000-000000000001"

    from datetime import datetime, timezone

    now = datetime.now(tz=timezone.utc)

    # DB returns rows ORDER BY created_at DESC (newest first)
    fake_rows = [
        ("crm.orders", 1500, now),
        ("crm.orders", 1000, now),  # older snapshot
        ("crm.users", 800, now),
    ]

    mock_result = MagicMock()
    mock_result.fetchall = MagicMock(return_value=fake_rows)
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    from core.agents.dataset_priority_scorer import load_row_count_snapshots_for_scorer

    snapshots = await load_row_count_snapshots_for_scorer(mock_db, space_id)

    assert snapshots["crm.orders"] == [1500, 1000]
    assert snapshots["crm.users"] == [800]


@pytest.mark.asyncio
async def test_load_row_count_snapshots_caps_at_2():
    space_id = "aaaaaaaa-0000-0000-0000-000000000001"

    from datetime import datetime, timezone

    now = datetime.now(tz=timezone.utc)

    # 3 snapshots for same table — should only keep first 2
    fake_rows = [
        ("events", 3000, now),
        ("events", 2000, now),
        ("events", 1000, now),
    ]

    mock_result = MagicMock()
    mock_result.fetchall = MagicMock(return_value=fake_rows)
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    from core.agents.dataset_priority_scorer import load_row_count_snapshots_for_scorer

    snapshots = await load_row_count_snapshots_for_scorer(mock_db, space_id)

    assert snapshots["events"] == [3000, 2000]  # 3rd dropped


@pytest.mark.asyncio
async def test_load_row_count_snapshots_returns_empty_on_db_error():
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=Exception("DB down"))

    from core.agents.dataset_priority_scorer import load_row_count_snapshots_for_scorer

    snapshots = await load_row_count_snapshots_for_scorer(mock_db, "any-space")

    assert snapshots == {}
