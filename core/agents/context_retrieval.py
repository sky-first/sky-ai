# core/agents/context_retrieval.py
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.rag.embeddings import EmbeddingProvider
from core.rag.vector_store import search_embeddings_async
from core.logging_utils import log_event


async def build_retrieval_context_for_question(
    db: AsyncSession,
    embedding_provider: EmbeddingProvider,
    space_id: str,
    crew_ids: Optional[List[str]],
    question: str,
    top_k: int = 20,
    connection_id: Optional[str] = None,
) -> str:
    """
    Usa o vector_store para buscar os embeddings mais relevantes e
    monta um único grande contexto textual para o LLM.

    Esse contexto pode misturar:
    - metadados de tabelas (TableMetadata -> embedding kind 'table_metadata')
    - descrições de colunas
    - pedaços de documentos
    - exemplos de queries históricas

    Tudo isso é empacotado em um texto único que o agente recebe.
    """
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
        log_event(
            "build_retrieval_context_empty",
            {
                "space_id": space_id,
                "crew_ids": crew_ids,
                "question_preview": question[:200],
            },
        )
        return ""

    # Junta os textos em formato legível
    # No futuro você pode separar por tipo (tabelas, docs, APIs, etc.)
    parts: List[str] = []
    for rec in records:
        meta = rec.metadata or {}
        kind = meta.get("kind", "unknown")
        source_info = ""
        if kind == "table_metadata":
            source_info = f"(table: {meta.get('table_name')}, column: {meta.get('column_name')})"
        elif kind == "document_chunk":
            source_info = f"(document: {meta.get('document_name')})"
        else:
            source_info = f"({kind})"

        parts.append(f"[SOURCE {kind}] {source_info}\n{rec.text}")

    context = "\n\n---\n\n".join(parts)

    log_event(
        "build_retrieval_context_done",
        {
            "space_id": space_id,
            "crew_ids": crew_ids,
            "question_preview": question[:200],
            "num_records": len(records),
        },
    )

    return context
