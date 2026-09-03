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


# Local provider (in-process, sem rede)
class LocalEmbeddingProvider(EmbeddingProvider):
    """Embeddings calculados dentro do próprio processo, via ONNX.

    Sem chamadas de rede: o modelo é carregado uma vez para memória e as
    chamadas seguintes são locais. Existe porque a inferência on-demand
    do Bedrock está bloqueada ao nível da conta AWS — quota 0 e
    ``Adjustable: False`` em eu-west-1, e estrangulada em us-east-1
    apesar de a quota reportar 6000 — e o proxy mantle que salva o
    caminho do chat serve 35 modelos de chat e zero de embedding.

    Medido em CPU, com o modelo já quente:

        1 texto        ~370 ms
        lote de 32     ~130 ms por texto
        memória        ~1,5 GB residentes

    Contra os ~18 s que o caminho Bedrock gastava a esgotar 4 retries
    antes de falhar na mesma.

    O modelo por omissão dá **1024 dimensões**, exactamente o que a
    coluna pgvector espera — trocar para aqui não obriga a migração de
    schema. Qualquer modelo configurado tem de manter essa largura,
    senão ``embedding_dim`` deixa de bater certo.

    Nota sobre espaço vectorial: vectores gravados por outro modelo
    (Titan, no caso) têm a mesma largura mas vivem noutro espaço.
    Misturá-los degrada a pesquisa em silêncio, por isso é preciso
    re-embed do corpo já indexado ao mudar de modelo.
    """

    # 1024 dims, ~2,24 GB. Multilingue de propósito: a plataforma serve
    # conteúdo em PT e EN, e o Titan que este provider substitui também
    # era multilingue.
    #
    # Medido, com a mesma pergunta em PT e EN (similaridade do cosseno,
    # média de 3 pares — quanto mais alto, melhor a pesquisa cruzada):
    #
    #     mixedbread-ai/mxbai-embed-large-v1   0,549   853 ms/par   0,64 GB
    #     intfloat/multilingual-e5-large       0,917   529 ms/par   2,24 GB
    #
    # O multilingue é melhor E mais rápido; só pesa mais em disco e
    # memória (~2,5 GB residentes contra ~1,5 GB). Trocar para o mxbai
    # via LOCAL_EMBEDDING_MODEL se a memória do pod alguma vez apertar —
    # ambos dão 1024 dims, portanto não há migração de schema, mas
    # obriga a re-embed por ser outro espaço vectorial.
    _DEFAULT_MODEL = "intfloat/multilingual-e5-large"

    def __init__(self, model: str = None, cache_dir: str = None):
        from config.settings import settings

        self.model = model or self._DEFAULT_MODEL
        self._cache_dir = cache_dir or getattr(settings, "embedding_cache_dir", None)
        # Carregamento preguiçoso: construir o TextEmbedding descarrega o
        # modelo (0,64 GB, ou 2,24 GB no multilingue) e carrega-o para
        # memória. A fábrica é chamada no arranque do processo, e fazer
        # isso aqui atrasaria o readiness probe do pod — ou, pior,
        # falharia o arranque se a rede estivesse indisponível nesse
        # instante. O primeiro embed() paga o custo, os seguintes não.
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            from fastembed import TextEmbedding

            self._client = TextEmbedding(
                model_name=self.model,
                cache_dir=self._cache_dir,
            )
        return self._client

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        # fastembed devolve um gerador de numpy arrays; a interface do
        # projecto é List[List[float]].
        return [v.tolist() for v in self._ensure_client().embed(list(texts))]


# OpenAI provider (Cloud)
class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    Provider baseado em OpenAI (Cloud).
    Usa text-embedding-3-large por padrão com dimensions=1024.
    """

    # Default OpenAI embedding model — NOT picked from settings.embedding_model
    # because that field defaults to a Bedrock model name (amazon.titan-embed-text-v2:0)
    # which causes 404s when called via the OpenAI endpoint.
    _DEFAULT_OPENAI_EMBED_MODEL = "text-embedding-3-large"

    def __init__(self, model: str = None, api_key: str = None):
        from config.settings import settings
        from langchain_openai import OpenAIEmbeddings

        # Use explicit arg, then fall back to the OpenAI-specific default.
        # Intentionally NOT using settings.embedding_model here — that field
        # shares its default with the Bedrock model name.
        self.model = model or self._DEFAULT_OPENAI_EMBED_MODEL
        api_key = api_key or settings.openai_api_key

        # base_url is set explicitly so langchain_openai never inherits
        # OPENAI_BASE_URL from the environment. In staging that variable
        # points to bedrock-mantle, which serves LLM calls but returns
        # 404 for /v1/embeddings — causing every embed call to fail and
        # falling back to text search silently.
        self._client = OpenAIEmbeddings(
            model=self.model,
            openai_api_key=api_key,
            dimensions=settings.embedding_dim,
            base_url="https://api.openai.com/v1",
        )

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        """Chamada direta à API OpenAI (sem cache). Use embed_with_cache() para cache."""
        if not texts:
            return []
        # LangChain usa embed_documents para listas
        return self._client.embed_documents(list(texts))


# AWS Bedrock provider (Cloud, IRSA-authenticated)
class BedrockEmbeddingProvider(EmbeddingProvider):
    """Provider that talks to AWS Bedrock directly via boto3.

    Authentication is via IRSA when running on EKS — boto3 transparently
    picks up the OIDC token mounted at
    ``/var/run/secrets/eks.amazonaws.com/serviceaccount/token`` and
    exchanges it for the EKS role. Mirrors the ``ChatBedrockConverse``
    auth path used by the chat models, so there's no extra secret to
    rotate.

    Default model: ``amazon.titan-embed-text-v2:0`` (1024 dims native,
    multilingual). Swap via ``BEDROCK_EMBEDDING_MODEL`` env. The
    schema's ``Vector(N)`` column must match the model's output dim —
    see ``settings.embedding_dim``.
    """

    def __init__(self, model: str = None, region: str = None):
        from config.settings import settings
        from langchain_aws import BedrockEmbeddings  # type: ignore

        self.model = model or settings.embedding_model_bedrock
        self.region = region or settings.bedrock_region
        self._client = BedrockEmbeddings(
            model_id=self.model,
            region_name=self.region,
        )

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        """Direct Bedrock call (no cache). Use ``embed_with_cache`` instead."""
        if not texts:
            return []
        return self._client.embed_documents(list(texts))


# ========= HELPERS PARA TEXTO DE METADADOS =========


def build_metadata_text(tm: TableMetadata) -> str:
    """
    Constrói um texto rico que descreve a coluna para ser embedado.
    """
    desc = tm.description or ""
    nullable = "nullable" if tm.is_nullable else "not nullable"
    extra = tm.extra or {}

    parts = [
        f"Table: {tm.table_name}",
        f"Column: {tm.column_name}",
        f"Type: {tm.data_type}",
        f"Nullability: {nullable}",
    ]

    # Adicionar info de Chaves de forma natural para o RAG
    if extra.get("is_primary_key"):
        parts.append("This is a Primary Key (unique identifier).")
    if extra.get("is_foreign_key"):
        parts.append("This is a Foreign Key (links this table to another table).")

    if desc:
        parts.append(f"Description: {desc}")

    # Outros extras
    other_extras = {
        k: v
        for k, v in extra.items()
        if k not in ["is_primary_key", "is_foreign_key", "original_name"]
    }
    if other_extras:
        extra_str = ", ".join(f"{k}={v}" for k, v in other_extras.items())
        parts.append(f"Additional Metadata: {extra_str}")

    return " | ".join(parts)


def build_strategy_text(request: any) -> str:
    """
    Constrói um texto rico para Pillar, Objective (Goal), OKR, Key Result, Cycle, Initiative ou Risk (Assumption).
    """
    entity_type = request.entity_type
    name = request.name or ""
    description = request.description or ""
    details = request.entity_details or {}

    # Mapeamento amigável para o RAG
    display_type = entity_type.replace("_", " ").title()
    if entity_type == "strategic_objective":
        display_type = "Strategic Goal / Objective"
    elif entity_type == "strategy_assumption":
        display_type = "Strategic Risk / Assumption"

    parts = [
        f"Type: {display_type}",
        f"Name: {name}",
    ]
    if description:
        parts.append(f"Description: {description}")

    # Adicionar detalhes genéricos
    for key, value in details.items():
        if value and key not in ["name", "description"]:
            parts.append(f"{key.replace('_', ' ').title()}: {value}")

    return " | ".join(parts)


def build_signal_text(request: any) -> str:
    """
    Constrói um texto rico para Signal Event.
    """
    parts = [
        f"Type: Intelligence Signal / Event",
        f"Category: {request.category}",
        f"Nature: {request.nature}",
    ]
    if request.name:
        parts.append(f"Title: {request.name}")
    if request.description:
        parts.append(f"Description: {request.description}")

    if request.sub_type:
        parts.append(f"Sub-type: {request.sub_type}")
    if request.start_date:
        parts.append(f"Date: {request.start_date}")
    if request.confidence:
        parts.append(f"Confidence: {request.confidence}")

    return " | ".join(parts)


# ========= GERA EMBEDDINGS DE METADADOS =========


async def create_embeddings_for_table_metadata(
    db: AsyncSession,
    embedding_provider: EmbeddingProvider,
    space_id: Optional[str] = None,
    crew_id: Optional[str] = None,
    data_connection_id: Optional[str] = None,
    table_names: Optional[List[str]] = None,
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

    if table_names:
        query = query.filter(TableMetadata.table_name.in_(table_names))

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
    all_data = [
        {
            "id": tm.id,
            "data_connection_id": str(tm.data_connection_id),
            "table_name": tm.table_name,
            "column_name": tm.column_name,
            "text": build_metadata_text(tm),
        }
        for tm in rows
    ]

    # Processa em lotes
    for i in range(0, total_rows, batch_size):
        batch = all_data[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total_rows + batch_size - 1) // batch_size

        print(f"Processando lote {batch_num}/{total_batches} ({len(batch)} itens)...")

        # Prepara textos do lote

        # Gera embeddings do lote (async)
        try:
            vectors = await embedding_provider.embed_async(
                [item["text"] for item in batch]
            )
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
        for item, vec in zip(batch, vectors):
            rec = EmbeddingRecord(
                space_id=space_id,
                crew_id=crew_id,
                user_id=None,
                document_id=None,
                table_metadata_id=item["id"],
                embedding=vec,
                text=item["text"],
                extra_metadata={
                    "kind": "table_metadata",
                    "data_connection_id": item["data_connection_id"],
                    "table_name": item["table_name"],
                    "column_name": item["column_name"],
                },
            )
            db.add(rec)
            batch_created += 1

        # Commit incremental após cada lote
        try:
            await db.commit()
            created += batch_created
            print(
                f"✅ Lote {batch_num}/{total_batches} concluído: {batch_created} embeddings salvos (total: {created}/{total_rows})"
            )
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


def get_embedding_provider() -> EmbeddingProvider:
    """O mesmo provedor que o resto da aplicação usa. Uma fábrica só.

    ── Havia duas, e discordavam. ───────────────────────────────────────

    Esta não conhecia o modo ``local``: com ``EMBEDDING_PROVIDER=local``,
    que é o que produção tem, caía no fim e devolvia **Ollama** — outro
    serviço, outro modelo, e por omissão 768 dimensões contra as 1024 que
    a coluna ``Vector`` espera.

    Quem chamava esta era a ingestão de ficheiros
    (``core/ingestion/service.py``). Ninguém deu por isso porque a tabela
    ``knowledge_file_chunks`` está vazia em produção: o caminho existe e
    nunca correu a sério. No dia em que corresse, ou rebentava na
    dimensão, ou — pior — gravava vectores de outro modelo ao lado dos
    bons, e a pesquisa degradava-se em silêncio.

    Passa a delegar. A escolha do provedor vive em
    ``core.llm.factory.create_embedding_provider``, que também garante
    **uma instância por processo** — cada uma carrega ~1,5 GB de modelo,
    e foi isso que matou o serviço a 02/09/2026.
    """
    from core.llm.factory import create_embedding_provider

    return create_embedding_provider()

