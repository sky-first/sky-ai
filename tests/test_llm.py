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
    monkeypatch.setattr(settings, "use_bedrock", False)
    monkeypatch.setattr(settings, "ollama_base_url", "http://localhost:11434")

    from core.llm.factory import create_llm_orchestrator

    llm = create_llm_orchestrator()
    assert isinstance(llm, OllamaProvider)


def test_factory_returns_bedrock_provider_when_ai_provider_is_bedrock(monkeypatch):
    # use_bedrock takes precedence over use_local_models in the factory.
    # Bedrock client construction reaches out to STS via boto3, so stub
    # ChatBedrockConverse to keep this a pure unit test.
    monkeypatch.setattr(settings, "ai_provider", "bedrock")
    monkeypatch.setattr(settings, "use_local_models", False)
    monkeypatch.setattr(settings, "use_bedrock", True)
    monkeypatch.setattr(settings, "bedrock_region", "eu-west-1")
    # Pin the orchestrator model explicitly so the test doesn't drift
    # if cost-tier defaults change (e.g. Haiku ↔ Sonnet flip).
    monkeypatch.setattr(
        settings,
        "llm_model_orchestrator_bedrock",
        "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
    )

    import sys
    import types

    fake_module = types.ModuleType("langchain_aws")

    class _FakeChatBedrockConverse:  # noqa: D401 — test double
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_module.ChatBedrockConverse = _FakeChatBedrockConverse
    monkeypatch.setitem(sys.modules, "langchain_aws", fake_module)

    from core.llm.factory import create_llm_orchestrator
    from core.llm.providers import BedrockChatProvider

    llm = create_llm_orchestrator()
    assert isinstance(llm, BedrockChatProvider)
    assert llm.model_name == "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert llm._chat.kwargs["region_name"] == "eu-west-1"
