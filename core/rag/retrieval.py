"""RAG retrieval utilities."""

from typing import List, Dict, Any, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from core.rag.vector_store import search_similar
from core.constants import MAX_RETRIEVAL_DOCUMENTS


def retrieve_context(
    db: Session,
    query: str,
    space_id: Optional[UUID] = None,
    crew_id: Optional[UUID] = None,
    max_documents: int = MAX_RETRIEVAL_DOCUMENTS,
) -> List[Dict[str, Any]]:
    """
    Retrieve relevant context for a query using RAG.

    Args:
        db: Database session
        query: Query text
        space_id: Optional space ID
        crew_id: Optional crew ID
        max_documents: Maximum number of documents to retrieve

    Returns:
        List of relevant documents with metadata
    """
    results = search_similar(
        db=db, query_text=query, space_id=space_id, crew_id=crew_id, limit=max_documents
    )

    return results


def format_context_for_llm(documents: List[Dict[str, Any]]) -> str:
    """
    Format retrieved documents for LLM context.

    Args:
        documents: List of document dictionaries

    Returns:
        Formatted context string
    """
    context_parts = []

    for doc in documents:
        content_type = doc.get("content_type", "unknown")
        content_text = doc.get("content_text", "")
        metadata = doc.get("metadata", {})

        context_parts.append(
            f"[{content_type}] {content_text}\n" f"Metadata: {metadata}\n"
        )

    return "\n---\n".join(context_parts)
