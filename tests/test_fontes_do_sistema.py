# -*- coding: utf-8 -*-
"""Fontes do sistema (dados públicos geridos pela Sky) — lado do sky-ai.

Desenho aprovado a 13/10/2026 (``design-fontes-do-sistema.md``):

1. **Portão da Fase 0 (decisão 4).** As perguntas mistas — dados do cliente ×
   dados públicos — passam pelo caminho multi-ligação. O portão
   (``scripts/portao_fontes``) corre as 10 perguntas do Anexo C contra duas
   bases separadas, com números certos calculados em SQL escrito à mão.
   Medido a 13/10/2026 com o oráculo (o modelo ideal, limitado ao que o
   prompt mostra): ``origin/main`` = 6/10, esta versão = 10/10. As quatro
   falhas de main eram TODAS a fatia do cliente cortada pelo ``LIMIT 100``
   que o prompt do especialista exige — o merger somava 100 dias de 365.
2. **Discover (L1/L4).** Tabelas que saem do catálogo (fonte desligada,
   REVOKE) saem do índice: metadados, embeddings e cache semântica, em todos
   os âmbitos — e o guarda «descoberta recente» deixa de saltar a descoberta
   quando o conjunto de tabelas mudou.
3. **Conector ``sky-world``.** Credencial por referência ao segredo (nunca de
   outro cliente) e a citação obrigatória da fonte e da hora do dado.
"""

from __future__ import annotations

import datetime as dt
import os
import re

import pytest

os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")


# ═══════════════════════════════════════════════════════════════════════
# 1. O portão
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def portao():
    from scripts.portao_fontes.correr import correr

    return correr(llm="oraculo", arquitectura="nova", com_formatter=True)


def test_portao_da_fase_0_passa_com_folga(portao):
    """Critério do desenho: ≥ 8/10 com o número certo. Com o modelo ideal
    tem de dar 10/10 — uma falha aqui é estrutural, não do modelo."""
    falhas = {r["id"]: r.get("porque") for r in portao if not r.get("ok")}
    assert len(portao) == 10
    assert not falhas, falhas


def test_portao_cada_pergunta_cruza_duas_ligacoes(portao):
    for r in portao:
        assert r["multi_ligacao"], r["id"]
        assert len(r["fatias"]) == 2, (r["id"], r["fatias"])


def test_fatia_ao_grao_do_dia_chega_inteira(portao):
    """P4: viagens em feriado — a fatia do cliente tem uma linha por dia do
    ano (365). Com «LIMIT 100» o merger contava 16 viagens em vez de 37."""
    p4 = next(r for r in portao if r["id"] == "P4")
    cliente = next(f for f in p4["fatias"] if "trips" in f["tabelas"])
    assert cliente["linhas"] == 365
    assert "LIMIT 5000" in cliente["sql"]


def test_tabelas_da_mesma_ligacao_vao_na_mesma_fatia(portao):
    """trips × routes (Badajoz–Madrid) junta-se no SQL nativo do cliente;
    o merger só junta o que vive em bases diferentes."""
    p7 = next(r for r in portao if r["id"] == "P7")
    assert any(f["tabelas"] == "trips, vehicles, routes" for f in p7["fatias"])


def test_resposta_cita_fonte_e_hora_e_diz_atrasado(portao):
    p10 = next(r for r in portao if r["id"] == "P10")
    assert "AEMET" in p10["resposta"]
    assert "actualizado a las" in p10["resposta"]
    # o tempo parou há 2 dias com cadência de 6 h
    assert "con retraso" in p10["resposta"]
    p9 = next(r for r in portao if r["id"] == "P9")
    assert "Weekly Oil Bulletin" in p9["resposta"]
    assert "con retraso" not in p9["resposta"]


# ═══════════════════════════════════════════════════════════════════════
# 1b. As peças do caminho multi-ligação
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def amb():
    from scripts.portao_fontes.fixtures import Ambiente

    return Ambiente()


def test_agrupar_por_ligacao(amb):
    from core.llm.multi_fonte import agrupar_por_ligacao
    from scripts.portao_fontes.fixtures import LIGACAO_CLIENTE, LIGACAO_MUNDO

    fatias = agrupar_por_ligacao(
        ["trips", "festivos", "routes", "gasolineras_rota"],
        amb.config,
        amb.dispatch_map,
    )
    assert [f.connection_id for f in fatias] == [LIGACAO_CLIENTE, LIGACAO_MUNDO]
    assert fatias[0].rotulos == ["trips", "routes"]
    assert fatias[1].fisicas == ["mundo.festivos", "mundo.gasolineras_rota"]
    assert fatias[1].rotulo_fonte == "Dados públicos (sky-world)"


def test_pistas_de_juncao_usam_a_referencia_documentada_e_a_data(amb):
    from core.llm.multi_fonte import agrupar_por_ligacao, pistas_de_juncao

    cli, mun = agrupar_por_ligacao(
        ["trips", "routes", "gasolineras_rota", "festivos"],
        amb.config,
        amb.dispatch_map,
    )
    pistas = pistas_de_juncao(cli.tabelas, mun.tabelas)
    assert "gasolineras_rota.origem = routes.origin" in pistas
    assert "gasolineras_rota.destino = routes.destination" in pistas
    assert "festivos.data = CAST(trips.departed_at AS DATE) (day grain)" in pistas
    # uma vez cada par, e um só instante por data (não 3 variantes)
    assert len(pistas) == len(set(pistas))
    assert not any("arrived_at" in p for p in pistas)


def test_contrato_mostra_as_outras_tabelas_e_o_limite(amb):
    from core.llm.multi_fonte import agrupar_por_ligacao, contrato_da_fatia

    cli, mun = agrupar_por_ligacao(["trips", "festivos"], amb.config, amb.dispatch_map)
    c = contrato_da_fatia(cli, [mun])
    assert "festivos (mundo.festivos)" in c
    assert "regiao text" in c
    assert "LIMIT 5000" in c
    assert "KEEP the join key columns" in c


class _LLMGravador:
    """Responde com SQL fixo e guarda as mensagens."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.mensagens = []

    def invoke(self, msgs, **_):
        self.mensagens.append(msgs)
        r = self.respostas.pop(0) if self.respostas else "IMPOSSIBLE: fim"

        class R:
            content = r

        return R()


def _estado(pergunta):
    return {
        "question": pergunta,
        "detected_language": "es",
        "chat_history": [],
        "retrieval_context": [],
    }


def test_especialista_de_fatia_pede_limit_5000_e_leva_o_contrato(amb):
    from core.llm.specialist import run_specialist

    llm = _LLMGravador(["-- TITLE: x\nSELECT data FROM mundo.festivos LIMIT 5000"])
    st = _estado("¿viajes en festivo?")
    st.update(
        chosen_table="festivos",
        chosen_table_physical="mundo.festivos",
        chosen_tables=["festivos"],
        chosen_tables_physical=["mundo.festivos"],
        multi_source_subquery=True,
        contrato_da_fatia="MULTI-SOURCE SLICE CONTRACT (mandatory): xyz",
    )
    r = run_specialist(st, amb.config, amb.fonte_mundo, llm)
    sistema, user = llm.mensagens[0][0]["content"], llm.mensagens[0][1]["content"]
    assert "LIMIT 5000" in sistema and "LIMIT 100 " not in sistema
    assert "MULTI-SOURCE SLICE CONTRACT (mandatory): xyz" in user
    assert len(r["data"]) == 26  # todos os feriados, sem corte


def test_especialista_normal_mantem_limit_100(amb):
    from core.llm.specialist import run_specialist

    llm = _LLMGravador(
        ["-- TITLE: x\nSELECT COUNT(*) AS n FROM mundo.festivos LIMIT 100"]
    )
    st = _estado("¿cuántos festivos hay?")
    st.update(
        chosen_table="festivos",
        chosen_table_physical="mundo.festivos",
        chosen_tables=["festivos"],
        chosen_tables_physical=["mundo.festivos"],
    )
    run_specialist(st, amb.config, amb.fonte_mundo, llm)
    assert "LIMIT 100" in llm.mensagens[0][0]["content"]
    assert "LIMIT 5000" not in llm.mensagens[0][0]["content"]


def test_reparacao_de_fanout_nao_troca_sql_por_impossible(amb):
    """trips × drivers dispara o detector de fan-out (falso positivo: N:1).
    Se o modelo responder IMPOSSIBLE à reparação, o SQL bom fica — antes
    trocava-o por prosa e a fatia morria em «Only SELECT queries»."""
    from core.llm.specialist import run_specialist

    sql = (
        "SELECT CAST(t.departed_at AS DATE) AS dia, SUM(t.driver_hours * d.cost_per_hour) AS c "
        "FROM ops.trips t JOIN fleet.drivers d ON d.id = t.driver_id GROUP BY 1 LIMIT 5000"
    )
    llm = _LLMGravador([f"-- TITLE: x\n{sql}", "IMPOSSIBLE: não sei"])
    st = _estado("coste de conductor por día")
    st.update(
        chosen_table="trips",
        chosen_table_physical="ops.trips",
        chosen_tables=["trips", "drivers"],
        chosen_tables_physical=["ops.trips", "fleet.drivers"],
        multi_source_subquery=True,
        contrato_da_fatia="MULTI-SOURCE SLICE CONTRACT (mandatory): xyz",
    )
    r = run_specialist(st, amb.config, amb.fonte_cliente, llm)
    assert not r.get("error"), r.get("error")
    assert len(r["data"]) == 365
    # houve reparação, e levou o contrato
    assert len(llm.mensagens) == 2
    assert "MULTI-SOURCE SLICE CONTRACT" in llm.mensagens[1][1]["content"]


def test_merger_corrige_uma_vez_o_erro_do_duckdb():
    from core.llm.merger import run_merger
    from core.agents.generic_sql_agent import AgentConfig

    llm = _LLMGravador(
        [
            "```sql\nSELECT SUM(litro) AS l FROM dataset_1\n```",
            "```sql\nWITH x AS (SELECT litros FROM dataset_1) SELECT SUM(litros) AS l FROM x\n```",
        ]
    )
    st = {
        "question": "litros",
        "plan": "",
        "multi_fonte_por_ligacao": True,
        "partial_results": [
            {
                "table": "trips",
                "data": [{"litros": 1.5}, {"litros": 2.0}],
                "metadata": {},
            },
            {"table": "festivos", "data": [{"data": "2026-01-01"}], "metadata": {}},
        ],
    }
    r = run_merger(st, AgentConfig(id="t", name="t", tables=[]), llm)
    assert not r.get("error"), r.get("error")
    assert r["data"] == [{"l": 3.5}]
    assert "DuckDB rejected that query" in llm.mensagens[1][-1]["content"]


def test_merger_mostra_pistas_de_data_e_de_texto():
    from core.llm.merger import (
        _generate_merger_prompt_por_ligacao as _generate_merger_prompt,
    )

    pr = [
        {
            "table": "trips, routes",
            "data": [
                {
                    "origin": "Badajoz",
                    "dia": dt.datetime(2026, 9, 1, 6, tzinfo=dt.timezone.utc),
                    "n": 1,
                }
            ],
            "metadata": {
                "source": "Operaciones",
                "descricoes": {"origin": "Cidade de origem"},
            },
        },
        {
            "table": "gasolineras_rota",
            "data": [{"origem": "BADAJOZ", "data": dt.date(2026, 9, 1)}],
            "metadata": {"source": "Dados públicos"},
        },
    ]
    user = _generate_merger_prompt("q", pr, "")[1]["content"]
    assert (
        "lower(strip_accents(dataset_1.origin)) = lower(strip_accents(dataset_2.origem))"
        in user
    )
    assert "CAST(dataset_1.dia AS DATE) = CAST(dataset_2.data AS DATE)" in user
    assert "origin — Cidade de origem" in user
    assert '"2026-09-01"' in user  # amostras em JSON, não repr de Python


# ═══════════════════════════════════════════════════════════════════════
# 2. Discover: o que saiu do catálogo sai do índice
# ═══════════════════════════════════════════════════════════════════════


class _Res:
    def __init__(self, linhas=None, rowcount=0):
        self._linhas = linhas or []
        self.rowcount = rowcount

    def first(self):
        return self._linhas[0] if self._linhas else None

    def fetchall(self):
        return self._linhas


class _BaseFalsa:
    def __init__(self, catalogo, indice, desc=None, sem_linha=False):
        self.catalogo = catalogo
        self.indice = indice
        self.desc = desc or []
        self.sem_linha = sem_linha
        self.chamadas = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.chamadas.append((sql, params or {}))
        if sql.startswith("SELECT tables FROM connection_metadata"):
            return _Res([] if self.sem_linha else [(self.catalogo,)])
        if sql.startswith("SELECT DISTINCT table_name FROM table_metadata"):
            return _Res([(n,) for n in self.indice])
        if sql.startswith("SELECT DISTINCT metadata->>'table_name'"):
            return _Res([(n,) for n in self.desc])
        return _Res(rowcount=2)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


async def test_poda_tira_do_indice_as_tabelas_que_sairam():
    from core.ingestion.podar import podar_tabelas_removidas

    db = _BaseFalsa(
        catalogo=[{"name": "mundo.festivos"}, {"name": "mundo.portagens"}],
        indice=["festivos", "portagens", "gasolineras_precio"],
        desc=["gasolineras_precio", "festivos"],
    )
    r = await podar_tabelas_removidas(db, "c1")
    assert r["removidas"] == ["gasolineras_precio"]
    apagados = [(s, p) for s, p in db.chamadas if s.startswith("DELETE")]
    alvos = " | ".join(s for s, _ in apagados)
    assert "DELETE FROM embeddings WHERE table_metadata_id IN" in alvos
    assert "DELETE FROM table_metadata" in alvos
    assert "dataset_description" in alvos
    # todos os âmbitos: o DELETE não filtra por space_id nem crew_id
    assert "space_id" not in alvos and "crew_id" not in alvos
    cache = next(p for s, p in apagados if "semantic_cache" in s)
    assert cache["padroes"] == ["%gasolineras_precio%"]
    assert db.commits == 1


async def test_poda_com_catalogo_vazio_tira_tudo():
    """A última fonte desligada: o catálogo fica vazio e a ingestão saía no
    início sem apagar nada."""
    from core.ingestion.podar import podar_tabelas_removidas

    db = _BaseFalsa(catalogo=[], indice=["festivos", "portagens"])
    r = await podar_tabelas_removidas(db, "c1")
    assert r["removidas"] == ["festivos", "portagens"]


async def test_poda_sem_catalogo_nao_apaga_nada():
    from core.ingestion.podar import podar_tabelas_removidas

    db = _BaseFalsa(catalogo=None, indice=["festivos"], sem_linha=True)
    r = await podar_tabelas_removidas(db, "c1")
    assert r["removidas"] == []
    assert not any(s.startswith("DELETE") for s, _ in db.chamadas)


async def test_catalogo_difere_do_indice():
    from core.ingestion.podar import catalogo_difere_do_indice

    igual = _BaseFalsa(catalogo=[{"name": "mundo.festivos"}], indice=["festivos"])
    assert await catalogo_difere_do_indice(igual, "c1") is False
    nova = _BaseFalsa(
        catalogo=[{"name": "mundo.festivos"}, {"name": "mundo.portagens"}],
        indice=["festivos"],
    )
    assert await catalogo_difere_do_indice(nova, "c1") is True
    saiu = _BaseFalsa(catalogo=[], indice=["festivos"])
    assert await catalogo_difere_do_indice(saiu, "c1") is True


def test_o_guarda_da_descoberta_nao_salta_com_o_catalogo_mudado():
    import inspect

    from api.routes import connection_discover

    fonte = inspect.getsource(connection_discover.discover_tables)
    i = fonte.index('row["age"] is not None')
    assert "not await _catalogo_difere(db, connection_id)" in fonte[i : i + 900]
    # e a poda corre nos dois caminhos (síncrono e em segundo plano)
    assert fonte.count("podar_tabelas_removidas(") == 2


# ═══════════════════════════════════════════════════════════════════════
# 3. Conector sky-world e citação
# ═══════════════════════════════════════════════════════════════════════


def test_credential_ref_so_do_proprio_cliente():
    from core.data_sources.sky_world import CredencialRecusada, validar_credential_ref

    assert validar_credential_ref("sky/production/world/tenants/acme", "acme") == "acme"
    with pytest.raises(CredencialRecusada):
        validar_credential_ref("sky/production/world/tenants/outro", "acme")
    with pytest.raises(CredencialRecusada):
        validar_credential_ref("sky/production/tenants/acme/db", "acme")
    with pytest.raises(CredencialRecusada):
        validar_credential_ref("sky/production/world/tenants/acme/../outro", "acme")


def test_prefixo_do_backend_e_exacto(monkeypatch):
    from core.data_sources.sky_world import CredencialRecusada, validar_credential_ref

    monkeypatch.setenv("WORLD_TENANT_SECRET_PREFIX", "sky/test/world/tenants/")
    assert validar_credential_ref("sky/test/world/tenants/mopa", "mopa") == "mopa"
    with pytest.raises(CredencialRecusada):
        validar_credential_ref("sky/production/world/tenants/mopa", "mopa")


def test_modo_local_deriva_a_mesma_password_que_o_backend(monkeypatch):
    """sky-backend fontes_sistema/credenciais.py::_derivada — HMAC-SHA256 do
    ENCRYPTION_KEY sobre «sky_world:<slug>», base64 url-safe sem «=»."""
    import base64
    import hashlib
    import hmac

    from core.data_sources import sky_world

    monkeypatch.setenv("WORLD_CREDENTIAL_BACKEND", "local")
    monkeypatch.setenv("ENCRYPTION_KEY", "chave-de-teste")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    esperado = (
        base64.urlsafe_b64encode(
            hmac.new(b"chave-de-teste", b"sky_world:mopa-2", hashlib.sha256).digest()
        )
        .decode()
        .rstrip("=")
    )
    c = sky_world.resolver_credencial("sky/test/world/tenants/mopa-2", "mopa-2")
    assert c == {"username": "wt_mopa_2", "password": esperado}
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(sky_world.CredencialRecusada):
        sky_world.resolver_credencial("sky/test/world/tenants/mopa-2", "mopa-2")


def test_dsn_vem_do_segredo_e_ignora_password_na_config(monkeypatch):
    from core.data_sources import sky_world

    sky_world.limpar_cache_segredos()
    lidos = []

    def ler(ref):
        lidos.append(ref)
        return {"username": "wt_acme", "password": "s3gr3do"}

    monkeypatch.setattr(sky_world, "ler_segredo", ler)
    cfg = {
        "credential_ref": "sky/production/world/tenants/acme",
        "host": "rds.local",
        "database": "sky_world",
        "password": "da-config",
    }
    dsn = sky_world.dsn_da_config(cfg, "acme")
    assert dsn == "postgresql+psycopg2://wt_acme:s3gr3do@rds.local:5432/sky_world"
    sky_world.dsn_da_config(cfg, "acme")
    assert lidos == ["sky/production/world/tenants/acme"]  # cache de 5 min
    sky_world.limpar_cache_segredos()


def test_factory_monta_sky_world(monkeypatch):
    from core.data_sources import sky_world
    from core.data_sources.factory import DataSourceFactory

    sky_world.limpar_cache_segredos()
    monkeypatch.setattr(
        sky_world, "ler_segredo", lambda ref: {"username": "wt_x", "password": "p"}
    )
    monkeypatch.setattr(sky_world, "_slug_do_pedido", lambda: "acme")

    class Conn:
        id = "c-1"
        connector_id = "sky-world"
        config = {
            "credential_ref": "sky/production/world/tenants/acme",
            "host": "h",
            "schema": "mundo",
        }

    ds = DataSourceFactory.build_from_dataconnection(Conn())
    assert isinstance(ds, sky_world.SkyWorldDataSource)
    assert sky_world.e_fonte_do_sistema(ds)
    assert ds.esquema == "mundo"
    sky_world.limpar_cache_segredos()


def test_factory_recusa_referencia_de_outro_cliente(monkeypatch):
    from core.data_sources import sky_world
    from core.data_sources.factory import DataSourceFactory

    monkeypatch.setattr(sky_world, "_slug_do_pedido", lambda: "acme")

    class Conn:
        id = "c-1"
        connector_id = "sky-world"
        config = {"credential_ref": "sky/production/world/tenants/vizinho", "host": "h"}

    with pytest.raises(sky_world.CredencialRecusada):
        DataSourceFactory.build_from_dataconnection(Conn())


def test_sem_cliente_resolvido_recusa(monkeypatch):
    from core.data_sources import sky_world
    from core import tenant_context

    monkeypatch.setattr(tenant_context, "multi_tenant_enabled", lambda: True)
    with pytest.raises(sky_world.CredencialRecusada):
        sky_world._slug_do_pedido()


def test_atribuicao_e_atraso():
    from core.data_sources.sky_world import atribuicoes_das_linhas, fontes_das_tabelas

    agora = dt.datetime(2026, 10, 13, 12, tzinfo=dt.timezone.utc)
    linhas = [
        {
            "nome": "gasolineras",
            "atribuicao": "Fuente: MITECO",
            "dado_de": agora - dt.timedelta(minutes=20),
            "estado": "ok",
        },
        {
            "nome": "incidencias",
            "atribuicao": "Fuente: DGT",
            "dado_de": agora - dt.timedelta(minutes=20),
            "estado": "ok",
        },
        {"nome": "festivos", "atribuicao": "BOE", "dado_de": agora, "estado": "erro"},
    ]
    assert fontes_das_tabelas(
        ["mundo.gasolineras_rota", "gasolineras_precio", "mundo.festivos"]
    ) == [
        "gasolineras",
        "festivos",
    ]
    a = atribuicoes_das_linhas(
        linhas, ["gasolineras", "incidencias", "festivos"], agora
    )
    assert [x["atrasada"] for x in a] == [False, True, True]  # 20 min > 2×5 min; erro


def test_linha_de_citacao():
    from core.llm.fontes_publicas import acrescentar_citacao, linha_de_citacao

    f = [
        {
            "fonte": "gasolineras",
            "atribuicao": "Fuente: Ministerio para la Transición Ecológica (Geoportal). Não alterar a data",
            "dado_de": "2026-10-13T11:05:00+00:00",
            "atrasada": False,
        }
    ]
    assert linha_de_citacao(f, "pt") == (
        "Fonte: Ministerio para la Transición Ecológica (Geoportal) · actualizado às 12:05 (13/10/2026)"
    )
    assert linha_de_citacao(f, "es").startswith("Fuente: Ministerio")
    assert "13:05" in linha_de_citacao(f, "es")  # hora de Madrid
    f[0]["atrasada"] = True
    assert linha_de_citacao(f, "pt").endswith("(atrasado)")
    texto = acrescentar_citacao("Resposta.", f, "pt")
    assert acrescentar_citacao(texto, f, "pt") == texto  # uma só vez
    assert linha_de_citacao([], "pt") == ""


def test_especialista_regista_a_fonte_das_tabelas_usadas(amb):
    from core.llm.specialist import run_specialist

    llm = _LLMGravador(
        [
            "-- TITLE: x\nSELECT data FROM mundo.festivos WHERE regiao = 'ES-EX' LIMIT 100"
        ]
    )
    st = _estado("festivos de Extremadura")
    st.update(
        chosen_table="festivos",
        chosen_table_physical="mundo.festivos",
        chosen_tables=["festivos"],
        chosen_tables_physical=["mundo.festivos"],
    )
    r = run_specialist(st, amb.config, amb.fonte_mundo, llm)
    assert [f["fonte"] for f in r["fontes_publicas"]] == ["festivos"]
    # a fonte do cliente não é «do sistema»: nada a citar
    llm2 = _LLMGravador(["-- TITLE: x\nSELECT COUNT(*) AS n FROM ops.routes LIMIT 100"])
    st2 = _estado("rutas")
    st2.update(
        chosen_table="routes",
        chosen_table_physical="ops.routes",
        chosen_tables=["routes"],
        chosen_tables_physical=["ops.routes"],
    )
    r2 = run_specialist(st2, amb.config, amb.fonte_cliente, llm2)
    assert not r2.get("fontes_publicas")


# ═══════════════════════════════════════════════════════════════════════
# 4. Flag: o caminho novo só para os clientes escolhidos
# ═══════════════════════════════════════════════════════════════════════


def test_flag_desligada_por_omissao(monkeypatch):
    from core.llm.multi_fonte import multi_fonte_por_ligacao_ativo

    monkeypatch.delenv("MULTI_FONTE_POR_LIGACAO", raising=False)
    monkeypatch.delenv("MULTI_FONTE_POR_LIGACAO_TENANTS", raising=False)
    assert multi_fonte_por_ligacao_ativo("sandbox") is False
    assert multi_fonte_por_ligacao_ativo() is False


def test_flag_por_cliente_e_global(monkeypatch):
    from core.llm.multi_fonte import multi_fonte_por_ligacao_ativo

    monkeypatch.delenv("MULTI_FONTE_POR_LIGACAO", raising=False)
    monkeypatch.setenv("MULTI_FONTE_POR_LIGACAO_TENANTS", " sandbox, skyfirstlabs ")
    assert multi_fonte_por_ligacao_ativo("sandbox") is True
    assert multi_fonte_por_ligacao_ativo("skyfirstlabs") is True
    assert multi_fonte_por_ligacao_ativo("acme") is False
    monkeypatch.setenv("MULTI_FONTE_POR_LIGACAO", "false")
    assert multi_fonte_por_ligacao_ativo("acme") is False
    monkeypatch.setenv("MULTI_FONTE_POR_LIGACAO", "true")
    assert multi_fonte_por_ligacao_ativo("acme") is True


def test_flag_le_o_cliente_do_contexto(monkeypatch):
    from uuid import uuid4

    from core.llm.multi_fonte import multi_fonte_por_ligacao_ativo
    from core.tenant_context import (
        TenantContext,
        reset_current_tenant,
        set_current_tenant,
    )

    monkeypatch.delenv("MULTI_FONTE_POR_LIGACAO", raising=False)
    monkeypatch.setenv("MULTI_FONTE_POR_LIGACAO_TENANTS", "sandbox")
    tok = set_current_tenant(
        TenantContext(slug="sandbox", id=uuid4(), tier="pro", display_name="S")
    )
    try:
        assert multi_fonte_por_ligacao_ativo() is True
    finally:
        reset_current_tenant(tok)
    assert multi_fonte_por_ligacao_ativo() is False  # contexto por omissão


def test_sem_flag_o_merger_e_o_de_sempre():
    """Sem a marca, o merger de main (#289): fatias com o nome lógico da
    tabela, sem pistas nem descrições nem as regras do caminho novo."""
    from core.agents.generic_sql_agent import AgentConfig
    from core.llm.merger import run_merger

    llm = _LLMGravador(
        [
            "```sql\nSELECT SUM(t.litros) AS l FROM trips t "
            "JOIN festivos f ON t.dia = f.dia\n```"
        ]
    )
    st = {
        "question": "litros",
        "plan": "",
        "partial_results": [
            {
                "table": "trips",
                "data": [
                    {"dia": "2026-01-01", "litros": 1.5},
                    {"dia": "2026-01-02", "litros": 2.0},
                ],
                "metadata": {},
            },
            {"table": "festivos", "data": [{"dia": "2026-01-01"}], "metadata": {}},
        ],
    }
    r = run_merger(st, AgentConfig(id="t", name="t", tables=[]), llm)
    assert not r.get("error"), r.get("error")
    assert r["data"] == [{"l": 1.5}]
    sistema, user = llm.mensagens[0][0]["content"], llm.mensagens[0][1]["content"]
    assert "`trips`" in user and "dataset_1" not in user
    assert "Likely join keys" not in user and "Column meaning" not in user
    assert "Geographic level" not in sistema


def test_merger_por_ligacao_leva_as_regras_de_raciocinio():
    """P3/P6/P10 do portão (14/10): OU entre colunas, nível geográfico e
    propriedade de uma entidade de várias linhas — no prompt do merger novo."""
    from core.llm.merger import _generate_merger_prompt_por_ligacao

    pr = [
        {"table": "routes", "data": [{"id": 1, "origin": "Badajoz"}], "metadata": {}},
        {"table": "tempo", "data": [{"cidade": "Badajoz"}], "metadata": {}},
    ]
    msgs = _generate_merger_prompt_por_ligacao(
        "q", pr, "", failed_slices=[{"table": "festivos", "reason": "x"}]
    )
    sistema, user = msgs[0]["content"], msgs[1]["content"]
    assert "OR across columns" in sistema
    assert "Geographic level" in sistema
    assert "bool_and" in sistema
    assert "NOT AVAILABLE" in user and "`festivos`" in user


def test_merger_por_ligacao_sem_nada_a_juntar_nao_chama_o_modelo():
    from core.agents.generic_sql_agent import AgentConfig
    from core.llm.merger import run_merger

    cfg = AgentConfig(id="t", name="t", tables=[])
    llm = _LLMGravador([])
    uma = run_merger(
        {
            "question": "q",
            "multi_fonte_por_ligacao": True,
            "partial_results": [
                {
                    "table": "trips, routes",
                    "data": [{"n": 3}],
                    "sql": "SELECT 3",
                    "metadata": {},
                }
            ],
            "failed_slices": [{"table": "festivos", "reason": "0 rows"}],
        },
        cfg,
        llm,
    )
    assert uma["data"] == [{"n": 3}] and uma["sql"] == "SELECT 3"
    nada = run_merger(
        {
            "question": "q",
            "multi_fonte_por_ligacao": True,
            "partial_results": [],
            "failed_slices": [{"table": "festivos", "reason": "0 rows"}],
        },
        cfg,
        llm,
    )
    assert nada["merge_failure"]["kind"] == "no_slices"
    assert llm.mensagens == []


def test_contrato_tem_as_regras_de_nivel_entidade_e_chave(amb):
    from core.llm.multi_fonte import agrupar_por_ligacao, contrato_da_fatia

    cli, mun = agrupar_por_ligacao(
        ["routes", "tempo_cidades"], amb.config, amb.dispatch_map
    )
    c = contrato_da_fatia(mun, [cli])
    assert "Geographic level" in c and "region IS NULL" in c
    assert "bool_and()" in c
    assert "Never stand in for an entity" in c


def test_fatia_sem_dados_vem_em_failed_slices(amb):
    from core.llm.multi_fonte import executar_fatias

    def especialista(st, cfg, src, llm):
        if "festivos" in st["chosen_tables"]:
            return {"data": [], "sql": "SELECT 1 WHERE FALSE"}
        return {"data": [{"dia": "2026-01-01", "n": 1}], "sql": "SELECT ..."}

    parciais, fontes, falhadas = executar_fatias(
        _estado("q"),
        amb.config,
        ["trips", "festivos"],
        amb.dispatch_map,
        amb.fonte_cliente,
        None,
        run_specialist=especialista,
    )
    assert [p["table"] for p in parciais] == ["trips"]
    assert falhadas == [
        {
            "table": "festivos",
            "connection_id": falhadas[0]["connection_id"],
            "reason": "query ran and returned 0 rows",
        }
    ]


def test_impossible_depois_do_titulo_e_reconhecido(amb):
    """Haiku como especialista: «-- TITLE: …» e IMPOSSIBLE na linha seguinte.
    Antes seguia para a extracção de SQL e morria no validador."""
    from core.llm.specialist import normalizar_impossible, run_specialist

    assert (
        normalizar_impossible("-- TITLE: x\nIMPOSSIBLE: falta") == "IMPOSSIBLE: falta"
    )
    assert normalizar_impossible("Lo siento.\n**IMPOSSIBLE**: no") == "IMPOSSIBLE: no"
    # com SQL, quem decide é o fluxo normal
    com_sql = "-- TITLE: x\nSELECT 1 -- IMPOSSIBLE de outra forma"
    assert normalizar_impossible(com_sql) == com_sql

    llm = _LLMGravador(
        [
            "-- TITLE: x\nIMPOSSIBLE: no hay datos de peajes",
            "-- TITLE: y\nIMPOSSIBLE: nada",
        ]
    )
    st = _estado("¿peajes?")
    st.update(
        chosen_table="festivos",
        chosen_table_physical="mundo.festivos",
        chosen_tables=["festivos"],
        chosen_tables_physical=["mundo.festivos"],
    )
    r = run_specialist(st, amb.config, amb.fonte_mundo, llm)
    assert r.get("impossible_reason"), r
    assert "nada" in r["impossible_reason"] or "peajes" in r["impossible_reason"]


def test_modelo_do_merger(monkeypatch):
    """BEDROCK_MODEL_MERGER / LLM_MODEL_MERGER; por omissão o especialista no
    caminho novo e o orquestrador no de sempre."""
    from config.settings import settings
    from core.agents.generic_sql_agent import escolher_llm_do_merger
    from core.llm import factory

    orq, esp, proprio = object(), object(), object()
    monkeypatch.setattr(factory, "modelo_do_merger_definido", lambda: False)
    assert escolher_llm_do_merger(True, orq, esp) is esp
    assert escolher_llm_do_merger(False, orq, esp) is orq
    assert escolher_llm_do_merger(False, orq, esp, proprio) is proprio
    monkeypatch.setattr(factory, "modelo_do_merger_definido", lambda: True)
    monkeypatch.setattr(factory, "create_llm_merger", lambda: proprio)
    assert escolher_llm_do_merger(False, orq, esp) is proprio
    monkeypatch.undo()

    monkeypatch.setattr(settings, "use_bedrock", True)
    monkeypatch.setattr(settings, "llm_model_merger_bedrock", None)
    assert factory.modelo_do_merger_definido() is False
    monkeypatch.setattr(
        settings, "llm_model_merger_bedrock", "eu.anthropic.claude-sonnet-4-6"
    )
    assert factory.modelo_do_merger_definido() is True


def test_sem_flag_a_fatia_mantem_limit_100(amb):
    """Sem contrato (caminho antigo), uma fatia continua a pedir LIMIT 100."""
    from core.llm.specialist import run_specialist

    llm = _LLMGravador(["-- TITLE: x\nSELECT data FROM mundo.festivos LIMIT 100"])
    st = _estado("¿viajes en festivo?")
    st.update(
        chosen_table="festivos",
        chosen_table_physical="mundo.festivos",
        chosen_tables=["festivos"],
        chosen_tables_physical=["mundo.festivos"],
        multi_source_subquery=True,
    )
    run_specialist(st, amb.config, amb.fonte_mundo, llm)
    assert "LIMIT 100" in llm.mensagens[0][0]["content"]
    assert "LIMIT 5000" not in llm.mensagens[0][0]["content"]


def test_grafo_tem_os_dois_caminhos_atras_da_flag():
    import inspect

    from core.agents import generic_sql_agent

    fonte = inspect.getsource(generic_sql_agent.build_generic_sql_graph)
    assert "_por_ligacao = multi_fonte_por_ligacao_ativo()" in fonte
    assert fonte.count("if _por_ligacao:") == 2
    # o caminho de sempre (uma fatia por tabela, #289) continua lá, nos dois
    # sítios, e o novo também
    assert fonte.count("executar_fatias_por_tabela(") == 2
    assert len(re.findall(r"\bexecutar_fatias\(", fonte)) == 2
