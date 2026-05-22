# core/agents/coverage_report.py
"""Item 35 — Dataset coverage report.

Aggregates per-dataset scan coverage stats from the embeddings table:
  - last_queried_at / times_queried  (from scan_insight.metadata.tables_queried)
  - combos_explored                  (from depth_tracker records)
  - latest_row_count                 (from row_count_snapshot records)
  - depth_remaining_pct              (100 × depth_remaining_score)

Used by GET /spaces/{space_id}/dataset-coverage.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def build_coverage_report(
    db: AsyncSession,
    space_id: str,
) -> List[Dict[str, Any]]:
    """Return a list of per-dataset coverage dicts for the given space.

    Each dict:
      logical_name       str
      last_queried_at    ISO-8601 string | None
      times_queried      int
      combos_explored    int
      latest_row_count   int | None
      depth_remaining_pct  int  (0-100; 100 = unexplored)
    """
    if not space_id:
        return []

    try:
        # ── 1. Scan insight staleness ────────────────────────────────────────
        result = await db.execute(
            text(
                "SELECT metadata, created_at FROM embeddings "
                "WHERE space_id = CAST(:sid AS uuid) "
                "AND metadata->>'type' = 'scan_insight' "
                "ORDER BY created_at DESC"
            ),
            {"sid": space_id},
        )
        insight_rows = result.fetchall()

        last_queried: Dict[str, datetime] = {}
        times_queried: Dict[str, int] = defaultdict(int)

        for meta, created_at in insight_rows:
            if not isinstance(meta, dict):
                continue
            tables = meta.get("tables_queried") or []
            for tbl in tables:
                if not tbl:
                    continue
                times_queried[tbl] += 1
                if tbl not in last_queried:
                    ts = created_at
                    if ts is not None and getattr(ts, "tzinfo", None) is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    last_queried[tbl] = ts

        # ── 2. Depth combos ───────────────────────────────────────────────────
        result = await db.execute(
            text(
                "SELECT metadata->>'logical_name', text "
                "FROM embeddings "
                "WHERE space_id = CAST(:sid AS uuid) "
                "AND metadata->>'kind' = 'depth_tracker'"
            ),
            {"sid": space_id},
        )
        depth_rows = result.fetchall()

        combos_per_table: Dict[str, set] = defaultdict(set)
        for logical_name, text_val in depth_rows:
            if not logical_name or not text_val:
                continue
            try:
                combo_list = json.loads(text_val)
                # Access defaultdict entry so table is tracked even with 0 combos
                _ = combos_per_table[logical_name]
                for c in combo_list:
                    if len(c) == 2:
                        combos_per_table[logical_name].add((c[0], c[1]))
            except Exception:
                continue

        # ── 3. Row count snapshots ────────────────────────────────────────────
        result = await db.execute(
            text(
                "SELECT metadata->>'logical_name', (metadata->>'row_count')::int, created_at "
                "FROM embeddings "
                "WHERE space_id = CAST(:sid AS uuid) "
                "AND metadata->>'kind' = 'row_count_snapshot' "
                "ORDER BY created_at DESC"
            ),
            {"sid": space_id},
        )
        snapshot_rows = result.fetchall()

        latest_row_count: Dict[str, int] = {}
        for logical_name, row_count, _ in snapshot_rows:
            if (
                logical_name
                and row_count is not None
                and logical_name not in latest_row_count
            ):
                latest_row_count[logical_name] = int(row_count)

        # ── 4. Combine ────────────────────────────────────────────────────────
        all_tables = (
            set(times_queried.keys())
            | set(combos_per_table.keys())
            | set(latest_row_count.keys())
        )

        coverage = []
        for tbl in sorted(all_tables):
            combos = combos_per_table.get(tbl, set())
            combo_count = len(combos)

            # depth_remaining_pct: 100 when pristine, falls as more combos explored
            # Use a rough estimate based on total possible pairs from row-count proxy
            # (real column data not available here; use combo count as proxy)
            # If 0 combos explored → 100%; each combo explored reduces by estimated amount
            # We cap the estimate at 20 possible combos (typical table) for the pct calc.
            ASSUMED_POSSIBLE = 20
            depth_pct = max(
                0,
                int(
                    100 * (1.0 - min(combo_count, ASSUMED_POSSIBLE) / ASSUMED_POSSIBLE)
                ),
            )

            lq = last_queried.get(tbl)
            coverage.append(
                {
                    "logical_name": tbl,
                    "last_queried_at": lq.isoformat() if lq else None,
                    "times_queried": times_queried.get(tbl, 0),
                    "combos_explored": combo_count,
                    "latest_row_count": latest_row_count.get(tbl),
                    "depth_remaining_pct": depth_pct,
                }
            )

        # Sort: most recently queried first, then never-queried alphabetically
        coverage.sort(
            key=lambda x: (
                x["last_queried_at"] is None,
                x["last_queried_at"] or "",
                x["logical_name"],
            ),
            reverse=False,
        )
        # Actually: queried tables first (sorted by recency desc), then unqueried
        queried = [c for c in coverage if c["last_queried_at"] is not None]
        unqueried = [c for c in coverage if c["last_queried_at"] is None]
        queried.sort(key=lambda x: x["last_queried_at"], reverse=True)
        unqueried.sort(key=lambda x: x["logical_name"])

        return queried + unqueried

    except Exception as exc:
        logger.warning("build_coverage_report failed: %s", exc)
        return []
