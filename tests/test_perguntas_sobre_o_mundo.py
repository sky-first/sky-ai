"""Perguntas que nenhuma base de dados de empresa pode responder.

O Lucas pediu isto por palavras dele:

    «Ele pode falar tipo *bom dia, como vai por aí?* ou, *quantos graus
    fazem hoje em Lisboa*, ou coisas simples que poderíamos sim responder
    sem ir aos dados.»

Os cumprimentos ficaram feitos à primeira. A segunda metade não, e vi-a
em produção **depois** de publicar, a correr o classificador dentro do
pod:

    conversa  | bom dia
    data      | Quantos graus fazem hoje em Lisboa?   ← ia ao motor de SQL

── O que este ficheiro faz de diferente ────────────────────────────

Metade dos testes aqui não verifica o que a funcionalidade deve apanhar.
Verifica **o que ela não pode roubar.**

Estes padrões são a única coisa no classificador que ganha ao sinal de
negócio — têm de ser, porque «quantos graus fazem hoje» traz dois sinais
(«quantos», «hoje») e continua a ser uma pergunta sobre o tempo. E é essa
força que os torna perigosos: um padrão largo de mais responde «não sei o
tempo que faz» a quem perguntou pela receita.

Roubar uma pergunta de negócio é muito pior do que deixar passar uma
pergunta sobre o tempo. A primeira perde trabalho; a segunda é só
estranha.

── Três coisas que a lista de quase-erros já apanhou ───────────────

1. **Um `|` a mais antes do parêntese.** Deixava uma alternativa vazia no
   grupo, e uma alternativa vazia casa com tudo — «qual é a receita do
   trimestre» incluída. Ler o padrão não o mostrava; foram os quinze
   «ROUBADA» seguidos. Ainda antes de estar ligado ao classificador.

2. **«quantos graus»** apanhava *«quantos graus de satisfação temos?»*,
   que é uma métrica. Passou a excluir «graus de …».

3. **«campeonato»** apanhava *«quem ganhou o campeonato interno de
   vendas?»*. Saiu da lista: falhar um resultado de futebol custa muito
   menos do que responder «não sei» a um concurso de vendas.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.intent.perguntas_sobre_o_mundo import parece_do_mundo  # noqa: E402
from core.intent.question_intent import (  # noqa: E402
    QuestionIntent,
    classify_question_intent,
)


#: Perguntas sobre o mundo. Nenhuma base de dados de cliente as responde.
DO_MUNDO = [
    # o tempo que faz — o exemplo do Lucas
    "Quantos graus fazem hoje em Lisboa?",
    "Que tempo faz?",
    "Como está o tempo hoje?",
    "Vai chover amanhã?",
    "Está a chover?",
    "Previsão do tempo para amanhã",
    "What is the weather like today?",
    "What's the weather?",
    "Is it going to rain?",
    "¿Cuántos grados hace en Madrid?",
    "¿Qué tiempo hace hoy?",
    # o relógio e o calendário
    "Que horas são?",
    "Que dia é hoje?",
    "What time is it?",
    "What day is today?",
    "¿Qué hora es?",
    # desporto e notícias
    "Quem ganhou o jogo ontem?",
    "Quem ganhou a partida?",
    "Who won the game last night?",
    "Notícias de hoje",
]


#: ⚠️ **A lista que interessa.**
#:
#: Perguntas de negócio a sério, escolhidas por se parecerem com as de
#: cima. Cada padrão novo tem de passar por aqui antes de entrar.
QUASE_ERROS = [
    # «tempo» é uma das métricas mais comuns que há
    "Qual o tempo médio de entrega?",
    "Tempo médio de resposta dos agentes",
    "Mostra-me o tempo de ciclo por equipa",
    "Qual foi o tempo de resposta ontem?",
    "Average delivery time by region",
    # «horas» também
    "Quantas horas trabalhou a equipa este mês?",
    "Quantas horas de formação demos?",
    "How many hours did the team log?",
    "A que horas fechamos mais negócios?",
    # «temperatura» e «graus» — quem tem fábricas mede-as a sério
    "Temperatura média dos sensores da fábrica",
    "Qual a temperatura média dos equipamentos?",
    "Quantos graus de satisfação temos?",
    "Quantos graus de maturidade atingimos?",
    # «quem ganhou» é uma pergunta de vendas
    "Quem ganhou mais comissões este mês?",
    "Quem ganhou mais este trimestre?",
    "Quem ganhou o campeonato interno de vendas?",
    "Who won the most deals this quarter?",
    # «hoje» e «dia» são temporais, não meteorológicos
    "Quantos clientes fecharam hoje?",
    "Qual é a receita de hoje?",
    "Que dia é o fecho do mês?",
    "Qual o dia com mais vendas?",
    # e os restantes substantivos
    "Quantas notícias publicámos este mês?",
    "Quantos jogos vendemos?",
]


@pytest.mark.parametrize("frase", DO_MUNDO)
def test_uma_pergunta_sobre_o_mundo_nao_vai_ao_motor(frase):
    assert parece_do_mundo(frase), f"{frase!r} ia procurar uma tabela que não existe"


@pytest.mark.parametrize("frase", QUASE_ERROS)
def test_uma_pergunta_de_negocio_nunca_e_roubada(frase):
    """O defeito que isto podia introduzir, e que seria muito pior."""
    assert not parece_do_mundo(frase), (
        f"{frase!r} é uma pergunta a sério e ia receber «não sei o tempo que faz»"
    )


@pytest.mark.parametrize("frase", DO_MUNDO)
def test_o_classificador_manda_as_para_a_conversa(frase):
    """A ponta a ponta: não basta o padrão, tem de ganhar ao sinal de negócio.

    «Quantos graus fazem hoje em Lisboa?» traz DOIS sinais de dados —
    «quantos» e «hoje». Se estes padrões não ganhassem, nada mudava.
    """
    assert classify_question_intent(frase) is QuestionIntent.CONVERSA


@pytest.mark.parametrize("frase", QUASE_ERROS)
def test_o_classificador_deixa_passar_o_negocio(frase):
    assert classify_question_intent(frase) is not QuestionIntent.CONVERSA


def test_o_padrao_nao_casa_com_o_vazio():
    """A armadilha que já cá esteve.

    Um `|` antes do parêntese deixa uma alternativa vazia no grupo, e uma
    alternativa vazia casa com **tudo**. Ler o padrão não o mostra.
    """
    assert not parece_do_mundo("x")
    assert not parece_do_mundo("Qual é a receita do trimestre?")
    assert not parece_do_mundo("")
    assert not parece_do_mundo("   ")


def test_ha_mais_quase_erros_do_que_casos_felizes():
    """Não é uma métrica bonita — é a proporção certa para isto.

    O risco aqui é assimétrico: estes padrões ganham ao sinal de negócio.
    Se um dia esta lista encolher abaixo da outra, é sinal de que alguém
    acrescentou padrões sem acrescentar medo.
    """
    assert len(QUASE_ERROS) >= len(DO_MUNDO)
