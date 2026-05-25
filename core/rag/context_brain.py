"""Context-layer retrieval — Phase 2.5.

This is the *brain* retrieval path described in §3.6 of the agent
master plan. It blends every kind of context document (strategy,
events, relationships, platform fabric, connections, outputs) under
RBAC scope, ranks with a hybrid score (cosine + BM25 + recency +
intent-weighted kind bonus), and hands the supervisor / specialists
a single list of evidence.

It is a *new* entry point alongside the existing
``core/rag/context_retrieval.py`` — we do not rewrite the connection-
only path yet (still used in the 3-node orchestrator for data
questions). Phase 2.6 will wire the supervisor to call this one
first.

The implementation here is provider-agnostic in the test-ready sense:
it takes a ``searcher`` callable (hybrid + vector search against
context_documents) and a ``query_embedder`` callable. Both have
default Postgres / provider implementations, but tests can pass fakes
to cover the ranking maths without a DB.

PII handling: documents flagged with pii_flags ARE returned (the
retrieval layer doesn't mask), but they carry their flags through so
the response filter (core.security.response_filter) can redact
cell-level values at render time. Never mask here — we'd lose signal
the supervisor needs.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, Optional, Sequence

logger = logging.getLogger(__name__)


# ───────────────────────────── data types ─────────────────────────────────
@dataclass
class Scope:
    user_id: Optional[str] = None
    space_id: Optional[str] = None
    crew_ids: list[str] = field(default_factory=list)


@dataclass
class CandidateDoc:
    """Row-shaped struct returned by the search layer."""

    id: str
    kind: str
    source_table: str
    source_id: str
    title: str
    body: str
    metadata: dict[str, Any]
    space_id: Optional[str]
    crew_id: Optional[str]
    owner_user_id: Optional[str]
    visibility: str
    pii_flags: list[str]
    updated_at: datetime
    # Scoring signals supplied by the searcher (if not present, zero).
    cosine: float = 0.0
    bm25: float = 0.0


@dataclass
class RankedDoc:
    doc: CandidateDoc
    score: float
    components: dict[str, float]


# ──────────────────────── default intent weights ──────────────────────────
# Additive bonus per kind, indexed by supervisor-classified intent. These
# are starting points informed by the master plan use cases — e.g. an
# "okrs vs finance" intent should pull Strategy docs a little harder than
# Signals — and will be tuned against the eval suite in Phase 2.7.
INTENT_WEIGHTS: dict[str, dict[str, float]] = {
    "strategy": {
        "pillar": 0.25,
        "goal": 0.25,
        "okr": 0.30,
        "initiative": 0.20,
        "kpi": 0.20,
        "risk": 0.15,
        "glossary": 0.10,
    },
    "events": {
        "event_internal": 0.30,
        "event_external": 0.30,
        "event_trend": 0.25,
        "event_macro": 0.20,
    },
    "data": {
        "connection": 0.25,
        "table": 0.35,
        "column": 0.30,
        "relationship": 0.15,
    },
    "relationships": {
        "relationship": 0.35,
        "table": 0.20,
        "column": 0.15,
    },
    "people": {
        "user": 0.30,
        "crew": 0.25,
        "space": 0.20,
        "membership": 0.20,
        "role": 0.10,
    },
    "widgets": {
        "widget": 0.30,
        "insight": 0.30,
        "pin": 0.20,
        "conversation": 0.15,
        "message": 0.10,
    },
}


# ────────────────────────── RBAC filter ───────────────────────────────────
def _rbac_allows(doc: CandidateDoc, scope: Scope) -> bool:
    """Hard RBAC filter — run BEFORE scoring so a blocked doc never
    occupies a slot in the top-k.

    Rules (same as the backend's visibility semantics):
    - `public`: visible to everyone.
    - `space`: visible iff the scope's space_id matches.
    - `crew` : visible iff doc.crew_id is in scope.crew_ids.
    - `user` : visible iff doc.owner_user_id == scope.user_id.
    """
    v = (doc.visibility or "space").lower()
    if v == "public":
        return True
    if v == "space":
        return scope.space_id is not None and doc.space_id == scope.space_id
    if v == "crew":
        return bool(doc.crew_id) and doc.crew_id in (scope.crew_ids or [])
    if v == "user":
        return doc.owner_user_id is not None and doc.owner_user_id == scope.user_id
    return False


# ────────────────────────── scoring maths ─────────────────────────────────
# Component weights. Kept simple and explicit — this is not an ML model;
# the goal is to make the ranking *legible* so product owners can reason
# about why a document showed up.
ALPHA_COSINE = 0.55
BETA_BM25 = 0.25
GAMMA_INTENT = 0.15  # multiplied by the bonus for the doc's kind
DELTA_RECENCY = 0.05  # multiplied by recency_decay(updated_at)


def _recency_decay(updated_at: Optional[datetime]) -> float:
    if updated_at is None:
        return 0.0
    now = datetime.now(timezone.utc)
    age_days = max(
        0.0, (now - updated_at.astimezone(timezone.utc)).total_seconds() / 86_400.0
    )
    # Halving time ~ 30 days; shape chosen so a 30-day-old doc scores ~0.5.
    return math.exp(-age_days / 30.0)


def _score(doc: CandidateDoc, intent: Optional[str]) -> tuple[float, dict[str, float]]:
    cos = max(0.0, min(1.0, doc.cosine))
    bm = max(0.0, min(1.0, doc.bm25))
    intent_bonus = 0.0
    if intent:
        intent_bonus = INTENT_WEIGHTS.get(intent, {}).get(doc.kind, 0.0)
    rec = _recency_decay(doc.updated_at)
    score = (
        ALPHA_COSINE * cos
        + BETA_BM25 * bm
        + GAMMA_INTENT * intent_bonus
        + DELTA_RECENCY * rec
    )
    return score, {
        "cosine": cos,
        "bm25": bm,
        "intent_bonus": intent_bonus,
        "recency": rec,
    }


# ──────────────────────────── retrieval API ───────────────────────────────
Searcher = Callable[
    [str, Optional[Sequence[float]], Optional[Iterable[str]], int],
    "Awaitable[list[CandidateDoc]]",
]
QueryEmbedder = Callable[[str], "Awaitable[Optional[Sequence[float]]]"]


async def retrieve_context(
    query: str,
    scope: Scope,
    *,
    searcher: Searcher,
    query_embedder: QueryEmbedder,
    kinds: Optional[Iterable[str]] = None,
    k: int = 20,
    intent: Optional[str] = None,
    overfetch: int = 5,
) -> list[RankedDoc]:
    """Retrieve the top-k ranked context documents for ``query`` under
    ``scope``.

    ``searcher`` is called with ``(query, embedding_or_none, kinds, k*overfetch)``
    and is expected to return candidate docs pre-filled with cosine
    and bm25 scores. We over-fetch so that RBAC filtering doesn't
    leave us under-k.

    When ``query_embedder`` returns None (dim mismatch, provider down),
    we still call ``searcher`` — it should fall back to full-text only
    in that case.
    """
    embedding: Optional[Sequence[float]] = None
    try:
        embedding = await query_embedder(query)
    except Exception:
        logger.exception("query embedder failed — proceeding with text-only search")

    candidates = await searcher(query, embedding, kinds, k * max(1, overfetch))

    allowed = [c for c in candidates if _rbac_allows(c, scope)]

    ranked: list[RankedDoc] = []
    for doc in allowed:
        score, components = _score(doc, intent)
        ranked.append(RankedDoc(doc=doc, score=score, components=components))

    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked[:k]


# ────────────────────────── convenience: blend ────────────────────────────
def format_evidence(ranked: Iterable[RankedDoc]) -> str:
    """Turn a ranked list into the compact prompt form the supervisor
    injects before calling a specialist.

    We prefix each block with the kind in square brackets so the LLM
    can tell a ``[goal]`` apart from a ``[table]``, and the upstream
    response filter can trace back which kind contributed what.
    """
    blocks: list[str] = []
    for r in ranked:
        d = r.doc
        blocks.append(f"[{d.kind}] {d.title}\n{d.body}")
    return "\n\n".join(blocks)
