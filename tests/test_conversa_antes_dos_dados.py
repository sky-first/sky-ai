"""Nem tudo o que se escreve e uma pergunta a base de dados.

O Lucas, depois de experimentar o live talk:

    «Ele pode falar tipo *bom dia, como vai por ai?*, ou coisas simples
    que poderiamos sim responder sem ir aos dados. Ter uma certa abertura
    para esse tipo de conversas eu acho muito bom.»

    «Ao dizer *1 2 3* precisamos falar: *4 5 6, haha, quer seguir?*»

O classificador pontua a frase contra padroes de negocio. O que nao
pontua em nada cai no valor por omissao — que e `data`. «Bom dia»
pontuava zero, virava uma tentativa de gerar SQL, falhava, e a pessoa
recebia a formula de erro.

⚠️ O risco desta correccao **nao e falhar um cumprimento**. E roubar uma
pergunta de negocio: alguem escrever «obrigado, agora mostra-me as
vendas» e receber um «ola!». Metade destes testes existe so para isso.
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
    "bom dia",
    "Bom dia, como vai por aí?",
    "Olá!",
    "oi",
    "boa noite",
    "obrigado",
    "valeu",
    "hello",
    "hi there",
    "good morning",
    "thanks",
    "hola",
    "buenos días",
    "qué tal",
    "gracias",
    "adeus",
    "até logo",
    "bye",
]

#: O «1 2 3» que o Lucas disse ao microfone. Nao e uma pergunta — e
#: alguem a ver se o aparelho o ouve.
TESTES_DE_MICROFONE = ["1 2 3", "um dois três", "one two three", "uno dos tres"]

#: O que **nao** pode virar conversa. Cada uma destas comeca de forma
#: inocente e acaba num pedido a serio.
PERGUNTAS_A_SERIO = [
    "obrigado, agora mostra-me as vendas do trimestre",
    "thanks for the sales report, now show me revenue by region",
    "gracias, ahora muéstrame las ventas",
    "Qual é a receita do trimestre?",
    "Mostra-me a receita total por região",
    "quantos clientes temos?",
    "Show me total revenue by region",
    "Quantas faturas foram pagas este mês?",
]


@pytest.mark.parametrize("frase", CUMPRIMENTOS)
def test_um_cumprimento_nao_vai_a_base_de_dados(frase):
    assert classify_question_intent(frase) is QuestionIntent.CONVERSA, (
        f"{frase!r} ia gerar SQL e devolver a formula de erro"
    )


@pytest.mark.parametrize("frase", TESTES_DE_MICROFONE)
def test_o_1_2_3_do_microfone_e_conversa(frase):
    """«Ao dizer 1 2 3 precisamos falar 4 5 6, haha, quer seguir?»"""
    assert classify_question_intent(frase) is QuestionIntent.CONVERSA


@pytest.mark.parametrize("frase", PERGUNTAS_A_SERIO)
def test_uma_pergunta_de_negocio_nunca_vira_conversa(frase):
    """O defeito que esta correccao podia introduzir, e que seria pior.

    Uma pergunta de negocio respondida com «ola!» e muito pior do que um
    «ola» respondido com dados: a primeira perde trabalho, a segunda so
    e estranha.
    """
    assert classify_question_intent(frase) is not QuestionIntent.CONVERSA, (
        f"{frase!r} e uma pergunta a serio e ia receber um cumprimento"
    )


def test_o_vocabulario_de_negocio_nao_e_so_ingles():
    """Descoberto a corrigir o resto.

    Os padroes de dados eram **so em ingles**, num produto cuja interface
    esta em portugues. «Show me total revenue» pontuava; «Mostra-me a
    receita total» pontuava zero.

    Dava certo por acidente — o valor por omissao tambem e `data` — mas
    qualquer regra que dependa da pontuacao via zero onde devia ver um
    sinal forte. Foi assim que «obrigado, agora mostra-me as vendas» ia
    parar a conversa: «vendas» nao existia e «sales» existia.
    """
    from core.intent.question_intent import _DATA_BOOST_PATTERNS

    for palavra in ("vendas", "receita", "clientes", "ventas", "ingresos"):
        assert _DATA_BOOST_PATTERNS.search(palavra), (
            f"{palavra!r} nao conta como sinal de dados"
        )


def test_uma_frase_vazia_nao_rebenta():
    assert classify_question_intent("") is QuestionIntent.DATA
    assert classify_question_intent("   ") is QuestionIntent.DATA


class _LlmFalso:
    def __init__(self, resposta=None, rebenta=False):
        self._r = resposta
        self._rebenta = rebenta
        self.chamadas = []

    def invoke(self, mensagens):
        self.chamadas.append(mensagens)
        if self._rebenta:
            raise RuntimeError("o modelo caiu")

        class _R:
            content = self._r

        return _R()


def test_o_especialista_responde_sem_tocar_em_dados():
    from core.llm.conversa_specialist import run_conversa_specialist

    llm = _LlmFalso("Bom dia! Quer que veja as vendas de ontem?")
    estado = run_conversa_specialist(
        {"question": "bom dia", "detected_language": "pt"}, llm
    )

    assert estado["answer"].startswith("Bom dia")
    # Sem consulta, sem dados. Fingir que houve confundia quem le os
    # registos a seguir.
    assert estado["sql"] is None
    assert estado["data"] == []


def test_o_especialista_responde_na_lingua_de_quem_falou():
    from core.llm.conversa_specialist import run_conversa_specialist

    llm = _LlmFalso("olá")
    run_conversa_specialist({"question": "bom dia", "detected_language": "pt"}, llm)

    sistema = llm.chamadas[0][0]["content"]
    assert "Portuguese" in sistema

    llm_es = _LlmFalso("hola")
    run_conversa_specialist({"question": "hola", "detected_language": "es"}, llm_es)
    assert "Spanish" in llm_es.chamadas[0][0]["content"]


def test_o_especialista_e_mandado_a_nao_inventar():
    """«Quantos graus fazem hoje em Lisboa» nao tem resposta certa aqui.

    Uma resposta errada com ar de certa e pior do que um «nao sei».
    """
    from core.llm.conversa_specialist import _INSTRUCOES

    baixo = _INSTRUCOES.lower()
    assert "never guess" in baixo
    assert "weather" in baixo


def test_um_cumprimento_nunca_morre_numa_formula_de_erro():
    """Se o modelo cair, ha uma frase escrita a mao — nas tres linguas."""
    from core.llm.conversa_specialist import run_conversa_specialist

    for lang, inicio in (("pt", "Olá"), ("es", "¡Hola"), ("en", "Hello")):
        estado = run_conversa_specialist(
            {"question": "bom dia", "detected_language": lang},
            _LlmFalso(rebenta=True),
        )
        assert estado["answer"].startswith(inicio), estado["answer"]


def test_uma_resposta_vazia_tambem_cai_na_reserva():
    """O modelo pode responder com uma string vazia sem rebentar."""
    from core.llm.conversa_specialist import run_conversa_specialist

    estado = run_conversa_specialist(
        {"question": "bom dia", "detected_language": "pt"}, _LlmFalso("   ")
    )
    assert estado["answer"].strip()


# ── A lingua da resposta ─────────────────────────────────────────────
#
# Apanhado EM PRODUCAO, minutos depois de publicar a primeira versao.
# Perguntei «Bom dia! Como vai por ai?» e recebi «Good morning! I'm doing
# well». Em portugues limpo, resposta em ingles — exactamente o defeito
# que este ficheiro veio corrigir.
#
# O estado nao trazia lingua nenhuma: nos caminhos de dados ela e
# detectada mais acima no grafo, e este no e o primeiro a responder.


def test_a_lingua_vem_da_frase_quando_o_estado_nao_a_diz():
    from core.llm.conversa_specialist import _lingua

    assert _lingua({}, "Bom dia! Como vai por ai?") == "pt"
    assert _lingua({}, "Good morning! How are you?") == "en"
    assert _lingua({}, "Buenos dias, que tal?") == "es"


def test_o_estado_manda_sobre_a_deteccao():
    """Quem passa a lingua sabe mais do que um detector."""
    from core.llm.conversa_specialist import _lingua

    assert _lingua({"detected_language": "pt"}, "Good morning") == "pt"
    assert _lingua({"locale": "es-ES"}, "Good morning") == "es"


def test_uma_frase_em_portugues_recebe_instrucoes_em_portugues():
    """A prova de ponta a ponta do defeito de producao."""
    from core.llm.conversa_specialist import run_conversa_specialist

    llm = _LlmFalso("ola")
    run_conversa_specialist({"question": "Bom dia! Como vai por ai?"}, llm)

    assert "Portuguese" in llm.chamadas[0][0]["content"]

