"""LLM provider selection with CI-safe mock and safe defaults."""

import os

from openai import OpenAI

from .mock import MockLLM

DEFAULT_TIMEOUT_SECONDS = 30


def get_llm():
    """Return a CI-safe LLM client.

    When ENV=ci, a local mock is returned to guarantee zero external calls.
    Production defaults to an OpenAI client with a conservative timeout.
    """
    env = os.getenv("ENV", "prod").lower()
    if env == "ci":
        return MockLLM()

    api_key = os.getenv("OPENAI_API_KEY")
    # Never log prompts or API keys. Keep client construction side-effect free.
    return OpenAI(api_key=api_key, timeout=DEFAULT_TIMEOUT_SECONDS)
