# core/rag/context_retrieval.py
from __future__ import annotations

from typing import List, Optional, Any, Dict
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from core.rag.embeddings import EmbeddingProvider
from core.rag.vector_store import search_embeddings, search_embeddings_async
from core.logging_utils import log_event


def _format_records(records: List[Any]) -> List[str]:
    """Helper para formatar os records em blocos de texto."""
    contexts: List[str] = []
    for rec in records:
        meta_raw = rec.extra_metadata
        if not isinstance(meta_raw, dict):
            meta = {}
        else:
            meta = meta_raw
        
        # Try 'type' first, then 'kind'
        kind = meta.get("type") or meta.get("kind", "unknown")

        if kind == "table_metadata":
            header = f"[TABLE METADATA] table={meta.get('table_name', 'unknown')} column={meta.get('column_name', 'unknown')}"
        elif kind == "document_chunk":
            header = f"[DOCUMENT] name={meta.get('document_name', 'unknown')}"
        elif kind == "api_schema":
            header = f"[API] name={meta.get('api_name', 'unknown')} endpoint={meta.get('endpoint', 'unknown')}"
        elif kind == "business_context":
            header = f"[BUSINESS CONTEXT] name={meta.get('name', 'unknown')} entity_type={meta.get('entity_type', 'unknown')}"
        else:
            header = f"[{str(kind).upper()}]"

        text = rec.text or ""
        block = f"{header}\n{text}"
        contexts.append(block)
    return contexts


async def build_retrieval_context_for_question(
    db: AsyncSession,
    embedding_provider: EmbeddingProvider,
    space_id: str,
    crew_ids: Optional[List[str]],
    question: str,
    top_k: int = 20,
    connection_id: Optional[str] = None,
) -> List[str]:
    """Versão assíncrona para routes FastAPI."""
    records = await search_embeddings_async(
        db=db,
        embedding_provider=embedding_provider,
        space_id=space_id,
        crew_ids=crew_ids,
        query_text=question,
        top_k=top_k,
        connection_id=connection_id,
    )

    if not records:
        return []

    return _format_records(records)


def build_retrieval_context_for_question_sync(
    db: Session,
    embedding_provider: EmbeddingProvider,
    space_id: str,
    crew_ids: Optional[List[str]],
    question: str,
    top_k: int = 20,
    connection_id: Optional[str] = None,
) -> List[str]:
    """Versão síncrona para LangGraph nodes."""
    records = search_embeddings(
        db=db,
        embedding_provider=embedding_provider,
        space_id=space_id,
        crew_ids=crew_ids,
        query_text=question,
        top_k=top_k,
        connection_id=connection_id,
    )

    if not records:
        return []

    return _format_records(records)
