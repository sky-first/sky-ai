# core/llm/factory.py
"""
Factory para criar providers LLM e Embedding usando configurações centralizadas.
"""
from __future__ import annotations

from typing import Optional
from config.settings import settings
from core.llm.providers import OllamaProvider, LLMProvider  # Only Ollama
from core.rag.embeddings import OllamaEmbeddingProvider  # ✅ OLLAMA EMBEDDINGS
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


def _convert_length_to_max_tokens(length: Optional[int]) -> Optional[int]:
    """
    Converte nível de comprimento (0-100) para max_tokens do LLM.
    - 0 = 100 tokens (resposta muito curta)
    - 50 = 1000 tokens (padrão)
    - 100 = 4000 tokens (resposta muito longa)
    
    Se length > 100, será limitado a 100 (4000 tokens máximo).
    """
    if length is None:
        return None
    
    # Limitar a 0-100
    length = max(0, min(100, length))
    
    # Interpolação linear: 0 -> 100, 50 -> 1000, 100 -> 4000
    if length <= 50:
        return int(100 + (length / 50.0) * (1000 - 100))
    else:
        return int(1000 + ((length - 50) / 50.0) * (4000 - 1000))


def create_llm_orchestrator(creativity: Optional[int] = None, length: Optional[int] = None) -> LLMProvider:
    """
    Creates LLM orchestrator using Ollama.
    Always uses phi3-sky for fast routing.
    """
    return OllamaProvider(
        model=settings.llm_model_orchestrator_local,
        base_url=settings.ollama_base_url,
        temperature=0.0,  # Always deterministic for routing
        num_ctx=settings.ollama_num_ctx_orchestrator
    )


def create_llm_specialist(creativity: Optional[int] = None, length: Optional[int] = None) -> LLMProvider:
    """
    Creates LLM specialist using Ollama.
    Always uses sqlcoder-sky for SQL generation.
    """
    return OllamaProvider(
        model=settings.llm_model_specialist_local,
        base_url=settings.ollama_base_url,
        temperature=0.0,  # SQL must be deterministic
        num_ctx=settings.ollama_num_ctx_specialist
    )


def create_llm_formatter(creativity: Optional[int] = None, length: Optional[int] = None) -> LLMProvider:
    """
    Creates LLM formatter using Ollama.
    Always uses phi3-sky for text formatting.
    """
    return OllamaProvider(
        model=settings.llm_model_formatter_local,
        base_url=settings.ollama_base_url,
        temperature=0.3,  # Slight creativity for natural text
        num_ctx=settings.ollama_num_ctx_formatter
    )


def create_embedding_provider() -> OllamaEmbeddingProvider:
    """
    Creates embedding provider using Ollama local model.
    Uses nomic-embed-text (274MB, 768 dimensions).
    """
    return OllamaEmbeddingProvider()

