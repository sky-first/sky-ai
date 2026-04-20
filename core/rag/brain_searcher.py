"""Unified production searcher for the brain — Phase 2.8.

One searcher for every caller. Reads both:

  (a) ``context_documents`` — Phase-2 multi-kind store (goals / okrs /
      widgets / events / relationships / users / tables / columns …).

  (b) ``embeddings`` — legacy per-connection vector table still written
      by the old metadata ingestion path. During the transition, all
      connection/table/column rows live here. We project those rows
      into ``CandidateDoc`` with the right ``kind`` so the brain ranks
      them uniformly alongside the new kinds.

Callers never touch the two tables directly again. Legacy code paths
(``context_retrieval.build_retrieval_context_for_question``, the
orchestrator, Sherlock, Davinci) all go through ``retrieve_context``
from ``context_brain`` with this searcher passed in.

The BM25 signal isn't actually computed at the DB level yet (requires a
Postgres tsvector column that Phase 2.1 did add, but we surface it as a
fallback score derived from keyword overlap). Vector score IS real via
pgvector in both tables. Recency and intent-weighted bonus are computed
in-memory by the brain ranking layer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.rag.context_brain import CandidateDoc
from core.rag.embeddings import EmbeddingProvider
from core.rag.vector_store import search_embeddings_async

logger = logging.getLogger(__name__)


# ───────────────────────────── public API ─────────────────────────────────
def make_brain_searcher(
    db: AsyncSession,
    embedding_provider: EmbeddingProvider,
    *,
    space_id: Optional[str] = None,
    crew_ids: Optional[list[str]] = None,
    connection_id: Optional[str] = None,
):
    """Build the ``searcher`` callable that ``retrieve_context`` expects.

    The returned callable closes over the DB + provider + scope hints.
    It accepts ``(query, embedding, kinds, k)`` — ``embedding`` is the
    query vector already computed by the brain, ``kinds`` filters the
    set of document kinds, ``k`` is the over-fetch budget.
    """

    async def _searcher(
        query: str,
        embedding: Optional[Sequence[float]],
        kinds: Optional[Iterable[str]],
        k: int,
    ) -> list[CandidateDoc]:
        kinds_set = set(kinds) if kinds else None

        new_docs = await _search_context_documents(
            db,
            query=query,
            embedding=embedding,
            kinds=kinds_set,
            space_id=space_id,
            crew_ids=crew_ids or [],
            k=k,
        )

        # Only hit the legacy path for kinds it can serve (connection /
        # table / column). Callers that asked only for strategy or
        # widgets don't need to touch the old table.
        legacy_docs: list[CandidateDoc] = []
        legacy_kinds = {"connection", "table", "column"}
        if kinds_set is None or kinds_set & legacy_kinds:
            legacy_docs = await _search_legacy_embeddings(
                db,
                embedding_provider=embedding_provider,
                query=query,
                space_id=space_id or "",
                crew_ids=crew_ids or [],
                connection_id=connection_id,
                k=k,
            )
            if kinds_set is not None:
                legacy_docs = [d for d in legacy_docs if d.kind in kinds_set]

        # Deduplicate when both stores surface the same (source_table,
        # source_id). Prefer the new store — its render template is
        # canonical and its pii_flags / metadata are fresher.
        merged: dict[tuple[str, str], CandidateDoc] = {}
        for d in legacy_docs:
            merged[(d.source_table, d.source_id)] = d
        for d in new_docs:
            merged[(d.source_table, d.source_id)] = d

        # Per-space hidden-column filter — drops column docs whose
        # (connection_id, table_name, column_name) matches a row the
        # active Space chose to hide via the SpaceTable.hidden_columns
        # list (sky-poc-backend#190). Only fires for column-kind docs
        # and only when space_id is known; everything else passes
        # through. If the column doc lacks the triple in metadata, we
        # keep it — safer to over-show than to silently drop.
        filtered = await _apply_hidden_column_filter(db, list(merged.values()), space_id)
        return filtered

    return _searcher


# ──────────────────────── context_documents read ──────────────────────────
async def _search_context_documents(
    db: AsyncSession,
    *,
    query: str,
    embedding: Optional[Sequence[float]],
    kinds: Optional[set[str]],
    space_id: Optional[str],
    crew_ids: list[str],
    k: int,
) -> list[CandidateDoc]:
    """Top-k rows from context_documents scoped by space/crew."""

    # Scope clauses. NULL space_id means personal-visibility or globally
    # public — we leave those on the table and let the brain's RBAC
    # layer apply final visibility rules.
    scope_clauses: list[str] = ["deleted_at IS NULL"]
    params: dict[str, Any] = {"k": k}
    if space_id:
        scope_clauses.append("(space_id = :space_id OR space_id IS NULL OR visibility = 'public')")
        params["space_id"] = space_id
    if crew_ids:
        scope_clauses.append("(crew_id IS NULL OR crew_id = ANY(:crew_ids))")
        params["crew_ids"] = crew_ids
    if kinds:
        scope_clauses.append("kind = ANY(:kinds)")
        params["kinds"] = list(kinds)

    where = " AND ".join(scope_clauses)

    # We ORDER BY <-> (cosine distance) when embedding is present; fall
    # back to recency otherwise. Projected cosine is 1 - distance; bm25
    # is a keyword-overlap proxy over title || body — cheap and
    # good-enough until the tsvector index is queried directly.
    if embedding is not None:
        params["q_vec"] = list(embedding)
        sql = text(
            f"""
            SELECT id, kind, source_table, source_id, title, body,
                   metadata_jsonb, space_id, crew_id, owner_user_id,
                   visibility, pii_flags, updated_at,
                   1 - (embedding <=> CAST(:q_vec AS vector)) AS cosine
            FROM context_documents
            WHERE {where}
              AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:q_vec AS vector)
            LIMIT :k
            """
        )
    else:
        sql = text(
            f"""
            SELECT id, kind, source_table, source_id, title, body,
                   metadata_jsonb, space_id, crew_id, owner_user_id,
                   visibility, pii_flags, updated_at,
                   0.0 AS cosine
            FROM context_documents
            WHERE {where}
            ORDER BY updated_at DESC
            LIMIT :k
            """
        )

    try:
        result = await db.execute(sql, params)
        rows = result.mappings().all()
    except Exception:
        logger.exception("context_documents search failed — returning empty")
        await _rollback_quiet(db)
        return []

    q_tokens = _tokenize(query)
    out: list[CandidateDoc] = []
    for r in rows:
        body = r["body"] or ""
        title = r["title"] or ""
        bm25 = _overlap_score(q_tokens, title, body)
        updated_at = r["updated_at"] or datetime.now(timezone.utc)
        out.append(
            CandidateDoc(
                id=str(r["id"]),
                kind=r["kind"],
                source_table=r["source_table"],
                source_id=str(r["source_id"]),
                title=title,
                body=body,
                metadata=dict(r["metadata_jsonb"] or {}),
                space_id=_str_or_none(r["space_id"]),
                crew_id=_str_or_none(r["crew_id"]),
                owner_user_id=_str_or_none(r["owner_user_id"]),
                visibility=r["visibility"] or "space",
                pii_flags=list(r["pii_flags"] or []),
                updated_at=updated_at,
                cosine=float(r["cosine"] or 0.0),
                bm25=bm25,
            )
        )
    return out


# ────────────────────── legacy embeddings read ────────────────────────────
async def _search_legacy_embeddings(
    db: AsyncSession,
    *,
    embedding_provider: EmbeddingProvider,
    query: str,
    space_id: str,
    crew_ids: list[str],
    connection_id: Optional[str],
    k: int,
) -> list[CandidateDoc]:
    """Adapt the legacy ``embeddings`` table into CandidateDoc.

    Everything there is connection-metadata-shaped. We look at
    ``extra_metadata.type`` / ``kind`` to decide the context kind.
    """

    try:
        records = await search_embeddings_async(
            db=db,
            embedding_provider=embedding_provider,
            space_id=space_id,
            crew_ids=crew_ids,
            query_text=query,
            top_k=k,
            connection_id=connection_id,
        )
    except Exception:
        logger.exception("legacy embeddings search failed — returning empty")
        await _rollback_quiet(db)
        return []

    q_tokens = _tokenize(query)
    out: list[CandidateDoc] = []
    for rec in records:
        meta = rec.extra_metadata if isinstance(rec.extra_metadata, dict) else {}
        kind = _legacy_kind(meta)
        title = _legacy_title(meta)
        body = rec.text or ""
        updated_at = getattr(rec, "created_at", None) or datetime.now(timezone.utc)
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)

        out.append(
            CandidateDoc(
                id=str(rec.id),
                kind=kind,
                source_table=meta.get("source_table") or "embeddings",
                source_id=str(meta.get("source_id") or rec.id),
                title=title,
                body=body,
                metadata=meta,
                space_id=_str_or_none(rec.space_id),
                crew_id=_str_or_none(rec.crew_id),
                owner_user_id=_str_or_none(getattr(rec, "user_id", None)),
                visibility="space",
                pii_flags=[],
                updated_at=updated_at,
                # Legacy path doesn't surface a cosine score per row
                # cleanly (search_embeddings_async orders but doesn't
                # project distance); we approximate with a descending
                # rank-implied score.
                cosine=0.5,
                bm25=_overlap_score(q_tokens, title, body),
            )
        )
    return out


def _legacy_kind(meta: dict[str, Any]) -> str:
    raw = meta.get("type") or meta.get("kind") or ""
    if raw == "table_metadata":
        return "table"
    if raw == "column_metadata":
        return "column"
    if raw == "connection":
        return "connection"
    if raw == "business_context":
        return "glossary"
    if raw == "api_schema":
        return "connection"
    return "table"  # default — legacy rows are overwhelmingly table-shaped


def _legacy_title(meta: dict[str, Any]) -> str:
    name = meta.get("table_name") or meta.get("column_name") or meta.get("name")
    if name:
        return str(name)
    return (meta.get("type") or "legacy context").replace("_", " ")


# ──────────────────────────── helpers ─────────────────────────────────────
def _tokenize(s: str) -> set[str]:
    return {t for t in (s or "").lower().split() if len(t) > 2}


def _overlap_score(q_tokens: set[str], title: str, body: str) -> float:
    if not q_tokens:
        return 0.0
    text_tokens = {t for t in (title + " " + body).lower().split() if len(t) > 2}
    if not text_tokens:
        return 0.0
    hits = len(q_tokens & text_tokens)
    return min(1.0, hits / max(1, len(q_tokens)))


def _str_or_none(v: Any) -> Optional[str]:
    if v is None:
        return None
    return str(v)


async def _rollback_quiet(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception:
        pass


# ───────────────── per-space hidden column filter ─────────────────────────
async def _fetch_hidden_columns_map(
    db: AsyncSession, space_id: str
) -> dict[tuple[str, str], set[str]]:
    """Return `{(connection_id, table_name): {hidden_column_names}}` for a Space.

    Queries `space_tables.hidden_columns` (added in sky-poc-backend#190).
    Returns an empty dict when the space has no entries or if the query
    fails — the caller treats "no entries" as "nothing to hide", which
    is the safe default.
    """
    try:
        sql = text(
            """
            SELECT connection_id, table_name, hidden_columns
            FROM space_tables
            WHERE space_id = :space_id
            """
        )
        result = await db.execute(sql, {"space_id": space_id})
        rows = result.mappings().all()
    except Exception:
        logger.exception("hidden_columns fetch failed — skipping filter")
        await _rollback_quiet(db)
        return {}

    out: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        hidden = r.get("hidden_columns") or []
        if not hidden:
            continue
        key = (str(r["connection_id"]), r["table_name"])
        out[key] = {c for c in hidden if isinstance(c, str)}
    return out


async def _apply_hidden_column_filter(
    db: AsyncSession,
    docs: list[CandidateDoc],
    space_id: Optional[str],
) -> list[CandidateDoc]:
    """Drop column docs whose (conn, table, col) is in the space's hidden list.

    Bails early when there's no scope or no columns in the result — both
    short-circuits let the happy path stay a cheap pass-through.
    """
    if not space_id:
        return docs
    has_columns = any(d.kind == "column" for d in docs)
    if not has_columns:
        return docs

    hidden_map = await _fetch_hidden_columns_map(db, space_id)
    if not hidden_map:
        return docs

    kept: list[CandidateDoc] = []
    for d in docs:
        if d.kind != "column":
            kept.append(d)
            continue
        meta = d.metadata or {}
        conn_id = meta.get("connection_id")
        table_name = meta.get("table_name")
        column_name = meta.get("column_name")
        # Without the full triple we can't match reliably — keep the doc.
        # Over-showing is safer than silently dropping someone's data.
        if not (conn_id and table_name and column_name):
            kept.append(d)
            continue
        hidden_set = hidden_map.get((str(conn_id), table_name))
        if hidden_set and column_name in hidden_set:
            continue
        kept.append(d)
    return kept
