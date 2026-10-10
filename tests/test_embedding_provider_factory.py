"""Smoke tests for the embedding provider factory.

The factory now branches on ``settings.embedding_provider`` instead of
hard-coding on ``use_local_models``. We don't instantiate the real
clients (Bedrock needs IRSA, OpenAI needs a key) — just verify the
branch picks the right *class*, which is the behaviour PR
``feat/bedrock-embeddings`` introduced.
"""

from __future__ import annotations
import os

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


def test_factory_picks_local_when_provider_is_local(monkeypatch):
    """EMBEDDING_PROVIDER=local corre o modelo dentro do processo.

    Existe porque a inferência on-demand do Bedrock está bloqueada ao
    nível da conta AWS e o proxy mantle não serve embeddings.
    """
    monkeypatch.setattr(settings, "embedding_provider", "local")
    monkeypatch.setattr(
        settings, "embedding_model_local", "mixedbread-ai/mxbai-embed-large-v1"
    )

    from core.llm.factory import create_embedding_provider
    from core.rag.embeddings import LocalEmbeddingProvider

    provider = create_embedding_provider()
    assert isinstance(provider, LocalEmbeddingProvider)
    assert provider.model == "mixedbread-ai/mxbai-embed-large-v1"


def test_local_model_is_configurable(monkeypatch):
    """Trocar para o modelo multilingue não deve exigir alteração de código."""
    monkeypatch.setattr(settings, "embedding_provider", "local")
    monkeypatch.setattr(
        settings, "embedding_model_local", "intfloat/multilingual-e5-large"
    )

    from core.llm.factory import create_embedding_provider

    provider = create_embedding_provider()
    assert provider.model == "intfloat/multilingual-e5-large"


def test_ollama_model_comes_from_settings(monkeypatch):
    """The Ollama path must honour OLLAMA_EMBEDDING_MODEL.

    Regression cover: the factory used to call ``OllamaEmbeddingProvider()``
    with no arguments, so it always got the provider's hardcoded
    ``nomic-embed-text`` (768 dims). A deployment backing the 1024-dim
    pgvector column needs ``mxbai-embed-large`` and had no way to say so —
    every self-hosted embedding would have been the wrong width.
    """
    monkeypatch.setattr(settings, "embedding_provider", "ollama")
    monkeypatch.setattr(settings, "embedding_model_ollama", "mxbai-embed-large")

    from core.llm.factory import create_embedding_provider

    provider = create_embedding_provider()
    assert provider.model == "mxbai-embed-large"


def test_local_default_model_is_1024_dims():
    """A coluna pgvector está a 1024. Um default de outra largura partiria
    todas as escritas — este teste trava a troca acidental."""
    from core.rag.embeddings import LocalEmbeddingProvider
    from fastembed import TextEmbedding

    dims = {m["model"]: m.get("dim") for m in TextEmbedding.list_supported_models()}
    assert dims[LocalEmbeddingProvider._DEFAULT_MODEL] == 1024


def test_local_model_setting_reads_the_env_alias(monkeypatch):
    from config.settings import Settings

    monkeypatch.setenv("LOCAL_EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
    assert Settings().embedding_model_local == "intfloat/multilingual-e5-large"


def test_local_provider_does_not_load_the_model_on_construction(monkeypatch):
    """Construir não pode descarregar nem carregar o modelo.

    A fábrica corre no arranque do processo. Carregar 0,64-2,24 GB aí
    atrasaria o readiness probe do pod, e falharia o arranque se a rede
    estivesse em baixo nesse instante. O primeiro embed() é que paga.
    """
    from core.rag.embeddings import LocalEmbeddingProvider

    provider = LocalEmbeddingProvider(model="intfloat/multilingual-e5-large")
    assert provider._client is None


def test_ollama_model_defaults_to_nomic_for_backwards_compatibility(monkeypatch):
    """Unset env keeps the pre-existing behaviour."""
    monkeypatch.setattr(settings, "embedding_provider", "ollama")
    monkeypatch.setattr(settings, "embedding_model_ollama", "nomic-embed-text")

    from core.llm.factory import create_embedding_provider

    provider = create_embedding_provider()
    assert provider.model == "nomic-embed-text"


def test_ollama_model_setting_reads_the_env_alias(monkeypatch):
    """OLLAMA_EMBEDDING_MODEL is the name used in the deployment manifests."""
    from config.settings import Settings

    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "mxbai-embed-large")
    assert Settings().embedding_model_ollama == "mxbai-embed-large"


def test_a_descarga_do_modelo_grava_na_cache_e_nao_na_home(monkeypatch, tmp_path):
    """O disco do pod é só de leitura: o huggingface_hub (xet) gravava em
    ~/.cache/huggingface, a descarga morria e o RAG falhava em silêncio
    em todas as perguntas (produção, 10/10)."""
    import sys
    import types

    from core.rag.embeddings import LocalEmbeddingProvider

    monkeypatch.delenv("HF_HOME", raising=False)
    visto = {}

    class _TextEmbedding:
        def __init__(self, model_name, cache_dir):
            visto["hf_home"] = os.environ.get("HF_HOME")

    monkeypatch.setitem(
        sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=_TextEmbedding)
    )
    LocalEmbeddingProvider(model="m", cache_dir=str(tmp_path))._ensure_client()
    assert visto["hf_home"] == os.path.join(str(tmp_path), "hf")


def test_um_hf_home_configurado_nao_e_pisado(monkeypatch, tmp_path):
    import sys
    import types

    from core.rag.embeddings import LocalEmbeddingProvider

    monkeypatch.setenv("HF_HOME", "/configurado")
    monkeypatch.setitem(
        sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=lambda **k: None)
    )
    LocalEmbeddingProvider(model="m", cache_dir=str(tmp_path))._ensure_client()
    assert os.environ["HF_HOME"] == "/configurado"


def test_o_modelo_carrega_de_uma_pasta_sem_symlinks(monkeypatch, tmp_path):
    """onnxruntime 1.31 recusa pesos externos que são symlinks para blobs/
    («External data path escapes model directory») — produção, 10/10."""
    from core.rag.embeddings import LocalEmbeddingProvider

    descarregado = {}

    def snapshot_download(repo_id, local_dir):
        descarregado.update(repo=repo_id, pasta=local_dir)
        return local_dir

    class _TextEmbedding:
        @staticmethod
        def _list_supported_models():
            return [
                types.SimpleNamespace(
                    model="m", sources=types.SimpleNamespace(hf="qdrant/m-onnx")
                )
            ]

        def __init__(self, model_name, cache_dir, specific_model_path=None):
            descarregado["usado"] = specific_model_path

    monkeypatch.setitem(
        sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=_TextEmbedding)
    )
    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        types.SimpleNamespace(snapshot_download=snapshot_download),
    )
    LocalEmbeddingProvider(model="m", cache_dir=str(tmp_path))._ensure_client()
    assert descarregado["repo"] == "qdrant/m-onnx"
    assert descarregado["usado"] == os.path.join(
        str(tmp_path), "materializado", "qdrant__m-onnx"
    )


def test_se_a_materializacao_falhar_cai_no_caminho_antigo(monkeypatch, tmp_path):
    from core.rag.embeddings import LocalEmbeddingProvider

    visto = {}

    class _TextEmbedding:
        @staticmethod
        def _list_supported_models():
            raise RuntimeError("sem rede")

        def __init__(self, model_name, cache_dir, **kw):
            visto["kw"] = kw

    monkeypatch.setitem(
        sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=_TextEmbedding)
    )
    LocalEmbeddingProvider(model="m", cache_dir=str(tmp_path))._ensure_client()
    assert visto["kw"] == {}
