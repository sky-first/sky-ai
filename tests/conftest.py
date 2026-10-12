import os
import pytest

# A cache dos valores das colunas tem um segundo nível no Redis. Nos testes
# não há Redis: sem isto, cada leitura esperava pelo timeout da ligação. Os
# testes da cache injectam um Redis falso (valores_de_coluna.usar_redis).
os.environ.setdefault("SKY_VALORES_CACHE_REDIS", "0")


@pytest.fixture(autouse=True)
def inject_dummy_env():
    # Mocking OpenAI key in runtime to shield infrastructure from hardcoded secrets.
    os.environ["OPENAI_API_KEY"] = "sk-dummy-key-for-unit-tests"
