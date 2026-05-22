"""Dataset Priority Scorer — item 13 of the proactive intelligence roadmap.

Scores each table in the merged AgentConfig and returns the top-K most
valuable datasets for the current scan run.

Score formula (weights sum to 1.0):
  score = staleness          × 0.45   ← tables not seen recently score higher
        + strategic_relevance × 0.30   ← cosine sim(dataset_emb, OKR_embs) — item 17/18
        + depth               × 0.15   ← tables with more columns have more analytical depth
        + volatility          × 0.10   ← (placeholder 0.5 until item 20 row-count snapshots)

Roadmap:
  ✅ Item 16-18: cosine similarity OKR→dataset via pre-loaded embeddings
  Item 19:    auto-recalculate when new OKR added to brain
  Item 20-22: replace _volatility_score() with row-count delta tracking
  Item 34:    replace _depth_score() with real combination-coverage tracking
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# How long until a table's staleness reaches 1.0 (maximum priority).
# A table not queried for this many hours is treated as "fully stale".
STALENESS_WINDOW_HOURS = 24

# Default number of top tables to return each run.
DEFAULT_TOP_K = 5

# How many recent scan_insight records to load for staleness calculation.
INSIGHTS_HISTORY_LIMIT = 50

# Every N scan runs, the agent is forced to pick one table per connection
# so it explores cross-source correlations instead of always focusing on
# the same high-scoring dataset.
CROSS_DATASET_EVERY_N = 5

# Brain metadata types that carry strategic relevance context.
OKR_TYPES = {"pillar", "okr", "kpi", "metric", "business_context"}


# ─── Cosine similarity (no external deps) ─────────────────────────────────────


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Return cosine similarity in [−1, 1]. Returns 0.0 on zero/mismatched vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


# ─── DB loaders (async, separated from pure scorer) ───────────────────────────


async def load_okr_embeddings_for_scorer(
    db: AsyncSession,
    space_id: str,
) -> List[List[float]]:
    """Load brain OKR/pillar/KPI embedding vectors for the given space.

    Returns a flat list of vectors (one per brain document). Empty list when
    the space has no brain documents or the query fails.
    """
    try:
        result = await db.execute(
            text(
                "SELECT embedding::text FROM embeddings "
                "WHERE space_id = :space_id "
                "AND metadata->>'type' = ANY(:types)"
            ),
            {"space_id": space_id, "types": list(OKR_TYPES)},
        )
        rows = result.fetchall()
        vectors: List[List[float]] = []
        for (vec_text,) in rows:
            if vec_text is None:
                continue
            # pgvector returns '[0.1,0.2,...]' as text
            cleaned = vec_text.strip().strip("[]")
            if not cleaned:
                continue
            try:
                vectors.append([float(v) for v in cleaned.split(",")])
            except (ValueError, AttributeError):
                continue
        return vectors
    except Exception as exc:
        logger.warning("load_okr_embeddings_for_scorer failed: %s", exc)
        return []


async def load_dataset_embeddings_for_scorer(
    db: AsyncSession,
    space_id: str,
) -> Dict[str, List[float]]:
    """Load dataset_description embedding vectors keyed by logical_name.

    Returns a dict {logical_name: vector}. Empty dict when no embeddings
    exist yet (item 16 hasn't run for this connection) or query fails.
    """
    try:
        result = await db.execute(
            text(
                "SELECT metadata->>'logical_name', embedding::text FROM embeddings "
                "WHERE space_id = :space_id "
                "AND metadata->>'kind' = 'dataset_description'"
            ),
            {"space_id": space_id},
        )
        rows = result.fetchall()
        out: Dict[str, List[float]] = {}
        for logical_name, vec_text in rows:
            if not logical_name or not vec_text:
                continue
            cleaned = vec_text.strip().strip("[]")
            if not cleaned:
                continue
            try:
                out[logical_name] = [float(v) for v in cleaned.split(",")]
            except (ValueError, AttributeError):
                continue
        return out
    except Exception as exc:
        logger.warning("load_dataset_embeddings_for_scorer failed: %s", exc)
        return {}


async def load_row_count_snapshots_for_scorer(
    db: AsyncSession,
    space_id: str,
) -> Dict[str, List[int]]:
    """Load the last 2 row_count snapshots per table for volatility calculation.

    Returns {logical_name: [count_newest, count_older]} — newest first.
    Tables with fewer than 2 snapshots get a shorter list.
    Empty dict on failure or no snapshots.
    """
    try:
        result = await db.execute(
            text(
                "SELECT metadata->>'logical_name', "
                "       CAST(metadata->>'row_count' AS INTEGER), "
                "       created_at "
                "FROM embeddings "
                "WHERE space_id = :space_id "
                "AND metadata->>'kind' = 'row_count_snapshot' "
                "ORDER BY created_at DESC"
            ),
            {"space_id": space_id},
        )
        rows = result.fetchall()
        snapshots: Dict[str, List[int]] = {}
        for logical_name, row_count, _created_at in rows:
            if not logical_name or row_count is None:
                continue
            bucket = snapshots.setdefault(logical_name, [])
            if len(bucket) < 2:
                bucket.append(row_count)
        return snapshots
    except Exception as exc:
        logger.warning("load_row_count_snapshots_for_scorer failed: %s", exc)
        return {}


async def save_row_count_snapshots(
    db: AsyncSession,
    space_id: str,
    tables: List[Any],
) -> int:
    """Persist a row_count snapshot for each table using connection_metadata as source.

    Reads `connection_metadata.tables[].row_count` (populated during /discover).
    Skips tables where row_count == -1 (unknown) or the connection has no catalog.
    Snapshots accumulate over time — the load function always reads only the latest 2.

    Returns the number of records saved.
    """
    from uuid import uuid4, UUID as _UUID
    from db.models import EmbeddingRecord

    if not tables or not space_id:
        return 0

    # Group tables by data_connection_id for a single query per connection
    conn_to_tables: Dict[Optional[str], List[Any]] = {}
    for t in tables:
        cid = getattr(t, "data_connection_id", None)
        conn_to_tables.setdefault(cid, []).append(t)

    # Build map: {logical_name → row_count} from connection_metadata
    row_count_map: Dict[str, int] = {}
    for conn_id, conn_tables in conn_to_tables.items():
        if not conn_id:
            continue
        try:
            result = await db.execute(
                text("SELECT tables FROM connection_metadata WHERE connection_id = CAST(:cid AS uuid) LIMIT 1"),
                {"cid": conn_id},
            )
            tables_json = result.scalar_one_or_none()
        except Exception as exc:
            logger.debug("save_row_count_snapshots: connection_metadata fetch failed for %s: %s", conn_id, exc)
            continue

        if not tables_json or not isinstance(tables_json, list):
            continue

        # Build a lookup: logical_name → row_count from the catalog
        catalog: Dict[str, int] = {}
        for entry in tables_json:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name") or entry.get("table_name")
            if not name:
                continue
            schema = entry.get("schema") or ""
            logical = f"{schema}.{name}" if schema else name
            rc = entry.get("row_count", -1)
            if isinstance(rc, int) and rc >= 0:
                catalog[logical] = rc
                catalog[name] = rc  # also index by bare name for fallback

        for t in conn_tables:
            rc = catalog.get(t.logical_name) or catalog.get(getattr(t, "physical_name", ""))
            if rc is not None and rc >= 0:
                row_count_map[t.logical_name] = rc

    if not row_count_map:
        return 0

    try:
        space_uuid = _UUID(space_id)
    except Exception:
        return 0

    dummy_embedding = [0.0] * 1024
    created = 0
    for logical_name, row_count in row_count_map.items():
        db.add(EmbeddingRecord(
            id=uuid4(),
            space_id=space_uuid,
            user_id=None,
            embedding=dummy_embedding,
            text=f"row_count_snapshot:{logical_name}:{row_count}",
            extra_metadata={
                "kind": "row_count_snapshot",
                "logical_name": logical_name,
                "row_count": row_count,
            },
        ))
        created += 1

    try:
        await db.flush()
    except Exception as exc:
        logger.warning("save_row_count_snapshots flush failed: %s", exc)
        try:
            await db.rollback()
        except Exception:
            pass
        return 0

    logger.debug("save_row_count_snapshots: saved %d snapshots for space %s", created, space_id)
    return created


# ─── Data structures ──────────────────────────────────────────────────────────


@dataclass
class TableScore:
    logical_name: str
    score: float
    staleness: float
    strategic_relevance: float
    depth: float
    volatility: float
    last_queried_at: Optional[datetime] = None

    def __repr__(self) -> str:
        lq = self.last_queried_at.strftime("%H:%M") if self.last_queried_at else "never"
        return (
            f"TableScore({self.logical_name!r} score={self.score:.3f} "
            f"staleness={self.staleness:.2f} relevance={self.strategic_relevance:.2f} "
            f"depth={self.depth:.2f} last_queried={lq})"
        )


# ─── DB loader (async, separated from pure scorer) ────────────────────────────


async def load_insights_for_scorer(
    db: AsyncSession,
    space_id: str,
    limit: int = INSIGHTS_HISTORY_LIMIT,
) -> List[Dict[str, Any]]:
    """Load recent scan_insight metadata rows for staleness calculation.

    Returns a list of raw metadata dicts, each containing at minimum:
      {"tables_queried": [...], "title": "..."}
    and a synthetic "_created_at" key with the row timestamp.
    """
    try:
        result = await db.execute(
            text(
                "SELECT metadata, created_at FROM embeddings "
                "WHERE space_id = :space_id "
                "AND metadata->>'type' = 'scan_insight' "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {"space_id": space_id, "limit": limit},
        )
        rows = result.fetchall()
        out: List[Dict[str, Any]] = []
        for meta, created_at in rows:
            if not isinstance(meta, dict):
                continue
            meta["_created_at"] = created_at
            out.append(meta)
        return out
    except Exception as exc:
        logger.warning("load_insights_for_scorer failed: %s", exc)
        return []


# ─── Pure scorer (sync) ───────────────────────────────────────────────────────


class DatasetPriorityScorer:
    """Score and rank tables so the scan agent always explores the highest-value
    dataset for the current run, rather than gravitating toward the same obvious
    table every time.

    Usage:
        insights = await load_insights_for_scorer(db, space_id)
        scorer = DatasetPriorityScorer(brain_context=brain_ctx, top_k=5)
        top_tables = scorer.rank(all_tables, insights)
    """

    WEIGHTS = {
        "staleness":            0.45,
        "strategic_relevance":  0.30,
        "depth":                0.15,
        "volatility":           0.10,
    }

    def __init__(
        self,
        brain_context: str = "",
        top_k: int = DEFAULT_TOP_K,
        staleness_window_hours: int = STALENESS_WINDOW_HOURS,
        okr_vectors: Optional[List[List[float]]] = None,
        dataset_embeddings: Optional[Dict[str, List[float]]] = None,
        row_count_snapshots: Optional[Dict[str, List[int]]] = None,
    ) -> None:
        self._brain_context = brain_context.lower()
        self._top_k = top_k
        self._staleness_window = timedelta(hours=staleness_window_hours)
        # Keyword fallback (used when embeddings not available)
        self._brain_keywords = self._extract_keywords(self._brain_context)
        # Cosine similarity inputs (items 17-18)
        self._okr_vectors: List[List[float]] = okr_vectors or []
        self._dataset_embeddings: Dict[str, List[float]] = dataset_embeddings or {}
        # Row-count snapshots for volatility (items 20-22)
        self._row_count_snapshots: Dict[str, List[int]] = row_count_snapshots or {}

    # ── Public API ────────────────────────────────────────────────────────────

    def rank(
        self,
        tables: List[Any],  # List[TableSchema]
        insights: List[Dict[str, Any]],
    ) -> List[Any]:
        """Return the top-K tables sorted by priority score (highest first).

        Always returns at least 1 table. If top_k >= len(tables), returns all.
        """
        if not tables:
            return []

        now = datetime.now(tz=timezone.utc)
        max_cols = max((len(t.columns or []) for t in tables), default=1)

        scores: List[TableScore] = []
        for table in tables:
            staleness, last_queried_at = self._staleness_score(
                table.logical_name, insights, now
            )
            relevance = self._strategic_relevance_score(table)
            depth = self._depth_score(table, max_cols)
            volatility = self._volatility_score(table)

            score = (
                self.WEIGHTS["staleness"]           * staleness
                + self.WEIGHTS["strategic_relevance"] * relevance
                + self.WEIGHTS["depth"]               * depth
                + self.WEIGHTS["volatility"]          * volatility
            )

            scores.append(TableScore(
                logical_name=table.logical_name,
                score=score,
                staleness=staleness,
                strategic_relevance=relevance,
                depth=depth,
                volatility=volatility,
                last_queried_at=last_queried_at,
            ))

        scores.sort(key=lambda s: s.score, reverse=True)

        logger.debug(
            "DatasetPriorityScorer: top-%d from %d tables\n%s",
            self._top_k, len(tables),
            "\n".join(f"  {s}" for s in scores[:self._top_k]),
        )

        top_k = max(1, self._top_k)
        top_names = {s.logical_name for s in scores[:top_k]}

        # Preserve original order within the top-K for determinism
        return [t for t in tables if t.logical_name in top_names]

    def cross_dataset_rank(
        self,
        tables: List[Any],
        insights: List[Dict[str, Any]],
    ) -> List[Any]:
        """Pick the top-scored table from each unique data_connection_id.

        Used every CROSS_DATASET_EVERY_N runs to guarantee the agent queries
        at least one table per connected source, forcing cross-dataset analysis.
        Falls back to normal rank() when all tables share the same connection.
        """
        if not tables:
            return []

        groups: Dict[Optional[str], List[Any]] = defaultdict(list)
        for t in tables:
            conn_id = getattr(t, "data_connection_id", None)
            groups[conn_id].append(t)

        if len(groups) <= 1:
            # Single connection — cross-dataset mode has no effect; use normal rank
            return self.rank(tables, insights)

        scores_map = {s.logical_name: s.score for s in self.score_breakdown(tables, insights)}

        selected = []
        for group_tables in groups.values():
            best = max(group_tables, key=lambda t: scores_map.get(t.logical_name, 0.0))
            selected.append(best)

        logger.debug(
            "DatasetPriorityScorer cross_dataset_rank: %d connections → %d tables: %s",
            len(groups),
            len(selected),
            [t.logical_name for t in selected],
        )
        return selected

    def score_breakdown(
        self,
        tables: List[Any],
        insights: List[Dict[str, Any]],
    ) -> List[TableScore]:
        """Return scored entries for all tables (useful for logging/debugging)."""
        now = datetime.now(tz=timezone.utc)
        max_cols = max((len(t.columns or []) for t in tables), default=1)
        out = []
        for table in tables:
            staleness, last_queried_at = self._staleness_score(
                table.logical_name, insights, now
            )
            relevance = self._strategic_relevance_score(table)
            depth = self._depth_score(table, max_cols)
            volatility = self._volatility_score(table)
            score = (
                self.WEIGHTS["staleness"]            * staleness
                + self.WEIGHTS["strategic_relevance"] * relevance
                + self.WEIGHTS["depth"]               * depth
                + self.WEIGHTS["volatility"]          * volatility
            )
            out.append(TableScore(
                logical_name=table.logical_name,
                score=score,
                staleness=staleness,
                strategic_relevance=relevance,
                depth=depth,
                volatility=volatility,
                last_queried_at=last_queried_at,
            ))
        out.sort(key=lambda s: s.score, reverse=True)
        return out

    # ── Component scorers ─────────────────────────────────────────────────────

    def _staleness_score(
        self,
        logical_name: str,
        insights: List[Dict[str, Any]],
        now: datetime,
    ) -> Tuple[float, Optional[datetime]]:
        """0.0 = queried very recently, 1.0 = never queried (or beyond window)."""
        last_queried_at: Optional[datetime] = None

        for insight in insights:
            tables_in_run = insight.get("tables_queried") or []
            if logical_name in tables_in_run:
                ts = insight.get("_created_at")
                if ts is not None:
                    # Normalise to UTC-aware datetime
                    if isinstance(ts, datetime):
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                    if last_queried_at is None or ts > last_queried_at:
                        last_queried_at = ts

        if last_queried_at is None:
            return 1.0, None  # never queried → maximum staleness

        age = now - last_queried_at
        # Linear decay: 0 at age=0, 1.0 at age=staleness_window
        staleness = min(1.0, age / self._staleness_window)
        return staleness, last_queried_at

    def _strategic_relevance_score(self, table: Any) -> float:
        """Strategic relevance: cosine similarity between dataset embedding and OKR embeddings.

        When both dataset_embeddings and okr_vectors are available (items 17-18),
        takes the maximum cosine similarity across all OKR vectors for this table.

        Falls back to keyword overlap when embeddings are not yet available
        (e.g. /discover hasn't run since item 16 was deployed).

        Returns 0.5 (neutral) when no brain context exists at all.
        """
        # ── Path 1: cosine similarity (items 17-18) ───────────────────────────
        if self._okr_vectors and self._dataset_embeddings:
            dataset_vec = self._dataset_embeddings.get(table.logical_name)
            if dataset_vec:
                sims = [
                    cosine_similarity(dataset_vec, okr_vec)
                    for okr_vec in self._okr_vectors
                ]
                max_sim = max(sims)
                # cosine in [-1, 1] → map to [0.1, 0.95]
                # neutral (sim=0) → 0.525, high sim (sim=1) → 0.95
                mapped = 0.525 + max_sim * 0.425
                return max(0.1, min(0.95, mapped))
            # Dataset embedding not yet generated — fall through to keyword

        # ── Path 2: keyword overlap fallback ─────────────────────────────────
        if not self._brain_keywords:
            return 0.5

        table_text = " ".join(filter(None, [
            str(table.description or ""),
            table.logical_name,
            " ".join(
                str(c.get("name", "") if isinstance(c, dict) else getattr(c, "name", ""))
                for c in (table.columns or [])
            ),
        ])).lower()

        table_keywords = self._extract_keywords(table_text)
        if not table_keywords:
            return 0.5

        overlap = len(self._brain_keywords & table_keywords)
        score = min(1.0, overlap / max(1, len(self._brain_keywords) * 0.3))
        return max(0.1, min(0.95, score))

    def _depth_score(self, table: Any, max_cols: int) -> float:
        """Proxy for analytical depth = num_columns / max_columns_across_all_tables.

        Tables with more columns offer more unexplored analytical combinations.
        Will be replaced by real combination-coverage tracking in item 34.
        """
        if max_cols == 0:
            return 0.5
        num_cols = len(table.columns or [])
        return min(1.0, num_cols / max_cols)

    def _volatility_score(self, table: Any) -> float:
        """Delta percentual de row_count entre os últimos 2 snapshots (items 20-22).

        Returns 0.5 (neutral) when fewer than 2 snapshots exist.
        High-churn event tables (large % delta) approach 1.0.
        Static reference tables with no change stay at 0.0.
        """
        counts = self._row_count_snapshots.get(table.logical_name, [])
        if len(counts) < 2:
            return 0.5  # neutral — not enough history yet

        newest, older = counts[0], counts[1]
        if older == 0:
            # Table was empty last time; any rows now = maximum volatility
            return 1.0 if newest > 0 else 0.5

        delta_pct = abs(newest - older) / older
        # Cap at 100% delta → 1.0; linear scale below that
        return min(1.0, delta_pct)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_keywords(text: str) -> set:
        """Extract meaningful words (length >= 4) from text, ignoring stop words."""
        stop_words = {
            "this", "that", "with", "from", "have", "will", "been", "they",
            "their", "when", "than", "into", "your", "each", "which", "also",
            "more", "most", "over", "such", "then", "only", "like", "both",
            "data", "table", "column", "value", "values", "field", "type",
        }
        words = re.findall(r"[a-z][a-z0-9_]{2,}", text.lower())
        return {w for w in words if w not in stop_words and len(w) >= 4}
