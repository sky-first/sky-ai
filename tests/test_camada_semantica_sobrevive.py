"""A camada semântica deixa de ser a primeira coisa que se deita fora.

Fatia 4 do modelo (``sky-poc-backend/docs/modelo-projeto-equipa-e-pedidos-de-acesso.md``
§5). O glossário era descartado por inteiro logo no quarto passo da truncagem, e
as métricas ficavam reduzidas a uma. Ou seja: quando a pergunta era grande — que
é precisamente quando as definições do negócio mais importam — a definição do
negócio era a primeira a desaparecer, e o modelo respondia com a **sua** ideia de
"margem" em vez da do cliente.

É a diferença de estatuto que nos separa de quem faz isto bem: na Snowflake, se
a coluna não está na *semantic view*, o Cortex não gera query contra ela; o
Genie Ontology organiza as definições num grafo e desempata por autoridade.
Neles a camada semântica é caminho obrigatório. Aqui era contexto opcional.
"""

from __future__ import annotations

from core.llm.context.builder import _truncate_bundle
from core.llm.context.models import (
    ContextBundle,
    CrewContext,
    DataContext,
    HistoricalContext,
    QueryContext,
    UserContext,
)


def _pacote(**camadas) -> ContextBundle:
    historico = HistoricalContext(**camadas)
    return ContextBundle(
        user=UserContext(user_id="u1"),
        crew=CrewContext(),
        query=QueryContext(),
        data=DataContext(),
        historical=historico,
    )


def _texto(prefixo: str, n: int):
    return [f"{prefixo} {i} " + ("x" * 400) for i in range(n)]


def test_o_glossario_sobrevive_a_um_contexto_a_rebentar():
    """Com o orçamento muito abaixo do necessário, o glossário fica.

    O que cai primeiro são os sinais, o catálogo, os comentários — coisas que
    ajudam à margem. A definição de um termo do negócio não é margem: é a
    diferença entre responder e responder certo.
    """
    pacote = _pacote(
        glossary_rag=_texto("[GLOSSARY] margem =", 6),
        signals_rag=_texto("[SIGNAL]", 20),
        comments_rag=_texto("[COMMENT]", 20),
        catalog_rag=_texto("[CATALOG]", 20),
        schema_rag=_texto("[TABLE METADATA]", 10),
    )

    cortado = _truncate_bundle(pacote, max_tokens=300)

    assert cortado.historical.glossary_rag, "o glossário não pode desaparecer"
    assert len(cortado.historical.glossary_rag) == 3
    # E o que devia ter caído, caiu.
    assert cortado.historical.signals_rag == []
    assert cortado.historical.comments_rag == []


def test_as_metricas_sobrevivem_em_tres_e_nao_em_uma():
    """Uma métrica só não chega a uma pergunta que compare duas."""
    pacote = _pacote(
        metrics_rag=_texto("[METRIC]", 8),
        signals_rag=_texto("[SIGNAL]", 30),
        schema_rag=_texto("[TABLE METADATA]", 10),
    )

    cortado = _truncate_bundle(pacote, max_tokens=300)

    assert len(cortado.historical.metrics_rag) == 3


def test_prefere_se_cortar_esquema_a_perder_a_definicao():
    """A ordem que interessa, dita por um teste.

    Se um dia alguém voltar a pôr o glossário a sair antes do esquema, isto
    falha — e falha com o motivo escrito, que é o ponto.
    """
    pacote = _pacote(
        glossary_rag=_texto("[GLOSSARY]", 4),
        schema_rag=_texto("[TABLE METADATA]", 12),
    )

    cortado = _truncate_bundle(pacote, max_tokens=200)

    assert len(cortado.historical.glossary_rag) == 3
    assert len(cortado.historical.schema_rag) == 2


def test_sem_aperto_nada_se_corta():
    """A truncagem não pode roubar contexto quando ele cabe."""
    pacote = _pacote(
        glossary_rag=_texto("[GLOSSARY]", 5),
        metrics_rag=_texto("[METRIC]", 5),
    )
    antes_g = len(pacote.historical.glossary_rag)
    antes_m = len(pacote.historical.metrics_rag)

    cortado = _truncate_bundle(pacote, max_tokens=10_000_000)

    assert len(cortado.historical.glossary_rag) == antes_g
    assert len(cortado.historical.metrics_rag) == antes_m
