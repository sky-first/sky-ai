"""O «bom dia» dava «Erro ao executar agente».

⚠️ **Defeito meu, apanhado a percorrer a jornada do revisor da App Store.**

A 30/09 fiz a primeira coisa que um revisor faz — escrever «Bom dia!» — e
recebi:

    {"type": "progress", "message": "A pensar…"}
    {"type": "error", "message": "Erro ao executar agente", "code": "stream_error"}

Os registos do sky-ai diziam SUCESSO na mesma janela: intent `conversa`,
`llm_invoke_success` em 1,1 s. O motor respondeu; o cliente recebeu erro.

── A causa ─────────────────────────────────────────────────────────

O laço que segue o grafo só guarda o estado dos nós que estão numa lista.
O `conversa_specialist` entrou no grafo a 08/09 e **nunca foi posto lá**.
Sem estado guardado, `final_state` fica `None`, e mais abaixo:

    if not final_state:
        yield {"type": "error", "message": "Erro ao executar agente"}

O comentário imediatamente acima da lista descreve este mesmo erro a
acontecer antes com o `full_context`. Aconteceu segunda vez porque a lista
é uma segunda fonte de verdade sobre quais os nós terminais — e ninguém a
liga ao grafo.

Por isso o teste que interessa não é «o conversa está na lista». É: **todo
o nó terminal do grafo tem de estar na lista.**
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

ROTA = RAIZ / "api" / "routes" / "connection_query.py"
GRAFO = RAIZ / "core" / "agents" / "generic_sql_agent.py"


def _lista_de_captura() -> set[str]:
    """Os nós cujo estado o laço do stream guarda."""
    fonte = ROTA.read_text(encoding="utf-8")
    i = fonte.index('"people_specialist"')
    bloco = fonte[i - 400 : fonte.index("]:", i)]
    return set(re.findall(r'"(\w+)"', bloco))


def _nos_terminais_do_grafo() -> set[str]:
    """Os nós que respondem sozinhos — os que têm aresta para END."""
    fonte = GRAFO.read_text(encoding="utf-8")
    return set(re.findall(r'add_edge\("(\w+)",\s*END\)', fonte))


def test_as_excepcoes_nao_sao_lixo():
    """Uma excepcao que ja nao corresponde a nenhum no esconde a proxima."""
    orfas = TERMINAIS_QUE_NAO_PRECISAM - _nos_terminais_do_grafo()
    assert not orfas, f"excepcoes que ja nao existem no grafo: {sorted(orfas)}"


def test_a_lista_de_captura_nao_esta_vazia():
    """Uma leitura que falha em silêncio tornaria o resto inútil."""
    assert len(_lista_de_captura()) >= 5


def test_o_conversa_e_capturado():
    """O defeito exacto: o «bom dia» dava erro."""
    assert "conversa_specialist" in _lista_de_captura()


#: Nos terminais que NAO precisam de ser capturados, e porque.
#:
#: A lista existe para a diferenca entre "nao precisa" e "alguem esqueceu-se"
#: ficar escrita, em vez de se adivinhar. Acrescentar aqui exige uma razao.
TERMINAIS_QUE_NAO_PRECISAM = {
    # Fim do caminho de DADOS. O estado ja foi capturado no `specialist`, que
    # e quem traz o SQL e as linhas; o `formatter` so poe a resposta em
    # palavras e o stream trata-a no ramo do `specialist`. Prova de que
    # funciona: o smoke test de producao passa as 20 perguntas de dados.
    "formatter",
}


def test_todo_o_no_terminal_e_capturado():
    """A regra, não o caso.

    Se alguém acrescentar um nó terminal novo ao grafo e se esquecer desta
    lista, a resposta dele é deitada fora e quem pergunta recebe «Erro ao
    executar agente» — com o motor a registar sucesso. Já aconteceu duas
    vezes: `full_context` e `conversa_specialist`.
    """
    terminais = _nos_terminais_do_grafo()
    assert terminais, "nao encontrei nos terminais — o teste nao esta a ver o grafo"

    em_falta = terminais - _lista_de_captura() - TERMINAIS_QUE_NAO_PRECISAM
    assert not em_falta, (
        f"nos terminais que o stream deita fora: {sorted(em_falta)} — "
        "a resposta deles nunca chega a quem pergunta"
    )
