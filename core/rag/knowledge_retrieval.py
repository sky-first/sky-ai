"""Vector search over knowledge_file_chunks with @mention boost.

This module is the RAG layer for the Knowledge Library. It queries
``knowledge_file_chunks`` using pgvector cosine similarity, applies a
configurable boost multiplier to chunks belonging to files explicitly
@mentioned by the user, and returns both context blocks (for the prompt)
and structured Citation objects (for the response meta).

The caller (context_retrieval.py) merges the returned blocks into the
existing retrieval context so that the orchestrator and specialist nodes
receive file context alongside table metadata with no protocol changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import Citation
from core.rag.embeddings import EmbeddingProvider
from db.models import KnowledgeFile, KnowledgeFileChunk

logger = logging.getLogger(__name__)

# Similarity score is in [0, 1] (cosine). Chunks below this threshold
# are discarded even after boosting.
_MIN_SCORE = 0.25

# Multiplier applied to mentioned-file chunks before re-ranking.
# 10× means a chunk at 0.45 sim beats an un-mentioned chunk at 0.90 * (1/10) = 0.09.
_MENTION_BOOST = 10.0

# Max characters taken from a chunk for the Citation excerpt.
_EXCERPT_MAX = 300


@dataclass
class KnowledgeHit:
    chunk: KnowledgeFileChunk
    file: KnowledgeFile
    score: float  # raw cosine similarity


async def retrieve_knowledge_context(
    db: AsyncSession,
    embedding_provider: EmbeddingProvider,
    question: str,
    *,
    user_id: Optional[str] = None,
    space_id: Optional[str] = None,
    crew_ids: Optional[List[str]] = None,
    mentioned_file_ids: Optional[List[str]] = None,
    top_k: int = 6,
    is_personal: bool = False,
) -> tuple[List[str], List[Citation]]:
    """Search knowledge chunks and return (context_blocks, citations).

    Scope rules (mirrors the backend's KnowledgeService):
    - ``personal`` chunks: only returned when ``is_personal=True`` and
      ``user_id`` matches the file owner.
    - ``crew`` chunks: returned when ``crew_ids`` contains the file's scope_id.
    - ``space`` chunks: returned when ``space_id`` matches the file's scope_id.
    - Mentioned files: always included regardless of top_k, if accessible.

    Returns empty lists on any retrieval error so the main query is never blocked.
    """
    if not question:
        return [], []

    try:
        query_vec = await _embed(embedding_provider, question)
    except Exception:
        logger.exception("knowledge_retrieval: embedding failed")
        return [], []

    if query_vec is None:
        return [], []

    try:
        hits = await _search(
            db=db,
            query_vec=query_vec,
            user_id=user_id,
            space_id=space_id,
            crew_ids=crew_ids,
            mentioned_file_ids=mentioned_file_ids or [],
            top_k=top_k,
            is_personal=is_personal,
        )
    except Exception:
        logger.exception("knowledge_retrieval: pgvector search failed")
        return [], []

    if not hits:
        return [], []

    context_blocks = _format_blocks(hits, mentioned_file_ids or [])
    citations = _make_citations(hits)
    return context_blocks, citations


# ─────────────────────────── internals ────────────────────────────────────

async def _embed(provider: EmbeddingProvider, text_: str) -> Optional[List[float]]:
    vecs = await provider.embed_async([text_])
    return vecs[0] if vecs else None


async def _search(
    db: AsyncSession,
    query_vec: List[float],
    *,
    user_id: Optional[str],
    space_id: Optional[str],
    crew_ids: Optional[Sequence[str]],
    mentioned_file_ids: Sequence[str],
    top_k: int,
    is_personal: bool,
) -> List[KnowledgeHit]:
    """Fetch candidate chunks via pgvector, apply boost, re-rank, prune."""

    # Build scope filter conditions as SQL.
    # We query more than top_k so that after boost re-ranking we still
    # return the desired number of results.
    prefetch = max(top_k * 4, 20)

    # Build the accessible file ID subquery via Python-side filtering
    # (avoids dynamic SQL injection risks from crew_ids list).
    file_ids_clause = _build_scope_filter(
        user_id=user_id,
        space_id=space_id,
        crew_ids=list(crew_ids or []),
        mentioned_file_ids=list(mentioned_file_ids),
        is_personal=is_personal,
    )

    if file_ids_clause is None:
        return []

    # Fetch files matching scope
    file_stmt = (
        select(KnowledgeFile)
        .where(file_ids_clause)
        .where(KnowledgeFile.status == "ready")
        .where(KnowledgeFile.deleted_at.is_(None))
    )
    file_result = await db.execute(file_stmt)
    accessible_files = {str(f.id): f for f in file_result.scalars().all()}

    if not accessible_files:
        return []

    # Always include mentioned files that are accessible
    accessible_ids = list(accessible_files.keys())

    # pgvector cosine similarity search — SQLAlchemy doesn't have a
    # native operator so we use text() with a parameterised query.
    # Cast the Python list to the postgres vector literal format.
    vec_literal = "[" + ",".join(str(v) for v in query_vec) + "]"

    chunk_stmt = (
        select(
            KnowledgeFileChunk,
            text(f"1 - (embedding <=> '{vec_literal}'::vector) AS score"),
        )
        .where(KnowledgeFileChunk.file_id.in_(accessible_ids))
        .where(KnowledgeFileChunk.embedding.isnot(None))
        .order_by(text(f"embedding <=> '{vec_literal}'::vector"))
        .limit(prefetch)
    )

    chunk_result = await db.execute(chunk_stmt)
    rows = chunk_result.all()

    if not rows:
        return []

    hits: List[KnowledgeHit] = []
    mentioned_set = set(str(fid) for fid in mentioned_file_ids)

    for chunk, raw_score in rows:
        raw_score = float(raw_score) if raw_score is not None else 0.0
        file = accessible_files.get(str(chunk.file_id))
        if file is None:
            continue

        effective_score = raw_score
        if str(chunk.file_id) in mentioned_set:
            effective_score = raw_score * _MENTION_BOOST

        if raw_score < _MIN_SCORE and str(chunk.file_id) not in mentioned_set:
            continue

        hits.append(KnowledgeHit(chunk=chunk, file=file, score=effective_score))

    # Re-rank by effective score (descending), take top_k
    hits.sort(key=lambda h: h.score, reverse=True)

    # Always keep all mentioned-file hits; cap the rest to top_k
    mentioned_hits = [h for h in hits if str(h.chunk.file_id) in mentioned_set]
    other_hits = [h for h in hits if str(h.chunk.file_id) not in mentioned_set]

    final = mentioned_hits + other_hits[:max(0, top_k - len(mentioned_hits))]
    return final[:top_k + len(mentioned_hits)]


def _build_scope_filter(
    *,
    user_id: Optional[str],
    space_id: Optional[str],
    crew_ids: List[str],
    mentioned_file_ids: List[str],
    is_personal: bool,
) -> Optional[object]:
    """Return a SQLAlchemy WHERE clause covering accessible file scopes."""
    from sqlalchemy import or_, and_

    clauses = []

    # Crew scope
    if crew_ids:
        clauses.append(
            and_(
                KnowledgeFile.scope == "crew",
                KnowledgeFile.scope_id.in_(crew_ids),
            )
        )

    # Space scope
    if space_id:
        clauses.append(
            and_(
                KnowledgeFile.scope == "space",
                KnowledgeFile.scope_id == space_id,
            )
        )

    # Personal scope — only when is_personal and we have a user_id
    if is_personal and user_id:
        clauses.append(
            and_(
                KnowledgeFile.scope == "personal",
                KnowledgeFile.user_id == user_id,
            )
        )

    if not clauses:
        return None

    return or_(*clauses)


def _format_blocks(hits: List[KnowledgeHit], mentioned_ids: List[str]) -> List[str]:
    mentioned_set = set(str(fid) for fid in mentioned_ids)
    blocks: List[str] = []
    for h in hits:
        label = "[REFERENCED BY USER] " if str(h.chunk.file_id) in mentioned_set else ""
        header = (
            f"{label}[KNOWLEDGE FILE] name={h.file.original_name}"
            f" chunk={h.chunk.chunk_index}"
            + (f" page={h.chunk.page_number}" if h.chunk.page_number else "")
        )
        blocks.append(f"{header}\n{h.chunk.text}")
    return blocks


def _make_citations(hits: List[KnowledgeHit]) -> List[Citation]:
    # Deduplicate by (file_id, chunk_index); keep highest score
    seen: dict[tuple, Citation] = {}
    for h in hits:
        key = (str(h.chunk.file_id), h.chunk.chunk_index)
        raw_score = min(h.score, 1.0)  # cap boosted score at 1.0 for display
        if key not in seen or raw_score > seen[key].score:
            seen[key] = Citation(
                file_id=str(h.chunk.file_id),
                file_name=h.file.original_name,
                chunk_index=h.chunk.chunk_index,
                page_number=h.chunk.page_number,
                excerpt=h.chunk.text[:_EXCERPT_MAX].strip(),
                score=round(raw_score, 4),
            )
    return list(seen.values())
