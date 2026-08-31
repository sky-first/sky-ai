"""
Multi-Layer RAG System

Provides specialized retrieval layers to enrich context for small CPU-based models:
1. Schema RAG - Table/column semantics (including Knowledge Graph context)
2. Metrics RAG - Business KPI definitions
3. Questions RAG - Past validated queries
4. Comments RAG - User clarifications
5. Glossary RAG - Domain terminology
6. Strategy RAG - Strategic Pillars, Goals, OKRs
7. Signals RAG - External and Internal Intelligence Signals

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
    top_k: int = 3,
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
            embeddings = await embedding_provider.embed_async([question])
            embedding_list = embeddings[0] if embeddings else [0.0] * 768

            # Manual serialization for pgvector format
            question_embedding = f"[{','.join(map(str, embedding_list))}]"

            # Duas camadas: o que é global, e o que é DO PROJETO.
            #
            # Eram três, e a do meio deixava linhas de fora: o nível do
            # projeto exigia `crew_id IS NULL`, e o da equipa exigia estar
            # naquela equipa exacta. Uma linha escrita com um `crew_id`
            # desaparecia de quem alcança o projeto e não está nessa equipa
            # — e a resposta saía sem a parte do contexto que a explicava,
            # sem nada no ecrã a dizer porquê.
            #
            # O projeto é a fronteira; a equipa é uma etiqueta (decisão de
            # 2026-08-27). Quem alcança o projeto vê o contexto do projeto,
            # tenha ele equipa escrita ou não.
            query = text("""
                SELECT 
                    text
                FROM embeddings
                WHERE (
                    -- Global
                    (space_id IS NULL AND crew_id IS NULL)
                    OR
                    -- Do projeto, com ou sem equipa escrita
                    (space_id = ANY(:space_ids))
                )
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :top_k
            """)

            # Normalize inputs
            space_list = (
                [space_id]
                if isinstance(space_id, str) and space_id
                else (space_id or [])
            )
            space_list = [uuid for uuid in space_list if uuid]

            # `crew_ids` já não entra na consulta — ver a nota nela. Fica no
            # contexto porque quem chama continua a passá-lo e os registos
            # ainda o querem.
            _ = crew_ids

            # Provide default UUID to prevent ANY() crashes on empty arrays
            empty_uuid = "00000000-0000-0000-0000-000000000000"

            res = await db.execute(
                query,
                {
                    "space_ids": space_list if space_list else [empty_uuid],
                    "embedding": question_embedding,
                    "top_k": top_k,
                },
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
# Layer 2: Metrics RAG
# ============================================================================


def retrieve_metrics_rag(
    question: str,
    embedding_provider: EmbeddingProvider,
    db: Optional[AsyncSession] = None,
    space_id: Optional[str] = None,
    top_k: int = 3,
) -> List[str]:
    """Retrieve business metric definitions."""
    results = []

    # Keyword-based fallback
    q_lower = question.lower()
    common_metrics = {
        "mrr": "MRR (Monthly Recurring Revenue): Sum of active subscription amounts per month",
        "arr": "ARR (Annual Recurring Revenue): MRR × 12",
        "churn": "Churn Rate: (Cancelled customers / Total customers) × 100",
        "cac": "CAC (Customer Acquisition Cost): Total marketing spend / New customers",
        "ltv": "LTV (Lifetime Value): Average revenue per customer × Average customer lifetime",
    }

    for keyword, definition in common_metrics.items():
        if keyword in q_lower:
            results.append(definition)
            if len(results) >= top_k:
                break

    return results


# ============================================================================
# Layer 3: Questions RAG
# ============================================================================


def retrieve_questions_rag(
    question: str,
    embedding_provider: EmbeddingProvider,
    db: Optional[AsyncSession] = None,
    space_id: Optional[str] = None,
    top_k: int = 3,
) -> List[str]:
    """Retrieve similar past questions with validated SQL."""
    return []


# ============================================================================
# Layer 4: Strategy RAG
# ============================================================================


async def retrieve_strategy_rag(
    question: str,
    embedding_provider: EmbeddingProvider,
    db: Optional[AsyncSession] = None,
    space_id: Optional[str] = None,
    crew_ids: Optional[List[str]] = None,
    top_k: int = 3,
) -> List[str]:
    """Retrieve strategic elements (Pillars, Objectives, OKRs, etc)."""
    results = []
    if not db:
        return results

    try:
        embeddings = await embedding_provider.embed_async([question])
        embedding_list = embeddings[0] if embeddings else [0.0] * 768
        question_embedding = f"[{','.join(map(str, embedding_list))}]"

        # Space filter logic
        space_list = (
            [space_id] if isinstance(space_id, str) and space_id else (space_id or [])
        )
        space_list = [s for s in space_list if s]
        empty_uuid = "00000000-0000-0000-0000-000000000000"

        # Query embeddings table with similarity search and multi-level filter
        query = text("""
            SELECT text
            FROM embeddings
            WHERE (
                (space_id IS NULL)
                OR
                (space_id = ANY(:space_ids))
            )
            AND (metadata->>'kind' = 'knowledge_graph')
            AND (metadata->>'entity_type' IN ('strategic_pillar', 'strategic_objective', 'strategy_okr', 'strategy_key_result', 'strategy_initiative', 'strategy_assumption', 'strategy_cycle'))
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
        """)

        res = await db.execute(
            query,
            {
                "space_ids": space_list if space_list else [empty_uuid],
                "embedding": question_embedding,
                "top_k": top_k,
            },
        )
        rows = res.fetchall()

        for row in rows:
            results.append(row[0])

    except Exception as e:
        logger.error(f"Error in retrieve_strategy_rag: {e}")
        log_event("strategy_rag_error", {"error": str(e)[:200]})

    return results


# ============================================================================
# Layer 5: Signals RAG
# ============================================================================


async def retrieve_signals_rag(
    question: str,
    embedding_provider: EmbeddingProvider,
    db: Optional[AsyncSession] = None,
    space_id: Optional[str] = None,
    crew_ids: Optional[List[str]] = None,
    top_k: int = 2,
) -> List[str]:
    """Retrieve external signals and events."""
    results = []
    if not db:
        return results

    try:
        embeddings = await embedding_provider.embed_async([question])
        embedding_list = embeddings[0] if embeddings else [0.0] * 768
        question_embedding = f"[{','.join(map(str, embedding_list))}]"

        space_list = (
            [space_id] if isinstance(space_id, str) and space_id else (space_id or [])
        )
        space_list = [s for s in space_list if s]
        empty_uuid = "00000000-0000-0000-0000-000000000000"

        query = text("""
            SELECT text
            FROM embeddings
            WHERE (
                (space_id IS NULL)
                OR
                (space_id = ANY(:space_ids))
            )
            AND (metadata->>'kind' = 'knowledge_graph')
            AND (metadata->>'entity_type' = 'signal_event')
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
        """)

        res = await db.execute(
            query,
            {
                "space_ids": space_list if space_list else [empty_uuid],
                "embedding": question_embedding,
                "top_k": top_k,
            },
        )
        rows = res.fetchall()

        for row in rows:
            results.append(row[0])

    except Exception as e:
        logger.error(f"Error in retrieve_signals_rag: {e}")
        log_event("signals_rag_error", {"error": str(e)[:200]})

    return results


# ============================================================================
# Utils & Orchestrator
# ============================================================================


async def _run_layer(fn, *args, **kwargs):
    """Unified Layer function to handle sync/async variety."""
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    else:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_rag_executor, lambda: fn(*args, **kwargs))


async def retrieve_all_layers_async(
    question: str,
    tables: List[TableSchema],
    embedding_provider: EmbeddingProvider,
    db: Optional[AsyncSession] = None,
    space_id: Optional[str] = None,
    crew_ids: Optional[List[str]] = None,
    top_k: int = 3,
) -> Dict[str, List[str]]:
    """
    Main entry point for multi-level RAG.
    """

    # Layer definitions
    tasks = {
        "schema_rag": retrieve_schema_rag(
            question, tables, embedding_provider, db, space_id, crew_ids, top_k=top_k
        ),
        "metrics_rag": _run_layer(
            retrieve_metrics_rag, question, embedding_provider, db=db, space_id=space_id
        ),
        "questions_rag": _run_layer(
            retrieve_questions_rag,
            question,
            embedding_provider,
            db=db,
            space_id=space_id,
        ),
        "strategy_rag": _run_layer(
            retrieve_strategy_rag,
            question,
            embedding_provider,
            db=db,
            space_id=space_id,
            crew_ids=crew_ids,
        ),
        "signals_rag": _run_layer(
            retrieve_signals_rag,
            question,
            embedding_provider,
            db=db,
            space_id=space_id,
            crew_ids=crew_ids,
        ),
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
                fut = pool.submit(
                    asyncio.run,
                    retrieve_all_layers_async(
                        question, tables, embedding_provider, db, space_id, crew_ids
                    ),
                )
                return fut.result()
        else:
            return loop.run_until_complete(
                retrieve_all_layers_async(
                    question, tables, embedding_provider, db, space_id, crew_ids
                )
            )
    except Exception:
        return asyncio.run(
            retrieve_all_layers_async(
                question, tables, embedding_provider, db, space_id, crew_ids
            )
        )
