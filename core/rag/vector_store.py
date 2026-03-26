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
):
    """
    Constrói a query base para buscar embeddings.
    
    Lógica de visualização:
    1. Se connection_id for fornecido (Busca Global/Híbrida):
       - Retorna embeddings da connection específica.
       - Inclui tanto embeddings do Space atual quanto Globais (space_id=NULL).
       - Exige JOIN com TableMetadata para verificar connection_id.
       
    2. Se connection_id NÃO for fornecido (Busca Legada/Local):
       - Retorna apenas embeddings do Space atual.
       - Comportamento padrão para compatibilidade.
    """
    query = select(EmbeddingRecord)
    
    if connection_id:
        # join opcional para incluir records sem tabela (knowledge graph, docs)
        query = query.outerjoin(TableMetadata, EmbeddingRecord.table_metadata_id == TableMetadata.id)
        
        # Filtro principal: (Space Local OR Global) AND (Pertence à Connection OR Não tem Tabela)
        query = query.filter(
            and_(
                or_(
                    EmbeddingRecord.space_id == space_id,
                    EmbeddingRecord.space_id.is_(None)
                ),
                or_(
                    TableMetadata.data_connection_id == connection_id,
                    EmbeddingRecord.table_metadata_id.is_(None)
                )
            )
        )
    else:
        # Filtro legado: Apenas Space Local
        query = query.filter(EmbeddingRecord.space_id == space_id)
        
    # Filtro de Crew (se aplicável ao registro)
    query = query.filter(
        or_(
            EmbeddingRecord.crew_id.is_(None),
            EmbeddingRecord.crew_id.in_(crew_ids) if crew_ids else False,
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
) -> List[EmbeddingRecord]:
    """
    Faz busca semântica em EmbeddingRecord usando pgvector.
    Suporta busca global se connection_id for fornecido.
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
                "fallback": "simple_filter",
            },
        )
        
        query = _build_embedding_base_query(space_id, crew_ids, connection_id)
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
        query = _build_embedding_base_query(space_id, crew_ids, connection_id)
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
        
        query = _build_embedding_base_query(space_id, crew_ids, connection_id)
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
) -> List[EmbeddingRecord]:
    """
    Versão síncrona de search_embeddings.
    Faz busca semântica em EmbeddingRecord usando pgvector (se disponível).
    Suporta busca global se connection_id for fornecido.
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
                "connection_id": connection_id,
                "fallback": "simple_filter",
            },
        )
        
        query = _build_embedding_base_query(space_id, crew_ids, connection_id)
        query = query.limit(top_k)
        
        try:
            result = db.execute(query)
            results: List[EmbeddingRecord] = list(result.scalars().all())
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            
            log_event(
                "search_embeddings_fallback_error",
                {"space_id": space_id, "error": str(e)[:500]},
            )
            return []
        
        return results

    # Busca vetorial com pgvector
    query_vec = embedding_provider.embed([query_text])[0]

    try:
        query = _build_embedding_base_query(space_id, crew_ids, connection_id)
        query = query.order_by(EmbeddingRecord.embedding.l2_distance(query_vec))
        query = query.limit(top_k)

        result = db.execute(query)
        results: List[EmbeddingRecord] = list(result.scalars().all())
    except Exception as e:
        log_event(
            "search_embeddings_vector_error",
            {
                "space_id": space_id,
                "error": str(e)[:500],
                "fallback": "simple_filter",
            },
        )
        
        query = _build_embedding_base_query(space_id, crew_ids, connection_id)
        query = query.limit(top_k)
        
        try:
            result = db.execute(query)
            results: List[EmbeddingRecord] = list(result.scalars().all())
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            
            return []

    log_event(
        "search_embeddings",
        {
            "space_id": space_id,
            "connection_id": connection_id,
            "query_preview": query_text[:200],
            "top_k": top_k,
            "num_results": len(results),
            "pgvector_enabled": pgvector_available,
        },
    )

    return results
