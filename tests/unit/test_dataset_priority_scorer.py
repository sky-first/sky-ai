"""Unit tests for DatasetPriorityScorer (roadmap items 13, 15, 17, 18)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from core.agents.dataset_priority_scorer import (
    DatasetPriorityScorer,
    TableScore,
    cosine_similarity,
)

# ─── Minimal TableSchema stub ─────────────────────────────────────────────────


@dataclass
class _Table:
    logical_name: str
    physical_name: str = ""
    description: str = ""
    columns: List[Dict[str, Any]] = field(default_factory=list)
    data_connection_id: Optional[str] = None


def _col(name: str) -> Dict[str, str]:
    return {"name": name, "type": "text"}


def _insight(
    tables: List[str],
    hours_ago: float,
) -> Dict[str, Any]:
    """Build a fake scan_insight metadata dict."""
    ts = datetime.now(tz=timezone.utc) - timedelta(hours=hours_ago)
    return {"tables_queried": tables, "_created_at": ts}


# ─── staleness ────────────────────────────────────────────────────────────────


class TestStaleness:
    def test_never_queried_returns_max(self):
        scorer = DatasetPriorityScorer()
        tables = [_Table("orders")]
        result = scorer.score_breakdown(tables, insights=[])
        assert result[0].staleness == 1.0

    def test_just_queried_returns_near_zero(self):
        scorer = DatasetPriorityScorer(staleness_window_hours=24)
        insights = [_insight(["orders"], hours_ago=0.1)]
        result = scorer.score_breakdown([_Table("orders")], insights)
        assert result[0].staleness < 0.02

    def test_queried_half_window_ago_returns_half(self):
        scorer = DatasetPriorityScorer(staleness_window_hours=24)
        insights = [_insight(["orders"], hours_ago=12)]
        result = scorer.score_breakdown([_Table("orders")], insights)
        assert abs(result[0].staleness - 0.5) < 0.05

    def test_queried_beyond_window_caps_at_one(self):
        scorer = DatasetPriorityScorer(staleness_window_hours=24)
        insights = [_insight(["orders"], hours_ago=30)]
        result = scorer.score_breakdown([_Table("orders")], insights)
        assert result[0].staleness == 1.0

    def test_uses_most_recent_query_for_staleness(self):
        """When a table appears in multiple insights, the freshest one counts."""
        scorer = DatasetPriorityScorer(staleness_window_hours=24)
        insights = [
            _insight(["orders"], hours_ago=20),
            _insight(["orders"], hours_ago=2),  # most recent
        ]
        result = scorer.score_breakdown([_Table("orders")], insights)
        assert result[0].staleness < 0.2  # driven by 2-hour-ago insight

    def test_unrelated_insight_does_not_affect_staleness(self):
        scorer = DatasetPriorityScorer(staleness_window_hours=24)
        insights = [_insight(["users"], hours_ago=1)]  # different table
        result = scorer.score_breakdown([_Table("orders")], insights)
        assert result[0].staleness == 1.0  # orders never queried


# ─── depth ────────────────────────────────────────────────────────────────────


class TestDepth:
    def test_most_columns_gets_score_one(self):
        scorer = DatasetPriorityScorer()
        fat = _Table("fat", columns=[_col(f"c{i}") for i in range(20)])
        thin = _Table("thin", columns=[_col("c1")])
        scores = {s.logical_name: s for s in scorer.score_breakdown([fat, thin], [])}
        assert scores["fat"].depth == 1.0

    def test_fewer_columns_gets_lower_depth(self):
        scorer = DatasetPriorityScorer()
        fat = _Table("fat", columns=[_col(f"c{i}") for i in range(20)])
        thin = _Table("thin", columns=[_col("c1"), _col("c2")])
        scores = {s.logical_name: s for s in scorer.score_breakdown([fat, thin], [])}
        assert scores["thin"].depth == pytest.approx(2 / 20)

    def test_single_table_with_cols_gets_full_depth(self):
        scorer = DatasetPriorityScorer()
        t = _Table("t", columns=[_col("a"), _col("b")])
        result = scorer.score_breakdown([t], [])
        assert result[0].depth == 1.0

    def test_no_columns_returns_neutral(self):
        # When ALL tables have 0 columns, max_cols=0 → scorer returns 0.5 (neutral)
        scorer = DatasetPriorityScorer()
        result = scorer.score_breakdown([_Table("empty")], [])
        assert result[0].depth == 0.5

    def test_zero_cols_vs_nonzero_cols_returns_zero(self):
        scorer = DatasetPriorityScorer()
        fat = _Table("fat", columns=[_col("a"), _col("b")])
        empty = _Table("empty")
        scores = {s.logical_name: s for s in scorer.score_breakdown([fat, empty], [])}
        assert scores["empty"].depth == 0.0


# ─── strategic relevance ──────────────────────────────────────────────────────


class TestStrategicRelevance:
    def test_no_brain_context_returns_neutral(self):
        scorer = DatasetPriorityScorer(brain_context="")
        result = scorer.score_breakdown([_Table("anything")], [])
        assert result[0].strategic_relevance == 0.5

    def test_matching_keywords_raise_score_above_half(self):
        scorer = DatasetPriorityScorer(brain_context="revenue growth churn retention")
        t = _Table(
            "subscriptions",
            description="tracks user retention and churn rates",
            columns=[_col("revenue"), _col("plan_id")],
        )
        result = scorer.score_breakdown([t], [])
        assert result[0].strategic_relevance > 0.5

    def test_zero_matching_keywords_returns_at_least_minimum(self):
        scorer = DatasetPriorityScorer(brain_context="quantum blockchain metaverse")
        t = _Table("orders", description="order transactions", columns=[_col("amount")])
        result = scorer.score_breakdown([t], [])
        # Clamped to minimum 0.1
        assert result[0].strategic_relevance >= 0.1

    def test_high_overlap_capped_at_095(self):
        long_brain = " ".join(
            ["revenue", "orders", "amount", "profit", "sales", "growth"] * 10
        )
        scorer = DatasetPriorityScorer(brain_context=long_brain)
        t = _Table(
            "orders",
            description="revenue amount profit sales growth",
            columns=[_col("revenue"), _col("profit"), _col("sales")],
        )
        result = scorer.score_breakdown([t], [])
        assert result[0].strategic_relevance <= 0.95


# ─── volatility (placeholder) ─────────────────────────────────────────────────


class TestVolatility:
    def test_placeholder_returns_half(self):
        scorer = DatasetPriorityScorer()
        result = scorer.score_breakdown([_Table("anything")], [])
        assert result[0].volatility == 0.5


# ─── score formula ────────────────────────────────────────────────────────────


class TestScoreFormula:
    def test_weights_sum_to_one(self):
        assert sum(DatasetPriorityScorer.WEIGHTS.values()) == pytest.approx(1.0)

    def test_never_queried_table_with_many_columns_wins_over_fresh_small_table(self):
        """Stale + deep table should beat fresh + shallow table."""
        scorer = DatasetPriorityScorer(staleness_window_hours=24)
        stale_deep = _Table("big", columns=[_col(f"c{i}") for i in range(20)])
        fresh_small = _Table("small", columns=[_col("c1")])

        insights = [_insight(["small"], hours_ago=0.5)]  # small was just queried
        scores = {
            s.logical_name: s
            for s in scorer.score_breakdown([stale_deep, fresh_small], insights)
        }

        assert scores["big"].score > scores["small"].score

    def test_score_is_between_zero_and_one(self):
        scorer = DatasetPriorityScorer(brain_context="revenue sales growth")
        tables = [
            _Table("orders", columns=[_col(f"c{i}") for i in range(5)]),
            _Table("users", description="user revenue sales", columns=[_col("id")]),
        ]
        for s in scorer.score_breakdown(tables, []):
            assert 0.0 <= s.score <= 1.0


# ─── rank (top-K selection) ───────────────────────────────────────────────────


class TestRank:
    def test_returns_top_k(self):
        scorer = DatasetPriorityScorer(top_k=2)
        tables = [_Table(f"t{i}") for i in range(5)]
        result = scorer.rank(tables, insights=[])
        assert len(result) == 2

    def test_returns_all_when_fewer_than_k(self):
        scorer = DatasetPriorityScorer(top_k=10)
        tables = [_Table("a"), _Table("b")]
        result = scorer.rank(tables, insights=[])
        assert len(result) == 2

    def test_returns_at_least_one_even_if_top_k_zero(self):
        scorer = DatasetPriorityScorer(top_k=0)
        tables = [_Table("only")]
        result = scorer.rank(tables, insights=[])
        assert len(result) >= 1

    def test_empty_tables_returns_empty(self):
        scorer = DatasetPriorityScorer(top_k=5)
        assert scorer.rank([], insights=[]) == []

    def test_stale_tables_are_prioritised(self):
        """Tables never queried should rank above freshly-queried ones."""
        scorer = DatasetPriorityScorer(top_k=1, staleness_window_hours=24)
        stale = _Table("stale_table")
        fresh = _Table("fresh_table")
        insights = [_insight(["fresh_table"], hours_ago=0.1)]
        result = scorer.rank([stale, fresh], insights)
        assert result[0].logical_name == "stale_table"

    def test_preserves_original_table_objects(self):
        """rank() must return the same TableSchema objects, not copies."""
        scorer = DatasetPriorityScorer(top_k=2)
        t1 = _Table("a", data_connection_id="conn-1")
        t2 = _Table("b", data_connection_id="conn-2")
        result = scorer.rank([t1, t2], insights=[])
        returned_names = {r.logical_name for r in result}
        assert "a" in returned_names or "b" in returned_names
        for r in result:
            assert r.data_connection_id is not None  # object identity preserved


# ─── cross_dataset_rank (item 15) ────────────────────────────────────────────


class TestCrossDatasetRank:
    def test_returns_one_table_per_connection(self):
        scorer = DatasetPriorityScorer(top_k=5)
        tables = [
            _Table("orders", data_connection_id="conn-crm"),
            _Table("deals", data_connection_id="conn-crm"),
            _Table("sessions", data_connection_id="conn-web"),
            _Table("campaigns", data_connection_id="conn-marketing"),
        ]
        result = scorer.cross_dataset_rank(tables, insights=[])
        conn_ids = [getattr(t, "data_connection_id", None) for t in result]
        assert len(result) == 3
        assert set(conn_ids) == {"conn-crm", "conn-web", "conn-marketing"}

    def test_selects_best_scored_table_per_connection(self):
        """The stale (never queried) table should beat the fresh one within the same conn."""
        scorer = DatasetPriorityScorer(staleness_window_hours=24, top_k=5)
        stale = _Table(
            "big",
            data_connection_id="conn-a",
            columns=[_col(f"c{i}") for i in range(10)],
        )
        fresh = _Table("small", data_connection_id="conn-a", columns=[_col("c1")])
        other = _Table("other", data_connection_id="conn-b")

        insights = [_insight(["small"], hours_ago=0.1)]
        result = scorer.cross_dataset_rank([stale, fresh, other], insights)

        conn_a_result = next(t for t in result if t.data_connection_id == "conn-a")
        assert conn_a_result.logical_name == "big"

    def test_single_connection_falls_back_to_normal_rank(self):
        scorer = DatasetPriorityScorer(top_k=2)
        tables = [
            _Table("orders", data_connection_id="conn-a"),
            _Table("users", data_connection_id="conn-a"),
            _Table("products", data_connection_id="conn-a"),
        ]
        result = scorer.cross_dataset_rank(tables, insights=[])
        assert len(result) == 2  # top_k=2, not 1-per-connection

    def test_no_data_connection_id_treated_as_single_group(self):
        scorer = DatasetPriorityScorer(top_k=1)
        tables = [_Table("a"), _Table("b"), _Table("c")]
        result = scorer.cross_dataset_rank(tables, insights=[])
        # All in one group → fallback to rank → top_k=1
        assert len(result) == 1

    def test_empty_tables_returns_empty(self):
        scorer = DatasetPriorityScorer()
        assert scorer.cross_dataset_rank([], insights=[]) == []

    def test_returns_original_table_objects(self):
        scorer = DatasetPriorityScorer(top_k=5)
        t1 = _Table("orders", data_connection_id="conn-a")
        t2 = _Table("sessions", data_connection_id="conn-b")
        result = scorer.cross_dataset_rank([t1, t2], insights=[])
        result_names = {t.logical_name for t in result}
        assert "orders" in result_names
        assert "sessions" in result_names


# ─── build_scan_briefing with cross_dataset flag ──────────────────────────────


class TestScanBriefingCrossDataset:
    def _make_topic_map(self):
        from core.agents.scan_briefing import TopicMap

        return TopicMap(has_history=False)

    def test_cross_dataset_block_appears_when_flag_true(self):
        from core.agents.scan_briefing import build_scan_briefing

        briefing = build_scan_briefing(
            topic_map=self._make_topic_map(),
            brain_context="",
            recent_insights=[],
            table_count=6,
            is_cross_dataset=True,
        )
        assert "CROSS-DATASET RUN" in briefing

    def test_cross_dataset_block_absent_when_flag_false(self):
        from core.agents.scan_briefing import build_scan_briefing

        briefing = build_scan_briefing(
            topic_map=self._make_topic_map(),
            brain_context="",
            recent_insights=[],
            table_count=6,
            is_cross_dataset=False,
        )
        assert "CROSS-DATASET RUN" not in briefing

    def test_cross_dataset_mentions_correlations(self):
        from core.agents.scan_briefing import build_scan_briefing

        briefing = build_scan_briefing(
            topic_map=self._make_topic_map(),
            brain_context="",
            recent_insights=[],
            table_count=4,
            is_cross_dataset=True,
        )
        assert "CORRELATIONS" in briefing.upper() or "correlations" in briefing.lower()


# ─── keyword extractor ────────────────────────────────────────────────────────


class TestExtractKeywords:
    def test_short_words_filtered(self):
        kw = DatasetPriorityScorer._extract_keywords("go is do be up")
        assert not kw  # all < 4 chars

    def test_stop_words_filtered(self):
        kw = DatasetPriorityScorer._extract_keywords("data table value type")
        assert not kw

    def test_extracts_valid_keywords(self):
        kw = DatasetPriorityScorer._extract_keywords("revenue growth churn")
        assert "revenue" in kw
        assert "growth" in kw
        assert "churn" in kw

    def test_deduplicates(self):
        kw = DatasetPriorityScorer._extract_keywords("revenue revenue revenue")
        assert len(kw) == 1


# ─── cosine_similarity (item 17) ──────────────────────────────────────────────


class TestCosineSimilarity:
    def test_identical_vectors_return_one(self):
        assert abs(cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) - 1.0) < 1e-9

    def test_orthogonal_vectors_return_zero(self):
        assert abs(cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9

    def test_opposite_vectors_return_negative_one(self):
        assert abs(cosine_similarity([1.0, 0.0], [-1.0, 0.0]) + 1.0) < 1e-9

    def test_empty_vectors_return_zero(self):
        assert cosine_similarity([], []) == 0.0

    def test_mismatched_dims_return_zero(self):
        assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0

    def test_zero_vector_returns_zero(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_partial_similarity(self):
        a = [1.0, 1.0, 0.0]
        b = [1.0, 0.0, 0.0]
        sim = cosine_similarity(a, b)
        import math

        expected = 1.0 / math.sqrt(2)
        assert abs(sim - expected) < 1e-6


# ─── strategic_relevance cosine path (items 17-18) ────────────────────────────


class TestStrategicRelevanceCosine:
    def _okr_vec(self) -> List[float]:
        return [1.0, 0.5, 0.2]

    def _close_dataset_vec(self) -> List[float]:
        # High cosine with okr_vec
        return [0.9, 0.6, 0.3]

    def _unrelated_dataset_vec(self) -> List[float]:
        # Orthogonal to okr_vec
        return [0.0, -0.2, 1.0]

    def test_high_similarity_scores_above_neutral(self):
        t = _Table("revenue")
        scorer = DatasetPriorityScorer(
            okr_vectors=[self._okr_vec()],
            dataset_embeddings={"revenue": self._close_dataset_vec()},
        )
        score = scorer._strategic_relevance_score(t)
        assert score > 0.5

    def test_opposite_direction_scores_below_neutral(self):
        # Cosine = -1 (exact opposite) → mapped = 0.525 + (-1)*0.425 = 0.1
        t = _Table("revenue")
        okr = [1.0, 0.0, 0.0]
        opposite = [-1.0, 0.0, 0.0]
        scorer = DatasetPriorityScorer(
            okr_vectors=[okr],
            dataset_embeddings={"revenue": opposite},
        )
        score = scorer._strategic_relevance_score(t)
        assert score < 0.5

    def test_low_similarity_scores_lower_than_high(self):
        close = _Table("close")
        far = _Table("far")
        okr = [1.0, 0.5, 0.2]
        scorer = DatasetPriorityScorer(
            okr_vectors=[okr],
            dataset_embeddings={
                "close": [0.9, 0.6, 0.3],  # high cosine
                "far": self._unrelated_dataset_vec(),  # low cosine
            },
        )
        assert scorer._strategic_relevance_score(
            close
        ) > scorer._strategic_relevance_score(far)

    def test_score_clamped_to_0_1_0_95(self):
        t = _Table("revenue")
        scorer = DatasetPriorityScorer(
            okr_vectors=[[1.0, 0.0]],
            dataset_embeddings={"revenue": [1.0, 0.0]},
        )
        score = scorer._strategic_relevance_score(t)
        assert 0.1 <= score <= 0.95

    def test_missing_dataset_embedding_falls_back_to_keyword(self):
        # dataset_embeddings exist but not for this table → keyword fallback
        t = _Table("revenue", description="revenue growth")
        scorer = DatasetPriorityScorer(
            brain_context="revenue growth churn",
            okr_vectors=[[1.0, 0.0]],
            dataset_embeddings={"other_table": [1.0, 0.0]},
        )
        score = scorer._strategic_relevance_score(t)
        # Keyword path: brain has 'revenue', 'growth', 'churn'; table matches two → > 0.5
        assert score > 0.5

    def test_no_embeddings_no_brain_returns_neutral(self):
        t = _Table("revenue")
        scorer = DatasetPriorityScorer()
        assert scorer._strategic_relevance_score(t) == 0.5

    def test_uses_max_similarity_across_multiple_okr_vectors(self):
        t = _Table("revenue")
        low_okr = [0.0, 0.0, 1.0]  # orthogonal to dataset
        high_okr = [1.0, 0.5, 0.2]  # similar to dataset
        scorer = DatasetPriorityScorer(
            okr_vectors=[low_okr, high_okr],
            dataset_embeddings={"revenue": [0.9, 0.6, 0.3]},
        )
        score_multi = scorer._strategic_relevance_score(t)

        scorer_single_low = DatasetPriorityScorer(
            okr_vectors=[low_okr],
            dataset_embeddings={"revenue": [0.9, 0.6, 0.3]},
        )
        score_low = scorer_single_low._strategic_relevance_score(t)

        assert score_multi > score_low  # max wins over only-low

    def test_ranked_higher_than_unrelated_table(self):
        revenue = _Table("revenue")
        logs = _Table("logs")
        okr_vec = [1.0, 0.5, 0.0]
        scorer = DatasetPriorityScorer(
            top_k=1,
            okr_vectors=[okr_vec],
            dataset_embeddings={
                "revenue": [0.9, 0.6, 0.0],  # similar to OKR
                "logs": [0.0, 0.0, 1.0],  # unrelated
            },
        )
        top = scorer.rank([revenue, logs], insights=[])
        assert top[0].logical_name == "revenue"
