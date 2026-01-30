"""
Multi-Layer RAG System

Provides 5 specialized retrieval layers to enrich context for small CPU-based models:
1. Schema RAG - Table/column semantics
2. Metrics RAG - Business KPI definitions
3. Questions RAG - Past validated queries
4. Comments RAG - User clarifications
5. Glossary RAG - Domain terminology

Each layer uses pgvector embeddings for semantic search.
"""
from __future__ import annotations

from typing import List, Optional
import re

from sqlalchemy.orm import Session
from sqlalchemy import text

from core.rag.embeddings import EmbeddingProvider
from core.agents.generic_sql_agent import TableSchema
from core.logging_utils import log_event


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
        
        # Add sample columns (first 5)
        sample_cols = []
        for col in table.columns[:5]:
            if isinstance(col, dict):
                col_name = col.get("name", "")
                col_type = col.get("type", "")
            else:
                col_name = getattr(col, "name", "")
                col_type = str(getattr(col, "type", ""))
            
            sample_cols.append(f"{col_name} ({col_type})")
        
        if sample_cols:
            table_info += f" - Sample columns: {', '.join(sample_cols)}"
        
        results.append(table_info)
    
    # ✅ IMPLEMENTED: Query embeddings table with vector search
    if db and space_id:
        try:
            # Embed question
            question_embedding = embedding_provider.embed(question)
            
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
        question_embedding = embedding_provider.embed(question)
        
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
