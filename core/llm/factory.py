# core/llm/factory.py
"""
Factory para criar providers LLM e Embedding usando configurações centralizadas.
Suporta alternância entre OpenAI (Cloud) e Ollama (Local).
"""
from __future__ import annotations

from typing import Optional
from config.settings import settings
from core.llm.providers import OllamaProvider, LLMProvider
from langchain_openai import ChatOpenAI, OpenAIEmbeddings # type: ignore
from core.rag.embeddings import OllamaEmbeddingProvider, EmbeddingProvider
from core.logging_utils import log_event


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
        return settings.llm_temperature + ((creativity - 50) / 50.0) * (2.0 - settings.llm_temperature)


def create_llm_orchestrator(creativity: Optional[int] = None, length: Optional[int] = None) -> LLMProvider:
    """
    Creates LLM orchestrator using configuring provider (OpenAI or Ollama).
    """
    if settings.use_local_models:
        return OllamaProvider(
            model=settings.llm_model_orchestrator_local,
            base_url=settings.ollama_base_url,
            temperature=0.0,
            num_ctx=getattr(settings, "ollama_num_ctx_orchestrator", 4096)
        )
    else:
        # OpenAI Strategy utilizing the proper wrapper for tools support
        from core.llm.providers import LangChainChatOpenAIProvider
        return LangChainChatOpenAIProvider(
            model=settings.llm_model_orchestrator,
            temperature=0.0
        )


def create_llm_specialist(creativity: Optional[int] = None, length: Optional[int] = None) -> LLMProvider:
    """
    Creates LLM specialist (SQL Expert).
    """
    if settings.use_local_models:
        return OllamaProvider(
            model=settings.llm_model_specialist_local,
            base_url=settings.ollama_base_url,
            temperature=0.0, 
            num_ctx=getattr(settings, "ollama_num_ctx_specialist", 8192)
        )
    else:
        # OpenAI Strategy
        from core.llm.providers import LangChainChatOpenAIProvider
        return LangChainChatOpenAIProvider(
            model=settings.llm_model_specialist,
            temperature=0.0
        )


def create_llm_formatter(creativity: Optional[int] = None, length: Optional[int] = None) -> LLMProvider:
    """
    Creates LLM for formatting/summarization.
    """
    temp = _convert_creativity_to_temperature(creativity)
    
    if settings.use_local_models:
        return OllamaProvider(
            model=settings.llm_model_formatter_local,
            base_url=settings.ollama_base_url,
            temperature=temp,
            num_ctx=getattr(settings, "ollama_num_ctx_formatter", 4096)
        )
    else:
        # OpenAI Strategy
        from core.llm.providers import LangChainChatOpenAIProvider
        return LangChainChatOpenAIProvider(
            model=settings.llm_model_formatter,
            temperature=temp
        )


def create_embedding_provider() -> EmbeddingProvider:
    """
    Creates embedding provider.
    """
    if settings.use_local_models:
        return OllamaEmbeddingProvider()
    else:
        # OpenAI Strategy utilizing the proper wrapper
        from core.rag.embeddings import OpenAIEmbeddingProvider
        return OpenAIEmbeddingProvider(
            model=settings.embedding_model,
            api_key=settings.openai_api_key
        )
