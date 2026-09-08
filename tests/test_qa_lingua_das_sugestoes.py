"""QA — as sugestoes tem de sair na lingua de quem pergunta.

O Lucas, sobre uma sugestao que a app lhe mostrou:

    «Qual e o total de *amount* das oportunidades agrupado por *region*
    das contas? Amount? Stage? Deve haver muitas outras palavras
    mescladas entre portugues e ingles. Esta errado, e tambem deve
    acontecer no espanhol — deve ser o mecanismo errado.»

Tinha razao nas duas coisas.
"""

from __future__ import annotations

import io
import pathlib
import re
import tokenize

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
ROTA = RAIZ / "api" / "routes" / "connection_query.py"
FONTE = ROTA.read_text(encoding="utf-8")


def _codigo() -> str:
    """A fonte sem comentarios nem docstrings.

    Duas versoes destes testes falharam por apanhar o **proprio
    comentario** que explicava o defeito — o que ensina a apagar
    comentarios para calar o teste, que e o contrario do que se quer.

    Usa-se o tokenizador do Python, e nao expressoes regulares: um
    comentario dentro de uma string nao e um comentario.
    """
    fora = []
    with io.open(ROTA, encoding="utf-8") as f:
        anterior = tokenize.INDENT
        for tok in tokenize.generate_tokens(f.readline):
            if tok.type == tokenize.COMMENT:
                continue
            # Uma string sozinha numa linha e uma docstring.
            if tok.type == tokenize.STRING and anterior in (
                tokenize.INDENT,
                tokenize.NEWLINE,
                tokenize.NL,
            ):
                continue
            fora.append(tok.string)
            if tok.type not in (tokenize.NL, tokenize.COMMENT):
                anterior = tok.type
    return "\n".join(fora)


CODIGO = _codigo()


def test_a_lista_de_linguas_nao_e_copiada_a_mao():
    """Havia TRES copias neste ficheiro, e uma tinha uma lingua a menos.

    A das sugestoes aceitava `{"en", "pt"}`: quem abrisse a app em
    espanhol recebia as sugestoes em ingles. Sem erro, sem registo, so na
    lingua errada — e o dicionario espanhol da app tem 833 frases.

    Nenhuma copia. A lista vive em `core.i18n.i18n.SUPPORTED_LANGUAGES`.
    """
    copias = re.findall(r'lang\s+not\s+in\s+\{[^}]*"[a-z]{2}"[^}]*\}', CODIGO)
    assert not copias, (
        f"a lista de linguas esta escrita a mao em {len(copias)} sitio(s): "
        f"{copias}. Use SUPPORTED_LANGUAGES — tres copias significam que "
        "uma delas vai divergir, e foi o que aconteceu ao espanhol."
    )


def test_o_espanhol_e_aceite():
    """A verificacao de fundo, independente de como esta escrita."""
    import sys

    sys.path.insert(0, str(RAIZ))
    from core.i18n.i18n import SUPPORTED_LANGUAGES

    assert "es" in SUPPORTED_LANGUAGES


def test_o_prompt_nao_manda_escrever_nomes_de_coluna():
    """A causa directa do «total de *amount*».

    O prompt dizia::

        "- Use the actual column names from the schema (but phrase naturally)"

    O modelo cumpria a primeira metade e ignorava a segunda. E a
    instrucao contradizia a proibicao tres linhas acima, que ja mandava
    nao fazer perguntas sobre colunas.
    """
    maus = re.findall(r"Use the actual column names", CODIGO)
    assert not maus, (
        "o prompt manda usar os nomes das colunas em bruto. Numa frase "
        "portuguesa isso da «o total de amount agrupado por region»"
    )


def test_o_prompt_diz_o_que_fazer_em_vez_de_so_proibir():
    """Proibir sem dar o caminho deixa o modelo a adivinhar.

    A regra nova traz um exemplo mau e um bom, na lingua do problema.
    """
    assert "NEVER write a raw column or table name" in CODIGO
    assert "BAD:" in CODIGO and "GOOD:" in CODIGO


def test_a_lingua_pedida_chega_ao_fallback():
    """O `_fallback_bootstrap` ja teve o `lang` a ser ignorado."""
    m = re.search(r"def _fallback_bootstrap\(([^)]*)\)", FONTE)
    assert m, "nao encontrei o _fallback_bootstrap"
    assert "lang" in m.group(1), "o fallback nem recebe a lingua"

    inicio = FONTE.index("def _fallback_bootstrap")
    corpo = FONTE[inicio : inicio + 4000]
    assert re.search(r"\blang\b", corpo[corpo.index(":") :]), (
        "o fallback recebe a lingua e nao a usa"
    )
