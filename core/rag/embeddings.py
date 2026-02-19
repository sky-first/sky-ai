# core/rag/embeddings.py - OLLAMA VERSION
from __future__ import annotations

from typing import List, Sequence, Optional
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor


from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import TableMetadata, EmbeddingRecord
from core.logging_utils import log_event
from core.rag.embedding_cache import get_cached_embedding, set_cached_embedding


# ThreadPool para operações de embedding
_executor = ThreadPoolExecutor(max_workers=4)


# ========= PROVIDER GEN ÉRICO =========

class EmbeddingProvider:
    """
    Interface simples: embed uma lista de textos -> lista de vetores.

    O método `embed_with_cache` é a entrada recomendada: verifica o cache
    Redis antes de chamar a API e armazena o resultado após a chamada.
    O método `embed` (sem cache) deve ser implementado pelos subclasses.
    """

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        """Implementação pura (sem cache). Deve ser sobrescrito pelos subclasses."""
        raise NotImplementedError

    def embed_with_cache(self, texts: Sequence[str]) -> List[List[float]]:
        """
        Versão com cache Redis. Para cada texto:
          1. Verifica cache → retorna imediatamente se encontrado (cache hit).
          2. Agrupa textos sem cache → chama embed() em lote.
          3. Armazena resultados no cache para futuras chamadas.
        """
        if not texts:
            return []

        texts_list = list(texts)
        results: List[Optional[List[float]]] = [None] * len(texts_list)
        uncached_indices: List[int] = []

        # ── Fase 1: verificar cache ────────────────────────────────────────
        for i, text in enumerate(texts_list):
            cached = get_cached_embedding(text)
            if cached is not None:
                results[i] = cached
            else:
                uncached_indices.append(i)

        # ── Fase 2: chamar API apenas para textos sem cache ────────────────
        if uncached_indices:
            uncached_texts = [texts_list[i] for i in uncached_indices]
            try:
                vectors = self.embed(uncached_texts)
            except Exception:
                # Se a API falhar, tenta retornar o que temos do cache
                # (textos sem cache ficam como None → serão vetores vazios)
                vectors = [[] for _ in uncached_texts]
                raise

            # ── Fase 3: armazenar no cache e preencher resultados ──────────
            for idx, vector in zip(uncached_indices, vectors):
                results[idx] = vector
                if vector:  # não armazena vetores vazios
                    set_cached_embedding(texts_list[idx], vector)

        # Garante que não há None na lista final
        return [r if r is not None else [] for r in results]

    async def embed_async(self, texts: Sequence[str]) -> List[List[float]]:
        """Versão async do embed_with_cache (usa ThreadPoolExecutor por padrão)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self.embed_with_cache, texts)


class OllamaEmbeddingProvider(EmbeddingProvider):
    """
    Provider baseado em Ollama local via langchain_ollama.
    Usa nomic-embed-text (274MB, 768 dimensions) por padrão.
    """
    def __init__(self, model: str = "nomic-embed-text", base_url: str = None):
        from config.settings import settings
        from langchain_ollama import OllamaEmbeddings
        
        self.model = model
        self.base_url = base_url or settings.ollama_base_url
        self._client = OllamaEmbeddings(
            model=self.model,
            base_url=self.base_url,
        )
    
    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        """Chamada direta à API Ollama (sem cache). Use embed_with_cache() para cache."""
        if not texts:
            return []
        # LangChain handles the API calls efficiently
        return self._client.embed_documents(list(texts))


# OpenAI provider (Cloud)
class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    Provider baseado em OpenAI (Cloud).
    Usa text-embedding-3-large por padrão.
    Força dimensions=768 para compatibilidade com o esquema de banco legado (Ollama).
    """
    def __init__(self, model: str = None, api_key: str = None):
        from config.settings import settings
        from langchain_openai import OpenAIEmbeddings
        
        self.model = model or settings.embedding_model
        api_key = api_key or settings.openai_api_key
        
        # IMPORTANTE: O banco define Vector(768). O text-embedding-3-large gera 3072.
        # Precisamos truncar para 768 via parâmetro da API.
        self._client = OpenAIEmbeddings(
            model=self.model,
            openai_api_key=api_key,
            dimensions=768
        )
    
    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        """Chamada direta à API OpenAI (sem cache). Use embed_with_cache() para cache."""
        if not texts:
            return []
        # LangChain usa embed_documents para listas
        return self._client.embed_documents(list(texts))


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
    space_id: Optional[str] = None,
    crew_id: Optional[str] = None,
    data_connection_id: Optional[str] = None,
    limit: Optional[int] = None,
    batch_size: int = 20,
    delay_between_batches: float = 1.0,
) -> int:
    """
    Cria embeddings para TableMetadata usando Ollama local.
    """
    query = select(TableMetadata)
    
    if space_id:
        query = query.filter(TableMetadata.space_id == space_id)
    else:
        query = query.filter(TableMetadata.space_id.is_(None))

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
