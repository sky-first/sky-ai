"""Quem nao passa pelo orquestrador nao sabe em que lingua responder.

Encontrado a seguir a corrigir o `conversa_specialist`, e e o mesmo
defeito seis vezes.

── O buraco ─────────────────────────────────────────────────────────

O `intent_classifier` encaminha a pergunta para um de varios nos. Sete
deles — conversa, knowledge, events, relationships, people, widgets e
full_context — respondem **directamente**, sem passar pelo orquestrador.

E o orquestrador e o unico sitio do grafo que escreve
`detected_language` no estado.

Resultado: nenhum destes nos tem lingua nenhuma para consultar. Cinco
deles resolviam isso com uma frase no meio de um prompt em ingles:

    Respond in the same language as the user's question.

Nao e uma instrucao, e um pedido — e o proprio `lingua_da_resposta.py`
avisa, com um caso ja acontecido neste repositorio, que misturar linguas
dentro de um prompt faz o modelo responder na lingua das INSTRUCOES.
Todo o resto do prompt, e os proprios dados que vao la dentro («(No
spaces)», «No description»), estao em ingles.

O `conversa_specialist` chegou a produzir exactamente isso: pergunta em
portugues limpo, resposta em ingles.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


#: Os nos que respondem sem passar pelo orquestrador — e que por isso
#: nao podem contar com `detected_language` no estado.
SEM_ORQUESTRADOR = [
    "conversa",
    "knowledge",
    "events",
    "relationships",
    "people",
    "widgets",
]


def _fonte(nome: str) -> str:
    return (RAIZ / "core" / "llm" / f"{nome}_specialist.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("nome", SEM_ORQUESTRADOR)
def test_cada_um_resolve_a_lingua_por_si(nome):
    """Nao ha ninguem acima deles que a resolva."""
    assert "lingua_de_quem_fala" in _fonte(nome), (
        f"{nome}_specialist responde sem saber em que lingua"
    )


@pytest.mark.parametrize("nome", SEM_ORQUESTRADOR)
def test_ninguem_pede_por_favor_ao_modelo(nome):
    """«Respond in the same language» e um pedido, nao uma instrucao.

    O prompt inteiro esta em ingles, e os dados que vao la dentro tambem.
    Uma frase no meio disso perde para o peso do resto.
    """
    assert "same language as the user" not in _fonte(nome), (
        f"{nome}_specialist ainda pede por favor em vez de dizer a lingua"
    )


def test_a_lista_acompanha_o_grafo():
    """Se aparecer um no novo que responde sozinho, este teste chumba.

    E o ponto todo: o defeito nao foi escrever mal um ficheiro, foi
    acrescentar nos que respondem sem passar pelo sitio que resolve a
    lingua. Sem isto, o setimo especialista nasce com o mesmo buraco e
    ninguem da por ela ate um cliente ler a resposta.
    """
    grafo = (RAIZ / "core" / "agents" / "generic_sql_agent.py").read_text(encoding="utf-8")

    # O bloco que liga o classificador de intencoes aos nos.
    #
    # ⚠️ A primeira versao disto procurava a primeira ocorrencia de
    # `route_by_intent` — que e a DEFINICAO da funcao, muito acima do
    # mapa. O bloco saia vazio, o teste passava, e nao verificava nada.
    # Dai o `assert encaminhados` la em baixo.
    inicio = grafo.index('add_conditional_edges(\n        "brain_retrieval"')
    bloco = grafo[inicio : grafo.index("},", inicio)]

    encaminhados = set(re.findall(r'"(\w+_specialist)"', bloco))
    assert encaminhados, "nao encontrei o mapa de encaminhamento — o teste nao esta a ver nada"
    cobertos = {f"{n}_specialist" for n in SEM_ORQUESTRADOR}

    em_falta = encaminhados - cobertos
    assert not em_falta, (
        f"nos novos que respondem sem orquestrador: {sorted(em_falta)} — "
        "ou resolvem a lingua e entram em SEM_ORQUESTRADOR, ou passam pelo "
        "orquestrador"
    )


def test_o_orquestrador_continua_a_ser_o_unico_que_resolve():
    """A premissa de tudo isto. Se deixar de ser verdade, isto muda."""
    llm = RAIZ / "core" / "llm"
    escrevem = {
        f.name
        for f in llm.glob("*.py")
        if 'state["detected_language"] =' in f.read_text(encoding="utf-8")
    }
    assert escrevem == {"orchestrator.py", "formatter.py"}, (
        f"quem escreve detected_language mudou: {sorted(escrevem)}"
    )
