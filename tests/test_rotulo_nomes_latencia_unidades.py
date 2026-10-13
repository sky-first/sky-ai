"""Produção, 12/10/2026 — tenant skyfirstlabs, ligação «Operaciones» (``ops``),
modelos qwen3-coder-30b (especialista) + gpt-oss-120b.

1. «¿Cuál es la gasolinera más barata de gasóleo A en la ruta de Lisboa a
   Madrid?» → «…es la de id 16440, con un precio de 1,69 €». O nome do posto
   (``rotulo`` + ``localidad``) é que responde, não o IDEESS.
2. «Lista las 5 gasolineras más baratas … Badajoz-Madrid» → «… 1,71 € en
   Alcobón». Os dados (MITECO, só com ``strip``) dizem Alcorcón; o modelo
   reescreveu o nome. Os nomes próprios copiam-se dos dados.
3. A pergunta 1 levou 50 s: 16 ``SELECT DISTINCT`` por pergunta, um a um, e
   cache só no processo. Agora cache local + Redis (30 min), em paralelo, sem
   colunas de texto livre.
4. Análise «context» de um agente: «con una diferencia de 36,81» — sem
   unidade. A coluna era ``service_sec``: «36,81 s».
"""

from __future__ import annotations

import re
import threading
import time
from types import SimpleNamespace

import pytest

from core.agents.generic_sql_agent import AgentConfig, TableSchema
from core.llm.nomes import corrigir_nomes, nomear_ids, regras_de_nomes
from core.llm.numeros import (
    CorrecaoEmFluxo,
    corrigir_resposta,
    descricoes_das_colunas,
    regras_de_numeros,
    unidade_do_nome,
    unidades_do_resultado,
)
from core.sql import valores_de_coluna
from core.sql.correcao_de_literais import corrigir_literais
from core.sql.rotulos import ids_com_rotulo, marca_de_rotulo

LIGACAO = "4b0c1e2a-0000-4000-8000-0000000000ops"


def _precio():
    return TableSchema(
        logical_name="gasolineras_precio",
        physical_name="ops.gasolineras_precio",
        description="Postos de combustível de Espanha (MITECO), preço actual.",
        data_connection_id=LIGACAO,
        columns=[
            {
                "name": "id_estacion",
                "type": "integer",
                "description": "IDEESS do MITECO",
            },
            {
                "name": "rotulo",
                "type": "text",
                "description": "Marca / rótulo do posto",
            },
            {"name": "direccion", "type": "text", "description": None},
            {"name": "cp", "type": "text", "description": "Código postal"},
            {"name": "localidad", "type": "text", "description": None},
            {"name": "municipio", "type": "text", "description": None},
            {"name": "provincia", "type": "text", "description": "Província"},
            {"name": "horario", "type": "text", "description": None},
            {"name": "fonte", "type": "text", "description": None},
            {
                "name": "precio_gasoleo_a",
                "type": "numeric",
                "description": "Gasóleo A, €/l, preço de bomba publicado",
            },
        ],
    )


def _rota():
    return TableSchema(
        logical_name="gasolineras_rota",
        physical_name="ops.gasolineras_rota",
        description="Postos a ≤5 km do traçado de cada rota.",
        data_connection_id=LIGACAO,
        columns=[
            {"name": "origem", "type": "text", "description": "Cidade de origem"},
            {"name": "destino", "type": "text", "description": "Cidade de destino"},
            {
                "name": "id_estacion",
                "type": "integer",
                "description": "FK gasolineras_precio.id_estacion",
            },
            {"name": "dist_km", "type": "double precision", "description": None},
        ],
    )


DOMINIOS = {
    ("ops.gasolineras_rota", "origem"): ["LISBOA", "BADAJOZ", "MADRID"],
    ("ops.gasolineras_rota", "destino"): ["MADRID", "LISBOA", "BADAJOZ"],
    ("ops.gasolineras_precio", "rotulo"): ["REPSOL", "CEPSA", "BP", "GALP"],
    ("ops.gasolineras_precio", "localidad"): ["ALCORCON", "BADAJOZ", "MERIDA"],
    ("ops.gasolineras_precio", "municipio"): ["Alcorcón", "Badajoz", "Mérida"],
    ("ops.gasolineras_precio", "provincia"): ["MADRID", "BADAJOZ"],
    ("ops.gasolineras_precio", "direccion"): [f"CALLE {i}" for i in range(80)],
    ("ops.gasolineras_precio", "cp"): [f"{28000 + i}" for i in range(80)],
    ("ops.gasolineras_precio", "horario"): [f"L-D {i}:00" for i in range(80)],
    ("ops.gasolineras_precio", "fonte"): ["MITECO"],
}

SQL_DO_MODELO = (
    "-- TITLE: Gasolinera más barata Lisboa-Madrid\n"
    "SELECT gp.id_estacion, gp.rotulo, gp.localidad, gp.precio_gasoleo_a\n"
    "FROM ops.gasolineras_rota gr\n"
    "JOIN ops.gasolineras_precio gp ON gr.id_estacion = gp.id_estacion\n"
    "WHERE UPPER(gr.origem) = 'LISBOA' AND UPPER(gr.destino) = 'MADRID'\n"
    "ORDER BY gp.precio_gasoleo_a ASC\nLIMIT 1"
)
LINHA_16440 = {
    "id_estacion": 16440,
    "rotulo": "REPSOL",
    "localidad": "ALCORCON",
    "precio_gasoleo_a": 1.69,
}


class _Fonte:
    """Fonte falsa: responde aos SELECT DISTINCT com o domínio de cada coluna
    (com uma espera, para medir o paralelismo) e à consulta principal."""

    dialect = "postgres"

    def __init__(self, espera=0.0, linhas=None):
        self.espera = espera
        self.linhas = linhas if linhas is not None else [LINHA_16440]
        self.distintos = []
        self._lock = threading.Lock()
        self.em_simultaneo = 0
        self.max_em_simultaneo = 0

    def sample_table_rows(self, *_a, **_k):
        return []

    def run_query(self, sql):
        m = re.match(
            r"SELECT DISTINCT (\w+) AS v FROM ([\w.]+) .* LIMIT (\d+)", sql, re.S
        )
        if not m:
            return list(self.linhas)
        with self._lock:
            self.distintos.append((m.group(2), m.group(1)))
            self.em_simultaneo += 1
            self.max_em_simultaneo = max(self.max_em_simultaneo, self.em_simultaneo)
        try:
            if self.espera:
                time.sleep(self.espera)
            col, fisica, limite = m.group(1), m.group(2), int(m.group(3))
            return [{"v": v} for v in DOMINIOS.get((fisica, col), [])][:limite]
        finally:
            with self._lock:
                self.em_simultaneo -= 1


class _Modelo:
    def __init__(self, sql):
        self.sql = sql
        self.mensagens = []

    def invoke(self, mensagens, *_a, **_k):
        self.mensagens.append(mensagens)
        return SimpleNamespace(content=self.sql)


class _RedisFalso:
    """O mínimo do redis-py que a cache usa (mget/setex), partilhado entre
    «pods» — os testes limpam a cache LOCAL para simular outro processo."""

    def __init__(self):
        self.dados = {}
        self.ttls = {}

    def mget(self, chaves):
        return [self.dados.get(c) for c in chaves]

    def setex(self, chave, ttl, valor):
        self.dados[chave] = valor
        self.ttls[chave] = ttl


class _RedisEmBaixo:
    def __init__(self):
        self.chamadas = 0

    def mget(self, chaves):
        self.chamadas += 1
        raise ConnectionError("redis down")

    def setex(self, *_a):
        self.chamadas += 1
        raise ConnectionError("redis down")


@pytest.fixture(autouse=True)
def _cache_limpa():
    valores_de_coluna.limpar_cache()
    valores_de_coluna.usar_redis(None)
    yield
    valores_de_coluna.limpar_cache()
    valores_de_coluna.usar_redis(None)


PERGUNTA = (
    "¿Cuál es la gasolinera más barata de gasóleo A en la ruta de Lisboa a Madrid?"
)


def _correr(fonte, sql=SQL_DO_MODELO, pergunta=PERGUNTA):
    from core.llm.specialist import run_specialist

    cfg = AgentConfig(id="t", name="t", tables=[_precio(), _rota()])
    modelo = _Modelo(sql)
    st = run_specialist(
        {
            "question": pergunta,
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


def _em_fluxo(texto, lingua, linhas, **kw):
    """A mesma correcção, letra a letra, como no streaming."""
    c = CorrecaoEmFluxo(lingua, linhas, **kw)
    saida = "".join(c.receber(ch) for ch in texto)
    return saida + c.terminar()


# ── 1. O nome do posto, não o id ─────────────────────────────────────────


class TestRotulo:
    def test_colunas_de_rotulo_e_de_lugar(self):
        assert marca_de_rotulo("rotulo", "text") == "LABEL"
        assert marca_de_rotulo("nombre", "varchar") == "LABEL"
        assert marca_de_rotulo("customer_name", "text") == "LABEL"
        assert marca_de_rotulo("localidad", "text") == "LABEL: place"
        assert marca_de_rotulo("municipio", "text") == "LABEL: place"
        assert marca_de_rotulo("id_estacion", "integer") == ""
        assert marca_de_rotulo("customer_id", "text") == ""
        assert marca_de_rotulo("precio_gasoleo_a", "numeric") == ""
        # Um nome de rótulo num tipo que não é texto não é rótulo.
        assert marca_de_rotulo("nombre", "integer") == ""

    def test_o_esquema_marca_os_rotulos_e_a_regra_pede_os(self):
        _, modelo = _correr(_Fonte())
        prompt = _prompt(modelo)
        linha = lambda nome: next(  # noqa: E731
            l for l in prompt.splitlines() if l.strip().startswith(f"- {nome} (")
        )
        assert "[LABEL]" in linha("rotulo")
        assert "[LABEL: place]" in linha("localidad")
        assert "LABEL" not in linha("id_estacion")
        assert "ENTITY NAMES" in prompt and "An id ALONE never names" in prompt

    def test_id_16440_vira_o_nome_do_posto(self):
        resposta = (
            "La gasolinera más barata de gasóleo A en la ruta de Lisboa a Madrid "
            "es la de id 16440, con un precio de 1,69 €."
        )
        out = corrigir_resposta(resposta, "es", [LINHA_16440])
        assert "16440" not in out
        assert "es la de REPSOL (ALCORCON), con un precio de 1,69 €/l" in out or (
            "es la de REPSOL (ALCORCON), con un precio de 1,69 €" in out
        )

    def test_con_id_e_entre_parentesis(self):
        linhas = [LINHA_16440]
        assert (
            nomear_ids("La gasolinera con id 16440 es la más barata.", linhas)
            == "La gasolinera REPSOL (ALCORCON) es la más barata."
        )
        # O nome já foi dito: o id entre parêntesis sobra.
        assert (
            nomear_ids("La más barata es REPSOL (id 16440).", linhas)
            == "La más barata es REPSOL."
        )
        assert (
            nomear_ids("La más barata (ID: 16440) cuesta 1,69 €.", linhas)
            == "La más barata (REPSOL (ALCORCON)) cuesta 1,69 €."
        )

    def test_sem_rotulo_na_linha_o_id_fica(self):
        """Não se inventa um nome: sem rótulo na linha, o texto não muda."""
        linhas = [{"id_estacion": 16440, "precio_gasoleo_a": 1.69}]
        texto = "Es la de id 16440."
        assert nomear_ids(texto, linhas) == texto
        # Um número que não é id de nenhuma linha também não.
        assert nomear_ids("Es la de id 99.", [LINHA_16440]) == "Es la de id 99."

    def test_id_com_dois_rotulos_nao_se_adivinha(self):
        linhas = [
            {"id": 7, "nombre": "Ana"},
            {"id": 7, "nombre": "Rui"},
        ]
        assert ids_com_rotulo(linhas) == {}

    def test_em_streaming_sai_o_mesmo(self):
        resposta = (
            "Es la de id 16440, con un precio de 1,69 €. La gasolinera con id "
            "16440 queda en la ruta (id 16440)."
        )
        assert _em_fluxo(resposta, "es", [LINHA_16440]) == corrigir_resposta(
            resposta, "es", [LINHA_16440]
        )

    def test_a_regra_do_formatador(self):
        r = regras_de_nomes()
        assert "never by an internal id" in r
        assert "EXACTLY as they" in r


# ── 2. Nomes próprios copiados dos dados ─────────────────────────────────


LINHAS_A5 = [
    {"rotulo": "BALLENOIL", "localidad": "ALCORCÓN", "precio_gasoleo_a": 1.71},
    {"rotulo": "PLENOIL", "localidad": "ALCORCÓN", "precio_gasoleo_a": 1.71},
    {"rotulo": "REPSOL", "localidad": "MÓSTOLES", "precio_gasoleo_a": 1.74},
]


class TestNomesProprios:
    def test_alcobon_volta_a_ser_o_valor_dos_dados(self):
        texto = "Hay dos precios de 1,71 € en Alcobón y uno de 1,74 € en Móstoles."
        out = corrigir_nomes(texto, LINHAS_A5)
        assert "Alcobón" not in out
        assert "en ALCORCÓN y uno" in out
        # O que já está certo (sem acentos nem maiúsculas) não se toca.
        assert "en Móstoles." in out

    def test_se_os_dados_dizem_alcobon_nada_muda(self):
        linhas = [{"rotulo": "BP", "localidad": "Alcobón", "precio_gasoleo_a": 1.71}]
        texto = "Hay un precio de 1,71 € en Alcobón."
        assert corrigir_nomes(texto, linhas) == texto

    def test_palavras_da_pergunta_e_comuns_nao_se_trocam(self):
        linhas = [{"localidad": "ENTRENA"}, {"localidad": "MADRIZ"}]
        # «Madrid» vem da pergunta; «Entre» é uma palavra comum.
        texto = "Entre Lisboa y Madrid no hay más."
        assert corrigir_nomes(texto, linhas, "ruta de Lisboa a Madrid") == texto

    def test_ambiguo_nao_se_troca(self):
        linhas = [{"localidad": "ALCORCON"}, {"localidad": "ALCORCOX"}]
        assert corrigir_nomes("en Alcorcoz", linhas) == "en Alcorcoz"

    def test_longe_de_mais_nao_se_troca(self):
        assert corrigir_nomes("en Getafe", LINHAS_A5) == "en Getafe"

    def test_pela_correcao_inteira_e_em_streaming(self):
        texto = (
            "Las 5 gasolineras más baratas son BALLENOIL y PLENOIL, con dos "
            "precios de 1,71 € en Alcobón, y REPSOL con 1,74 € en Mostoles."
        )
        inteira = corrigir_resposta(texto, "es", LINHAS_A5, pergunta="Badajoz-Madrid")
        assert "en ALCORCÓN, y REPSOL" in inteira
        assert "en Mostoles." in inteira  # igual sem acentos: fica
        assert _em_fluxo(texto, "es", LINHAS_A5, pergunta="Badajoz-Madrid") == inteira


# ── 3. Latência: cache partilhada, paralelo, sem texto livre ─────────────


class TestLatencia:
    def test_amostras_reutilizadas_entre_dois_pedidos_noutro_processo(self):
        """Dois pedidos, cada um com a SUA fonte (como na rota), e a cache
        local apagada entre eles (outro pod / worker): o segundo não faz
        nenhum SELECT DISTINCT — vem tudo do Redis."""
        redis = _RedisFalso()
        valores_de_coluna.usar_redis(redis)

        primeira = _Fonte()
        _, m1 = _correr(primeira)
        assert primeira.distintos, "o primeiro pedido tem de amostrar"
        assert redis.dados and set(redis.ttls.values()) == {30 * 60}

        valores_de_coluna.limpar_cache()  # outro processo
        segunda = _Fonte()
        _, m2 = _correr(segunda)
        assert segunda.distintos == []
        assert valores_de_coluna.estatisticas["redis"] > 0
        # E o prompt leva os mesmos valores.
        for modelo in (m1, m2):
            origem = next(
                l
                for l in _prompt(modelo).splitlines()
                if l.strip().startswith("- origem")
            )
            assert "LISBOA" in origem

    def test_amostras_reutilizadas_no_mesmo_processo_sem_redis(self):
        _correr(_Fonte())
        segunda = _Fonte()
        _correr(segunda)
        assert segunda.distintos == []

    def test_cache_expira(self, monkeypatch):
        monkeypatch.setattr(valores_de_coluna, "TTL_SEGUNDOS", -1)
        _correr(_Fonte())
        segunda = _Fonte()
        _correr(segunda)
        assert segunda.distintos

    def test_chave_separa_tenants_e_ligacoes(self):
        from core.tenant_context import (
            TenantContext,
            reset_current_tenant,
            set_current_tenant,
        )

        a = valores_de_coluna.chave_da_coluna("lig1", "ops.t", "c")
        assert a != valores_de_coluna.chave_da_coluna("lig2", "ops.t", "c")
        token = set_current_tenant(
            TenantContext(
                slug="outro",
                id="11111111-1111-1111-1111-111111111111",
                tier="pilot",
                display_name="Outro",
            )
        )
        try:
            assert valores_de_coluna.chave_da_coluna("lig1", "ops.t", "c") != a
        finally:
            reset_current_tenant(token)

    def test_texto_livre_nao_se_amostra(self):
        fonte = _Fonte()
        _correr(fonte)
        lidas = {c for _, c in fonte.distintos}
        assert {"direccion", "cp", "horario", "fonte"}.isdisjoint(lidas)
        assert {"origem", "destino", "rotulo", "localidad", "provincia"} <= lidas

    def test_texto_livre_nomeado_na_pergunta_amostra_se(self):
        fonte = _Fonte()
        _correr(fonte, pergunta="¿Qué horario tiene la gasolinera más barata?")
        assert "horario" in {c for _, c in fonte.distintos}

    def test_consultas_em_paralelo(self):
        fonte = _Fonte(espera=0.15)
        inicio = time.monotonic()
        _correr(fonte)
        decorrido = time.monotonic() - inicio
        n = len(fonte.distintos)
        assert n >= 6
        assert fonte.max_em_simultaneo > 1
        # Em série seriam n × 0,15 s.
        assert decorrido < n * 0.15 * 0.6

    def test_correcao_de_literais_usa_a_mesma_cache(self):
        rota, precio = _rota(), _precio()
        fonte = _Fonte()
        valores_de_coluna.anotar_valores([rota, precio], fonte)
        antes = len(fonte.distintos)
        c = corrigir_literais(
            SQL_DO_MODELO.replace("'LISBOA'", "'LISBOAA'"),
            "postgres",
            [rota, precio],
            fonte,
        )
        assert c is not None and "'LISBOA'" in c.sql
        assert len(fonte.distintos) == antes  # domínio completo já lido

    def test_redis_em_baixo_nao_soma_timeouts(self):
        redis = _RedisEmBaixo()
        valores_de_coluna.usar_redis(redis)
        fonte = _Fonte()
        st, _ = _correr(fonte)
        assert fonte.distintos  # leu da fonte
        assert st.get("sql")
        # Uma falha pausa o Redis: não uma chamada por coluna.
        assert redis.chamadas == 1


# ── 4. Unidades ──────────────────────────────────────────────────────────

SQL_CANAIS = (
    "SELECT channel, AVG(service_sec) AS avg_service_sec, "
    "AVG(service_sec) - (SELECT AVG(service_sec) FROM ops.drive_thru) AS diferencia "
    "FROM ops.drive_thru GROUP BY channel"
)
LINHAS_CANAIS = [
    {"channel": "drive", "avg_service_sec": 120.5, "diferencia": 36.81},
    {"channel": "sala", "avg_service_sec": 46.88, "diferencia": -36.81},
]
FRASE = (
    "La mayor diferencia está en el canal drive, con una diferencia de 36,81; "
    "aproximar el peor a la media generaría un ganho de 36,81."
)


class TestUnidades:
    def test_unidade_pelo_nome(self):
        assert unidade_do_nome("service_sec") == "s"
        assert unidade_do_nome("avg_wait_min") == "min"
        assert unidade_do_nome("dist_km") == "km"
        assert unidade_do_nome("margen_pct") == "%"
        assert unidade_do_nome("litros_vendidos") == "l"
        assert unidade_do_nome("unidades_vendidas") == "un"
        assert unidade_do_nome("precio_gasoleo_a") is None  # dinheiro: €
        assert unidade_do_nome("id_estacion") is None
        assert unidade_do_nome("channel") is None

    def test_service_sec_36_81_leva_segundos(self):
        linhas = [
            {"channel": "drive", "service_sec": 120.5},
            {"channel": "sala", "service_sec": 46.88},
        ]
        # 120,5 − média (83,69) = 36,81: a diferença também é em segundos.
        out = corrigir_resposta(FRASE, "es", linhas)
        assert "una diferencia de 36,81 s;" in out
        assert "un ganho de 36,81 s." in out

    def test_alias_herda_a_unidade_pelo_sql(self):
        assert unidades_do_resultado(
            ["channel", "avg_service_sec", "diferencia"], SQL_CANAIS
        ) == {"avg_service_sec": "s", "diferencia": "s"}
        out = corrigir_resposta(FRASE, "es", LINHAS_CANAIS, sql=SQL_CANAIS)
        assert "36,81 s;" in out and "36,81 s." in out

    def test_divisao_ou_contagem_nao_herdam(self):
        sql = (
            "SELECT SUM(service_sec) / 60 AS x, COUNT(service_sec) AS n, "
            "service_sec * 2 AS y FROM t"
        )
        assert unidades_do_resultado(["x", "n", "y"], sql) == {}

    def test_unidade_pela_descricao(self):
        assert unidades_do_resultado(
            ["duracion"], None, {"duracion": "Duración del servicio en segundos"}
        ) == {"duracion": "s"}
        # «€/l» na descrição é preço, não litros.
        assert (
            unidades_do_resultado(["media"], None, {"media": "Média diária, €/l"}) == {}
        )

    def test_descricoes_das_tabelas_do_agente(self):
        t = TableSchema(
            logical_name="servicio",
            physical_name="ops.servicio",
            columns=[{"name": "duracion", "type": "int", "description": "en minutos"}],
        )
        d = descricoes_das_colunas([t], ["servicio"])
        assert unidades_do_resultado(["duracion"], None, d) == {"duracion": "min"}

    def test_unidade_ja_escrita_nao_se_repete(self):
        linhas = [{"service_sec": 36.81}, {"service_sec": 10.0}]
        for t in ("Fue de 36,81 s.", "Fue de 36,81 segundos.", "Fue de 36,81 seg."):
            assert corrigir_resposta(t, "es", linhas) == t

    def test_numero_seguido_de_substantivo_nao_leva_unidade(self):
        """«las 5 gasolineras»: o 5 conta postos, mesmo que um dist_km seja 5."""
        linhas = [{"rotulo": "BP", "dist_km": 5.0}, {"rotulo": "GALP", "dist_km": 2.5}]
        out = corrigir_resposta("Las 5 gasolineras más cercanas.", "es", linhas)
        assert out == "Las 5 gasolineras más cercanas."
        assert "a 2,50 km." in corrigir_resposta("La GALP está a 2,5.", "es", linhas)

    def test_valor_ambiguo_nao_leva_unidade(self):
        linhas = [{"service_sec": 12.0, "pedidos": 12}]
        assert corrigir_resposta("Fueron 12.", "es", linhas) == "Fueron 12."

    def test_percentagem_em_fraccao_nao_leva_percentagem(self):
        linhas = [{"conversion_pct": 0.75}, {"conversion_pct": 0.5}]
        assert corrigir_resposta("Fue de 0,75.", "es", linhas) == "Fue de 0,75."
        linhas = [{"conversion_pct": 75.0}, {"conversion_pct": 50.0}]
        assert corrigir_resposta("Fue de 75.", "es", linhas) == "Fue de 75 %."
        assert corrigir_resposta("It was 75.", "en", linhas) == "It was 75%."

    def test_em_ingles_e_portugues(self):
        linhas = [{"wait_min": 12.5}, {"wait_min": 3.5}]
        assert corrigir_resposta("The longest wait was 12.5.", "en", linhas) == (
            "The longest wait was 12.50 min."
        )
        linhas = [{"unidades_vendidas": 1250}, {"unidades_vendidas": 300}]
        # Uma contagem do resultado leva separador desde 1000 (13/10/2026:
        # «Tienda 01 con 4526 pedidos» → «4.526 pedidos»).
        assert corrigir_resposta("Vendeu 1250 e 300.", "pt", linhas) == (
            "Vendeu 1.250 unidades e 300 unidades."
        )

    def test_regra_no_prompt(self):
        r = regras_de_numeros(
            "es", ["channel", "diferencia"], unidades={"diferencia": "s"}
        )
        assert "UNITS" in r and "diferencia is in s" in r and "36,81 s" in r

    def test_em_streaming_sai_o_mesmo(self):
        inteira = corrigir_resposta(FRASE, "es", LINHAS_CANAIS, sql=SQL_CANAIS)
        assert _em_fluxo(FRASE, "es", LINHAS_CANAIS, sql=SQL_CANAIS) == inteira
        assert "36,81 s;" in inteira

    @pytest.mark.parametrize("tamanho", [1, 2, 3, 5, 7, 11])
    def test_streaming_com_pedacos_de_qualquer_tamanho(self, tamanho):
        casos = [
            (FRASE, LINHAS_CANAIS, {"sql": SQL_CANAIS}),
            (
                "Es la de id 16440, con un precio de 1,69 €. Queda en Alcorcon.",
                [LINHA_16440],
                {},
            ),
            (
                "Dos precios de 1,71 € en Alcobón, y REPSOL con 1,74 € en Mostoles.",
                LINHAS_A5,
                {},
            ),
        ]
        for texto, linhas, kw in casos:
            c = CorrecaoEmFluxo("es", linhas, **kw)
            saida = "".join(
                c.receber(texto[i : i + tamanho]) for i in range(0, len(texto), tamanho)
            )
            saida += c.terminar()
            assert saida == corrigir_resposta(texto, "es", linhas, **kw)

    def test_o_formatador_aplica_as_unidades(self):
        from core.llm.formatter import run_formatter

        class _M:
            def __init__(self):
                self.mensagens = None

            def invoke(self, mensagens, *_a, **_k):
                self.mensagens = mensagens
                return SimpleNamespace(content=FRASE)

        cfg = AgentConfig(id="t", name="t", tables=[])
        modelo = _M()
        st = run_formatter(
            {
                "question": "¿Dónde está la mayor diferencia de servicio?",
                "detected_language": "es",
                "data": list(LINHAS_CANAIS),
                "sql": SQL_CANAIS,
            },
            cfg,
            modelo,
        )
        assert "36,81 s;" in st["answer"]
        prompt = "\n".join(m["content"] for m in modelo.mensagens)
        assert "diferencia is in s" in prompt
        assert "NAMES (NON-NEGOTIABLE)" in prompt
