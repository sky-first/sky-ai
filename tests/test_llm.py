from llm import MockLLM
from llm.provider import get_llm


def test_get_llm_returns_mock_in_ci(monkeypatch):
    monkeypatch.setenv("ENV", "ci")

    llm = get_llm()

    assert isinstance(llm, MockLLM)
    assert llm.invoke("alguma coisa") == "resposta mockada"


def test_get_llm_defaults_to_openai(monkeypatch):
    from openai import OpenAI

    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")

    llm = get_llm()

    assert isinstance(llm, OpenAI)
