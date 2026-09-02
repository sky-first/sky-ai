"""Cada base tem as suas manias, e o prompt tem de as dizer.

O `ROUND(x, 2)` do Postgres so existe para `numeric`. Aplicado a um
`double precision` — o que sai de qualquer divisao ou `AVG()` — a base
recusa:

    function round(double precision, integer) does not exist

Apanhado a 02/09/2026 pelo teste das 20 perguntas, na pergunta sobre
DAU/MAU. Um racio e uma divisao, e arredonda-lo e o gesto seguinte mais
natural do mundo — por isso isto nao e um caso de bordo.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.dialects import Dialect, get_dialect_specifics  # noqa: E402


def _avisos(d: Dialect) -> str:
    return get_dialect_specifics(d)["details"].get("warnings", "")


def test_postgres_avisa_do_round():
    a = _avisos(Dialect.POSTGRES)
    assert "ROUND" in a, "o prompt nao diz nada sobre o ROUND no Postgres"
    assert "::numeric" in a, "avisar sem dizer o remedio nao ajuda o modelo"


def test_bigquery_nao_perdeu_os_avisos_que_ja_tinha():
    """Vinham de um `if` no specialist.py; mudaram de sitio, nao de conteudo."""
    a = _avisos(Dialect.BIGQUERY)
    assert "ILIKE" in a
    assert "FULLY QUALIFIED" in a


@pytest.mark.parametrize("d", [Dialect.MYSQL, Dialect.SQLITE, Dialect.ORACLE])
def test_quem_nao_tem_avisos_devolve_vazio(d):
    """O prompt faz `.get(..., '')`; um None ali punha 'None' no prompt."""
    assert _avisos(d) == ""


@pytest.mark.parametrize("modelos_locais", [False, True])
def test_os_dois_caminhos_do_prompt_dizem_as_manias_do_postgres(modelos_locais):
    """A funcao tem dois ramos: modelos locais e o resto.

    Producao usa o segundo. Mas foi assim que este defeito nasceu — uma
    regra num caminho e nao no outro — e e assim que voltaria, no dia em
    que alguem mudasse de modelo.
    """
    from core.llm.specialist import _build_secure_system_prompt

    prompt = _build_secure_system_prompt(
        physical_names=["public.subscriptions"],
        dialect=Dialect.POSTGRES,
        use_local_models=modelos_locais,
    )
    assert "::numeric" in prompt["content"], (
        f"use_local_models={modelos_locais}: o prompt nao avisa do ROUND"
    )
