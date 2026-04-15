"""Single entry point for surface-level brain access — Phase 2.9.

The three product surfaces that currently run their own retrieval —

  - Sherlock (chat bootstrap / suggestions)
  - Davinci  (dashboard plan)
  - the LangGraph query pipeline

should, going forward, all reach the brain through this helper. It
normalises the call-site ergonomics (per-surface defaults, intent
mapping, token-budget for prompt injection) so individual callers
don't each re-derive the same logic.

The LangGraph pipeline already pulls via the brain_retrieval_node
(Phase 2.6b). Sherlock and Davinci still run their own legacy
retrieval — a follow-up will swap their internals to call this helper
instead. The function is public and stable now so that swap is a
drop-in.

Keeping the call-site refactor OUT of this PR on purpose. The
connection_query.py file is ~4700 lines; a safe, well-tested drop-in
belongs in its own PR with the reviewer focused only on the swap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from core.rag.brain_searcher import make_brain_searcher
from core.rag.context_brain import Scope, format_evidence, retrieve_context
from core.rag.embeddings import EmbeddingProvider

logger = logging.getLogger(__name__)


Surface = Literal[
    "chat_bootstrap",    # Sherlock
    "chat_query",        # main query endpoint (LangGraph path already wired)
    "dashboard_plan",    # Davinci
    "agent_run",         # scheduled agent invocation
]


@dataclass
class BrainAccess:
    """Per-call bundle returned from ``fetch_brain_context_for_surface``.

    The call sites consume ``prompt_block`` and optionally ``evidence_ids``
    (to record what was retrieved on this surface's audit row, e.g.
    ``agent_executions.context_doc_ids`` for the agent_run surface).
    """

    surface: Surface
    doc_ids: list[str] = field(default_factory=list)
    doc_kinds: list[str] = field(default_factory=list)
    prompt_block: str = ""
    intent: Optional[str] = None

    @property
    def empty(self) -> bool:
        return not self.doc_ids


# Per-surface defaults. Tuned for the way each surface consumes the blob.
# - chat_bootstrap gets a tight 8-doc blend because suggestions must
#   fit inside Sherlock's concise prompt (tokens are precious there).
# - dashboard_plan gets a wider net so Davinci can see both strategy
#   and data tables in one pass.
# - chat_query / agent_run default to the LangGraph path's width.
_DEFAULT_K: dict[Surface, int] = {
    "chat_bootstrap": 8,
    "dashboard_plan": 30,
    "chat_query": 20,
    "agent_run": 20,
}

# Kind filters per surface. A question-suggestion assistant doesn't
# need every widget in the space, just the strategy/data shape. Davinci
# wants everything the brain has. Leaving ``None`` means "no filter".
_DEFAULT_KINDS: dict[Surface, Optional[list[str]]] = {
    "chat_bootstrap": ["pillar", "goal", "okr", "kpi", "table", "column", "connection"],
    "dashboard_plan": None,
    "chat_query": None,
    "agent_run": None,
}


async def fetch_brain_context_for_surface(
    *,
    surface: Surface,
    question: str,
    db: AsyncSession,
    embedding_provider: EmbeddingProvider,
    space_id: Optional[str],
    crew_ids: Optional[Iterable[str]] = None,
    user_id: Optional[str] = None,
    intent: Optional[str] = None,
    k: Optional[int] = None,
    kinds: Optional[Iterable[str]] = None,
    connection_id: Optional[str] = None,
) -> BrainAccess:
    """Fetch + format brain context ready for prompt injection.

    Never raises on retrieval-layer problems. An empty BrainAccess
    ``evidence`` is the caller's signal to fall back to its legacy
    behaviour — which is exactly what it did before this helper
    existed, so swapping is zero-risk.
    """
    question = (question or "").strip()
    if not question:
        return BrainAccess(surface=surface, intent=intent)

    effective_k = k if k is not None else _DEFAULT_K.get(surface, 20)
    effective_kinds = list(kinds) if kinds is not None else _DEFAULT_KINDS.get(surface)

    searcher = make_brain_searcher(
        db=db,
        embedding_provider=embedding_provider,
        space_id=space_id,
        crew_ids=list(crew_ids or []),
        connection_id=connection_id,
    )

    async def _qe(q: str) -> Optional[Sequence[float]]:
        try:
            vec = await embedding_provider.embed_async([q])
            return vec[0] if vec else None
        except Exception:
            logger.exception("embedding_provider failed for %s", surface)
            return None

    try:
        ranked = await retrieve_context(
            question,
            Scope(user_id=user_id, space_id=space_id, crew_ids=list(crew_ids or [])),
            searcher=searcher,
            query_embedder=_qe,
            intent=intent,
            kinds=effective_kinds,
            k=effective_k,
        )
    except Exception:
        logger.exception("brain retrieval failed for %s", surface)
        return BrainAccess(surface=surface, intent=intent)

    if not ranked:
        return BrainAccess(surface=surface, intent=intent)

    return BrainAccess(
        surface=surface,
        doc_ids=[r.doc.id for r in ranked],
        doc_kinds=[r.doc.kind for r in ranked],
        prompt_block=format_evidence(ranked),
        intent=intent,
    )


# ─── Prompt-injection helpers ─────────────────────────────────────────────
# Small, explicit helpers that Sherlock / Davinci / the specialists
# compose into their LLM prompts. Keeping them out of the shared
# retrieval path so each surface can phrase its system message to
# taste, while the BRAIN context is always introduced the same way.


def sherlock_context_section(access: BrainAccess) -> str:
    """Tight intro used by chat_bootstrap suggestions.

    Optimised for conciseness — Sherlock's prompt already has the
    table stats and the greeting, so the brain section must stay
    short. We surface pillars, goals, OKRs, KPIs so suggestions lean
    toward "what leadership cares about" rather than arbitrary tables.
    """
    if access.empty:
        return ""
    return (
        "<contexto_estrategico>\n"
        "Estes pilares / metas / OKRs / KPIs / tabelas já existem para este espaço:\n"
        f"{access.prompt_block}\n"
        "</contexto_estrategico>"
    )


def davinci_context_section(access: BrainAccess) -> str:
    """Wider intro used by the dashboard planner.

    Davinci is allowed to see everything — strategy docs help it pick
    widgets that track company goals, connection docs tell it which
    data sources are safe to suggest.
    """
    if access.empty:
        return ""
    return (
        "<contexto_da_empresa>\n"
        "Contexto relevante do space / crew (pilares, metas, OKRs, KPIs, conexões, tabelas, widgets existentes, eventos):\n"
        f"{access.prompt_block}\n"
        "</contexto_da_empresa>"
    )
