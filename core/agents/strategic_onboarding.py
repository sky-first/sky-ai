# core/agents/strategic_onboarding.py
"""Item 32 — Strategic onboarding: suggest OKRs when the brain is empty.

When /discover runs for the first time and no brain documents (OKRs/KPIs/pillars)
exist for the space, this module:
  1. Inspects the discovered dataset names and column types.
  2. Asks an LLM to suggest 3-5 OKRs the organisation likely tracks.
  3. Persists the suggestions as EmbeddingRecord rows (kind='okr_suggestion').

The frontend can display these suggestions so the user can adopt or customise
them when filling in the brain — removing the blank-page problem.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Types that count as "brain has content"
_BRAIN_TYPES = {"pillar", "okr", "kpi", "metric", "business_context"}


async def is_brain_empty(db: AsyncSession, space_id: str) -> bool:
    """Return True when the space has no brain documents (OKRs/KPIs/pillars).

    Falls back to True (treat as empty) on DB error — safe default that
    triggers onboarding rather than suppressing it.
    """
    if not space_id:
        return True
    try:
        result = await db.execute(
            text(
                "SELECT COUNT(*) FROM embeddings "
                "WHERE space_id = CAST(:sid AS uuid) "
                "AND metadata->>'type' = ANY(:types)"
            ),
            {"sid": space_id, "types": list(_BRAIN_TYPES)},
        )
        count = result.scalar() or 0
        return int(count) == 0
    except Exception as exc:
        logger.debug("is_brain_empty check failed (treating as empty): %s", exc)
        return True


def suggest_okrs_from_datasets(
    table_names: List[str],
    llm: Any = None,
) -> List[Dict[str, str]]:
    """Ask an LLM to suggest OKRs based on the detected dataset names.

    Returns a list of suggestion dicts:
      [{"title": "...", "type": "okr|kpi|pillar", "category": "..."}]

    Falls back to a short generic list when the LLM is unavailable or fails.
    """
    if not table_names:
        return _generic_suggestions()

    compact = ", ".join(t.split(".")[-1].replace("_", " ") for t in table_names[:20])
    prompt = (
        "You are a business analyst helping a company set up their data strategy.\n"
        "Based on the following dataset names detected in their data warehouse, "
        "suggest 4-5 OKRs or KPIs they likely track.\n\n"
        f"DATASETS: {compact}\n\n"
        'Return ONLY valid JSON — a list of objects with keys "title", "type", "category".\n'
        '"type" must be one of: okr, kpi, pillar\n'
        '"category" is a short tag like: revenue, growth, retention, operations, product\n'
        "Example: "
        '[{"title": "Grow MRR by 20% this quarter", "type": "okr", "category": "revenue"}]\n'
        "Return 4-5 items. JSON only, no markdown."
    )

    if llm is None:
        return _generic_suggestions()

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

        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError("expected a list")

        suggestions = []
        for item in parsed[:6]:
            if not isinstance(item, dict) or "title" not in item:
                continue
            suggestions.append(
                {
                    "title": str(item.get("title", ""))[:300],
                    "type": str(item.get("type", "okr")).lower(),
                    "category": str(item.get("category", "general")).lower(),
                }
            )
        return suggestions if suggestions else _generic_suggestions()

    except Exception as exc:
        logger.debug("suggest_okrs_from_datasets LLM call failed: %s", exc)
        return _generic_suggestions()


async def save_okr_suggestions(
    db: AsyncSession,
    space_id: str,
    suggestions: List[Dict[str, str]],
) -> None:
    """Persist OKR suggestions to the embeddings table (kind='okr_suggestion').

    Old suggestions for the space are deleted first so re-running discover
    doesn't accumulate stale recommendations.
    """
    if not suggestions or not space_id:
        return
    try:
        from db.models import EmbeddingRecord
        from uuid import uuid4, UUID as _UUID

        space_uuid = _UUID(space_id)

        # Clear old suggestions for this space (idempotent re-runs)
        await db.execute(
            text(
                "DELETE FROM embeddings "
                "WHERE space_id = CAST(:sid AS uuid) "
                "AND metadata->>'kind' = 'okr_suggestion'"
            ),
            {"sid": space_id},
        )

        for s in suggestions:
            db.add(
                EmbeddingRecord(
                    id=uuid4(),
                    space_id=space_uuid,
                    user_id=None,
                    embedding=[0.0] * 1024,
                    text=s["title"],
                    extra_metadata={
                        "kind": "okr_suggestion",
                        "type": s.get("type", "okr"),
                        "category": s.get("category", "general"),
                    },
                )
            )

        await db.flush()
        logger.debug(
            "save_okr_suggestions: saved %d suggestions for space %s",
            len(suggestions),
            space_id,
        )

    except Exception as exc:
        logger.warning("save_okr_suggestions failed: %s", exc)
        try:
            await db.rollback()
        except Exception:
            pass


async def load_okr_suggestions(
    db: AsyncSession,
    space_id: str,
) -> List[Dict[str, str]]:
    """Load stored OKR suggestions for the given space.

    Returns a list of suggestion dicts, or [] if none exist.
    """
    if not space_id:
        return []
    try:
        result = await db.execute(
            text(
                "SELECT text, metadata FROM embeddings "
                "WHERE space_id = CAST(:sid AS uuid) "
                "AND metadata->>'kind' = 'okr_suggestion' "
                "ORDER BY created_at ASC"
            ),
            {"sid": space_id},
        )
        rows = result.fetchall()
        suggestions = []
        for title, meta in rows:
            if not title:
                continue
            suggestions.append(
                {
                    "title": title,
                    "type": (meta or {}).get("type", "okr"),
                    "category": (meta or {}).get("category", "general"),
                }
            )
        return suggestions
    except Exception as exc:
        logger.debug("load_okr_suggestions failed: %s", exc)
        return []


# ─── Fallback ────────────────────────────────────────────────────────────────


def _generic_suggestions() -> List[Dict[str, str]]:
    """Generic OKR suggestions when no dataset context is available."""
    return [
        {
            "title": "Grow monthly recurring revenue by 20% this quarter",
            "type": "okr",
            "category": "revenue",
        },
        {
            "title": "Reduce customer churn rate below 5% per month",
            "type": "kpi",
            "category": "retention",
        },
        {
            "title": "Increase active users by 15% month-over-month",
            "type": "okr",
            "category": "growth",
        },
        {
            "title": "Achieve NPS score above 50 across all customer segments",
            "type": "kpi",
            "category": "satisfaction",
        },
    ]
