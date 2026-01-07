# core/rag/embeddings.py
from __future__ import annotations

from typing import List, Sequence, Optional
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import TableMetadata, EmbeddingRecord
from core.logging_utils import log_event


# ThreadPool para operações OpenAI (bloqueantes)
_executor = ThreadPoolExecutor(max_workers=4)


# ========= PROVIDER GENÉRICO =========

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

async def create_embeddings_for_table_metadata(
    db: AsyncSession,
    embedding_provider: EmbeddingProvider,
    space_id: str,
    crew_id: Optional[str] = None,
    data_connection_id: Optional[str] = None,  # filtragem por conexão
    limit: Optional[int] = None,
    batch_size: int = 20,  # processa em lotes de 20 por padrão
    delay_between_batches: float = 1.0,  # delay em segundos entre lotes
) -> int:
    """
    Cria embeddings para TableMetadata de um space (+ opcional crew + opcional data_connection).
    - Se data_connection_id for informado, filtra apenas metadados daquela conexão.
    - Usa build_metadata_text para criar o texto que será embedado.
    - Processa em lotes menores para evitar rate limits e melhorar progresso incremental.
    
    Args:
        batch_size: Número de embeddings a processar por lote (padrão: 20)
        delay_between_batches: Delay em segundos entre lotes (padrão: 1.0s)
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
            # Continua para o próximo lote mesmo se um falhar
            continue
        
        # Salva embeddings do lote
        batch_created = 0
        for tm, vec in zip(batch, vectors):
            rec = EmbeddingRecord(
                space_id=space_id,
                crew_id=crew_id,
                user_id=None,          # metadados de schema, não específicos de usuário
                document_id=None,
                table_metadata_id=tm.id,
                embedding=vec,
                text=build_metadata_text(tm),
                extra_metadata={
                    "kind": "table_metadata",
                    "data_connection_id": str(tm.data_connection_id),  # UUID -> string para JSON
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
