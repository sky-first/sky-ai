"""«Quantos clientes temos?» — sobre dados que nao tem clientes.

Producao, 09/10/2026, projecto de restauracao (encomendas anonimas). A
mesma pergunta teve quatro destinos conforme a lingua e o acaso:
«fica de fora» (a mensagem do tempo em Lisboa), um pedido de
esclarecimento so em PT/ES, e 158.340 ENCOMENDAS apresentadas como
clientes. Ver core/llm/conceito_em_falta.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.llm.conceito_em_falta import _honestidade_e_lingua, conceito_em_falta
from core.llm.orchestrator import _CONTAGEM


# ── A rede das contagens fala as tres linguas ────────────────────────


@pytest.mark.parametrize(
    "pergunta",
    [
        "how many customers do we have?",
        "how much clients do we have?",
        "quantos clientes temos?",
        "quantas lojas abriram?",
        "qual o número de encomendas?",
        "¿cuántos clientes tenemos?",
        "cuantas tiendas hay",
        "cantidad de pedidos",
    ],
)
def test_uma_contagem_e_uma_contagem_em_qualquer_lingua(pergunta):
    """So conhecia o ingles: em PT/ES o CLARIFY passava e em EN nao."""
    assert _CONTAGEM.search(pergunta)


@pytest.mark.parametrize(
    "pergunta",
    ["qual é a margem por loja?", "¿qué tienda vende más?", "which store sells most?"],
)
def test_o_que_nao_e_contagem_nao_e_apanhado(pergunta):
    assert not _CONTAGEM.search(pergunta)


# ── O especialista diz o que falta, em vez de inventar ──────────────


def test_le_o_que_falta_e_o_mais_proximo():
    assert conceito_em_falta(
        "MISSING datos de clientes — los pedidos son anónimos | NEAREST el número de pedidos"
    ) == ("datos de clientes — los pedidos son anónimos", "el número de pedidos")


def test_sem_alternativa_tambem_serve():
    assert conceito_em_falta("MISSING dados de margem") == ("dados de margem", None)


@pytest.mark.parametrize(
    "razao",
    [None, "", "Security Restriction", "the table has no rows", "missing"],
)
def test_outras_razoes_nao_sao_confundidas(razao):
    """Uma recusa de seguranca nao pode virar «os dados nao registam X»."""
    assert conceito_em_falta(razao) is None


@pytest.mark.parametrize(
    "codigo,nome",
    [("pt", "European Portuguese"), ("es", "Spanish (Spain)"), ("en", "English"), (None, "English")],
)
def test_o_prompt_pede_a_resposta_na_lingua_de_quem_pergunta(codigo, nome):
    bloco = _honestidade_e_lingua({"detected_language": codigo})
    assert f"Write both parts in {nome}" in bloco
    # E o caso concreto que se viu tem de estar la, com todas as letras.
    assert "Counting orders is NOT counting customers" in bloco
    assert "Translate filter terms into the language the values are stored in" in bloco


# ── O formatador monta a frase, na lingua certa ─────────────────────


def _formatar(razao, lang):
    from core.llm.formatter import run_formatter

    state = {
        "question": "quantos clientes temos?",
        "data": [],
        "impossible_reason": razao,
        "detected_language": lang,
        "retrieval_context": [{"texto": "um documento qualquer sobre clientes"}],
    }
    return run_formatter(state, SimpleNamespace(id="agente-teste"), llm=None)["answer"]


def test_em_portugues_diz_o_que_falta_e_oferece_o_mais_proximo():
    r = _formatar("MISSING dados de clientes — as encomendas são anónimas | NEAREST o número de encomendas", "pt")
    assert "não registam dados de clientes" in r
    assert "o número de encomendas" in r
    assert "fica de fora" not in r


def test_em_castelhano_tambem():
    r = _formatar("MISSING datos de clientes | NEAREST el número de pedidos", "es")
    assert r.startswith("Los datos a los que tengo acceso no registran datos de clientes")


def test_nao_vai_ao_rag_quando_o_conceito_nao_existe():
    """Havia contexto de RAG no estado e a resposta tem de ser a franca —
    um documento sobre clientes nao conta os clientes que a base nao tem."""
    r = _formatar("MISSING datos de clientes | NEAREST el número de pedidos", "es")
    assert "pedidos" in r
