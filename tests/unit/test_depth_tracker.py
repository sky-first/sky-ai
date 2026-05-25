"""
Unit tests for item 34 — Depth Tracker.

Tests:
  extract_explored_combos:
    - empty SQL returns empty set
    - SQL without GROUP BY returns empty set
    - SQL with GROUP BY and aggregates returns correct combos
    - JSON string pipeline also handled (edge case: no GROUP BY → empty)
    - handles table-qualified column names
    - handles DISTINCT inside aggregate
    - multiple aggregates × multiple dimensions
    - excludes dim == metric combos (no self-pairs)

  depth_remaining_score:
    - pristine table (no combos) → 1.0
    - fully explored → 0.0
    - partially explored → between 0 and 1
    - no columns → 0.5 fallback

  record_depth_combos:
    - persists combos as JSON in EmbeddingRecord
    - no-op when combos is empty
    - no-op when space_id missing

  load_depth_combos_for_scorer:
    - aggregates combos across multiple rows per table
    - returns empty dict on DB error
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

SPACE_ID = "00000000-0000-0000-0000-000000000001"


# ─── extract_explored_combos ──────────────────────────────────────────────────


class TestExtractExploredCombos:
    def test_empty_sql_returns_empty(self):
        from core.agents.depth_tracker import extract_explored_combos

        assert extract_explored_combos("") == set()

    def test_no_group_by_returns_empty(self):
        from core.agents.depth_tracker import extract_explored_combos

        sql = "SELECT SUM(amount) FROM orders"
        assert extract_explored_combos(sql) == set()

    def test_group_by_with_sum(self):
        from core.agents.depth_tracker import extract_explored_combos

        sql = "SELECT status, SUM(amount) FROM orders GROUP BY status"
        combos = extract_explored_combos(sql)
        assert ("status", "amount") in combos

    def test_multiple_dims_and_metrics(self):
        from core.agents.depth_tracker import extract_explored_combos

        sql = (
            "SELECT region, product, SUM(revenue), COUNT(order_id) "
            "FROM sales GROUP BY region, product"
        )
        combos = extract_explored_combos(sql)
        assert ("region", "revenue") in combos
        assert ("region", "order_id") in combos
        assert ("product", "revenue") in combos
        assert ("product", "order_id") in combos

    def test_no_self_pairs(self):
        from core.agents.depth_tracker import extract_explored_combos

        # If GROUP BY col is also inside agg, it should not produce (col, col)
        sql = "SELECT status, COUNT(status) FROM orders GROUP BY status"
        combos = extract_explored_combos(sql)
        assert ("status", "status") not in combos

    def test_table_qualified_columns_stripped(self):
        from core.agents.depth_tracker import extract_explored_combos

        sql = "SELECT o.region, SUM(o.amount) FROM orders o GROUP BY o.region"
        combos = extract_explored_combos(sql)
        assert ("region", "amount") in combos

    def test_distinct_inside_aggregate(self):
        from core.agents.depth_tracker import extract_explored_combos

        sql = "SELECT category, COUNT(DISTINCT user_id) FROM events GROUP BY category"
        combos = extract_explored_combos(sql)
        assert ("category", "user_id") in combos

    def test_order_by_does_not_bleed_into_group_by(self):
        from core.agents.depth_tracker import extract_explored_combos

        sql = (
            "SELECT region, SUM(revenue) FROM sales " "GROUP BY region ORDER BY region"
        )
        combos = extract_explored_combos(sql)
        assert ("region", "revenue") in combos
        assert len(combos) == 1  # only 1 dim × 1 metric

    def test_case_insensitive(self):
        from core.agents.depth_tracker import extract_explored_combos

        sql = "select status, sum(amount) from orders group by status"
        combos = extract_explored_combos(sql)
        assert ("status", "amount") in combos


# ─── depth_remaining_score ────────────────────────────────────────────────────


class _Col:
    def __init__(self, name, data_type="text"):
        self.name = name
        self.data_type = data_type


class TestDepthRemainingScore:
    def test_no_columns_returns_fallback(self):
        from core.agents.depth_tracker import depth_remaining_score

        score = depth_remaining_score("t", [], set())
        assert score == 0.5

    def test_pristine_table_returns_1(self):
        from core.agents.depth_tracker import depth_remaining_score

        cols = [_Col("region"), _Col("amount", "numeric")]
        score = depth_remaining_score("t", cols, set())
        assert score == 1.0

    def test_fully_explored_returns_0(self):
        from core.agents.depth_tracker import depth_remaining_score

        cols = [_Col("region"), _Col("amount", "numeric")]
        # 1 dim × 1 metric = 1 possible combo
        score = depth_remaining_score("t", cols, {("region", "amount")})
        assert score == 0.0

    def test_partial_exploration(self):
        from core.agents.depth_tracker import depth_remaining_score

        cols = [
            _Col("region"),
            _Col("product"),
            _Col("revenue", "numeric"),
            _Col("cost", "numeric"),
        ]
        # 2 dims × 2 metrics = 4 possible; 1 explored
        score = depth_remaining_score("t", cols, {("region", "revenue")})
        assert 0.0 < score < 1.0

    def test_score_decreases_as_more_explored(self):
        from core.agents.depth_tracker import depth_remaining_score

        cols = [_Col("region"), _Col("product"), _Col("revenue", "numeric")]
        s1 = depth_remaining_score("t", cols, {("region", "revenue")})
        s2 = depth_remaining_score(
            "t", cols, {("region", "revenue"), ("product", "revenue")}
        )
        assert s2 < s1


# ─── record_depth_combos ──────────────────────────────────────────────────────


class TestRecordDepthCombos:
    @pytest.mark.asyncio
    async def test_persists_combos(self):
        from core.agents.depth_tracker import record_depth_combos

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        combos = {("region", "revenue"), ("region", "cost")}
        with patch("db.models.EmbeddingRecord") as MockRecord:
            MockRecord.return_value = MagicMock()
            await record_depth_combos(db, SPACE_ID, "orders", combos)

        assert db.add.called
        kwargs = MockRecord.call_args[1]
        stored = json.loads(kwargs["text"])
        assert len(stored) == 2
        assert kwargs["extra_metadata"]["kind"] == "depth_tracker"
        assert kwargs["extra_metadata"]["logical_name"] == "orders"

    @pytest.mark.asyncio
    async def test_noop_when_empty_combos(self):
        from core.agents.depth_tracker import record_depth_combos

        db = AsyncMock()
        db.add = MagicMock()
        await record_depth_combos(db, SPACE_ID, "orders", set())
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_no_space_id(self):
        from core.agents.depth_tracker import record_depth_combos

        db = AsyncMock()
        db.add = MagicMock()
        await record_depth_combos(db, "", "orders", {("a", "b")})
        db.add.assert_not_called()


# ─── load_depth_combos_for_scorer ────────────────────────────────────────────


class TestLoadDepthCombosForScorer:
    @pytest.mark.asyncio
    async def test_aggregates_combos_per_table(self):
        from core.agents.depth_tracker import load_depth_combos_for_scorer

        rows = [
            ("orders", json.dumps([["region", "revenue"]])),
            ("orders", json.dumps([["product", "revenue"], ["region", "revenue"]])),
            ("users", json.dumps([["country", "count"]])),
        ]
        db = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = rows
        db.execute.return_value = result

        out = await load_depth_combos_for_scorer(db, SPACE_ID)

        assert "orders" in out
        assert ("region", "revenue") in out["orders"]
        assert ("product", "revenue") in out["orders"]
        assert len(out["orders"]) == 2  # deduped
        assert ("country", "count") in out["users"]

    @pytest.mark.asyncio
    async def test_returns_empty_dict_on_db_error(self):
        from core.agents.depth_tracker import load_depth_combos_for_scorer

        db = AsyncMock()
        db.execute.side_effect = Exception("pgvector unavailable")

        out = await load_depth_combos_for_scorer(db, SPACE_ID)
        assert out == {}

    @pytest.mark.asyncio
    async def test_skips_malformed_rows(self):
        from core.agents.depth_tracker import load_depth_combos_for_scorer

        rows = [
            ("orders", "not_valid_json"),
            ("orders", json.dumps([["region", "revenue"]])),
        ]
        db = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = rows
        db.execute.return_value = result

        out = await load_depth_combos_for_scorer(db, SPACE_ID)
        assert ("region", "revenue") in out["orders"]
