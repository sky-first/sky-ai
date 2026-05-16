"""Smoke tests for the embedding provider factory.

The factory now branches on ``settings.embedding_provider`` instead of
hard-coding on ``use_local_models``. We don't instantiate the real
clients (Bedrock needs IRSA, OpenAI needs a key) — just verify the
branch picks the right *class*, which is the behaviour PR
``feat/bedrock-embeddings`` introduced.
"""

from __future__ import annotations

import sys
import types

from config.settings import settings


def _stub_langchain_aws(monkeypatch):
    """Insert a dummy ``langchain_aws.BedrockEmbeddings`` so the
    BedrockEmbeddingProvider can be constructed without AWS creds."""

    class _FakeBedrockEmbeddings:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def embed_documents(self, texts):
            return [[0.0] * 1024 for _ in texts]

    fake = types.ModuleType("langchain_aws")
    fake.BedrockEmbeddings = _FakeBedrockEmbeddings
    monkeypatch.setitem(sys.modules, "langchain_aws", fake)


def test_factory_picks_bedrock_when_embedding_provider_is_bedrock(monkeypatch):
    _stub_langchain_aws(monkeypatch)
    monkeypatch.setattr(settings, "embedding_provider", "bedrock")
    monkeypatch.setattr(
        settings, "embedding_model_bedrock", "amazon.titan-embed-text-v2:0"
    )

    from core.llm.factory import create_embedding_provider
    from core.rag.embeddings import BedrockEmbeddingProvider

    provider = create_embedding_provider()
    assert isinstance(provider, BedrockEmbeddingProvider)
    assert provider.model == "amazon.titan-embed-text-v2:0"


def test_factory_picks_ollama_when_provider_is_ollama(monkeypatch):
    monkeypatch.setattr(settings, "embedding_provider", "ollama")

    from core.llm.factory import create_embedding_provider
    from core.rag.embeddings import OllamaEmbeddingProvider

    provider = create_embedding_provider()
    assert isinstance(provider, OllamaEmbeddingProvider)


def test_factory_picks_openai_when_provider_is_openai(monkeypatch):
    monkeypatch.setattr(settings, "embedding_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "embedding_model", "text-embedding-3-large")

    from core.llm.factory import create_embedding_provider
    from core.rag.embeddings import OpenAIEmbeddingProvider

    provider = create_embedding_provider()
    assert isinstance(provider, OpenAIEmbeddingProvider)


def test_factory_falls_back_to_use_local_models_when_provider_unset(monkeypatch):
    """Legacy setups that haven't migrated to EMBEDDING_PROVIDER still
    work via the use_local_models toggle."""
    monkeypatch.setattr(settings, "embedding_provider", None)
    monkeypatch.setattr(settings, "use_local_models", True)

    from core.llm.factory import create_embedding_provider
    from core.rag.embeddings import OllamaEmbeddingProvider

    provider = create_embedding_provider()
    assert isinstance(provider, OllamaEmbeddingProvider)
