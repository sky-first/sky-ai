"""Scan Briefing — Directional context for the full_context_agent.

When the full_context_agent runs in scan mode (scheduled or on-demand),
this module prepares a BRIEFING that tells the agent:

  1. What the user has already seen (do NOT repeat)
  2. What gaps exist in coverage (explore these)
  3. Which scenario applies (4 combinations of history × brain context)

Scenario matrix:
  No history  + No brain  → free statistical exploration
  No history  + With brain → OKR-oriented panorama
  With history + No brain  → user blind spots
  With history + With brain → max value (blind spots aligned with strategy)

All functions are fail-safe: any exception returns "" / empty list so the
main query flow is never interrupted.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional
from uuid import UUID as _UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ─── Data Structures ──────────────────────────────────────────────────────


@dataclass
class TopicMap:
    covered: List[str] = field(default_factory=list)  # topics user asked about
    uncovered: List[str] = field(
        default_factory=list
    )  # topics present in data but not asked
    has_history: bool = False


# ─── Topic Extraction ─────────────────────────────────────────────────────


async def extract_chat_topics(
    db: AsyncSession,
    user_id: str,
    days: int = 7,
    llm: Any = None,
) -> TopicMap:
    """Read last N days of ChatHistory for user_id, extract topic clusters via LLM.

    Queries ChatHistory where thread_id LIKE '{user_id}-%' and role='user'
    and created_at > now - days. Uses the LLM to classify topics into
    covered (asked by user) and uncovered (likely present but not asked).

    Returns TopicMap(has_history=False) when no messages exist.
    Falls back to TopicMap(has_history=True, covered=[], uncovered=[]) on LLM error.
    """
    try:
        since = datetime.now(tz=timezone.utc) - timedelta(days=days)
        result = await db.execute(
            text(
                "SELECT content FROM chat_history "
                "WHERE thread_id LIKE :pattern AND role = 'user' "
                "AND created_at > :since "
                "ORDER BY created_at DESC LIMIT 100"
            ),
            {"pattern": f"{user_id}-%", "since": since},
        )
        rows = result.fetchall()

        if not rows:
            return TopicMap(has_history=False)

        messages = [row[0] for row in rows if row[0]]
        if not messages:
            return TopicMap(has_history=False)

        # Build a compact text block for the LLM
        sample = "\n".join(f"- {m[:200]}" for m in messages[:30])
        prompt = (
            "Analyze these user questions and extract business topic clusters.\n\n"
            f"QUESTIONS:\n{sample}\n\n"
            "Return ONLY valid JSON with two arrays:\n"
            '{"covered": ["topic1", "topic2"], "uncovered": ["topic3", "topic4"]}\n\n'
            "- covered: topics the user has actively asked about\n"
            "- uncovered: related business topics NOT in these questions but "
            "likely present in a typical data warehouse "
            "(e.g., churn, cohorts, funnel, LTV, CAC, NPS)\n"
            "Return 3-6 items per array. JSON only, no markdown."
        )

        if llm is None:
            return TopicMap(has_history=True, covered=[], uncovered=[])

        try:
            chat_model = getattr(llm, "_chat", None) or llm
            if hasattr(chat_model, "invoke"):
                from langchain_core.messages import HumanMessage

                resp = chat_model.invoke([HumanMessage(content=prompt)])
                raw = resp.content if hasattr(resp, "content") else str(resp)
            elif hasattr(chat_model, "predict"):
                raw = chat_model.predict(prompt)
            else:
                raw = str(chat_model(prompt))

            # Strip markdown fences if present
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            parsed = json.loads(raw)
            covered = [str(t) for t in parsed.get("covered", [])][:6]
            uncovered = [str(t) for t in parsed.get("uncovered", [])][:6]
            return TopicMap(covered=covered, uncovered=uncovered, has_history=True)

        except Exception as llm_exc:
            logger.debug("extract_chat_topics LLM call failed: %s", llm_exc)
            return TopicMap(has_history=True, covered=[], uncovered=[])

    except Exception as exc:
        logger.debug("extract_chat_topics failed: %s", exc)
        return TopicMap(has_history=False)


# ─── Scan Run Counter ─────────────────────────────────────────────────────


async def count_scan_insights(db: AsyncSession, space_id: str) -> int:
    """Return the total number of scan_insight records for this space.

    Used by the cross-dataset cycle detector in connection_query.py:
    every CROSS_DATASET_EVERY_N runs the agent is forced to query one
    table per connected source instead of top-K from any source.
    """
    try:
        result = await db.execute(
            text(
                "SELECT COUNT(*) FROM embeddings "
                "WHERE space_id = :space_id "
                "AND metadata->>'type' = 'scan_insight'"
            ),
            {"space_id": space_id},
        )
        return int(result.scalar() or 0)
    except Exception as exc:
        logger.debug("count_scan_insights failed: %s", exc)
        return 0


# ─── Recent Scan Insights ─────────────────────────────────────────────────


async def load_recent_scan_insights(
    db: AsyncSession,
    space_id: str,
    user_id: Optional[str],
    limit: int = 5,
) -> List[str]:
    """Load recent scan insights from EmbeddingRecord.

    Filters by space_id and optionally user_id, where
    extra_metadata->>'type' = 'scan_insight'. Returns list of text strings.
    """
    try:
        params: dict = {"space_id": space_id, "limit": limit}
        user_filter = ""
        if user_id:
            user_filter = "AND user_id = :user_id "
            params["user_id"] = user_id

        result = await db.execute(
            text(
                "SELECT text FROM embeddings "
                "WHERE space_id = :space_id "
                + user_filter
                + "AND metadata->>'type' = 'scan_insight' "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            params,
        )
        rows = result.fetchall()
        return [row[0] for row in rows if row[0]]

    except Exception as exc:
        logger.debug("load_recent_scan_insights failed: %s", exc)
        return []


# ─── Semantic Deduplication ──────────────────────────────────────────────


async def is_semantic_duplicate(
    db: AsyncSession,
    space_id: str,
    embedding_vec: List[float],
    threshold: float = 0.85,
) -> bool:
    """Return True if any existing scan_insight for this space is semantically
    similar to the given embedding (cosine similarity >= threshold).

    Uses pgvector's cosine distance operator (<=>).  Falls back to False
    (never suppress) when pgvector is unavailable or the query fails.
    """
    if not embedding_vec or all(v == 0.0 for v in embedding_vec):
        return False

    try:
        vec_literal = "[" + ",".join(str(v) for v in embedding_vec) + "]"
        result = await db.execute(
            text(
                "SELECT 1 - (embedding <=> CAST(:vec AS vector)) AS similarity "
                "FROM embeddings "
                "WHERE space_id = CAST(:sid AS uuid) "
                "AND metadata->>'type' = 'scan_insight' "
                "ORDER BY embedding <=> CAST(:vec AS vector) "
                "LIMIT 1"
            ),
            {"vec": vec_literal, "sid": space_id},
        )
        row = result.fetchone()
        if row is None:
            return False
        similarity = row[0]
        if similarity is None or (
            isinstance(similarity, float) and similarity != similarity
        ):
            return False
        is_dup = float(similarity) >= threshold
        if is_dup:
            logger.debug(
                "is_semantic_duplicate: suppressed (similarity=%.3f)", similarity
            )
        return is_dup
    except Exception as exc:
        logger.debug(
            "is_semantic_duplicate: pgvector check failed (non-critical): %s", exc
        )
        try:
            await db.rollback()
        except Exception:
            pass
        return False


# ─── Save Scan Insight ────────────────────────────────────────────────────


async def save_scan_insight(
    db: AsyncSession,
    space_id: str,
    user_id: Optional[str],
    text_content: str,
    title: str = "",
    tables_queried: Optional[List[str]] = None,
    embedding: Optional[List[float]] = None,
) -> None:
    """Persist a generated insight to EmbeddingRecord for future deduplication.

    embedding: real vector from the embedding provider; falls back to a
    zero vector when not provided (no semantic dedup on that record).
    extra_metadata = {"type": "scan_insight", "title": title, "tables_queried": [...]}.
    tables_queried is consumed by DatasetPriorityScorer for staleness calculation.
    """
    try:
        from db.models import EmbeddingRecord
        from uuid import uuid4

        space_uuid: Optional[_UUID] = None
        if space_id:
            try:
                space_uuid = _UUID(space_id)
            except Exception:
                space_uuid = None

        stored_embedding = embedding if embedding else [0.0] * 1024

        # user_id is intentionally not set — insights are scoped by space_id.
        # Setting user_id would require the UUID to exist in the users table,
        # which we can't guarantee for system/scheduled runs.
        record = EmbeddingRecord(
            id=uuid4(),
            space_id=space_uuid,
            user_id=None,
            embedding=stored_embedding,
            text=text_content[:4000],
            extra_metadata={
                "type": "scan_insight",
                "title": title[:200],
                "tables_queried": tables_queried or [],
            },
        )
        db.add(record)
        await db.flush()  # persist in current transaction; get_db commits at end
        logger.debug("save_scan_insight: saved insight '%s'", title[:60])

    except Exception as exc:
        logger.warning("save_scan_insight failed: %s", exc)
        try:
            await db.rollback()
        except Exception:
            pass


# ─── Briefing Builder ─────────────────────────────────────────────────────


def build_scan_briefing(
    topic_map: TopicMap,
    brain_context: str,
    recent_insights: List[str],
    table_count: int,
    is_cross_dataset: bool = False,
) -> str:
    """Compose the directional briefing string injected into the agent's system prompt.

    Produces a structured block that tells the agent what scenario it is in,
    what has already been surfaced (deduplication), and a concrete direction
    for the current run.
    """
    has_history = topic_map.has_history
    has_brain = bool(brain_context and brain_context.strip())

    # ── Scenario header ───────────────────────────────────────────────────
    if not has_history and not has_brain:
        scenario_block = (
            "SCENARIO: Free Statistical Exploration\n"
            "No prior conversation history and no strategic context were found.\n"
            "Your mission: explore the available data freely and surface whatever\n"
            "is statistically interesting — trends, anomalies, outliers, or\n"
            "unexpected patterns. Think like a curious analyst on day 1."
        )
        direction = (
            "Pick the most data-rich table, run aggregations across multiple\n"
            "dimensions (time, segment, geography, product), and look for anything\n"
            f"that would surprise a smart executive reviewing {table_count} datasets\n"
            "for the first time."
        )

    elif not has_history and has_brain:
        scenario_block = (
            "SCENARIO: OKR-Oriented Panorama\n"
            "No prior conversation history exists, but strategic context is available.\n"
            "Your mission: give the executive a data-grounded status check against\n"
            "the organisation's stated goals, OKRs, and KPIs."
        )
        direction = (
            "Anchor your investigation to the OKRs and KPIs listed in ORGANISATION\n"
            "CONTEXT. For each key metric mentioned, find the actual current value\n"
            "in the data and compare it to the target. Surface the biggest gap\n"
            "or most positive momentum as your single insight."
        )

    elif has_history and not has_brain:
        covered = topic_map.covered
        uncovered = topic_map.uncovered
        covered_txt = (
            ", ".join(f'"{t}"' for t in covered) if covered else "general queries"
        )
        uncovered_txt = (
            ", ".join(f'"{t}"' for t in uncovered) if uncovered else "unexplored areas"
        )
        scenario_block = (
            "SCENARIO: User Blind Spots\n"
            f"The user has already explored: {covered_txt}.\n"
            f"Likely unexplored areas include: {uncovered_txt}.\n"
            "Your mission: investigate what the user has NOT yet seen."
        )
        direction = (
            f"Deliberately avoid repeating insights about {covered_txt}.\n"
            f"Instead, dig into {uncovered_txt}. Find a meaningful pattern\n"
            "in an area the user has overlooked — this is where the highest\n"
            "value of a proactive agent lies."
        )

    else:
        # has_history and has_brain
        covered = topic_map.covered
        uncovered = topic_map.uncovered
        covered_txt = (
            ", ".join(f'"{t}"' for t in covered) if covered else "general queries"
        )
        uncovered_txt = (
            ", ".join(f'"{t}"' for t in uncovered) if uncovered else "unexplored areas"
        )
        scenario_block = (
            "SCENARIO: Maximum Value — Blind Spots Aligned with Strategy\n"
            f"The user has already explored: {covered_txt}.\n"
            f"Likely unexplored areas include: {uncovered_txt}.\n"
            "Strategic context (OKRs, KPIs, pillars) is also available.\n"
            "Your mission: find a blind spot that ALSO connects to a stated\n"
            "strategic goal — the highest-value intersection."
        )
        direction = (
            f"Prioritise investigating {uncovered_txt} — areas the user has\n"
            "not yet explored. Cross-reference your finding with the OKRs and\n"
            "KPIs in ORGANISATION CONTEXT. Surface the one insight that is\n"
            "both novel to the user AND strategically relevant."
        )

    # ── Already-surfaced block ────────────────────────────────────────────
    if recent_insights:
        already_block_lines = []
        for insight in recent_insights[:5]:
            # Show first line / first 120 chars as a summary
            first_line = insight.strip().split("\n")[0][:120].strip("# ").strip()
            if first_line:
                already_block_lines.append(f"  - {first_line}")
        already_block = (
            "\nWHAT HAS ALREADY BEEN SURFACED (do NOT repeat these):\n"
            + "\n".join(already_block_lines)
            + "\n"
        )
    else:
        already_block = (
            "\nWHAT HAS ALREADY BEEN SURFACED: Nothing yet — this is the first scan.\n"
        )

    # ── Cross-dataset override note ───────────────────────────────────────
    cross_dataset_block = ""
    if is_cross_dataset:
        cross_dataset_block = (
            "\n⚡ CROSS-DATASET RUN:\n"
            "This is a special cycle. You have been given one table from each\n"
            "connected data source. Your primary goal is to find CORRELATIONS\n"
            "or CONTRASTS that span multiple sources — e.g., do sales trends\n"
            "align with marketing spend? Does web activity predict CRM conversions?\n"
            "Look for the story that only emerges when you cross datasets.\n"
        )

    # ── Assemble full briefing ────────────────────────────────────────────
    briefing = (
        "\n══════════════════════════════════════════\n"
        "SCAN BRIEFING — YOUR MISSION FOR THIS RUN:\n"
        "══════════════════════════════════════════\n"
        + scenario_block
        + "\n"
        + already_block
        + cross_dataset_block
        + "\nDIRECTION:\n"
        + direction
        + "\n══════════════════════════════════════════\n"
    )

    return briefing


# ─── Top-Level Orchestrator ───────────────────────────────────────────────


async def prepare_scan_briefing(
    db: AsyncSession,
    space_id: str,
    user_id: Optional[str],
    llm: Any,
    brain_context: str,
    table_count: int,
    is_cross_dataset: bool = False,
) -> str:
    """Orchestrate topic extraction + insight loading + briefing construction.

    Returns a formatted briefing string ready to be injected into the agent's
    system prompt, or "" on any error so the main flow is never interrupted.
    """
    try:
        # Extract what the user has already asked about
        topic_map = await extract_chat_topics(
            db=db,
            user_id=user_id or "",
            days=7,
            llm=llm,
        )

        # Load what the agent has already surfaced (for deduplication)
        recent_insights = await load_recent_scan_insights(
            db=db,
            space_id=space_id,
            user_id=user_id,
            limit=5,
        )

        # Build the directional briefing
        briefing = build_scan_briefing(
            topic_map=topic_map,
            brain_context=brain_context,
            recent_insights=recent_insights,
            table_count=table_count,
            is_cross_dataset=is_cross_dataset,
        )

        logger.debug(
            "prepare_scan_briefing: scenario=has_history=%s has_brain=%s "
            "recent_insights=%d table_count=%d",
            topic_map.has_history,
            bool(brain_context),
            len(recent_insights),
            table_count,
        )

        return briefing

    except Exception as exc:
        logger.warning("prepare_scan_briefing failed (returning empty): %s", exc)
        return ""
