"""Seed demo OKRs, pillars, KPIs and metrics into the brain (embeddings table).

Usage:
    python scripts/seed_demo_brain_docs.py [--space-id <uuid>] [--clear]

Defaults to the main Demo space (cb9d1501-...). Pass --clear to wipe existing
strategy docs for the space before re-seeding.

These records are picked up by _fetch_brain_context_sync() inside the
full_context_agent — the agent uses them to evaluate whether a data finding
is meaningful (goal gap, trend anomaly) or just noise (static fact).

Embeddings are seeded with a small random vector. The brain context sync path
does NOT use cosine similarity (it fetches by space_id + kind), so the vector
value does not affect retrieval. Run generate_embeddings.py afterwards if you
want real semantic search on these docs.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from uuid import UUID, uuid4

import numpy as np

sys.path.insert(0, ".")

from db.base import SyncSessionLocal
from db.models import EmbeddingRecord

DEFAULT_SPACE_ID = "cb9d1501-949a-4238-b0cd-2463a80ddefd"
EMBEDDING_DIM = 1024

DEMO_BRAIN_DOCS = [
    # ── Pillars ──────────────────────────────────────────────────────────
    {
        "type": "pillar",
        "name": "Revenue Growth",
        "text": (
            "Revenue Growth is the #1 strategic pillar for 2026. "
            "Target: grow ARR from $2.1M to $5M by Q4 2026 (+138%). "
            "Primary levers: new logo acquisition, upsell expansion, and pricing improvement."
        ),
    },
    {
        "type": "pillar",
        "name": "Customer Retention",
        "text": (
            "Customer Retention pillar: minimise churn and maximise lifetime value. "
            "Target NRR (Net Revenue Retention) of 120% for 2026. "
            "Every 1% churn reduction = $21k ARR saved."
        ),
    },
    # ── OKRs ─────────────────────────────────────────────────────────────
    {
        "type": "okr",
        "name": "Q2 2026 — Close 30 new accounts",
        "text": (
            "Objective: close 30 new enterprise accounts in Q2 2026. "
            "Key Results: (1) pipeline >120 qualified opportunities, "
            "(2) average sales cycle <45 days, "
            "(3) win rate >28% from Proposal to Closed Won."
        ),
    },
    {
        "type": "okr",
        "name": "Q2 2026 — Expand average deal size to $70k",
        "text": (
            "Objective: increase average deal size from $52k to $70k (+35%) in Q2 2026 "
            "by targeting enterprise tier. "
            "Current average deal size: $52,000. Target: $70,000. "
            "Upsell attach rate target: 40%."
        ),
    },
    {
        "type": "okr",
        "name": "Q2 2026 — Reduce churn to below 2%",
        "text": (
            "Objective: monthly customer churn below 2% for Q2 2026. "
            "Current churn: 3.2%. "
            "Key Results: (1) QBR coverage >80% of accounts, "
            "(2) health score >70 for all tier-1 accounts, "
            "(3) NPS >45."
        ),
    },
    # ── KPIs ─────────────────────────────────────────────────────────────
    {
        "type": "kpi",
        "name": "MRR (Monthly Recurring Revenue)",
        "text": (
            "KPI: MRR. Current value: $175,000/month. "
            "Target: $416,000/month by December 2026. "
            "Growth required: +15% month-over-month. "
            "Source: billing system."
        ),
    },
    {
        "type": "kpi",
        "name": "Sales Win Rate",
        "text": (
            "KPI: Win Rate from Qualified to Closed Won. "
            "Current: 24%. Target: 32% by Q4 2026. "
            "Industry benchmark: 28%. "
            "If we hit 32% we close 8 more deals per quarter without adding pipeline."
        ),
    },
    {
        "type": "kpi",
        "name": "Sales Cycle Length",
        "text": (
            "KPI: Average Sales Cycle. Current: 52 days. Target: 40 days by Q3 2026. "
            "Reduction levers: faster discovery, earlier legal engagement, "
            "champion enablement kits."
        ),
    },
    {
        "type": "kpi",
        "name": "Pipeline Coverage Ratio",
        "text": (
            "KPI: Pipeline Coverage = open opportunities value / quarterly revenue target. "
            "Current: 2.8x. Target: 4x. "
            "Coverage below 3x is an early warning signal for a miss."
        ),
    },
    # ── Metrics ──────────────────────────────────────────────────────────
    {
        "type": "metric",
        "name": "Lead-to-Opportunity Conversion",
        "text": (
            "Metric: Lead to Opportunity conversion rate. "
            "Current: 18%. Target: 25%. "
            "Main bottleneck: leads from Web (11% convert) vs Outbound (31% convert). "
            "Action: prioritise outbound prospecting."
        ),
    },
]


def seed(space_id: str, clear: bool) -> None:
    space_uuid = UUID(space_id)
    db = SyncSessionLocal()
    try:
        if clear:
            deleted = (
                db.query(EmbeddingRecord)
                .filter(
                    EmbeddingRecord.space_id == space_uuid,
                    EmbeddingRecord.extra_metadata.isnot(None),
                )
                .delete(synchronize_session=False)
            )
            print(f"Cleared {deleted} existing embedding records for space {space_id}")

        for doc in DEMO_BRAIN_DOCS:
            vec = (np.random.rand(EMBEDDING_DIM) * 0.01).tolist()
            record = EmbeddingRecord(
                id=uuid4(),
                space_id=space_uuid,
                crew_id=None,
                user_id=None,
                text=doc["text"],
                embedding=vec,
                extra_metadata={"type": doc["type"], "name": doc["name"]},
                created_at=datetime.now(timezone.utc),
            )
            db.add(record)

        db.commit()
        print(f"✅ Inserted {len(DEMO_BRAIN_DOCS)} brain docs into space {space_id}")

        # Quick verification
        from core.agents.full_context_agent import _fetch_brain_context_sync

        brain = _fetch_brain_context_sync(db, space_id, [])
        print(f"Brain context check: {len(brain)} chars fetched")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed demo brain docs (OKRs, KPIs, pillars)"
    )
    parser.add_argument("--space-id", default=DEFAULT_SPACE_ID)
    parser.add_argument(
        "--clear", action="store_true", help="Clear existing docs first"
    )
    args = parser.parse_args()
    seed(args.space_id, args.clear)
