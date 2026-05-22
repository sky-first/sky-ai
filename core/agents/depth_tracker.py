# core/agents/depth_tracker.py
"""Item 34 — Depth Tracker: records (dimension × metric) combos explored per dataset.

Each time the scan agent runs SQL against a table, the query is parsed to extract
GROUP BY columns (dimensions) and aggregate function targets (metrics). Those combos
are persisted as EmbeddingRecord rows with kind='depth_tracker'.

The DatasetPriorityScorer uses the accumulated combo set to calculate how much
analytical depth remains unexplored for each dataset.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Regex for GROUP BY clause — captures everything after GROUP BY up to ORDER/HAVING/LIMIT/;
_GROUP_BY_RE = re.compile(
    r"\bGROUP\s+BY\s+(.*?)(?:\s+(?:ORDER|HAVING|LIMIT|FETCH|UNION|INTERSECT|EXCEPT)\b|;|$)",
    re.IGNORECASE | re.DOTALL,
)

# Aggregate function targets — SUM(col), COUNT(col), AVG(col), MAX(col), MIN(col)
_AGG_RE = re.compile(
    r"\b(?:SUM|COUNT|AVG|AVERAGE|MAX|MIN|STDDEV|VARIANCE|MEDIAN)\s*\(\s*(?:DISTINCT\s+)?([a-zA-Z_][a-zA-Z0-9_.]*)\s*\)",
    re.IGNORECASE,
)


# Strip table-qualified column names: "orders.amount" → "amount"
def _bare(col: str) -> str:
    return col.strip().split(".")[-1].strip('"').strip("'").lower()


def extract_explored_combos(sql: str, table_name: str = "") -> Set[Tuple[str, str]]:
    """Parse a SQL string and extract (dimension, metric) combos.

    dimension = column in GROUP BY clause
    metric    = column inside an aggregate function call

    Returns an empty set when the SQL has no GROUP BY or no aggregates.
    """
    combos: Set[Tuple[str, str]] = set()
    if not sql:
        return combos

    group_by_match = _GROUP_BY_RE.search(sql)
    if not group_by_match:
        return combos

    group_by_raw = group_by_match.group(1)
    # Split on comma, handle basic expressions; skip position literals (numbers)
    dimensions: List[str] = []
    for part in group_by_raw.split(","):
        part = part.strip()
        if not part or part.isdigit():
            continue
        bare = _bare(part)
        if bare:
            dimensions.append(bare)

    metrics: List[str] = [_bare(m) for m in _AGG_RE.findall(sql)]
    metrics = [m for m in metrics if m and m != "*"]

    for dim in dimensions:
        for metric in metrics:
            if dim != metric:
                combos.add((dim, metric))

    return combos


async def record_depth_combos(
    db: AsyncSession,
    space_id: str,
    table_name: str,
    combos: Set[Tuple[str, str]],
) -> None:
    """Persist explored (dimension, metric) combos as an EmbeddingRecord.

    Appends a new row each call; the loader aggregates all rows per table.
    No-op when combos is empty or space_id is missing.
    """
    if not combos or not space_id or not table_name:
        return
    try:
        from db.models import EmbeddingRecord
        from uuid import uuid4, UUID as _UUID

        space_uuid = _UUID(space_id)
        combo_list = [list(c) for c in combos]
        record = EmbeddingRecord(
            id=uuid4(),
            space_id=space_uuid,
            user_id=None,
            embedding=[0.0] * 1024,
            text=json.dumps(combo_list),
            extra_metadata={
                "kind": "depth_tracker",
                "logical_name": table_name,
                "combo_count": len(combo_list),
            },
        )
        db.add(record)
        await db.flush()
        logger.debug(
            "record_depth_combos: %d combos for table '%s'", len(combos), table_name
        )
    except Exception as exc:
        logger.debug("record_depth_combos failed (non-critical): %s", exc)
        try:
            await db.rollback()
        except Exception:
            pass


async def load_depth_combos_for_scorer(
    db: AsyncSession,
    space_id: str,
) -> Dict[str, Set[Tuple[str, str]]]:
    """Load all recorded depth combos for the given space.

    Returns a dict mapping logical_name → set of (dimension, metric) tuples.
    Empty dict on error or when no records exist.
    """
    try:
        result = await db.execute(
            text(
                "SELECT metadata->>'logical_name', text "
                "FROM embeddings "
                "WHERE space_id = CAST(:sid AS uuid) "
                "AND metadata->>'kind' = 'depth_tracker'"
            ),
            {"sid": space_id},
        )
        rows = result.fetchall()
        out: Dict[str, Set[Tuple[str, str]]] = {}
        for logical_name, text_val in rows:
            if not logical_name or not text_val:
                continue
            try:
                combo_list = json.loads(text_val)
                combos = {(c[0], c[1]) for c in combo_list if len(c) == 2}
                if logical_name not in out:
                    out[logical_name] = set()
                out[logical_name].update(combos)
            except Exception:
                continue
        return out
    except Exception as exc:
        logger.debug("load_depth_combos_for_scorer failed (non-critical): %s", exc)
        return {}


def depth_remaining_score(
    table_name: str,
    columns: List[Any],
    explored_combos: Set[Tuple[str, str]],
) -> float:
    """Compute how much analytical depth remains unexplored for a table.

    score = 1.0  → fully unexplored (maximum priority)
    score = 0.0  → all plausible dimension×metric combos have been seen

    Falls back to a column-count proxy (0.5) when column metadata is unavailable.
    """
    if not columns:
        return 0.5

    # Estimate possible combos from column metadata
    # Numeric columns → potential metrics; others → potential dimensions
    numeric_types = {
        "int",
        "float",
        "numeric",
        "decimal",
        "double",
        "real",
        "bigint",
        "money",
    }
    dims: List[str] = []
    metrics: List[str] = []
    for col in columns:
        col_name = getattr(col, "name", None) or (col if isinstance(col, str) else "")
        col_type = str(getattr(col, "data_type", "") or "").lower()
        if any(t in col_type for t in numeric_types):
            metrics.append(col_name.lower())
        else:
            dims.append(col_name.lower())

    total_possible = len(dims) * len(metrics)
    if total_possible == 0:
        # All columns are the same type — treat all pairs as possible
        all_cols = [
            (
                (getattr(c, "name", None) or c).lower()
                if isinstance(c, str)
                else getattr(c, "name", "").lower()
            )
            for c in columns
        ]
        total_possible = max(1, len(all_cols) * (len(all_cols) - 1))

    explored_count = len(explored_combos)
    remaining_ratio = max(0.0, 1.0 - explored_count / total_possible)
    return min(1.0, remaining_ratio)
