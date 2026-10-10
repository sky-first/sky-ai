# -*- coding: utf-8 -*-
"""Ligar APIs públicas (e de clientes) ao motor — defeitos D1–D4 do Anexo C.

O Anexo C do ``ESTUDO_DADOS_PUBLICOS_2026-10`` (sky-backend/docs) fez
chamadas reais e encontrou:

* D1 — a chave escrita na web (``auth_type``/``auth_header``/``auth_value``)
  não era lida por ninguém; não havia chave na query string.
* D2 — com descrição preenchida, o caminho do endpoint nunca chegava ao LLM.
* D3 — XML (DGT DATEX2) e CSV (BCE SDMX) rebentavam; o MITECO chegava como
  1 linha com 277 postos aninhados em ``ListaEESSPrecio``.
* D4 — o formatter só via 15 linhas, sem aviso nem agregação.

As amostras em ``tests/fixtures/api_publicas/`` são recortes das respostas
reais de 10/10/2026. Nenhum teste aqui sai para a rede.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from core.data_sources import api_source as api_source_mod
from core.data_sources.api_payload import (
    parse_records,
    records_path_for,
    redact,
    resolve_auth,
)
from core.data_sources.api_source import APISource
from core.data_sources.base import DataSourceConfig

FIX = Path(__file__).parent / "fixtures" / "api_publicas"


def _fonte(extra):
    return APISource(
        DataSourceConfig(id="t", type="api", default_schema=None, extra=extra),
        label="api:t",
    )


def _com_resposta(monkeypatch, handler):
    """Troca o httpx.Client do APISource por um com transporte falso."""
    real_client = httpx.Client
    pedidos = []

    def _handler(request):
        pedidos.append(request)
        return handler(request)

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(_handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(api_source_mod.httpx, "Client", fake_client)
    return pedidos


# ──────────────────────────────────────────────────────────────────────
# D1 — autenticação
# ──────────────────────────────────────────────────────────────────────


class TestD1AChaveDaWebChegaAoPedido:
    def test_bearer_da_web(self):
        h, q, basic, seg = resolve_auth(
            {"auth_type": "bearer_token", "auth_value": "tok-123456"}
        )
        assert h["Authorization"] == "Bearer tok-123456"
        assert q == {} and basic is None
        assert "tok-123456" in seg

    def test_bearer_ja_com_prefixo_nao_duplica(self):
        h, *_ = resolve_auth(
            {"auth_type": "bearer_token", "auth_value": "Bearer tok-123456"}
        )
        assert h["Authorization"] == "Bearer tok-123456"

    def test_api_key_em_cabecalho(self):
        h, q, _, _ = resolve_auth(
            {
                "auth_type": "api_key",
                "auth_header": "X-Api-Key",
                "auth_value": "k-abcdef",
            }
        )
        assert h["X-Api-Key"] == "k-abcdef" and q == {}

    def test_api_key_sem_nome_usa_x_api_key(self):
        h, _, _, _ = resolve_auth({"auth_type": "api_key", "auth_value": "k-abcdef"})
        assert h["X-API-Key"] == "k-abcdef"

    @pytest.mark.parametrize(
        "cfg",
        [
            {"auth_type": "api_key", "auth_header": "?key", "auth_value": "k-abcdef"},
            {
                "auth_type": "api_key",
                "auth_header": "query:key",
                "auth_value": "k-abcdef",
            },
            {
                "auth_type": "api_key",
                "auth_header": "key",
                "auth_in": "query",
                "auth_value": "k-abcdef",
            },
            {
                "auth": {
                    "type": "apikey",
                    "token": "k-abcdef",
                    "in": "query",
                    "param_name": "key",
                }
            },
        ],
    )
    def test_api_key_na_query_string(self, cfg):
        """TomTom (``?key=``), Open-Meteo pago (``&apikey=``)."""
        h, q, _, _ = resolve_auth(cfg)
        assert q == {"key": "k-abcdef"}
        assert "key" not in h and "?key" not in h

    def test_basic_utilizador_e_senha(self):
        _, _, basic, seg = resolve_auth(
            {"auth_type": "basic_auth", "auth_value": "ana:segredo1"}
        )
        assert basic == ("ana", "segredo1")
        assert "segredo1" in seg

    def test_basic_com_utilizador_no_campo_do_cabecalho(self):
        _, _, basic, _ = resolve_auth(
            {"auth_type": "basic_auth", "auth_header": "ana", "auth_value": "segredo1"}
        )
        assert basic == ("ana", "segredo1")

    def test_contrato_do_backend_e_legado_continuam(self):
        h, *_ = resolve_auth({"auth": {"type": "bearer", "token": "t-999999"}})
        assert h["Authorization"] == "Bearer t-999999"
        h, *_ = resolve_auth({"api_key": "legado-1"})
        assert h["Authorization"] == "Bearer legado-1"

    def test_none_nao_poe_nada(self):
        h, q, basic, _ = resolve_auth({"auth_type": "none", "auth_value": "ignorado"})
        assert h == {} and q == {} and basic is None

    def test_a_chave_vai_no_pedido_e_ganha_ao_llm(self, monkeypatch):
        pedidos = _com_resposta(
            monkeypatch,
            lambda r: httpx.Response(200, json=[{"a": 1}]),
        )
        fonte = _fonte(
            {
                "base_url": "https://api.exemplo.test/v1",
                "auth_type": "api_key",
                "auth_header": "?key",
                "auth_value": "chave-verdadeira",
            }
        )
        fonte.run_query(
            json.dumps(
                {"endpoint": "/route", "params": {"key": "inventada-pelo-llm", "x": 1}}
            )
        )
        assert pedidos[0].url.params["key"] == "chave-verdadeira"
        assert pedidos[0].url.params["x"] == "1"

    def test_401_nao_deixa_a_chave_na_mensagem(self, monkeypatch):
        """O httpx põe o URL (com ``?key=``) na mensagem de erro."""
        _com_resposta(monkeypatch, lambda r: httpx.Response(401, json={"error": "no"}))
        fonte = _fonte(
            {
                "base_url": "https://api.exemplo.test/v1",
                "auth_type": "api_key",
                "auth_header": "?key",
                "auth_value": "chave-verdadeira",
            }
        )
        with pytest.raises(Exception) as exc:
            fonte.run_query(json.dumps({"endpoint": "/route"}))
        assert "chave-verdadeira" not in str(exc.value)
        assert "401" in str(exc.value)

    def test_redact(self):
        assert redact("https://x/?key=abc123", ["abc123"]) == "https://x/?key=***"

    def test_aceita_path_alem_de_endpoint(self, monkeypatch):
        """O especialista aceita ``path``; o APISource só lia ``endpoint``."""
        pedidos = _com_resposta(monkeypatch, lambda r: httpx.Response(200, json=[]))
        _fonte({"base_url": "https://api.exemplo.test/v1"}).run_query(
            json.dumps({"path": "/holidays"})
        )
        assert pedidos[0].url.path == "/v1/holidays"


# ──────────────────────────────────────────────────────────────────────
# D3 — respostas que não são uma lista JSON limpa
# ──────────────────────────────────────────────────────────────────────


class TestD3RespostasViramLinhas:
    def test_miteco_desembrulha_lista_eess_precio(self):
        linhas = parse_records(
            (FIX / "miteco_badajoz_gasoleo_a.json").read_bytes(),
            "application/json; charset=utf-8",
        )
        assert len(linhas) == 4
        assert {"Municipio", "PrecioProducto", "Rótulo"} <= set(linhas[0])
        assert "ListaEESSPrecio" not in linhas[0]

    def test_datex2_cada_situacao_e_uma_linha(self):
        linhas = parse_records(
            (FIX / "dgt_datex2_v37.xml").read_bytes(), "text/xml; charset=utf-8"
        )
        assert len(linhas) == 2
        primeira = linhas[0]
        assert primeira["roadName"] == "N-400"
        assert primeira["causeType"] == "roadMaintenance"
        # Folhas homónimas ficam distintas pelo antepassado que as separa.
        assert primeira["to.latitude"] == "39.994446"
        assert primeira["from.latitude"] == "39.993732"
        assert (
            primeira["situationRecord.@type"] == "sit:RoadOrCarriagewayOrLaneManagement"
        )

    def test_datex2_records_path_desce_aos_registos(self):
        linhas = parse_records(
            (FIX / "dgt_datex2_v37.xml").read_bytes(),
            "text/xml",
            records_path="situation.situationRecord",
        )
        assert len(linhas) == 3  # 1 + 2 registos nas duas situações

    def test_bce_csv(self):
        linhas = parse_records((FIX / "ecb_exr_usd.csv").read_bytes(), "text/csv")
        assert len(linhas) == 3
        assert linhas[-1]["TIME_PERIOD"] == "2026-10-09"
        assert linhas[-1]["OBS_VALUE"] == "1.1206"
        # A vírgula dentro de aspas não parte a coluna.
        assert linhas[0]["TITLE_COMPL"].startswith(
            "ECB reference exchange rate, US dollar"
        )

    def test_csv_detectado_sem_content_type(self):
        linhas = parse_records((FIX / "ecb_exr_usd.csv").read_bytes(), "text/plain")
        assert len(linhas) == 3

    def test_sdmx_csv_content_type(self):
        linhas = parse_records(
            (FIX / "ecb_exr_usd.csv").read_bytes(),
            "application/vnd.sdmx.data+csv;version=1.0.0",
        )
        assert len(linhas) == 3

    def test_csv_com_ponto_e_virgula(self):
        linhas = parse_records("a;b\n1,5;x\n2,5;y\n", "")
        assert linhas == [{"a": "1,5", "b": "x"}, {"a": "2,5", "b": "y"}]

    def test_xml_com_doctype_e_recusado(self):
        bomba = (
            b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><r><i>&a;</i></r>'
        )
        with pytest.raises(ValueError):
            parse_records(bomba, "application/xml")

    def test_achatar_um_nivel(self):
        """Frankfurter: ``rates`` vira colunas ``rates.USD``."""
        linhas = parse_records(
            json.dumps(
                {
                    "base": "EUR",
                    "date": "2026-10-09",
                    "rates": {"USD": 1.12, "GBP": 0.87},
                }
            ),
            "application/json",
        )
        assert linhas == [
            {"base": "EUR", "date": "2026-10-09", "rates.USD": 1.12, "rates.GBP": 0.87}
        ]

    def test_varias_listas_sem_nome_conhecido_ficam_inteiras(self):
        """OSRM devolve ``routes`` e ``waypoints``: escolher às cegas perdia a rota."""
        payload = {
            "code": "Ok",
            "routes": [{"distance": 1}],
            "waypoints": [{"a": 1}, {"a": 2}],
        }
        linhas = parse_records(json.dumps(payload), "application/json")
        assert len(linhas) == 1 and linhas[0]["routes"] == [{"distance": 1}]

    def test_records_path_json(self):
        payload = {
            "code": "Ok",
            "routes": [{"distance": 1}],
            "waypoints": [{"a": 1}, {"a": 2}],
        }
        assert parse_records(json.dumps(payload), "application/json", "routes") == [
            {"distance": 1}
        ]
        with pytest.raises(ValueError):
            parse_records(json.dumps(payload), "application/json", "nao.existe")

    def test_records_path_por_endpoint_com_marcadores(self):
        cfg = {
            "records_path": "data",
            "endpoints": [
                {
                    "path": "/FiltroProvinciaProducto/{prov}/{prod}",
                    "records_path": "ListaEESSPrecio",
                }
            ],
        }
        assert (
            records_path_for(cfg, "/FiltroProvinciaProducto/06/4") == "ListaEESSPrecio"
        )
        assert records_path_for(cfg, "/outra") == "data"
        assert records_path_for({}, "/x") is None

    def test_texto_continua_texto(self):
        assert parse_records("olá", "text/plain") == [{"text": "olá"}]

    def test_apisource_le_xml_em_vez_de_rebentar(self, monkeypatch):
        corpo = (FIX / "dgt_datex2_v37.xml").read_bytes()
        _com_resposta(
            monkeypatch,
            lambda r: httpx.Response(
                200, content=corpo, headers={"content-type": "text/xml"}
            ),
        )
        linhas = _fonte({"base_url": "https://nap.exemplo.test"}).run_query(
            json.dumps({"endpoint": "/datex2_v37.xml"})
        )
        assert len(linhas) == 2 and linhas[0]["roadName"] == "N-400"

    def test_apisource_usa_records_path_do_endpoint(self, monkeypatch):
        corpo = (FIX / "dgt_datex2_v37.xml").read_bytes()
        _com_resposta(
            monkeypatch,
            lambda r: httpx.Response(
                200, content=corpo, headers={"content-type": "text/xml"}
            ),
        )
        fonte = _fonte(
            {
                "base_url": "https://nap.exemplo.test",
                "endpoints": [
                    {
                        "path": "/datex2_v37.xml",
                        "records_path": "situation.situationRecord",
                    }
                ],
            }
        )
        assert len(fonte.run_query(json.dumps({"endpoint": "/datex2_v37.xml"}))) == 3


# ──────────────────────────────────────────────────────────────────────
# D2 — o caminho chega à descrição
# ──────────────────────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, value=None):
        self._v = value

    def scalar_one_or_none(self):
        return self._v


class _FakeDB:
    def __init__(self, tables):
        self._tables = tables
        self.added = []

    async def execute(self, stmt, params=None):
        return _FakeResult(self._tables)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def flush(self):
        pass


class TestD2OCaminhoChegaAoModelo:
    def _ingere(self, metadata):
        from core.ingestion.db_metadata import ingest_from_connection_metadata_cache

        db = _FakeDB(
            [
                {
                    "name": "previsao",
                    "columns": [],
                    "kind": "rest_endpoint",
                    "metadata": metadata,
                }
            ]
        )
        conn = SimpleNamespace(id="c1")
        asyncio.run(ingest_from_connection_metadata_cache(db, conn))
        return [o for o in db.added if getattr(o, "column_name", None) == "*"]

    def test_descricao_preenchida_leva_o_caminho(self):
        (linha,) = self._ingere(
            {
                "path": "/forecast",
                "method": "GET",
                "description": "Previsão por coordenada",
            }
        )
        assert "Previsão por coordenada" in linha.description
        assert "GET /forecast" in linha.description

    def test_sem_descricao_fica_metodo_e_caminho(self):
        (linha,) = self._ingere(
            {"path": "/forecast", "method": "GET", "description": ""}
        )
        assert linha.description == "GET /forecast"

    def test_descricao_que_ja_tem_o_caminho_nao_repete(self):
        desc = "GET /forecast?latitude=&longitude= — previsão"
        (linha,) = self._ingere(
            {"path": "/forecast", "method": "GET", "description": desc}
        )
        assert linha.description == desc


# ──────────────────────────────────────────────────────────────────────
# D4 — mais linhas do que as que cabem no prompt
# ──────────────────────────────────────────────────────────────────────


class TestD4OFormatterSabeQueEAmostra:
    def _postos(self):
        return json.loads(
            (FIX / "miteco_badajoz_gasoleo_a.json").read_text(encoding="utf-8")
        )["ListaEESSPrecio"]

    def test_ate_15_linhas_nada_muda(self):
        from core.llm.formatter import _compute_basic_stats

        linhas = [{"v": i} for i in range(5)]
        assert _compute_basic_stats(
            linhas[:15], all_rows=linhas
        ) == _compute_basic_stats(linhas[:15])
        assert "SAMPLE" not in _compute_basic_stats(linhas[:15], all_rows=linhas)

    def test_32_feriados_contam_32_e_nao_15(self):
        from core.llm.formatter import _compute_basic_stats

        linhas = [
            {"date": f"2026-{1 + i // 3:02d}-{1 + i:02d}", "dia": i + 1}
            for i in range(32)
        ]
        txt = _compute_basic_stats(linhas[:15], all_rows=linhas)
        assert "32 rows" in txt and "first 15" in txt
        assert "dia: count=32, min=1, max=32" in txt

    def test_minimo_sobre_todas_as_linhas_com_virgula_decimal(self):
        """O posto mais barato está FORA da amostra: tem de chegar na mesma."""
        from core.llm.formatter import _compute_basic_stats

        postos = self._postos()
        amostra = postos[:2]  # Acedera 1,749 e Aceuchal 1,969
        txt = _compute_basic_stats(amostra, all_rows=postos)
        assert "PrecioProducto: count=4, min=1.694, max=2.169" in txt
        assert "row with min PrecioProducto" in txt and "Zarza (La)" in txt
        # Identificadores e códigos postais não são médias.
        assert "IDEESS:" not in txt and "C.P.:" not in txt
        # Coordenadas também não: no real (277 postos) tiravam o lugar ao preço.
        assert "Latitud:" not in txt and "Longitud (WGS84):" not in txt
        assert txt.splitlines()[1].startswith("- PrecioProducto:")

    def test_os_tres_caminhos_de_resposta_passam_o_resultado_inteiro(self):
        """Web (/ai/query), stream (app) e agentes: os três chamam as stats
        com ``all_rows`` — corrigir só um deixava os outros com 15 linhas."""
        raiz = Path(__file__).parent.parent
        fontes = [
            raiz / "core" / "llm" / "formatter.py",
            raiz / "api" / "routes" / "agents.py",
            raiz / "api" / "routes" / "connection_query.py",
        ]
        total = 0
        for f in fontes:
            src = f.read_text(encoding="utf-8")
            for chamada in src.split("stats_text = _compute_basic_stats(")[1:]:
                total += 1
                assert "all_rows=" in chamada[:200].split("stats_text")[0], f.name
        assert total == 4
