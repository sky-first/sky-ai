"""
Unit tests for item 35 — Dataset coverage report.

Tests:
  build_coverage_report:
    - returns empty list for empty space_id
    - returns empty list on DB error
    - aggregates times_queried from scan_insight tables_queried
    - sets last_queried_at from most recent insight per table
    - counts combos_explored from depth_tracker rows
    - picks latest_row_count from most recent snapshot
    - tables with last_queried sort before never-queried
    - queried tables sorted by recency descending
    - depth_remaining_pct is 100 for pristine table (0 combos)
    - depth_remaining_pct decreases as combos increase
"""
from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


SPACE_ID = "00000000-0000-0000-0000-000000000001"

_DT1 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
_DT2 = datetime(2024, 6, 2, 12, 0, 0, tzinfo=timezone.utc)   # newer


def _mock_db_with_side_effects(insight_rows, depth_rows, snapshot_rows):
    """Build a DB mock that returns different results for sequential execute() calls."""
    db = AsyncMock()

    call_results = []
    for rows in [insight_rows, depth_rows, snapshot_rows]:
        r = MagicMock()
        r.fetchall.return_value = rows
        call_results.append(r)

    db.execute.side_effect = call_results
    return db


# ─── build_coverage_report ────────────────────────────────────────────────────

class TestBuildCoverageReport:
    @pytest.mark.asyncio
    async def test_empty_space_id_returns_empty(self):
        from core.agents.coverage_report import build_coverage_report
        db = AsyncMock()
        result = await build_coverage_report(db, "")
        assert result == []
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_error_returns_empty(self):
        from core.agents.coverage_report import build_coverage_report
        db = AsyncMock()
        db.execute.side_effect = Exception("pgvector error")
        result = await build_coverage_report(db, SPACE_ID)
        assert result == []

    @pytest.mark.asyncio
    async def test_aggregates_times_queried(self):
        from core.agents.coverage_report import build_coverage_report

        insight_rows = [
            ({"type": "scan_insight", "tables_queried": ["orders", "users"]}, _DT2),
            ({"type": "scan_insight", "tables_queried": ["orders"]}, _DT1),
        ]
        db = _mock_db_with_side_effects(insight_rows, [], [])
        result = await build_coverage_report(db, SPACE_ID)

        by_name = {r["logical_name"]: r for r in result}
        assert by_name["orders"]["times_queried"] == 2
        assert by_name["users"]["times_queried"] == 1

    @pytest.mark.asyncio
    async def test_last_queried_at_is_most_recent(self):
        from core.agents.coverage_report import build_coverage_report

        insight_rows = [
            ({"type": "scan_insight", "tables_queried": ["orders"]}, _DT2),
            ({"type": "scan_insight", "tables_queried": ["orders"]}, _DT1),
        ]
        db = _mock_db_with_side_effects(insight_rows, [], [])
        result = await build_coverage_report(db, SPACE_ID)

        orders = next(r for r in result if r["logical_name"] == "orders")
        # DT2 is more recent; rows are already sorted DESC so first row wins
        assert orders["last_queried_at"] == _DT2.isoformat()

    @pytest.mark.asyncio
    async def test_counts_combos_explored(self):
        from core.agents.coverage_report import build_coverage_report

        depth_rows = [
            ("orders", json.dumps([["region", "revenue"], ["product", "revenue"]])),
            ("orders", json.dumps([["region", "revenue"]])),  # dupe — deduped
        ]
        db = _mock_db_with_side_effects([], depth_rows, [])
        result = await build_coverage_report(db, SPACE_ID)

        orders = next(r for r in result if r["logical_name"] == "orders")
        assert orders["combos_explored"] == 2  # deduplicated

    @pytest.mark.asyncio
    async def test_picks_latest_row_count(self):
        from core.agents.coverage_report import build_coverage_report

        snapshot_rows = [
            ("orders", 15000, _DT2),
            ("orders", 12000, _DT1),
        ]
        db = _mock_db_with_side_effects([], [], snapshot_rows)
        result = await build_coverage_report(db, SPACE_ID)

        orders = next(r for r in result if r["logical_name"] == "orders")
        assert orders["latest_row_count"] == 15000

    @pytest.mark.asyncio
    async def test_queried_tables_sort_before_unqueried(self):
        from core.agents.coverage_report import build_coverage_report

        insight_rows = [
            ({"type": "scan_insight", "tables_queried": ["orders"]}, _DT1),
        ]
        depth_rows = [
            ("users", json.dumps([["country", "count"]])),
        ]
        db = _mock_db_with_side_effects(insight_rows, depth_rows, [])
        result = await build_coverage_report(db, SPACE_ID)

        names = [r["logical_name"] for r in result]
        # "orders" was queried, "users" was not
        assert names.index("orders") < names.index("users")

    @pytest.mark.asyncio
    async def test_pristine_table_has_100_pct(self):
        from core.agents.coverage_report import build_coverage_report

        depth_rows = [("orders", json.dumps([]))]  # 0 combos
        db = _mock_db_with_side_effects([], depth_rows, [])
        result = await build_coverage_report(db, SPACE_ID)

        orders = next(r for r in result if r["logical_name"] == "orders")
        assert orders["depth_remaining_pct"] == 100

    @pytest.mark.asyncio
    async def test_depth_pct_decreases_with_combos(self):
        from core.agents.coverage_report import build_coverage_report

        # 10 combos out of assumed 20 → 50%
        combos = [[f"dim{i}", f"metric{i}"] for i in range(10)]
        depth_rows = [("orders", json.dumps(combos))]
        db = _mock_db_with_side_effects([], depth_rows, [])
        result = await build_coverage_report(db, SPACE_ID)

        orders = next(r for r in result if r["logical_name"] == "orders")
        assert orders["depth_remaining_pct"] == 50

    @pytest.mark.asyncio
    async def test_no_data_returns_empty_list(self):
        from core.agents.coverage_report import build_coverage_report

        db = _mock_db_with_side_effects([], [], [])
        result = await build_coverage_report(db, SPACE_ID)
        assert result == []

    @pytest.mark.asyncio
    async def test_multiple_tables_all_present(self):
        from core.agents.coverage_report import build_coverage_report

        insight_rows = [
            ({"type": "scan_insight", "tables_queried": ["orders", "payments"]}, _DT1),
        ]
        snapshot_rows = [
            ("orders", 5000, _DT1),
            ("payments", 1000, _DT1),
        ]
        db = _mock_db_with_side_effects(insight_rows, [], snapshot_rows)
        result = await build_coverage_report(db, SPACE_ID)

        names = {r["logical_name"] for r in result}
        assert "orders" in names
        assert "payments" in names
