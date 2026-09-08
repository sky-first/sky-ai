"""«Como está?» é um cumprimento. «Como está a correr o mês?» não é.

Encontrado a escrever os testes do classificador por modelo, e é anterior
a esse trabalho — já estava em produção.

O padrão de cumprimentos casa com «como está», e a frase inteira não tem
vocabulário de negócio nenhum («mês», «projeto», «pipeline», «equipa»,
«fecho» não estão na lista de sinais). As três condições passavam, e
cinco perguntas a sério iam parar à conversa:

    conversa  | Como está a correr o mês?
    conversa  | Como está o projeto Alfa?
    conversa  | Como vai o pipeline?
    conversa  | Como está a equipa?
    conversa  | Tudo bem com o fecho?

E, com ironia, «Como vão as coisas por aí?» — que **é** um cumprimento —
ia aos dados, porque «vão» não estava no padrão.

── A regra ─────────────────────────────────────────────────────────

Estas aberturas servem para cumprimentar **e** para perguntar. O que as
separa é o que vem a seguir: um cumprimento acaba ali, ou continua com
uma palavra que não é assunto nenhum («por aí», «hoje», «contigo»).

Se vier um assunto, é uma pergunta.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.intent.question_intent import (  # noqa: E402
    QuestionIntent,
    classify_question_intent,
)


CUMPRIMENTOS = [
    "Como está?",
    "Como vai?",
    "Como estás?",
    "Como vai por aí?",
    "Como vão as coisas?",
    "Como vão as coisas por aí?",
    "Como estás hoje?",
    "Tudo bem?",
    "Tudo bem contigo?",
    "Que tal?",
    "Como vai você?",
    "How are you?",
    "How is it going?",
]

#: ⚠️ Perguntas a sério que começam exactamente como um cumprimento.
#:
#: Nenhuma tem vocabulário de negócio — «mês», «projeto», «pipeline»,
#: «equipa», «fecho» não são sinais. É por isso que passavam.
PERGUNTAS_A_SERIO = [
    "Como está a correr o mês?",
    "Como está o projeto Alfa?",
    "Como vai o pipeline?",
    "Como está a equipa?",
    "Como vão os custos?",
    "Como estão as vendas?",
    "Tudo bem com o fecho?",
    "Que tal foi o trimestre?",
    "Como vai a receita?",
]


@pytest.mark.parametrize("frase", CUMPRIMENTOS)
def test_um_cumprimento_continua_a_ser_um_cumprimento(frase):
    assert classify_question_intent(frase) is QuestionIntent.CONVERSA, frase


@pytest.mark.parametrize("frase", PERGUNTAS_A_SERIO)
def test_uma_pergunta_que_comeca_como_um_cumprimento_nao_e_um(frase):
    assert classify_question_intent(frase) is not QuestionIntent.CONVERSA, frase


def test_o_hoje_nao_estraga_um_cumprimento():
    """«Como estás hoje?» morria na regra dos zero sinais.

    «hoje» conta como sinal de dados — e conta bem, porque «quantos
    clientes fecharam hoje?» é uma pergunta a sério. Mas ali não há
    assunto nenhum, só um advérbio.

    Uma frase feita só de abertura e cauda não tem do que falar.
    """
    assert classify_question_intent("Como estás hoje?") is QuestionIntent.CONVERSA


def test_a_cauda_nao_tem_um_unico_substantivo_de_negocio():
    """É a lista fechada que torna o atalho seguro.

    Se alguém lhe acrescentar «vendas» ou «projeto», o atalho passa a
    roubar perguntas — e esse é o defeito que este ficheiro corrige.
    """
    from core.intent.question_intent import _CAUDA_DE_CUMPRIMENTO

    for substantivo in (
        "vendas",
        "receita",
        "projeto",
        "equipa",
        "clientes",
        "mês",
        "trimestre",
        "pipeline",
        "custos",
        "fecho",
    ):
        assert not _CAUDA_DE_CUMPRIMENTO.match(f" {substantivo}?"), substantivo
