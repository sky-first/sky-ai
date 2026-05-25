# core/rag/vector_store.py
from __future__ import annotations

from typing import List, Optional, Tuple, Union
import json
import asyncio

from sqlalchemy import or_, text, select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from db.models import EmbeddingRecord, TableMetadata
from core.rag.embeddings import EmbeddingProvider
from core.logging_utils import log_event


async def _is_pgvector_available_async(db: AsyncSession) -> bool:
    """Verifica se pgvector está disponível no banco (async)"""
    try:
        await db.execute(text("SELECT '[1,2,3]'::vector(3)"))
        return True
    except Exception:
        # IMPORTANTE: Se falhar (pgvector não instalado), a transação do Postgres é abortada.
        # Precisamos dar rollback para poder continuar usando a mesma sessão no fallback.
        try:
            await db.rollback()
        except Exception:
            pass
        return False


def _is_pgvector_available_sync(db: Session) -> bool:
    """Verifica se pgvector está disponível no banco (sync)"""
    try:
        db.execute(text("SELECT '[1,2,3]'::vector(3)"))
        return True
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return False


def _build_embedding_base_query(
    space_id: str,
    crew_ids: List[str],
    connection_id: Optional[str] = None,
    *,
    is_personal: bool = False,
    user_id: Optional[str] = None,
    allowed_document_ids: Optional[List[str]] = None,
    caller_space_ids: Optional[List[str]] = None,
):
    """
    Constrói a query base para buscar embeddings.

    Personal vs Space isolation (security-critical):
    - is_personal=True + user_id: só retorna embeddings onde
      owner_user_id == user_id. Outros filtros (space/crew) são
      ignorados porque o dono está identificado univocamente.
    - is_personal=False: só retorna embeddings onde owner_user_id IS
      NULL (itens verdadeiramente Space/Crew-scoped). Isso impede que
      items Personal de outro usuário vazem pro contexto de um Space
      ou Crew, mesmo se o space_id coincidir.

    Lógica de connection (independente de Personal/Space):
    1. Se connection_id for fornecido:
       - JOIN opcional com TableMetadata.
       - Inclui embeddings da connection + globais (sem tabela).
    2. Se connection_id NÃO for fornecido:
       - Apenas embeddings do Space atual (comportamento legado).
    """
    query = select(EmbeddingRecord)

    if is_personal:
        if not user_id:
            # Defense-in-depth: Personal sem user_id nunca deve
            # acontecer. Forçamos "match nada" para não cair em
            # comportamento legado e expor dados de outras pessoas.
            return query.filter(False)
        # Personal mode owner-rule:
        #   • without connection_id → strict (only this user's items)
        #   • with connection_id → ALSO surface shared-content rows
        #     (`user_id IS NULL`), because:
        #       1. the connection has been authorised by the API gate
        #          (caller has a SpaceConnection bridge to it);
        #       2. embeddings of the connection's schema/samples are
        #          per-connection, not per-user — they get stamped
        #          NULL when the BE indexes a shared connection (e.g.
        #          the demo dataset, see BE PR #389).
        #     Without OR-NULL here, a demo visitor querying in
        #     Personal — which is the default landing for Member
        #     mission — never sees the shared embeddings and the AI
        #     answers "I couldn't find any data". The connection_id
        #     match below pins the result to this connection only, so
        #     another user's Personal items (with user_id != caller)
        #     are still excluded by the join + data_connection_id
        #     filter.
        if connection_id:
            query = query.outerjoin(
                TableMetadata,
                EmbeddingRecord.table_metadata_id == TableMetadata.id,
            )
            # Personal-mode owner clause has THREE branches:
            #   1. `user_id == caller`                           — my Personal items
            #   2. `user_id IS NULL AND space_id IS NULL`        — truly connection-level shared
            #   3. `user_id IS NULL AND space_id IN caller_space_ids`
            #                                                    — space-scoped content (glossary,
            #                                                      metrics, etc.) of spaces the
            #                                                      caller is a member of
            # Branches 2 and 3 stay paired because a bare
            # `user_id IS NULL` accepting any `space_id` would let a
            # tenant member peek at other spaces' content via Personal
            # mode (Lucas's 2026-05-05 review caught this).
            owner_clauses = [
                EmbeddingRecord.user_id == user_id,
                and_(
                    EmbeddingRecord.user_id.is_(None),
                    EmbeddingRecord.space_id.is_(None),
                ),
            ]
            if caller_space_ids:
                # Tenant safety: only accept NULL-user_id rows whose
                # space_id is one the caller actually belongs to.
                owner_clauses.append(
                    and_(
                        EmbeddingRecord.user_id.is_(None),
                        EmbeddingRecord.space_id.in_(caller_space_ids),
                    )
                )
            query = query.filter(
                and_(
                    or_(*owner_clauses),
                    or_(
                        TableMetadata.data_connection_id == connection_id,
                        EmbeddingRecord.table_metadata_id.is_(None),
                    ),
                )
            )
        else:
            # No connection scope → strict per-user (legacy behaviour
            # for Personal listing of one's own items, glossary etc.).
            query = query.filter(EmbeddingRecord.user_id == user_id)
        # Agent-pinned subset (Personal branch): same semantics as
        # Space/Crew — restrict to listed doc ids, but keep rows with
        # table metadata so the orchestrator still sees schema.
        if allowed_document_ids:
            query = query.filter(
                or_(
                    EmbeddingRecord.document_id.in_(allowed_document_ids),
                    EmbeddingRecord.table_metadata_id.isnot(None),
                )
            )
        return query

    # Space/Crew scope: exclude anyone's Personal items.
    query = query.filter(EmbeddingRecord.user_id.is_(None))

    if connection_id:
        query = query.outerjoin(
            TableMetadata,
            EmbeddingRecord.table_metadata_id == TableMetadata.id,
        )
        query = query.filter(
            and_(
                or_(
                    EmbeddingRecord.space_id == space_id,
                    EmbeddingRecord.space_id.is_(None),
                ),
                or_(
                    TableMetadata.data_connection_id == connection_id,
                    EmbeddingRecord.table_metadata_id.is_(None),
                ),
            )
        )
    else:
        query = query.filter(EmbeddingRecord.space_id == space_id)

    # Crew scope filter: NULL (space-global) or in caller's crew list.
    query = query.filter(
        or_(
            EmbeddingRecord.crew_id.is_(None),
            EmbeddingRecord.crew_id.in_(crew_ids) if crew_ids else False,
        )
    )

    # Agent-pinned subset: when the caller explicitly lists document
    # ids (via QueryRequest.selected_context flattened to a single
    # allowlist), restrict retrieval to those + any table_metadata
    # row (the orchestrator still needs schema regardless of the
    # pinned set). Applies to BOTH personal and space branches — the
    # if-branch above returns before reaching this point; we re-apply
    # symmetrically for personal below if invoked with ids.
    if allowed_document_ids:
        query = query.filter(
            or_(
                EmbeddingRecord.document_id.in_(allowed_document_ids),
                EmbeddingRecord.table_metadata_id.isnot(None),
            )
        )

    return query


async def search_embeddings_async(
    db: AsyncSession,
    embedding_provider: EmbeddingProvider,
    space_id: str,
    crew_ids: Optional[List[str]],
    query_text: str,
    top_k: int = 20,
    connection_id: Optional[str] = None,
    *,
    is_personal: bool = False,
    user_id: Optional[str] = None,
    allowed_document_ids: Optional[List[str]] = None,
    caller_space_ids: Optional[List[str]] = None,
) -> List[EmbeddingRecord]:
    """
    Faz busca semântica em EmbeddingRecord usando pgvector.
    Suporta busca global se connection_id for fornecido.

    Personal isolation: is_personal=True + user_id limita embeddings
    a owner_user_id == user_id. is_personal=False exclui qualquer
    embedding com owner_user_id preenchido (Personal de terceiros).
    """
    if crew_ids is None:
        crew_ids = []

    # Verificar se pgvector está disponível
    pgvector_available = await _is_pgvector_available_async(db)

    if not pgvector_available:
        # Fallback: busca simples sem ordenação vetorial
        log_event(
            "search_embeddings_no_pgvector",
            {
                "space_id": space_id,
                "connection_id": connection_id,
                "is_personal": is_personal,
                "fallback": "simple_filter",
            },
        )

        query = _build_embedding_base_query(
            space_id,
            crew_ids,
            connection_id,
            is_personal=is_personal,
            user_id=user_id,
            allowed_document_ids=allowed_document_ids,
            caller_space_ids=caller_space_ids,
        )
        query = query.limit(top_k)

        try:
            result = await db.execute(query)
            results: List[EmbeddingRecord] = list(result.scalars().all())
        except Exception as e:
            try:
                await db.rollback()
            except Exception:
                pass

            log_event(
                "search_embeddings_fallback_error",
                {"space_id": space_id, "error": str(e)[:500]},
            )
            return []

        return results

    # Busca vetorial com pgvector
    query_vec = await embedding_provider.embed_async([query_text])
    query_vec = query_vec[0]

    try:
        query = _build_embedding_base_query(
            space_id,
            crew_ids,
            connection_id,
            is_personal=is_personal,
            user_id=user_id,
            allowed_document_ids=allowed_document_ids,
            caller_space_ids=caller_space_ids,
        )
        query = query.order_by(EmbeddingRecord.embedding.l2_distance(query_vec))
        query = query.limit(top_k)

        result = await db.execute(query)
        results: List[EmbeddingRecord] = list(result.scalars().all())
    except Exception as e:
        # Se falhar (ex: tipo não é vector), usar fallback
        log_event(
            "search_embeddings_vector_error",
            {
                "space_id": space_id,
                "error": str(e)[:500],
                "fallback": "simple_filter",
            },
        )

        query = _build_embedding_base_query(
            space_id,
            crew_ids,
            connection_id,
            is_personal=is_personal,
            user_id=user_id,
            allowed_document_ids=allowed_document_ids,
            caller_space_ids=caller_space_ids,
        )
        query = query.limit(top_k)

        try:
            result = await db.execute(query)
            results: List[EmbeddingRecord] = list(result.scalars().all())
        except Exception as e:
            try:
                await db.rollback()
            except Exception:
                pass

            return []

    log_event(
        "search_embeddings",
        {
            "space_id": space_id,
            "connection_id": connection_id,
            "is_personal": is_personal,
            "query": query_text[:100],
            "num_results": len(results),
            "pgvector_enabled": pgvector_available,
        },
    )

    return results


def search_embeddings(
    db: Session,
    embedding_provider: EmbeddingProvider,
    space_id: str,
    crew_ids: Optional[List[str]],
    query_text: str,
    top_k: int = 20,
    connection_id: Optional[str] = None,
    *,
    is_personal: bool = False,
    user_id: Optional[str] = None,
    allowed_document_ids: Optional[List[str]] = None,
    caller_space_ids: Optional[List[str]] = None,
) -> List[EmbeddingRecord]:
    """
    Versão síncrona de search_embeddings.
    Faz busca semântica em EmbeddingRecord usando pgvector (se disponível).
    """
    if crew_ids is None:
        crew_ids = []

    # Verificar se pgvector está disponível
    pgvector_available = _is_pgvector_available_sync(db)

    if not pgvector_available:
        # Fallback: busca simples sem ordenação vetorial, mas ainda
        # com isolamento Personal/Space.
        log_event(
            "search_embeddings_no_pgvector",
            {
                "space_id": space_id,
                "crew_ids": crew_ids,
                "is_personal": is_personal,
                "query_preview": query_text[:200],
                "fallback": "simple_filter",
            },
        )

        q = _build_embedding_base_query(
            space_id,
            crew_ids,
            connection_id,
            is_personal=is_personal,
            user_id=user_id,
            allowed_document_ids=allowed_document_ids,
            caller_space_ids=caller_space_ids,
        )
        q = q.limit(top_k)
        results: List[EmbeddingRecord] = list(db.execute(q).scalars().all())

        log_event(
            "search_embeddings_fallback",
            {
                "space_id": space_id,
                "crew_ids": crew_ids,
                "query_preview": query_text[:200],
                "top_k": top_k,
                "num_results": len(results),
            },
        )

        return results

    # Busca vetorial com pgvector
    query_vec = embedding_provider.embed([query_text])[0]

    try:
        query_obj = _build_embedding_base_query(
            space_id,
            crew_ids,
            connection_id,
            is_personal=is_personal,
            user_id=user_id,
            allowed_document_ids=allowed_document_ids,
            caller_space_ids=caller_space_ids,
        )
        query_obj = query_obj.order_by(EmbeddingRecord.embedding.l2_distance(query_vec))
        query_obj = query_obj.limit(top_k)
        results = list(db.execute(query_obj).scalars().all())
    except Exception as e:
        log_event(
            "search_embeddings_vector_error",
            {
                "space_id": space_id,
                "error": str(e)[:500],
                "fallback": "simple_filter",
            },
        )

        query_obj = _build_embedding_base_query(
            space_id,
            crew_ids,
            connection_id,
            is_personal=is_personal,
            user_id=user_id,
            allowed_document_ids=allowed_document_ids,
            caller_space_ids=caller_space_ids,
        )
        query_obj = query_obj.limit(top_k)
        results = list(db.execute(query_obj).scalars().all())

    log_event(
        "search_embeddings",
        {
            "space_id": space_id,
            "connection_id": connection_id,
            "is_personal": is_personal,
            "query_preview": query_text[:200],
            "top_k": top_k,
            "num_results": len(results),
            "pgvector_enabled": pgvector_available,
        },
    )

    return results
