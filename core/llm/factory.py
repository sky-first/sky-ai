# core/llm/factory.py
"""
Factory para criar providers LLM e Embedding usando configurações centralizadas.
Suporta alternância entre OpenAI (Cloud) e Ollama (Local).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional
from config.settings import settings
from core.llm.providers import OllamaProvider, LLMProvider
from langchain_openai import ChatOpenAI, OpenAIEmbeddings  # type: ignore
from core.rag.embeddings import OllamaEmbeddingProvider, EmbeddingProvider
from core.logging_utils import log_event
from core.tenant_context import current_tenant


def _tenant_bedrock_profile_arn() -> Optional[str]:
    """Return the current tenant's Bedrock inference profile ARN.

    Projeto A (Model B) — when a tenant has a per-tenant Application
    Inference Profile configured in ``tenant_registry``, every Bedrock
    call routes through that profile so AWS Cost Explorer can split
    spend per tenant. Default tenant or no ARN configured → return
    None and the factory uses the env-driven model id.
    """
    ctx = current_tenant()
    if ctx.is_default:
        return None
    return ctx.bedrock_inference_profile_arn or None


def _convert_creativity_to_temperature(creativity: Optional[int]) -> float:
    """
    Converte nível de criatividade (0-100) para temperatura do LLM (0.0-2.0).
    - 0 = temperatura mínima (0.0) - mais determinístico
    - 50 = temperatura padrão (settings.llm_temperature)
    - 100 = temperatura máxima (2.0) - mais criativo
    """
    if creativity is None:
        return settings.llm_temperature

    # Normaliza para 0.0-2.0
    # 0 -> 0.0, 50 -> settings.llm_temperature, 100 -> 2.0
    if creativity <= 50:
        # Interpolação linear de 0-50 para 0.0-settings.llm_temperature
        return (creativity / 50.0) * settings.llm_temperature
    else:
        # Interpolação linear de 50-100 para settings.llm_temperature-2.0
        return settings.llm_temperature + ((creativity - 50) / 50.0) * (
            2.0 - settings.llm_temperature
        )


def create_llm_orchestrator(
    creativity: Optional[int] = None, length: Optional[int] = None
) -> LLMProvider:
    """
    Creates LLM orchestrator using the configured provider (OpenAI / Ollama / Bedrock).
    """
    if settings.use_bedrock:
        from core.llm.providers import BedrockChatProvider

        return BedrockChatProvider(
            model=settings.llm_model_orchestrator_bedrock,
            region=settings.bedrock_region,
            temperature=0.0,
            inference_profile_arn=_tenant_bedrock_profile_arn(),
        )
    if settings.use_local_models:
        return OllamaProvider(
            model=settings.llm_model_orchestrator_local,
            base_url=settings.ollama_base_url,
            temperature=0.0,
            num_ctx=getattr(settings, "ollama_num_ctx_orchestrator", 4096),
        )
    # OpenAI Strategy utilizing the proper wrapper for tools support
    from core.llm.providers import LangChainChatOpenAIProvider

    return LangChainChatOpenAIProvider(
        model=settings.llm_model_orchestrator, temperature=0.0
    )


def create_llm_specialist(
    creativity: Optional[int] = None, length: Optional[int] = None
) -> LLMProvider:
    """
    Creates LLM specialist (SQL Expert).
    """
    if settings.use_bedrock:
        from core.llm.providers import BedrockChatProvider

        return BedrockChatProvider(
            model=settings.llm_model_specialist_bedrock,
            region=settings.bedrock_region,
            temperature=0.0,
            inference_profile_arn=_tenant_bedrock_profile_arn(),
        )
    if settings.use_local_models:
        return OllamaProvider(
            model=settings.llm_model_specialist_local,
            base_url=settings.ollama_base_url,
            temperature=0.0,
            num_ctx=getattr(settings, "ollama_num_ctx_specialist", 8192),
        )
    from core.llm.providers import LangChainChatOpenAIProvider

    return LangChainChatOpenAIProvider(
        model=settings.llm_model_specialist, temperature=0.0
    )


def create_llm_formatter(
    creativity: Optional[int] = None, length: Optional[int] = None
) -> LLMProvider:
    """
    Creates LLM for formatting/summarization.
    """
    temp = _convert_creativity_to_temperature(creativity)

    if settings.use_bedrock:
        from core.llm.providers import BedrockChatProvider

        return BedrockChatProvider(
            model=settings.llm_model_formatter_bedrock,
            region=settings.bedrock_region,
            temperature=temp,
            inference_profile_arn=_tenant_bedrock_profile_arn(),
        )
    if settings.use_local_models:
        return OllamaProvider(
            model=settings.llm_model_formatter_local,
            base_url=settings.ollama_base_url,
            temperature=temp,
            num_ctx=getattr(settings, "ollama_num_ctx_formatter", 4096),
        )
    from core.llm.providers import LangChainChatOpenAIProvider

    return LangChainChatOpenAIProvider(
        model=settings.llm_model_formatter, temperature=temp
    )


def create_embedding_provider() -> EmbeddingProvider:
    """Creates an embedding provider matching ``settings.embedding_provider``.

    Resolution: the validator on Settings derives ``embedding_provider``
    from ``AI_PROVIDER`` when unset, so a caller running with
    ``AI_PROVIDER=bedrock`` automatically gets Bedrock embeddings. Set
    ``EMBEDDING_PROVIDER`` explicitly to mix providers — e.g. keep chat
    on the mantle proxy (``AI_PROVIDER=openai``) while routing
    embeddings to Bedrock direct (``EMBEDDING_PROVIDER=bedrock``).

    ── Uma instância por processo, e não uma por chamada. ───────────────

    O ``LocalEmbeddingProvider`` carrega um modelo ONNX de **~1,5 GB**
    para dentro do processo, preguiçosamente, no primeiro ``embed()``. E
    guarda-o em ``self._client`` — por instância. Uma instância nova é um
    modelo novo em memória.

    Isto era chamado **por pedido**, e mais do que uma vez: só o
    ``connection_query.py`` chama-o em seis sítios. Cada pergunta podia
    portanto empilhar vários gigabytes de cópias do mesmo modelo.

    Foi o que matou o ``sky-ai`` em produção duas vezes a 02/09/2026 —
    ``OOMKilled`` contra um limite de 5 GiB, levando com ele as perguntas
    em curso. Medido no pod: base 119 MiB, e 1613 MiB depois de criar
    **um** provedor e embeber uma frase. Ao criar o segundo, o processo
    morria antes de o terminar.

    E cada construção ia à HuggingFace, o que acabou por esgotar o limite
    de pedidos do IP do cluster::

        429 Too Many Requests: you have reached your 'api' rate limit
        We had to rate limit your IP (34.250.237.99)

    A cache é **por configuração**, e não global. Em produção as
    definições não mudam em execução, portanto dá no mesmo — mas assim
    mudá-las devolve o provedor certo em vez do primeiro que calhou, que
    é o que os testes desta fábrica esperam, e com razão: uma cache que
    ignora a configuração é uma armadilha à espera de quem a mude.
    """
    return _provedor_de_embeddings(
        (settings.embedding_provider or "").lower(),
        settings.embedding_model_local,
        settings.embedding_model_ollama,
        settings.embedding_model_bedrock,
        settings.bedrock_region,
        settings.openai_api_key,
        bool(settings.use_local_models),
    )


@lru_cache(maxsize=8)
def _provedor_de_embeddings(
    provider: str,
    modelo_local: Optional[str],
    modelo_ollama: Optional[str],
    modelo_bedrock: Optional[str],
    regiao_bedrock: Optional[str],
    chave_openai: Optional[str],
    modelos_locais_legado: bool,
) -> EmbeddingProvider:
    """A construção propriamente dita, memorizada pelos seus argumentos.

    Os argumentos são as definições que decidem o resultado. Passá-los
    explicitamente — em vez de ler ``settings`` aqui dentro — é o que
    torna a memorização correcta: duas configurações diferentes dão dois
    provedores diferentes, e a mesma configuração dá sempre o mesmo.
    """
    if provider == "local":
        # Em-processo, via ONNX. Não fala com a rede — existe porque a
        # inferência on-demand do Bedrock está bloqueada ao nível da conta
        # e o proxy mantle não serve modelos de embedding.
        from core.rag.embeddings import LocalEmbeddingProvider

        return LocalEmbeddingProvider(model=modelo_local)
    if provider == "bedrock":
        from core.rag.embeddings import BedrockEmbeddingProvider

        return BedrockEmbeddingProvider(
            model=modelo_bedrock,
            region=regiao_bedrock,
        )
    if provider == "ollama":
        # Pass the model explicitly. The provider's own default is
        # nomic-embed-text (768 dims); a deployment backing a 1024-dim
        # pgvector column needs mxbai-embed-large, and with no argument
        # here there was no way to ask for it.
        return OllamaEmbeddingProvider(model=modelo_ollama)
    if provider == "openai":
        from core.rag.embeddings import OpenAIEmbeddingProvider

        # Do NOT pass model=settings.embedding_model — that field defaults to
        # a Bedrock model name (amazon.titan-embed-text-v2:0) and causes 404s.
        # OpenAIEmbeddingProvider uses text-embedding-3-large as its own default.
        return OpenAIEmbeddingProvider(api_key=chave_openai)
    # Fallback to the legacy use_local_models toggle for setups that
    # haven't migrated to the explicit setting yet.
    if modelos_locais_legado:
        return OllamaEmbeddingProvider()
    from core.rag.embeddings import OpenAIEmbeddingProvider

    # O argumento, não `settings`: ler as definições aqui dentro furava a
    # memorização — a cache é pelos argumentos, e o que ela não vê não a
    # invalida.
    return OpenAIEmbeddingProvider(api_key=chave_openai)
