# core/rag/embeddings.py
from __future__ import annotations

from typing import List, Sequence, Optional
import os

from openai import OpenAI
from sqlalchemy.orm import Session

from db.models import TableMetadata, EmbeddingRecord
from core.logging_utils import log_event


# ========= PROVIDER GENÉRICO =========

class EmbeddingProvider:
    """
    Interface simples: embed uma lista de textos -> lista de vetores.
    """
    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        raise NotImplementedError


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    Provider baseado em OpenAI Embeddings (ChatGPT).
    Usa o modelo text-embedding-3-large por default (3072 dimensões).
    """
    def __init__(self, model: str = "text-embedding-3-large"):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        resp = self.client.embeddings.create(
            model=self.model,
            input=list(texts),
        )
        vectors = [item.embedding for item in resp.data]
        return vectors


# ========= HELPERS PARA TEXTO DE METADADOS =========

def build_metadata_text(tm: TableMetadata) -> str:
    """
    Constrói um texto rico que descreve a coluna para ser embedado.
    Você pode ir enriquecendo isso aos poucos.
    """
    desc = tm.description or ""
    nullable = "nullable" if tm.is_nullable else "not nullable"
    extra = tm.extra or {}
    extra_str = ", ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""

    parts = [
        f"Table: {tm.table_name}",
        f"Column: {tm.column_name}",
        f"Type: {tm.data_type}",
        f"Nullability: {nullable}",
    ]
    if desc:
        parts.append(f"Description: {desc}")
    if extra_str:
        parts.append(f"Extra: {extra_str}")

    return " | ".join(parts)


# ========= GERA EMBEDDINGS DE METADADOS =========

def create_embeddings_for_table_metadata(
    db: Session,
    embedding_provider: EmbeddingProvider,
    space_id: str,
    crew_id: Optional[str] = None,
    data_connection_id: Optional[str] = None,  # filtragem por conexão
    limit: Optional[int] = None,
) -> int:
    """
    Cria embeddings para TableMetadata de um space (+ opcional crew + opcional data_connection).
    - Se data_connection_id for informado, filtra apenas metadados daquela conexão.
    - Usa build_metadata_text para criar o texto que será embedado.
    """
    q = db.query(TableMetadata).filter(TableMetadata.space_id == space_id)

    if crew_id:
        q = q.filter(TableMetadata.crew_id == crew_id)
    else:
        q = q.filter(TableMetadata.crew_id.is_(None))

    if data_connection_id:
        q = q.filter(TableMetadata.data_connection_id == data_connection_id)

    if limit:
        q = q.limit(limit)

    rows: List[TableMetadata] = q.all()
    if not rows:
        log_event(
            "create_embeddings_no_metadata",
            {
                "space_id": space_id,
                "crew_id": crew_id,
                "data_connection_id": data_connection_id,
            },
        )
        return 0

    texts = [build_metadata_text(tm) for tm in rows]
    vectors = embedding_provider.embed(texts)

    created = 0
    for tm, vec in zip(rows, vectors):
        rec = EmbeddingRecord(
            space_id=space_id,
            crew_id=crew_id,
            user_id=None,          # metadados de schema, não específicos de usuário
            document_id=None,
            table_metadata_id=tm.id,
            embedding=vec,
            text=build_metadata_text(tm),
            # 🔹 AQUI A MUDANÇA: agora usamos 'extra_metadata'
            extra_metadata={
                "kind": "table_metadata",
                "data_connection_id": tm.data_connection_id,
                "table_name": tm.table_name,
                "column_name": tm.column_name,
            },
        )
        db.add(rec)
        created += 1

    db.commit()

    log_event(
        "create_embeddings_metadata_done",
        {
            "space_id": space_id,
            "crew_id": crew_id,
            "data_connection_id": data_connection_id,
            "num_metadata": len(rows),
            "num_embeddings": created,
        },
    )

    return created
