"""Produção, 11/10/2026 — tenant skyfirstlabs, ligação «Operaciones» (``ops``).

«Lista las 5 gasolineras con el gasóleo A más barato en la tabla
gasolineras_rota para la ruta Badajoz-Madrid». O pipeline já escolhia
gasolineras_rota + gasolineras_precio com o JOIN em id_estacion (#279), mas o
especialista escreveu ``WHERE UPPER(gr.origem) = 'BAJAZOZ'`` — gralha —, 0
linhas, e a resposta foi «Lo siento, pero no puedo proporcionar esa lista.»

Três defeitos, três redes:
1. Os valores reais só eram amostrados para gasolineras_precio: a amostragem
   corria antes do orquestrador, sobre todas as tabelas da ligação, com tecto
   de 40 colunas por pedido — gasolineras_rota ficava de fora. Agora o
   especialista anota TODAS as tabelas escolhidas.
2. 0 linhas com um literal que não existe → compara com os valores da coluna
   e, se houver UM candidato claro, corrige e corre outra vez (uma vez).
3. 0 linhas genuínas → «no hay resultados para …», não uma recusa.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from core.agents.generic_sql_agent import AgentConfig, TableSchema
from core.sql import valores_de_coluna
from core.sql.correcao_de_literais import (
    corrigir_literais,
    descrever_filtros,
    melhor_candidato,
)

CIDADES = ["BADAJOZ", "MADRID", "LISBOA", "PORTO", "SEVILLA", "MÉRIDA"]

SQL_COM_GRALHA = (
    "-- TITLE: Gasolineras más baratas Badajoz-Madrid\n"
    "SELECT gp.rotulo, gp.precio_gasoleo_a\n"
    "FROM ops.gasolineras_rota gr\n"
    "JOIN ops.gasolineras_precio gp ON gr.id_estacion = gp.id_estacion\n"
    "WHERE UPPER(gr.origem) = 'BAJAZOZ' AND UPPER(gr.destino) = 'MADRID'\n"
    "ORDER BY gp.precio_gasoleo_a ASC\n"
    "LIMIT 5"
)


def _rota():
    return TableSchema(
        logical_name="gasolineras_rota",
        physical_name="ops.gasolineras_rota",
        description="Postos a ≤5 km do traçado de cada rota.",
        columns=[
            {"name": "origem", "type": "text", "description": "Cidade de origem"},
            {"name": "destino", "type": "text", "description": "Cidade de destino"},
            {
                "name": "id_estacion",
                "type": "integer",
                "description": "FK gasolineras_precio.id_estacion",
            },
        ],
    )


def _precio():
    return TableSchema(
        logical_name="gasolineras_precio",
        physical_name="ops.gasolineras_precio",
        description="Postos de combustível de Espanha, preço actual.",
        columns=[
            {"name": "id_estacion", "type": "integer", "description": "IDEESS"},
            {"name": "rotulo", "type": "text", "description": "Marca do posto"},
            {"name": "provincia", "type": "text", "description": "Província"},
            {"name": "precio_gasoleo_a", "type": "numeric", "description": "€/l"},
        ],
    )


class _Fonte:
    """Fonte falsa: responde aos SELECT DISTINCT com o domínio de cada coluna
    e à consulta principal com linhas só quando o filtro existe."""

    dialect = "postgres"

    def __init__(self, dominios, linhas_se=None):
        self.dominios = dominios
        self.linhas_se = linhas_se or {}
        self.consultas = []

    def sample_table_rows(self, *_a, **_k):
        return []

    def run_query(self, sql):
        self.consultas.append(sql)
        m = re.match(
            r"SELECT DISTINCT (\w+) AS v FROM ([\w.]+) .* LIMIT (\d+)", sql, re.S
        )
        if m:
            col, fisica, limite = m.group(1), m.group(2), int(m.group(3))
            return [{"v": v} for v in self.dominios.get((fisica, col), [])][:limite]
        for literal, linhas in self.linhas_se.items():
            if literal in sql:
                return linhas
        return []


class _Modelo:
    def __init__(self, sql):
        self.sql = sql
        self.mensagens = []

    def invoke(self, mensagens, *_a, **_k):
        self.mensagens.append(mensagens)
        return SimpleNamespace(content=self.sql)


@pytest.fixture(autouse=True)
def _cache_limpa():
    valores_de_coluna.limpar_cache()
    yield
    valores_de_coluna.limpar_cache()


def _dominios():
    return {
        ("ops.gasolineras_rota", "origem"): CIDADES,
        ("ops.gasolineras_rota", "destino"): CIDADES,
        ("ops.gasolineras_precio", "rotulo"): ["REPSOL", "CEPSA", "BP", "GALP"],
        ("ops.gasolineras_precio", "provincia"): ["BADAJOZ", "MADRID", "CÁCERES"],
    }


def _correr(sql_do_modelo, fonte, tabelas_antes=()):
    from core.llm.specialist import run_specialist

    rota, precio = _rota(), _precio()
    cfg = AgentConfig(id="t", name="t", tables=[*tabelas_antes, precio, rota])
    modelo = _Modelo(sql_do_modelo)
    st = run_specialist(
        {
            "question": "Lista las 5 gasolineras con el gasóleo A más barato en la tabla "
            "gasolineras_rota para la ruta Badajoz-Madrid",
            "detected_language": "es",
            "chosen_tables": ["gasolineras_rota", "gasolineras_precio"],
            "chosen_tables_physical": [
                "ops.gasolineras_rota",
                "ops.gasolineras_precio",
            ],
            "join_relationships": [
                {
                    "from_table": "gasolineras_rota",
                    "to_table": "gasolineras_precio",
                    "from_column": "id_estacion",
                    "to_column": "id_estacion",
                }
            ],
        },
        cfg,
        fonte,
        modelo,
    )
    return st, modelo


def _prompt(modelo):
    return "\n".join(m["content"] for m in modelo.mensagens[0])


# ── 1. Valores em TODAS as tabelas escolhidas ──────────────────────────


def test_as_duas_tabelas_escolhidas_levam_valores_ao_prompt():
    fonte = _Fonte(
        _dominios(), {"'BADAJOZ'": [{"rotulo": "REPSOL", "precio_gasoleo_a": 1.39}]}
    )
    _, modelo = _correr(SQL_COM_GRALHA.replace("BAJAZOZ", "BADAJOZ"), fonte)
    prompt = _prompt(modelo)

    linha_origem = next(
        l for l in prompt.splitlines() if l.strip().startswith("- origem")
    )
    linha_rotulo = next(
        l for l in prompt.splitlines() if l.strip().startswith("- rotulo")
    )
    assert "allowed values" in linha_origem and "BADAJOZ" in linha_origem
    assert "allowed values" in linha_rotulo and "REPSOL" in linha_rotulo
    # E a regra de copiar, não escrever.
    assert "COPIED" in prompt


def test_uma_ligacao_larga_nao_deixa_a_segunda_tabela_sem_valores():
    """O defeito: tecto de 40 colunas por PEDIDO, pela ordem do catálogo.
    Com 60 colunas de texto em tabelas que vêm antes, a gasolineras_rota
    ficava sem valores. Agora só as escolhidas são lidas, com tecto por
    tabela."""
    largas = [
        TableSchema(
            logical_name=f"a_tabela_{i}",
            physical_name=f"ops.a_tabela_{i}",
            columns=[{"name": f"c{j}", "type": "text"} for j in range(20)],
        )
        for i in range(3)
    ]
    fonte = _Fonte(
        _dominios(), {"'BADAJOZ'": [{"rotulo": "REPSOL", "precio_gasoleo_a": 1.39}]}
    )
    _, modelo = _correr(SQL_COM_GRALHA.replace("BAJAZOZ", "BADAJOZ"), fonte, largas)

    linha_destino = next(
        l for l in _prompt(modelo).splitlines() if l.strip().startswith("- destino")
    )
    assert "MADRID" in linha_destino
    # Nenhuma tabela não escolhida foi amostrada.
    assert not any("a_tabela_" in q for q in fonte.consultas)


def test_a_rota_ja_nao_amostra_todas_as_tabelas_da_ligacao():
    import api.routes.connection_query as cq

    assert not hasattr(cq, "_enrich_tables_with_sample_values")


def test_coluna_de_cardinalidade_alta_nao_entra_como_valores():
    rota = _rota()
    fonte = _Fonte(
        {("ops.gasolineras_rota", "origem"): [f"cidade {i}" for i in range(40)]}
    )
    anotadas = valores_de_coluna.anotar_valores([rota], fonte)
    assert "ops.gasolineras_rota.origem" not in anotadas
    assert "sample_values" not in rota.columns[0]


# ── 2. Rede: literal com gralha, corrigido e corrido outra vez ─────────


def test_bajazoz_e_corrigido_para_badajoz_e_a_consulta_corre_outra_vez():
    linhas = [{"rotulo": "REPSOL", "precio_gasoleo_a": 1.39}]
    fonte = _Fonte(_dominios(), {"'BADAJOZ'": linhas})
    st, _ = _correr(SQL_COM_GRALHA, fonte)

    assert "'BADAJOZ'" in st["sql"] and "BAJAZOZ" not in st["sql"]
    assert "'MADRID'" in st["sql"]
    assert st["data"] == linhas
    assert st["literal_corrections"] == [
        {
            "table": "ops.gasolineras_rota",
            "column": "origem",
            "from": "BAJAZOZ",
            "to": "BADAJOZ",
        }
    ]
    principais = [q for q in fonte.consultas if not q.startswith("SELECT DISTINCT")]
    assert len(principais) == 2  # a original e UMA repetição


def test_corrigir_literais_directo():
    fonte = _Fonte(_dominios())
    c = corrigir_literais(SQL_COM_GRALHA, "postgres", [_rota(), _precio()], fonte)
    assert c is not None
    assert "UPPER(gr.origem) = 'BADAJOZ'" in c.sql
    assert c.trocas == [
        {
            "table": "ops.gasolineras_rota",
            "column": "origem",
            "from": "BAJAZOZ",
            "to": "BADAJOZ",
        }
    ]


def test_respeita_o_upper_e_a_caixa_dos_valores():
    """Valores em caixa mista: com UPPER() o literal novo vai em maiúsculas;
    sem UPPER() vai exactamente como está na coluna."""
    dominios = {("ops.gasolineras_rota", "origem"): ["Badajoz", "Madrid", "Mérida"]}
    rota = _rota()
    com = corrigir_literais(
        "SELECT id_estacion FROM ops.gasolineras_rota WHERE UPPER(origem) = 'BAJAZOZ'",
        "postgres",
        [rota],
        _Fonte(dominios),
    )
    sem = corrigir_literais(
        "SELECT id_estacion FROM ops.gasolineras_rota WHERE origem = 'merida'",
        "postgres",
        [rota],
        _Fonte(dominios),
    )
    assert com is not None and "'BADAJOZ'" in com.sql
    assert sem is not None and "'Mérida'" in sem.sql


def test_ilike_mantem_os_curingas():
    c = corrigir_literais(
        "SELECT id_estacion FROM ops.gasolineras_rota WHERE origem ILIKE '%sevila%'",
        "postgres",
        [_rota()],
        _Fonte(_dominios()),
    )
    assert c is not None and "'%SEVILLA%'" in c.sql


def test_literal_ambiguo_nao_e_reescrito():
    dominios = {("ops.gasolineras_rota", "origem"): ["PORTO", "PORTE", "MADRID"]}
    assert melhor_candidato("PORTA", ["PORTO", "PORTE", "MADRID"]) is None
    c = corrigir_literais(
        "SELECT id_estacion FROM ops.gasolineras_rota WHERE UPPER(origem) = 'PORTA'",
        "postgres",
        [_rota()],
        _Fonte(dominios),
    )
    assert c is None


def test_literal_sem_parecenca_nao_e_reescrito():
    assert melhor_candidato("VALENCIA", CIDADES) is None
    assert (
        corrigir_literais(
            "SELECT id_estacion FROM ops.gasolineras_rota WHERE origem = 'VALENCIA'",
            "postgres",
            [_rota()],
            _Fonte(_dominios()),
        )
        is None
    )


def test_literal_que_existe_nao_e_tocado():
    assert (
        corrigir_literais(
            "SELECT id_estacion FROM ops.gasolineras_rota "
            "WHERE UPPER(origem) = 'BADAJOZ' AND UPPER(destino) = 'MADRID'",
            "postgres",
            [_rota()],
            _Fonte(_dominios()),
        )
        is None
    )


def test_coluna_de_cardinalidade_alta_nao_e_corrigida():
    """Domínio lido incompleto: um «melhor candidato» não prova nada."""
    muitos = [f"CIDADE{i:04d}" for i in range(600)] + ["BADAJOZ"]
    c = corrigir_literais(
        "SELECT id_estacion FROM ops.gasolineras_rota WHERE origem = 'BAJAZOZ'",
        "postgres",
        [_rota()],
        _Fonte({("ops.gasolineras_rota", "origem"): muitos}),
    )
    assert c is None


def test_zero_linhas_genuinas_nao_repetem_mais_de_uma_vez():
    fonte = _Fonte(_dominios())  # nenhuma combinação devolve linhas
    st, _ = _correr(SQL_COM_GRALHA, fonte)
    assert st["data"] == []
    assert "BAJAZOZ" in st["sql"]  # sem linhas, fica o SQL original
    assert "literal_corrections" not in st
    principais = [q for q in fonte.consultas if not q.startswith("SELECT DISTINCT")]
    assert len(principais) == 2


# ── 3. 0 linhas genuínas: «no hay resultados para …» ──────────────────


def _formatar(lang, sql, pergunta):
    from core.llm.formatter import run_formatter

    class _ModeloQueNaoPodeSerChamado:
        def invoke(self, *_a, **_k):
            raise AssertionError("o formatador não devia chamar o modelo")

    state = {
        "question": pergunta,
        "data": [],
        "sql": sql,
        "detected_language": lang,
        # Havia RAG: era isto que mandava o caso para o LLM e saía a recusa.
        "retrieval_context": ["gasolineras_rota: postos ao longo de cada rota"],
    }
    return run_formatter(
        state, SimpleNamespace(id="t"), llm=_ModeloQueNaoPodeSerChamado()
    )["answer"]


SQL_SEM_LINHAS = (
    "SELECT gp.rotulo FROM ops.gasolineras_rota gr JOIN ops.gasolineras_precio gp "
    "ON gr.id_estacion = gp.id_estacion "
    "WHERE UPPER(gr.origem) = 'BADAJOZ' AND UPPER(gr.destino) = 'VALENCIA' LIMIT 5"
)


@pytest.mark.parametrize(
    "lang, pergunta, comeco, conjuncao",
    [
        (
            "es",
            "Lista las gasolineras de la ruta Badajoz-Valencia",
            "No hay resultados para",
            " y ",
        ),
        (
            "pt",
            "Lista os postos da rota Badajoz-Valencia",
            "Não há resultados para",
            " e ",
        ),
        (
            "en",
            "List the stations on the Badajoz-Valencia route",
            "There are no results for",
            " and ",
        ),
    ],
)
def test_zero_linhas_diz_que_nada_cumpre_o_filtro(lang, pergunta, comeco, conjuncao):
    r = _formatar(lang, SQL_SEM_LINHAS, pergunta)
    assert r.startswith(comeco)
    assert f"origem = BADAJOZ{conjuncao}destino = VALENCIA" in r
    for recusa in ("no puedo", "não posso", "can't", "cannot", "Lo siento", "Sorry"):
        assert recusa not in r


# Sem filtro de texto, «0 linhas» é a resposta certa (agentes de monitorização:
# «lotes a punto de caducar» com caduca < now() + 7 dias). Fica o modelo a
# redigir, nos termos da pergunta — mas proibido de soar a recusa.

RESPOSTA_DO_MODELO = "No hay lotes a punto de caducar en los próximos 7 días."


class _ModeloQueRedige:
    def __init__(self):
        self.mensagens = []

    def invoke(self, mensagens, *_a, **_k):
        self.mensagens.append(mensagens)
        return SimpleNamespace(content=RESPOSTA_DO_MODELO)


@pytest.mark.parametrize(
    "sql",
    [
        # Só datas.
        "SELECT lote, caduca FROM ops.lotes WHERE caduca < now() + interval '7 days'",
        # Data como texto entre aspas: continua a não ser filtro de texto.
        "SELECT lote FROM ops.lotes WHERE caduca = '2026-10-18'",
        # Só números.
        "SELECT SUM(precio_gasoleo_a) FROM ops.gasolineras_precio WHERE precio_gasoleo_a > 9",
    ],
)
@pytest.mark.parametrize("com_rag", [True, False])
def test_zero_linhas_sem_filtro_de_texto_vai_ao_modelo_com_a_regra(sql, com_rag):
    from core.llm.formatter import run_formatter

    modelo = _ModeloQueRedige()
    state = {
        "question": "¿Qué lotes están a punto de caducar?",
        "data": [],
        "sql": sql,
        "detected_language": "es",
        "retrieval_context": ["lotes: caducidad por lote"] if com_rag else [],
    }
    cfg = AgentConfig(id="t", name="t", tables=[])
    r = run_formatter(state, cfg, llm=modelo)["answer"]

    assert len(modelo.mensagens) == 1, "0 linhas sem filtro de texto vai ao modelo"
    assert r.startswith("No hay lotes a punto de caducar")
    prompt = "\n".join(m["content"] for m in modelo.mensagens[0])
    assert "ZERO ROWS" in prompt
    for proibida in ("I cannot", "no puedo", "lo siento", "não posso"):
        assert proibida in prompt  # listadas como proibidas


def test_o_streaming_usa_a_mesma_regra_e_a_mesma_decisao():
    import inspect

    import api.routes.connection_query as cq

    fonte = inspect.getsource(cq)
    assert "REGRA_ZERO_LINHAS" in fonte
    assert "mensagem_sem_resultados" in fonte


def test_mensagem_deterministica_so_com_filtro_de_texto():
    from core.llm.formatter import mensagem_sem_resultados

    assert mensagem_sem_resultados(SQL_SEM_LINHAS, "es").startswith(
        "No hay resultados para origem = BADAJOZ"
    )
    assert (
        mensagem_sem_resultados(
            "SELECT lote FROM ops.lotes WHERE caduca < now() + interval '7 days'",
            "es",
        )
        is None
    )


def test_no_rows_generic_ja_nao_existe():
    from core.i18n.i18n import MESSAGES

    assert "NO_ROWS_GENERIC" not in MESSAGES


def test_descrever_filtros_le_igualdade_in_e_like():
    sql = (
        "SELECT 1 FROM t WHERE UPPER(origem) = 'BADAJOZ' AND destino IN ('MADRID') "
        "AND rotulo ILIKE '%repsol%' AND n = 3"
    )
    assert descrever_filtros(sql) == [
        ("origem", "BADAJOZ"),
        ("destino", "MADRID"),
        ("rotulo", "repsol"),
    ]
