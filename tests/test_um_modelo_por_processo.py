"""Um modelo por processo — nao um por pedido.

O `LocalEmbeddingProvider` carrega ~1,5 GB de modelo ONNX para dentro do
processo e guarda-o em `self._client`. Por instancia. Uma instancia nova
e um modelo novo em memoria.

A fabrica devolvia uma instancia nova a cada chamada, e era chamada por
pedido — so o `connection_query.py` chama-a em seis sitios. Cada pergunta
podia empilhar gigabytes de copias do mesmo modelo.

Matou o `sky-ai` em producao duas vezes a 02/09/2026 (`OOMKilled`, limite
de 5 GiB). Medido no pod: base 119 MiB, 1613 MiB depois de UM provedor
com um embed. Ao criar o segundo, o processo morria antes de acabar.

Nao se testa a memoria aqui — testa-se a identidade, que e a causa. Um
teste que medisse megabytes seria instavel e nao diria porque falhou.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _limpar():
    """Limpa a cache da fabrica, se ela existir.

    Tolerante de proposito: sem o `@lru_cache` nao ha `cache_clear`, e um
    `AttributeError` aqui transformava os testes em ERROS em vez de
    FALHAS. Uma falha diz o que esta errado; um erro no arranque so diz
    que rebentou.
    """
    from core.llm import factory

    limpar = getattr(factory._provedor_de_embeddings, "cache_clear", None)
    if limpar:
        limpar()


@pytest.fixture(autouse=True)
def _limpar_cache():
    _limpar()
    yield
    _limpar()


def test_a_fabrica_devolve_sempre_a_mesma_instancia():
    from core.llm.factory import create_embedding_provider

    a = create_embedding_provider()
    b = create_embedding_provider()

    assert a is b, (
        "cada chamada cria um provedor novo — com o modelo local, isso e "
        "~1,5 GB de memoria por chamada"
    )


def test_dez_chamadas_nao_criam_dez_provedores():
    """Seis chamadas por pedido nao podem ser seis modelos."""
    from core.llm.factory import create_embedding_provider

    instancias = {id(create_embedding_provider()) for _ in range(10)}

    assert len(instancias) == 1, f"criou {len(instancias)} provedores distintos"


def test_o_modelo_local_e_construido_uma_so_vez(monkeypatch):
    """A identidade podia repetir-se por acaso; conta-se a construcao.

    E o `LocalEmbeddingProvider` que interessa: e o unico que carrega
    ~1,5 GB para dentro do processo.
    """
    import core.rag.embeddings as emb
    from config.settings import settings
    from core.llm.factory import create_embedding_provider

    construcoes = []
    original = emb.LocalEmbeddingProvider

    class _Contado(original):
        def __init__(self, *a, **kw):
            construcoes.append(1)
            # Nao chama o __init__ real: ele so guarda nomes, mas manter
            # a distancia deixa o teste independente das definicoes.

    monkeypatch.setattr(emb, "LocalEmbeddingProvider", _Contado)
    monkeypatch.setattr(settings, "embedding_provider", "local")
    monkeypatch.setattr(settings, "embedding_model_local", "modelo-de-teste")

    _limpar()
    for _ in range(6):  # seis, como o connection_query.py faz por pedido
        create_embedding_provider()

    assert construcoes == [1], (
        f"o modelo foi construido {len(construcoes)} vezes — "
        f"a ~1,5 GB cada, sao {len(construcoes) * 1.5:.1f} GB"
    )


def test_ha_uma_so_fabrica():
    """Havia duas, e a outra nao conhecia o modo `local`.

    Com `EMBEDDING_PROVIDER=local` — o que producao tem — a
    `get_embedding_provider` caia no fim e devolvia Ollama: outro
    servico, outro modelo, 768 dimensoes contra as 1024 que a coluna
    espera. Quem a chamava era a ingestao de ficheiros.
    """
    from core.llm.factory import create_embedding_provider
    from core.rag.embeddings import get_embedding_provider

    assert get_embedding_provider() is create_embedding_provider(), (
        "as duas fabricas voltaram a divergir — a ingestao vai gravar "
        "vectores de outro modelo ao lado dos bons, e a pesquisa degrada-se "
        "sem erro nenhum"
    )
