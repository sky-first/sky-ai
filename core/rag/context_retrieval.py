"""Legacy-shaped retrieval helper — now an adapter over the brain.

Historically this module ran its own per-connection vector search
against ``embeddings`` and formatted rows into the ``[TABLE METADATA]
…`` text blocks that the orchestrator + specialists expect. That
path still works, but with Phase 2 we want a SINGLE retrieval substrate
across every surface (chat, agents, Sherlock, Davinci). So this file
becomes a thin adapter: callers keep the same signature, but the
underlying work is ``context_brain.retrieve_context`` with the unified
searcher that reads both ``context_documents`` (new) and ``embeddings``
(legacy) tables.

The ``_sync`` variant is preserved for the orchestrator's LangGraph
node path. Internally it still uses the async brain via a throw-away
loop — SQLAlchemy's async session cannot be called from a sync
context, so that path remains on the existing ``search_embeddings``
helper for now (see inline note). When the orchestrator is converted
to async (Phase 2.6b), the sync variant can be removed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from core.logging_utils import log_event
from core.rag.brain_searcher import make_brain_searcher
from core.rag.context_brain import RankedDoc, Scope, retrieve_context
from core.rag.embeddings import EmbeddingProvider
from core.rag.knowledge_retrieval import retrieve_knowledge_context
from core.rag.vector_store import search_embeddings

logger = logging.getLogger(__name__)


# ───────────────────────── formatting helpers ─────────────────────────────
def _format_records(records: List[Any]) -> List[str]:
    """Legacy EmbeddingRecord → string block. Kept for the sync path."""
    contexts: List[str] = []
    for rec in records:
        meta_raw = rec.extra_metadata
        meta: Dict[str, Any] = meta_raw if isinstance(meta_raw, dict) else {}
        kind = meta.get("type") or meta.get("kind", "unknown")

        if kind == "table_metadata":
            header = (
                f"[TABLE METADATA] table={meta.get('table_name', 'unknown')} "
                f"column={meta.get('column_name', 'unknown')}"
            )
        elif kind == "document_chunk":
            header = f"[DOCUMENT] name={meta.get('document_name', 'unknown')}"
        elif kind == "api_schema":
            header = (
                f"[API] name={meta.get('api_name', 'unknown')} "
                f"endpoint={meta.get('endpoint', 'unknown')}"
            )
        elif kind == "business_context":
            header = (
                f"[BUSINESS CONTEXT] name={meta.get('name', 'unknown')} "
                f"entity_type={meta.get('entity_type', 'unknown')}"
            )
        else:
            header = f"[{str(kind).upper()}]"

        text = rec.text or ""
        contexts.append(f"{header}\n{text}")
    return contexts


def _format_ranked(ranked: List[RankedDoc]) -> List[str]:
    """Unified RankedDoc → legacy string-block format.

    Kept compatible with the old output so callers don't need to change
    their prompt templates. The kind header uses the brain's canonical
    labels (``goal`` / ``okr`` / ``table`` / ``column`` / …) instead of
    the legacy-only labels (``table_metadata``), which means prompts
    that switch on the header will see more kinds than before — exactly
    the point of unification.
    """
    blocks: List[str] = []
    for r in ranked:
        d = r.doc
        if d.kind == "table":
            header = f"[TABLE] name={d.title}"
        elif d.kind == "column":
            header = f"[COLUMN] name={d.title}"
        elif d.kind == "connection":
            header = f"[CONNECTION] name={d.title}"
        else:
            header = f"[{d.kind.upper()}] {d.title}"
        blocks.append(f"{header}\n{d.body}")
    return blocks


def _normalize_table_name(name: str) -> str:
    """Strip connection/schema prefixes: 'conn::schema.table' -> 'table'."""
    n = (name or "").split("::")[-1]
    return n.rsplit(".", 1)[-1].strip()


def _filter_ranked_by_authorized_tables(
    ranked: List[RankedDoc], authorized_tables: Optional[List[str]]
) -> List[RankedDoc]:
    """Drop table/column docs whose table is not in the backend allow-list.

    ``authorized_tables`` is the control-plane list the backend resolved for
    this user/crew. Table and column docs whose table isn't in it are removed
    so the RAG can't surface names/descriptions of another crew's tables.
    Non-table docs (goals, okrs, connections, documents) keep their own
    crew_id scoping and pass through. ``None`` means "no restriction".
    """
    if authorized_tables is None:
        return ranked
    allowed = {_normalize_table_name(t) for t in authorized_tables}
    kept: List[RankedDoc] = []
    for r in ranked:
        d = r.doc
        if d.kind not in ("table", "column"):
            kept.append(r)
            continue
        md = d.metadata if isinstance(d.metadata, dict) else {}
        tname = md.get("table_name") or (d.title if d.kind == "table" else None)
        if tname and _normalize_table_name(tname) in allowed:
            kept.append(r)
        # else: a table/column we can't attribute to an authorized table → drop
    return kept


# ─────────────────────────── public API ───────────────────────────────────
async def build_retrieval_context_for_question(
    db: AsyncSession,
    embedding_provider: EmbeddingProvider,
    space_id: str,
    crew_ids: Optional[List[str]],
    question: str,
    top_k: int = 20,
    connection_id: Optional[str] = None,
    intent: Optional[str] = None,
    kinds: Optional[List[str]] = None,
    is_personal: bool = False,
    user_id: Optional[str] = None,
    allowed_document_ids: Optional[List[str]] = None,
    mentioned_file_ids: Optional[List[str]] = None,
    caller_space_ids: Optional[List[str]] = None,
    authorized_tables: Optional[List[str]] = None,
) -> tuple[List[str], List]:
    """Unified retrieval — reads context_documents, legacy embeddings,
    and knowledge_file_chunks (Knowledge Library).

    Returns ``(context_blocks, citations)`` where citations is a list of
    ``api.schemas.Citation`` objects populated only when knowledge chunks
    were retrieved. Callers that previously received just List[str] can
    ignore the second element.
    """
    searcher = make_brain_searcher(
        db=db,
        embedding_provider=embedding_provider,
        space_id=space_id,
        crew_ids=crew_ids,
        connection_id=connection_id,
        is_personal=is_personal,
        user_id=user_id,
        allowed_document_ids=allowed_document_ids,
        caller_space_ids=caller_space_ids,
    )

    async def _qe(q: str):
        try:
            vec = await embedding_provider.embed_async([q])
            return vec[0] if vec else None
        except Exception:
            logger.exception("query embedding failed — falling back to text search")
            return None

    # Run table/doc retrieval and knowledge retrieval concurrently
    import asyncio as _asyncio

    brain_task = _asyncio.ensure_future(
        retrieve_context(
            question,
            Scope(user_id=user_id, space_id=space_id, crew_ids=list(crew_ids or [])),
            searcher=searcher,
            query_embedder=_qe,
            kinds=kinds,
            k=top_k,
            intent=intent,
        )
    )

    knowledge_task = _asyncio.ensure_future(
        retrieve_knowledge_context(
            db=db,
            embedding_provider=embedding_provider,
            question=question,
            user_id=user_id,
            space_id=space_id,
            crew_ids=crew_ids,
            mentioned_file_ids=mentioned_file_ids,
            top_k=6,
            is_personal=is_personal,
        )
    )

    ranked, (knowledge_blocks, citations) = await _asyncio.gather(
        brain_task, knowledge_task
    )

    if not ranked and not knowledge_blocks:
        log_event(
            "context_retrieval_empty",
            {
                "space_id": space_id,
                "connection_id": connection_id,
                "question_len": len(question or ""),
            },
        )
        return [], []

    # Control-plane: drop table/column hits the user isn't authorized for, so
    # the RAG context can't leak another crew's table names/descriptions.
    if ranked:
        ranked = _filter_ranked_by_authorized_tables(ranked, authorized_tables)

    table_blocks = _format_ranked(ranked) if ranked else []

    # Knowledge blocks prepended so mentioned files surface prominently
    combined = knowledge_blocks + table_blocks
    return combined, citations


def build_retrieval_context_for_question_sync(
    db: Session,
    embedding_provider: EmbeddingProvider,
    space_id: str,
    crew_ids: Optional[List[str]],
    question: str,
    top_k: int = 20,
    connection_id: Optional[str] = None,
) -> List[str]:
    """Sync variant for the LangGraph orchestrator node.

    Still runs against the legacy ``search_embeddings`` path. The
    orchestrator node will be converted to async in Phase 2.6b; when
    that happens this function goes away and all callers land on the
    async unified path above.
    """
    records = search_embeddings(
        db=db,
        embedding_provider=embedding_provider,
        space_id=space_id,
        crew_ids=crew_ids,
        query_text=question,
        top_k=top_k,
        connection_id=connection_id,
    )
    if not records:
        return []
    return _format_records(records)
