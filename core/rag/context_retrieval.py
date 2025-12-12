# core/rag/context_retrieval.py
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from core.rag.embeddings import EmbeddingProvider
from core.rag.vector_store import search_embeddings
from core.logging_utils import log_event


def build_retrieval_context_for_question(
    db: Session,
    embedding_provider: EmbeddingProvider,
    space_id: str,
    crew_ids: Optional[List[str]],
    question: str,
    top_k: int = 20,
) -> List[str]:
    """
    Usa o vector_store para buscar os embeddings mais relevantes e
    retorna uma lista de pedaços de texto que servem como contexto para o LLM.

    Cada item da lista é um pequeno "bloco" textual, exemplo:
    - descrição de coluna/tabela
    - trecho de documento
    - query histórica bem-sucedida
    """
    records = search_embeddings(
        db=db,
        embedding_provider=embedding_provider,
        space_id=space_id,
        crew_ids=crew_ids,
        query_text=question,
        top_k=top_k,
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
        return []

    contexts: List[str] = []
    for rec in records:
        meta = rec.metadata or {}
        kind = meta.get("kind", "unknown")

        # monta um cabeçalho curto por tipo
        if kind == "table_metadata":
            header = f"[TABLE METADATA] table={meta.get('table_name')} column={meta.get('column_name')}"
        elif kind == "document_chunk":
            header = f"[DOCUMENT] name={meta.get('document_name')}"
        elif kind == "api_schema":
            header = f"[API] name={meta.get('api_name')} endpoint={meta.get('endpoint')}"
        else:
            header = f"[{kind.upper()}]"

        text = rec.text or ""
        block = f"{header}\n{text}"
        contexts.append(block)

    log_event(
        "build_retrieval_context_done",
        {
            "space_id": space_id,
            "crew_ids": crew_ids,
            "question_preview": question[:200],
            "num_records": len(records),
        },
    )

    return contexts
