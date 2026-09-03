"""A cadeia de migracoes tem de ter UMA cabeca.

Com duas, o `alembic upgrade head` recusa-se a escolher e aborta:

    Multiple head revisions are present for given argument 'head'

E entao **nenhuma** das linhas corre. Nao e "metade das migracoes
aplicadas" — e nenhuma, incluindo as antigas que ja la estavam.

Aconteceu: a 03/09/2026, em producao, a tabela `alembic_version` estava
VAZIA. O `semantic_cache` continuava sem as colunas `locale`,
`cache_version` e `temporal_bucket` que o ORM declarava desde a 006/007,
e por isso a cache de respostas estava morta — cada pergunta repetida
pagava o custo completo de LLM, sem alarme nenhum.

O erro so aparece nos registos do Job de migracao, que ninguem le quando
o deploy fica verde. Este teste poe a mesma verificacao antes do merge.
"""

import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def _cadeia():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    c = Config()
    c.set_main_option("script_location", str(RAIZ / "alembic"))
    return ScriptDirectory.from_config(c)


def test_ha_uma_so_cabeca():
    cabecas = _cadeia().get_heads()

    assert len(cabecas) == 1, (
        f"a cadeia tem {len(cabecas)} cabecas: {cabecas}.\n"
        "Com mais do que uma, `alembic upgrade head` aborta e NENHUMA "
        "migracao corre.\n"
        "Resolve-se com uma revisao de juncao: `alembic merge -m '...' "
        + " ".join(cabecas)
        + "'"
    )


def test_todas_as_revisoes_estao_alcancaveis():
    """Uma revisao orfa nunca corre, e nada se queixa.

    Ter uma cabeca so nao chega: uma revisao pode ficar fora do caminho
    se apontar para um pai que nao existe.
    """
    s = _cadeia()
    cabeca = s.get_heads()[0]

    no_caminho = {r.revision for r in s.walk_revisions("base", cabeca)}
    todas = {r.revision for r in s.walk_revisions()}

    orfas = todas - no_caminho
    assert not orfas, (
        f"revisoes fora do caminho ate a cabeca: {sorted(orfas)} — "
        "nunca vao correr"
    )


def test_as_colunas_da_cache_estao_na_cadeia():
    """As tres que faltavam em producao.

    Nao chega existirem os ficheiros: tem de estar no caminho. Foi
    exactamente essa a avaria — 006 e 007 existiam e estavam do lado
    errado da bifurcacao.
    """
    s = _cadeia()
    cabeca = s.get_heads()[0]
    no_caminho = {r.revision for r in s.walk_revisions("base", cabeca)}

    for revisao in ("006_temporal_bucket_cache", "007_locale_cache_version"):
        assert revisao in no_caminho, (
            f"{revisao} nao esta no caminho ate a cabeca — a cache de "
            "respostas fica morta em producao"
        )
