"""A Sky classifica o que encontra.

Todos os achados nasciam iguais: o worker gravava `type="insight"` e
`severity="medium"` cravados no código. Nenhum agente produziu alguma vez um
risco ou uma oportunidade, e por isso os filtros «Risco» e «Oportunidade» —
que existem nas duas interfaces — estavam sempre a zero para achados a sério.

Podia-se filtrar, mas não havia por onde.
"""

from __future__ import annotations

import pytest

from api.routes.classificar_achado import (
    Classificacao,
    PedidoDeClassificacao,
    _limpar,
    classificar,
    parece_um_achado,
)


class _Resposta:
    def __init__(self, content):
        self.content = content


class _ModeloFalso:
    def __init__(self, devolve):
        self.devolve = devolve
        self.chamado = 0

    def invoke(self, mensagens):
        self.chamado += 1
        return _Resposta(self.devolve)


class _ModeloQueRebenta:
    def invoke(self, mensagens):
        raise RuntimeError("o modelo caiu")


# ─── O que NÃO é um achado ──────────────────────────────────────────────────


def test_uma_desculpa_do_sistema_nao_e_um_achado():
    """Estas respostas chegam ao worker como qualquer outra e eram gravadas
    como achados. Classificá-las põe uma etiqueta numa desculpa."""
    assert not parece_um_achado(
        "Algo correu mal do nosso lado ao responder a esta pergunta."
    )
    assert not parece_um_achado(
        "Essa pergunta não parece estar relacionada aos seus dados."
    )
    assert not parece_um_achado(
        "Os valores de vendas de ontem não foram informados (estão nulos)."
    )


def test_um_achado_a_serio_e_um_achado():
    assert parece_um_achado("As vendas do Norte caíram 18% face à média.")


@pytest.mark.asyncio
async def test_uma_nao_resposta_nao_chega_a_ir_ao_modelo(monkeypatch):
    """Perguntar ao modelo o que é uma desculpa só produz uma etiqueta com ar
    de verdade — e gasta uma chamada."""
    modelo = _ModeloFalso('{"type":"risk","severity":"high"}')
    monkeypatch.setattr("api.routes.classificar_achado._modelo", lambda: modelo)

    out = await classificar(
        PedidoDeClassificacao(answer="Algo correu mal do nosso lado.", title="x")
    )
    assert modelo.chamado == 0
    assert out.type == "insight"
    assert out.severity == "low"
    assert out.classified is False


# ─── A classificação ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_classifica_um_risco(monkeypatch):
    monkeypatch.setattr(
        "api.routes.classificar_achado._modelo",
        lambda: _ModeloFalso('{"type":"risk","severity":"high"}'),
    )
    out = await classificar(
        PedidoDeClassificacao(answer="8 papéis abertos há mais de 45 dias.", title="x")
    )
    assert (out.type, out.severity, out.classified) == ("risk", "high", True)


@pytest.mark.asyncio
async def test_aceita_json_embrulhado(monkeypatch):
    """Modelos pequenos embrulham em ```json. Rejeitar por causa disso trocava
    uma classificação boa por um `insight` de omissão."""
    monkeypatch.setattr(
        "api.routes.classificar_achado._modelo",
        lambda: _ModeloFalso('```json\n{"type":"opportunity","severity":"med"}\n```'),
    )
    out = await classificar(PedidoDeClassificacao(answer="Margem subiu 12%.", title="x"))
    assert out.type == "opportunity"
    # E o «med» do modelo e traduzido para o que o backend aceita. Escrevi
    # `med` aqui a 22/08 e todo o achado assim gravado rebentava o detalhe do
    # agente com um 500 — o enum de la e `low|medium|high|critical`.
    assert out.severity == "medium"


# ─── Nunca rebenta ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_o_modelo_a_cair_nao_perde_o_achado(monkeypatch):
    """Um classificador que rebenta faz perder o achado que estava a
    classificar — e o achado vale mais do que a etiqueta."""
    monkeypatch.setattr(
        "api.routes.classificar_achado._modelo", lambda: _ModeloQueRebenta()
    )
    out = await classificar(PedidoDeClassificacao(answer="As vendas caíram 18%."))
    assert out.type == "insight"
    # A gravidade de omissao tem de ser um valor GRAVAVEL, e nao uma palavra
    # qualquer. Este teste fixava a string `"med"` e por isso ficou vermelho
    # com a correcao de um 500 que estava em producao — um guarda que se
    # queixa de uma correcao esta a guardar a coisa errada.
    from api.routes.classificar_achado import GRAVIDADES

    assert out.severity in GRAVIDADES
    assert out.classified is False


@pytest.mark.asyncio
async def test_um_valor_inventado_cai_no_de_omissao(monkeypatch):
    """Gravar «critical» numa coluna que os filtros não conhecem é pior do que
    gravar o valor de sempre."""
    monkeypatch.setattr(
        "api.routes.classificar_achado._modelo",
        lambda: _ModeloFalso('{"type":"catastrophe","severity":"critical"}'),
    )
    out = await classificar(PedidoDeClassificacao(answer="As vendas caíram 18%."))
    assert out.type == "insight"
    assert out.classified is False


@pytest.mark.asyncio
async def test_uma_resposta_sem_json_cai_no_de_omissao(monkeypatch):
    monkeypatch.setattr(
        "api.routes.classificar_achado._modelo",
        lambda: _ModeloFalso("Acho que isto é um risco grave!"),
    )
    out = await classificar(PedidoDeClassificacao(answer="As vendas caíram 18%."))
    assert out.classified is False


def test_o_limpador_devolve_none_em_vez_de_rebentar():
    assert _limpar("") is None
    assert _limpar("nada de json aqui") is None
    assert _limpar('{"type": partido') is None
    assert _limpar('{"type":"risk"}') == {"type": "risk"}
