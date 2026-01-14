# core/rag/vector_store.py
from __future__ import annotations

from typing import List, Optional, Tuple, Union
import json
import asyncio

from sqlalchemy import or_, text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from db.models import EmbeddingRecord
from core.rag.embeddings import EmbeddingProvider
from core.logging_utils import log_event


async def _is_pgvector_available_async(db: AsyncSession) -> bool:
    """Verifica se pgvector está disponível no banco (async)"""
    try:
        await db.execute(text("SELECT '[1,2,3]'::vector(3)"))
        return True
    except Exception:
        return False


def _is_pgvector_available_sync(db: Session) -> bool:
    """Verifica se pgvector está disponível no banco (sync)"""
    try:
        db.execute(text("SELECT '[1,2,3]'::vector(3)"))
        return True
    except Exception:
        return False


async def search_embeddings_async(
    db: AsyncSession,
    embedding_provider: EmbeddingProvider,
    space_id: str,
    crew_ids: Optional[List[str]],
    query_text: str,
    top_k: int = 20,
) -> List[EmbeddingRecord]:
    """
    Faz busca semântica em EmbeddingRecord usando pgvector (se disponível).
    
    Se pgvector não estiver disponível, retorna resultados sem ordenação vetorial
    (apenas filtrados por space_id e crew_id).
    
    Isso é a base do seu RAG agnóstico por Space/Crew.
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
                "crew_ids": crew_ids,
                "query_preview": query_text[:200],
                "fallback": "simple_filter",
            },
        )
        
        query = (
            select(EmbeddingRecord)
            .filter(EmbeddingRecord.space_id == space_id)
            .filter(
                or_(
                    EmbeddingRecord.crew_id.is_(None),
                    EmbeddingRecord.crew_id.in_(crew_ids) if crew_ids else False,
                )
            )
            .limit(top_k)
        )
        
        try:
            result = await db.execute(query)
            results: List[EmbeddingRecord] = list(result.scalars().all())
        except Exception as e:
            # ✅ PATCH 3: CRITICAL - Rollback para não deixar transação abortada
            try:
                await db.rollback()
            except Exception:
                pass
            
            log_event(
                "search_embeddings_fallback_error",
                {"space_id": space_id, "error": str(e)[:500]},
            )
            return []
        
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
    query_vec = await embedding_provider.embed_async([query_text])
    query_vec = query_vec[0]

    # A API do pgvector-sqlalchemy permite expressões tipo:
    # EmbeddingRecord.embedding.l2_distance(query_vec)
    try:
        query = (
            select(EmbeddingRecord)
            .filter(EmbeddingRecord.space_id == space_id)
            .filter(
                or_(
                    EmbeddingRecord.crew_id.is_(None),
                    EmbeddingRecord.crew_id.in_(crew_ids) if crew_ids else False,
                )
            )
            .order_by(EmbeddingRecord.embedding.l2_distance(query_vec))
            .limit(top_k)
        )

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
        
        query = (
            select(EmbeddingRecord)
            .filter(EmbeddingRecord.space_id == space_id)
            .filter(
                or_(
                    EmbeddingRecord.crew_id.is_(None),
                    EmbeddingRecord.crew_id.in_(crew_ids) if crew_ids else False,
                )
            )
            .limit(top_k)
        )
        
        try:
            result = await db.execute(query)
            results: List[EmbeddingRecord] = list(result.scalars().all())
        except Exception as e:
            # ✅ PATCH 3: CRITICAL - Rollback em fallback também
            try:
                await db.rollback()
            except Exception:
                pass
            
            log_event(
                "search_embeddings_vector_fallback_error",
                {"space_id": space_id, "error": str(e)[:500]},
            )
            return []

    log_event(
        "search_embeddings",
        {
            "space_id": space_id,
            "crew_ids": crew_ids,
            "query_preview": query_text[:200],
            "top_k": top_k,
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
        # Fallback: busca simples sem ordenação vetorial
        log_event(
            "search_embeddings_no_pgvector",
            {
                "space_id": space_id,
                "crew_ids": crew_ids,
                "query_preview": query_text[:200],
                "fallback": "simple_filter",
            },
        )
        
        q = (
            db.query(EmbeddingRecord)
            .filter(EmbeddingRecord.space_id == space_id)
            .filter(
                or_(
                    EmbeddingRecord.crew_id.is_(None),
                    EmbeddingRecord.crew_id.in_(crew_ids) if crew_ids else False,
                )
            )
            .limit(top_k)
        )
        
        results: List[EmbeddingRecord] = q.all()
        
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
        q = (
            db.query(EmbeddingRecord)
            .filter(EmbeddingRecord.space_id == space_id)
            .filter(
                or_(
                    EmbeddingRecord.crew_id.is_(None),
                    EmbeddingRecord.crew_id.in_(crew_ids) if crew_ids else False,
                )
            )
            .order_by(EmbeddingRecord.embedding.l2_distance(query_vec))
            .limit(top_k)
        )

        results: List[EmbeddingRecord] = q.all()
    except Exception as e:
        log_event(
            "search_embeddings_vector_error",
            {
                "space_id": space_id,
                "error": str(e)[:500],
                "fallback": "simple_filter",
            },
        )
        
        q = (
            db.query(EmbeddingRecord)
            .filter(EmbeddingRecord.space_id == space_id)
            .filter(
                or_(
                    EmbeddingRecord.crew_id.is_(None),
                    EmbeddingRecord.crew_id.in_(crew_ids) if crew_ids else False,
                )
            )
            .limit(top_k)
        )
        
        results: List[EmbeddingRecord] = q.all()

    log_event(
        "search_embeddings",
        {
            "space_id": space_id,
            "crew_ids": crew_ids,
            "query_preview": query_text[:200],
            "top_k": top_k,
            "num_results": len(results),
            "pgvector_enabled": pgvector_available,
        },
    )

    return results
