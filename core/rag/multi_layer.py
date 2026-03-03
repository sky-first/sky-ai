"""
Multi-Layer RAG System

Provides 5 specialized retrieval layers to enrich context for small CPU-based models:
1. Schema RAG - Table/column semantics
2. Metrics RAG - Business KPI definitions
3. Questions RAG - Past validated queries
4. Comments RAG - User clarifications
5. Glossary RAG - Domain terminology

Each layer uses pgvector embeddings for semantic search.

Performance: All 5 layers are executed in PARALLEL via asyncio.gather,
reducing total latency from ~sum(all layers) to ~max(single layer).
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
import re

from sqlalchemy.orm import Session
from sqlalchemy import text

from core.rag.embeddings import EmbeddingProvider
from core.agents.generic_sql_agent import TableSchema
from core.logging_utils import log_event


# ThreadPool dedicado para operações síncronas de DB dentro de contextos async
_rag_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="rag_layer")


# ============================================================================
# Layer 1: Schema RAG
# ============================================================================

def retrieve_schema_rag(
    question: str,
    tables: List[TableSchema],
    embedding_provider: EmbeddingProvider,
    db: Optional[Session] = None,
    space_id: Optional[str] = None,
    top_k: int = 3
) -> List[str]:
    """
    Retrieve semantic metadata about tables/columns.
    
    Sources:
    - table_metadata.description (if exists)
    - Table/column names and types (always available)
    
    Args:
        question: User's question
        tables: Available table schemas
        embedding_provider: For embedding the question
        db: Database session (optional, for metadata lookup)
        space_id: Space ID (optional, for metadata filtering)
        top_k: Number of chunks to retrieve
        
    Returns:
        List of schema context strings
    """
    results = []
    
    # Fallback: Use table/column info from TableSchema objects
    for table in tables[:top_k]:
        # Basic table info
        table_info = f"{table.logical_name}: {len(table.columns)} columns"
        if getattr(table, "description", None):
            table_info += f" - Description: {table.description}"
        
        # Add sample columns (first 5)
        sample_cols = []
        for col in table.columns[:5]:
            if isinstance(col, dict):
                col_name = col.get("name", "")
                col_type = col.get("type", "")
                col_desc = col.get("description", "")
            else:
                col_name = getattr(col, "name", "")
                col_type = str(getattr(col, "type", ""))
                col_desc = getattr(col, "description", "")
            
            col_info = f"{col_name} ({col_type})"
            if col_desc:
                col_info += f" - {col_desc}"
            sample_cols.append(col_info)
        
        if sample_cols:
            table_info += f" - Sample columns: {', '.join(sample_cols)}"
        
        results.append(table_info)
    
    # ✅ IMPLEMENTED: Query embeddings table with vector search
    if db and space_id:
        try:
            # Embed question
            question_embedding = embedding_provider.embed_with_cache(question)
            
            # Query embeddings table with similarity search
            # We search for chunks related to tables in the current space
            query = text("""
                SELECT 
                    text,
                    1 - (embedding <=> :embedding::vector) as similarity
                FROM embeddings
                WHERE space_id = :space_id
                ORDER BY embedding <=> :embedding::vector
                LIMIT :top_k
            """)
            
            rows = db.execute(
                query,
                {
                    "space_id": space_id,
                    "embedding": question_embedding,
                    "top_k": top_k
                }
            ).fetchall()
            
            for row in rows:
                results.append(row.text)
                
        except Exception as e:
            # Log error but fallback to basic schema info
            log_event(
                "schema_rag_error",
                {"error": str(e)[:200]}
            )
    
    # If no results from vector search, fallback to basic schema info (top 3 tables)
    if not results:
        for table in tables[:top_k]:
             # Basic table info
            table_info = f"{table.logical_name}: {len(table.columns)} columns"
            if getattr(table, "description", None):
                table_info += f" - Description: {table.description}"
            results.append(table_info)
    
    log_event(
        "schema_rag_retrieved",
        {"question_length": len(question), "chunks_retrieved": len(results)}
    )
    
    return results


# ============================================================================
# Layer 2: Metrics RAG
# ============================================================================

def retrieve_metrics_rag(
    question: str,
    embedding_provider: EmbeddingProvider,
    db: Optional[Session] = None,
    space_id: Optional[str] = None,
    top_k: int = 3
) -> List[str]:
    """
    Retrieve business metric definitions.
    
    Sources:
    - metrics_catalog table (if exists)
    - Keyword matching for common metrics
    
    Args:
        question: User's question
        embedding_provider: For embedding the question
        db: Database session
        space_id: Space ID for filtering
        top_k: Number of chunks to retrieve
        
    Returns:
        List of metric definition strings
    """
    results = []
    
    # Keyword-based fallback (until metrics_catalog table exists)
    q_lower = question.lower()
    
    common_metrics = {
        "mrr": "MRR (Monthly Recurring Revenue): Sum of active subscription amounts per month",
        "arr": "ARR (Annual Recurring Revenue): MRR × 12",
        "churn": "Churn Rate: (Cancelled customers / Total customers) × 100",
        "cac": "CAC (Customer Acquisition Cost): Total marketing spend / New customers",
        "ltv": "LTV (Lifetime Value): Average revenue per customer × Average customer lifetime",
        "revenue": "Revenue: Total income from sales/subscriptions",
        "arpu": "ARPU (Average Revenue Per User): Total revenue / Total users",
    }
    
    for keyword, definition in common_metrics.items():
        if keyword in q_lower:
            results.append(definition)
            if len(results) >= top_k:
                break
    
    # TODO: Query metrics_catalog table with embeddings
    # if db and space_id:
    #     embedding = embedding_provider.embed(question)
    #     ...
    
    log_event(
        "metrics_rag_retrieved",
        {"question_length": len(question), "chunks_retrieved": len(results)}
    )
    
    return results


# ============================================================================
# Layer 3: Questions RAG
# ============================================================================

def retrieve_questions_rag(
    question: str,
    embedding_provider: EmbeddingProvider,
    db: Optional[Session] = None,
    space_id: Optional[str] = None,
    top_k: int = 3
) -> List[str]:
    """
    Retrieve similar past questions with validated SQL.
    
    Sources:
    - query_history table (existing)
    - Only successful, validated queries
    
    Args:
        question: User's question
        embedding_provider: For embedding the question
        db: Database session
        space_id: Space ID for filtering
        top_k: Number of chunks to retrieve
        
    Returns:
        List of past question + SQL examples
    """
    results = []
    
    if not db or not space_id:
        return results
    
    try:
        # Embed question
        question_embedding = embedding_provider.embed_with_cache(question)
        
        # Query query_history with similarity search
        # Note: Assumes query_history has question_embedding column
        query = text("""
            SELECT 
                question,
                sql_generated
            FROM query_history
            WHERE space_id = :space_id
            AND sql_generated IS NOT NULL
            AND sql_generated != ''
            AND question_embedding IS NOT NULL
            ORDER BY question_embedding <=> :embedding::vector
            LIMIT :top_k
        """)
        
        rows = db.execute(
            query,
            {
                "space_id": space_id,
                "embedding": question_embedding,
                "top_k": top_k
            }
        ).fetchall()
        
        for row in rows:
            # Truncate SQL to save tokens
            sql_preview = row.sql_generated[:150] + "..." if len(row.sql_generated) > 150 else row.sql_generated
            results.append(f"Q: '{row.question}' → SQL: {sql_preview}")
        
        log_event(
            "questions_rag_retrieved",
            {"question_length": len(question), "chunks_retrieved": len(results)}
        )
    except Exception as e:
        # Graceful degradation if query_history doesn't have embeddings yet
        log_event(
            "questions_rag_error",
            {"error": str(e)[:200]}
        )
    
    return results


# ============================================================================
# Layer 4: Comments RAG
# ============================================================================

def retrieve_comments_rag(
    question: str,
    embedding_provider: EmbeddingProvider,
    db: Optional[Session] = None,
    space_id: Optional[str] = None,
    top_k: int = 2
) -> List[str]:
    """
    Retrieve user comments/clarifications.
    
    Sources:
    - query_comments table (to be created)
    - User feedback about column usage, interpretations
    
    Args:
        question: User's question
        embedding_provider: For embedding the question
        db: Database session
        space_id: Space ID for filtering
        top_k: Number of chunks to retrieve
        
    Returns:
        List of comment strings
    """
    results = []
    
    # TODO: Create query_comments table and implement retrieval
    # if db and space_id:
    #     embedding = embedding_provider.embed(question)
    #     query = text("""
    #         SELECT original_question, comment_text, correction_type
    #         FROM query_comments
    #         WHERE space_id = :space_id
    #         ORDER BY comment_embedding <=> :embedding::vector
    #         LIMIT :top_k
    #     """)
    #     ...
    
    log_event(
        "comments_rag_retrieved",
        {"question_length": len(question), "chunks_retrieved": len(results)}
    )
    
    return results


# ============================================================================
# Layer 5: Glossary RAG
# ============================================================================

def retrieve_glossary_rag(
    question: str,
    embedding_provider: EmbeddingProvider,
    db: Optional[Session] = None,
    space_id: Optional[str] = None,
    top_k: int = 2
) -> List[str]:
    """
    Retrieve business glossary terms.
    
    Sources:
    - business_glossary table (to be created)
    - Domain-specific acronyms and terminology
    
    Args:
        question: User's question
        embedding_provider: For embedding the question
        db: Database session
        space_id: Space ID for filtering
        top_k: Number of chunks to retrieve
        
    Returns:
        List of term definitions
    """
    results = []
    
    # Extract potential acronyms from question
    acronyms = re.findall(r'\b[A-Z]{2,}\b', question.upper())
    
    if not acronyms:
        return results
    
    # Hardcoded common business terms (fallback)
    glossary = {
        "MRR": "Monthly Recurring Revenue (subscription businesses)",
        "ARR": "Annual Recurring Revenue",
        "CAC": "Customer Acquisition Cost (marketing spend / new customers)",
        "LTV": "Lifetime Value (expected revenue from a customer)",
        "ARPU": "Average Revenue Per User",
        "NPS": "Net Promoter Score (customer satisfaction metric)",
        "KPI": "Key Performance Indicator",
        "ROI": "Return on Investment",
        "SaaS": "Software as a Service",
        "B2B": "Business to Business",
        "B2C": "Business to Consumer",
    }
    
    for acronym in acronyms[:top_k]:
        if acronym in glossary:
            results.append(f"{acronym}: {glossary[acronym]}")
    
    # TODO: Query business_glossary table
    # if db and space_id:
    #     query = text("""
    #         SELECT term, definition, category
    #         FROM business_glossary
    #         WHERE space_id = :space_id
    #         AND term = ANY(:terms)
    #         LIMIT :top_k
    #     """)
    #     ...
    
    log_event(
        "glossary_rag_retrieved",
        {"question_length": len(question), "chunks_retrieved": len(results)}
    )
    
    return results


# ============================================================================
# NEW Context Layers (Placeholders for Vector Search with Similarity Thresholds)
# ============================================================================

def retrieve_catalog_rag(
    question: str,
    embedding_provider: EmbeddingProvider,
    db: Optional[Session] = None,
    space_id: Optional[str] = None,
    top_k: int = 2
) -> List[str]:
    # Placeholder for Data Catalog, Connections, Systems
    return []

def retrieve_analytics_rag(
    question: str,
    embedding_provider: EmbeddingProvider,
    db: Optional[Session] = None,
    space_id: Optional[str] = None,
    top_k: int = 2
) -> List[str]:
    # Placeholder for Lineage, Quality, Provenance
    return []

def retrieve_strategy_rag(
    question: str,
    embedding_provider: EmbeddingProvider,
    db: Optional[Session] = None,
    space_id: Optional[str] = None,
    top_k: int = 2
) -> List[str]:
    # Placeholder for Objectives, OKRs, Initiatives
    return []

def retrieve_governance_rag(
    question: str,
    embedding_provider: EmbeddingProvider,
    db: Optional[Session] = None,
    space_id: Optional[str] = None,
    top_k: int = 2
) -> List[str]:
    # Placeholder for Governance, Legal, Compliance, Permissions
    return []

def retrieve_enterprise_rag(
    question: str,
    embedding_provider: EmbeddingProvider,
    db: Optional[Session] = None,
    space_id: Optional[str] = None,
    top_k: int = 2
) -> List[str]:
    # Placeholder for Enterprise Graph, Hidden Dependencies
    return []

def retrieve_signals_rag(
    question: str,
    embedding_provider: EmbeddingProvider,
    db: Optional[Session] = None,
    space_id: Optional[str] = None,
    top_k: int = 2
) -> List[str]:
    # Placeholder for Signals, Events, Macro Trends
    return []


# ============================================================================
# Parallel Orchestrator — asyncio.gather over all layers
# ============================================================================

async def retrieve_all_layers_async(
    question: str,
    tables: List[TableSchema],
    embedding_provider: EmbeddingProvider,
    db: Optional[Session] = None,
    space_id: Optional[str] = None,
) -> dict:
    """
    Execute all 5 RAG layers IN PARALLEL using asyncio.gather.

    Instead of running layers sequentially (total_time = sum of all layers),
    all layers are dispatched concurrently in a ThreadPoolExecutor, so
    total_time ≈ max(single_layer_time).

    Returns:
        dict with keys: schema_rag, metrics_rag, questions_rag,
                        comments_rag, glossary_rag
    """
    loop = asyncio.get_event_loop()

    def _run(fn, *args, **kwargs):
        """Wrap a sync function to run in the thread pool."""
        return fn(*args, **kwargs)

    # Dispatch all layers concurrently
    (
        schema_results,
        metrics_results,
        questions_results,
        comments_results,
        glossary_results,
        catalog_results,
        analytics_results,
        strategy_results,
        governance_results,
        enterprise_results,
        signals_results,
    ) = await asyncio.gather(
        loop.run_in_executor(
            _rag_executor,
            lambda: _run(
                retrieve_schema_rag,
                question=question,
                tables=tables,
                embedding_provider=embedding_provider,
                db=db,
                space_id=space_id,
                top_k=3,
            ),
        ),
        loop.run_in_executor(
            _rag_executor,
            lambda: _run(
                retrieve_metrics_rag,
                question=question,
                embedding_provider=embedding_provider,
                db=db,
                space_id=space_id,
                top_k=3,
            ),
        ),
        loop.run_in_executor(
            _rag_executor,
            lambda: _run(
                retrieve_questions_rag,
                question=question,
                embedding_provider=embedding_provider,
                db=db,
                space_id=space_id,
                top_k=3,
            ),
        ),
        loop.run_in_executor(
            _rag_executor,
            lambda: _run(
                retrieve_comments_rag,
                question=question,
                embedding_provider=embedding_provider,
                db=db,
                space_id=space_id,
                top_k=2,
            ),
        ),
        loop.run_in_executor(
            _rag_executor,
            lambda: _run(
                retrieve_glossary_rag,
                question=question,
                embedding_provider=embedding_provider,
                db=db,
                space_id=space_id,
                top_k=2,
            ),
        ),
        loop.run_in_executor(
            _rag_executor,
            lambda: _run(
                retrieve_catalog_rag,
                question=question,
                embedding_provider=embedding_provider,
                db=db,
                space_id=space_id,
                top_k=2,
            ),
        ),
        loop.run_in_executor(
            _rag_executor,
            lambda: _run(
                retrieve_analytics_rag,
                question=question,
                embedding_provider=embedding_provider,
                db=db,
                space_id=space_id,
                top_k=2,
            ),
        ),
        loop.run_in_executor(
            _rag_executor,
            lambda: _run(
                retrieve_strategy_rag,
                question=question,
                embedding_provider=embedding_provider,
                db=db,
                space_id=space_id,
                top_k=2,
            ),
        ),
        loop.run_in_executor(
            _rag_executor,
            lambda: _run(
                retrieve_governance_rag,
                question=question,
                embedding_provider=embedding_provider,
                db=db,
                space_id=space_id,
                top_k=2,
            ),
        ),
        loop.run_in_executor(
            _rag_executor,
            lambda: _run(
                retrieve_enterprise_rag,
                question=question,
                embedding_provider=embedding_provider,
                db=db,
                space_id=space_id,
                top_k=2,
            ),
        ),
        loop.run_in_executor(
            _rag_executor,
            lambda: _run(
                retrieve_signals_rag,
                question=question,
                embedding_provider=embedding_provider,
                db=db,
                space_id=space_id,
                top_k=2,
            ),
        ),
    )

    total_chunks = (
        len(schema_results)
        + len(metrics_results)
        + len(questions_results)
        + len(comments_results)
        + len(glossary_results)
        + len(catalog_results)
        + len(analytics_results)
        + len(strategy_results)
        + len(governance_results)
        + len(enterprise_results)
        + len(signals_results)
    )

    log_event(
        "multi_layer_rag_parallel_done",
        {
            "schema_chunks": len(schema_results),
            "metrics_chunks": len(metrics_results),
            "questions_chunks": len(questions_results),
            "comments_chunks": len(comments_results),
            "glossary_chunks": len(glossary_results),
            "catalog_chunks": len(catalog_results),
            "analytics_chunks": len(analytics_results),
            "strategy_chunks": len(strategy_results),
            "governance_chunks": len(governance_results),
            "enterprise_chunks": len(enterprise_results),
            "signals_chunks": len(signals_results),
            "total_chunks": total_chunks,
        },
    )

    return {
        "schema_rag": schema_results,
        "metrics_rag": metrics_results,
        "questions_rag": questions_results,
        "comments_rag": comments_results,
        "glossary_rag": glossary_results,
        "catalog_rag": catalog_results,
        "analytics_rag": analytics_results,
        "strategy_rag": strategy_results,
        "governance_rag": governance_results,
        "enterprise_rag": enterprise_results,
        "signals_rag": signals_results,
    }


def retrieve_all_layers_sync(
    question: str,
    tables: List[TableSchema],
    embedding_provider: EmbeddingProvider,
    db: Optional[Session] = None,
    space_id: Optional[str] = None,
) -> dict:
    """
    Synchronous wrapper for retrieve_all_layers_async.

    Use this when calling from a synchronous context (e.g., build_context_bundle).
    It safely runs the async orchestrator in the current or a new event loop.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already inside an async context (e.g., FastAPI/Starlette).
            # Schedule as a coroutine and block until done using a new thread.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    retrieve_all_layers_async(
                        question=question,
                        tables=tables,
                        embedding_provider=embedding_provider,
                        db=db,
                        space_id=space_id,
                    ),
                )
                return future.result()
        else:
            return loop.run_until_complete(
                retrieve_all_layers_async(
                    question=question,
                    tables=tables,
                    embedding_provider=embedding_provider,
                    db=db,
                    space_id=space_id,
                )
            )
    except RuntimeError:
        # No event loop at all — create one
        return asyncio.run(
            retrieve_all_layers_async(
                question=question,
                tables=tables,
                embedding_provider=embedding_provider,
                db=db,
                space_id=space_id,
            )
        )
