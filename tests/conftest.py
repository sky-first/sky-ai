import os
import pytest


@pytest.fixture(autouse=True)
def inject_dummy_env():
    # Mocking OpenAI key in runtime to shield infrastructure from hardcoded secrets.
    os.environ["OPENAI_API_KEY"] = "sk-dummy-key-for-unit-tests"
