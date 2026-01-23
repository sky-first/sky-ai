# core/rag/embeddings.py - OLLAMA VERSION
from __future__ import annotations

from typing import List, Sequence, Optional
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
import httpx

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import TableMetadata, EmbeddingRecord
from core.logging_utils import log_event


# ThreadPool para operações de embedding
_executor = ThreadPoolExecutor(max_workers=4)


# ========= PROVIDER GEN ÉRICO =========

class EmbeddingProvider:
    """
    Interface simples: embed uma lista de textos -> lista de vetores.
    """
    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        raise NotImplementedError
    
    async def embed_async(self, texts: Sequence[str]) -> List[List[float]]:
        """Versão async do embed (usa ThreadPoolExecutor por padrão)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self.embed, texts)


class OllamaEmbeddingProvider(EmbeddingProvider):
    """
    Provider baseado em Ollama local embeddings.
    Usa nomic-embed-text (274MB, 768 dimensions).
    """
    def __init__(self, model: str = "nomic-embed-text", base_url: str = None):
        from config.settings import settings
        self.model = model
        self.base_url = base_url or settings.ollama_base_url
    
    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        """Synchronous embedding via Ollama API"""
        if not texts:
            return []
        
        vectors = []
        for text in texts:
            response = httpx.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=30.0
            )
            response.raise_for_status()
            result = response.json()
            vectors.append(result["embedding"])
        
        return vectors


# Legacy OpenAI provider (DEPRECATED - DO NOT USE)
class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    DEPRECATED: Legacy OpenAI provider.
    Kept for backwards compatibility only.
    DO NOT USE - Will raise error if OpenAI key not set.
    Use OllamaEmbeddingProvider instead.
    """
    def __init__(self, model: str = "text-embedding-3-large"):
        raise RuntimeError(
            "OpenAI embeddings are DISABLED. "
            "Use OllamaEmbeddingProvider with nomic-embed-text instead. "
            "Example: OllamaEmbeddingProvider()"
        )
    
    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        raise RuntimeError("OpenAI is disabled")


# ========= HELPERS PARA TEXTO DE METADADOS =========

def build_metadata_text(tm: TableMetadata) -> str:
    """
    Constrói um texto rico que descreve a coluna para ser embedado.
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

async def create_embeddings_for_table_metadata(
    db: AsyncSession,
    embedding_provider: EmbeddingProvider,
    space_id: str,
    crew_id: Optional[str] = None,
    data_connection_id: Optional[str] = None,
    limit: Optional[int] = None,
    batch_size: int = 20,
    delay_between_batches: float = 1.0,
) -> int:
    """
    Cria embeddings para TableMetadata usando Ollama local.
    """
    query = select(TableMetadata).filter(TableMetadata.space_id == space_id)

    if crew_id:
        query = query.filter(TableMetadata.crew_id == crew_id)
    else:
        query = query.filter(TableMetadata.crew_id.is_(None))

    if data_connection_id:
        query = query.filter(TableMetadata.data_connection_id == data_connection_id)

    if limit:
        query = query.limit(limit)

    result = await db.execute(query)
    rows: List[TableMetadata] = list(result.scalars().all())
    
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

    total_rows = len(rows)
    created = 0
    
    # Processa em lotes
    for i in range(0, total_rows, batch_size):
        batch = rows[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total_rows + batch_size - 1) // batch_size
        
        print(f"Processando lote {batch_num}/{total_batches} ({len(batch)} itens)...")
        
        # Prepara textos do lote
        texts = [build_metadata_text(tm) for tm in batch]
        
        # Gera embeddings do lote (async)
        try:
            vectors = await embedding_provider.embed_async(texts)
        except Exception as e:
            log_event(
                "create_embeddings_batch_error",
                {
                    "space_id": space_id,
                    "batch_num": batch_num,
                    "error": str(e)[:500],
                },
            )
            print(f"Erro no lote {batch_num}: {e}")
            continue
        
        # Salva embeddings do lote
        batch_created = 0
        for tm, vec in zip(batch, vectors):
            rec = EmbeddingRecord(
                space_id=space_id,
                crew_id=crew_id,
                user_id=None,
                document_id=None,
                table_metadata_id=tm.id,
                embedding=vec,
                text=build_metadata_text(tm),
                extra_metadata={
                    "kind": "table_metadata",
                    "data_connection_id": str(tm.data_connection_id),
                    "table_name": tm.table_name,
                    "column_name": tm.column_name,
                },
            )
            db.add(rec)
            batch_created += 1
        
        # Commit incremental após cada lote
        try:
            await db.commit()
            created += batch_created
            print(f"✅ Lote {batch_num}/{total_batches} concluído: {batch_created} embeddings salvos (total: {created}/{total_rows})")
        except Exception as e:
            await db.rollback()
            log_event(
                "create_embeddings_batch_commit_error",
                {
                    "space_id": space_id,
                    "batch_num": batch_num,
                    "error": str(e)[:500],
                },
            )
            print(f"Erro ao salvar lote {batch_num}: {e}")
            continue
        
        # Delay entre lotes (exceto no último)
        if i + batch_size < total_rows and delay_between_batches > 0:
            await asyncio.sleep(delay_between_batches)

    log_event(
        "create_embeddings_metadata_done",
        {
            "space_id": space_id,
            "crew_id": crew_id,
            "data_connection_id": data_connection_id,
            "num_metadata": total_rows,
            "num_embeddings": created,
            "batch_size": batch_size,
        },
    )

    return created
