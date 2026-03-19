"""
Multi-Layer RAG System

Provides 5 specialized retrieval layers to enrich context for small CPU-based models:
1. Schema RAG - Table/column semantics
2. Metrics RAG - Business KPI definitions
3. Questions RAG - Past validated queries
4. Comments RAG - User clarifications
5. Glossary RAG - Domain terminology

Each layer uses pgvector embeddings for semantic search.

Performance: All layers are executed in PARALLEL via asyncio.gather.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Dict, Any
import re
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from core.rag.embeddings import EmbeddingProvider
from core.agents.generic_sql_agent import TableSchema
from core.logging_utils import log_event

logger = logging.getLogger(__name__)

# ThreadPool for sync fallbacks or non-async RAG layers
_rag_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="rag_layer")


# ============================================================================
# Layer 1: Schema RAG
# ============================================================================

async def retrieve_schema_rag(
    question: str,
    tables: List[TableSchema],
    embedding_provider: EmbeddingProvider,
    db: Optional[AsyncSession] = None,
    space_id: Optional[str] = None,
    crew_ids: Optional[List[str]] = None,
    top_k: int = 3
) -> List[str]:
    """
    Search into the embeddings table for relevant technical chunks (technical context).
    Supports multi-level filtering (Global, Space, Crew).
    """
    results = []
    
    # Trace level: Fallback basic table info from provided schemas
    for table in tables[:top_k]:
        table_info = f"{table.logical_name}: {len(table.columns)} columns"
        results.append(table_info)
    
    # Deep level: Vector search for Knowledge Graph and Table Metadata
    if db:
        try:
            # Embed question (ensure it's a list even for single string)
            embeddings = embedding_provider.embed_with_cache([question])
            embedding_list = embeddings[0] if embeddings else [0.0] * 768
            # Manual serialization for asyncpg with text()
            question_embedding = f"[{','.join(map(str, embedding_list))}]"
            
            # Hybrid query: Global nodes OR User Space nodes OR User Crew nodes
            query = text("""
                SELECT 
                    text
                FROM embeddings
                WHERE (
                    -- Global Level
                    (space_id IS NULL AND crew_id IS NULL)
                    OR
                    -- Space Level
                    (space_id = ANY(:space_ids) AND crew_id IS NULL)
                    OR
                    -- Crew Level
                    (space_id = ANY(:space_ids) AND crew_id = ANY(:crew_ids))
                )
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :top_k
            """)
            
            # Normalize inputs
            space_list = [space_id] if isinstance(space_id, str) and space_id else (space_id or [])
            space_list = [s for s in space_list if s]

            crew_list = crew_ids or []
            crew_list = [c for c in crew_list if c]

            # Provide default UUID to prevent ANY() crashes on empty arrays
            empty_uuid = "00000000-0000-0000-0000-000000000000"

            res = await db.execute(
                query,
                {
                    "space_ids": space_list if space_list else [empty_uuid],
                    "crew_ids": crew_list if crew_list else [empty_uuid],
                    "embedding": question_embedding,
                    "top_k": top_k
                }
            )
            rows = res.fetchall()
            
            for row in rows:
                results.append(row[0])
                
        except Exception as e:
            logger.error(f"Error in retrieve_schema_rag: {e}")
            log_event("schema_rag_error", {"error": str(e)[:200]})
    
    log_event("schema_rag_retrieved", {"count": len(results)})
    return results


# ============================================================================
# Other Layers (Placeholders)
# ============================================================================

def retrieve_metrics_rag(question: str, embedding_provider: EmbeddingProvider, **kwargs) -> List[str]:
    # TODO: Implement metrics retrieval
    return []

def retrieve_questions_rag(question: str, embedding_provider: EmbeddingProvider, **kwargs) -> List[str]:
    # TODO: Implement past questions retrieval
    return []

def retrieve_comments_rag(question: str, embedding_provider: EmbeddingProvider, **kwargs) -> List[str]:
    return []

def retrieve_glossary_rag(question: str, embedding_provider: EmbeddingProvider, **kwargs) -> List[str]:
    return []

# Unified Layer function to handle sync/async variety
async def _run_layer(fn, *args, **kwargs):
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    else:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_rag_executor, lambda: fn(*args, **kwargs))


# ============================================================================
# Parallel Orchestrator
# ============================================================================

async def retrieve_all_layers_async(
    question: str,
    tables: List[TableSchema],
    embedding_provider: EmbeddingProvider,
    db: Optional[AsyncSession] = None,
    space_id: Optional[str] = None,
    crew_ids: Optional[List[str]] = None,
    top_k: int = 3
) -> Dict[str, List[str]]:
    """
    Main entry point for multi-level RAG.
    """
    
    # Layer definitions
    tasks = {
        "schema_rag": retrieve_schema_rag(question, tables, embedding_provider, db, space_id, crew_ids, top_k=top_k),
        "metrics_rag": _run_layer(retrieve_metrics_rag, question, embedding_provider, space_id=space_id),
        "questions_rag": _run_layer(retrieve_questions_rag, question, embedding_provider, space_id=space_id),
        "comments_rag": _run_layer(retrieve_comments_rag, question, embedding_provider, space_id=space_id),
        "glossary_rag": _run_layer(retrieve_glossary_rag, question, embedding_provider, space_id=space_id)
    }
    
    results = {}
    keys = list(tasks.keys())
    values = await asyncio.gather(*[tasks[k] for k in keys])
    
    for i, key in enumerate(keys):
        results[key] = values[i]
        
    return results

def retrieve_all_layers_sync(
    question: str,
    tables: List[TableSchema],
    embedding_provider: EmbeddingProvider,
    db: Optional[AsyncSession] = None,
    space_id: Optional[str] = None,
    crew_ids: Optional[List[str]] = None,
) -> Dict[str, List[str]]:
    """Sync wrapper for use in standard contexts."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(asyncio.run, retrieve_all_layers_async(question, tables, embedding_provider, db, space_id, crew_ids))
                return fut.result()
        else:
            return loop.run_until_complete(retrieve_all_layers_async(question, tables, embedding_provider, db, space_id, crew_ids))
    except Exception:
        return asyncio.run(retrieve_all_layers_async(question, tables, embedding_provider, db, space_id, crew_ids))
