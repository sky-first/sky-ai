"""Provider factory routing tests.

Each test sets AI_PROVIDER explicitly. Don't rely on the default — defaults
flip across releases (most recently openai → ollama on 2026-04-16) and a
test that depends on the implicit default breaks the next time we adjust it.
"""

from config.settings import settings
from core.llm.providers import LangChainChatOpenAIProvider, OllamaProvider


def test_factory_returns_openai_provider_when_ai_provider_is_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "use_local_models", False)

    from core.llm.factory import create_llm_orchestrator

    llm = create_llm_orchestrator()
    assert isinstance(llm, LangChainChatOpenAIProvider)


def test_factory_returns_ollama_provider_when_ai_provider_is_ollama(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "ollama")
    monkeypatch.setattr(settings, "use_local_models", True)
    monkeypatch.setattr(settings, "ollama_base_url", "http://localhost:11434")

    from core.llm.factory import create_llm_orchestrator

    llm = create_llm_orchestrator()
    assert isinstance(llm, OllamaProvider)
