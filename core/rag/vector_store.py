# core/rag/vector_store.py
from __future__ import annotations

from typing import List, Optional, Tuple
import json

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from db.models import EmbeddingRecord
from core.rag.embeddings import EmbeddingProvider
from core.logging_utils import log_event


def _is_pgvector_available(db: Session) -> bool:
    """Verifica se pgvector está disponível no banco"""
    try:
        db.execute(text("SELECT '[1,2,3]'::vector(3)"))
        return True
    except Exception:
        return False


def search_embeddings(
    db: Session,
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
    pgvector_available = _is_pgvector_available(db)
    
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

    # A API do pgvector-sqlalchemy permite expressões tipo:
    # EmbeddingRecord.embedding.l2_distance(query_vec)
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
        # Se falhar (ex: tipo não é vector), usar fallback
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
