# core/llm/factory.py
"""
Factory para criar providers LLM e Embedding usando configurações centralizadas.
Suporta alternância entre OpenAI (Cloud) e Ollama (Local).
"""

from __future__ import annotations

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
    """
    provider = (settings.embedding_provider or "").lower()
    if provider == "bedrock":
        from core.rag.embeddings import BedrockEmbeddingProvider

        return BedrockEmbeddingProvider(
            model=settings.embedding_model_bedrock,
            region=settings.bedrock_region,
        )
    if provider == "ollama":
        return OllamaEmbeddingProvider()
    if provider == "openai":
        from core.rag.embeddings import OpenAIEmbeddingProvider

        # Do NOT pass model=settings.embedding_model — that field defaults to
        # a Bedrock model name (amazon.titan-embed-text-v2:0) and causes 404s.
        # OpenAIEmbeddingProvider uses text-embedding-3-large as its own default.
        return OpenAIEmbeddingProvider(api_key=settings.openai_api_key)
    # Fallback to the legacy use_local_models toggle for setups that
    # haven't migrated to the explicit setting yet.
    if settings.use_local_models:
        return OllamaEmbeddingProvider()
    from core.rag.embeddings import OpenAIEmbeddingProvider

    return OpenAIEmbeddingProvider(api_key=settings.openai_api_key)
