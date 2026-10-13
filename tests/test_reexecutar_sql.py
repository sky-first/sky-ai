"""Voltar a correr o SQL guardado — com as tabelas de quem abre.

Decisão do Lucas (13/10/2026): a plataforma nunca guarda as linhas do
cliente. O «ver a fonte», os widgets e os achados voltam a correr o SQL
quando se abrem. Esta rota é a porta — e tem de ter as MESMAS regras da
pergunta original, senão é uma segunda porta para os dados.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from api.routes import reexecutar_sql as rr

LIG = "11111111-1111-1111-1111-111111111111"
OUTRA = "22222222-2222-2222-2222-222222222222"

CATALOGO = {
    LIG: [
        {"schema": "vendas", "name": "encomendas"},
        {"schema": "rh", "name": "salarios"},
    ],
    OUTRA: [{"schema": "public", "name": "clientes"}],
}


class _FonteFalsa:
    class dialect:  # noqa: N801 — imita o Enum
        value = "postgres"

    def __init__(self, linhas: List[Dict[str, Any]]):
        self.linhas = linhas
        self.sql_recebido: List[str] = []

    def run_query(self, sql: str):
        self.sql_recebido.append(sql)
        return list(self.linhas)


class _Resposta:
    """O que o teste lê: o estado HTTP e o corpo, como numa chamada real."""

    def __init__(self, status_code: int, corpo: Any):
        self.status_code = status_code
        self._corpo = corpo
        self.text = str(corpo)

    def json(self):
        return self._corpo


class _Cliente:
    def __init__(self, fonte):
        self.fonte = fonte


class _SessaoQueNaoEscreve:
    def add(self, *a, **k):  # pragma: no cover — não pode acontecer
        raise AssertionError("a reexecução nunca grava nada")

    async def commit(self):  # pragma: no cover
        raise AssertionError("a reexecução nunca grava nada")


@pytest.fixture
def cliente(monkeypatch):
    fonte = _FonteFalsa([{"regiao": "Norte", "total": i} for i in range(5)])

    async def _catalogo(db, ids):
        cat = {c: CATALOGO[c] for c in ids if c in CATALOGO}
        lig = {c: (c, "x", "postgres", {}) for c in cat}
        return cat, {c: None for c in cat}, lig

    monkeypatch.setattr(rr, "_ler_catalogo", _catalogo)
    monkeypatch.setattr(rr, "_fonte_de_dados", lambda linha: fonte)
    return _Cliente(fonte)


def _pedir(cliente, sql, autorizadas, **extra):
    """Chama a rota como o FastAPI chamaria (validação do corpo incluída)."""
    from fastapi import HTTPException
    from pydantic import ValidationError

    corpo = {"sql": sql, "user_id": "u1", "tabelas_autorizadas": autorizadas, **extra}
    try:
        pedido = rr.PedidoDeReexecucao(**corpo)
        r = asyncio.run(rr.reexecutar(LIG, pedido, db=_SessaoQueNaoEscreve()))
        return _Resposta(200, r.model_dump())
    except HTTPException as e:
        return _Resposta(e.status_code, {"detail": e.detail})
    except ValidationError as e:
        return _Resposta(422, {"detail": str(e)})


def test_quem_pode_ver_a_tabela_recebe_as_linhas_de_agora(cliente):
    r = _pedir(
        cliente,
        "SELECT regiao, SUM(total) AS total FROM vendas.encomendas GROUP BY regiao",
        {LIG: ["encomendas"]},
    )
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["columns"] == ["regiao", "total"]
    assert corpo["row_count"] == 5
    assert corpo["truncated"] is False
    assert corpo["executed_at"]


def test_outra_equipa_sem_a_tabela_leva_403(cliente):
    """A tabela existe, mas não está na lista de quem abre: 403, e a fonte
    nem é tocada."""
    r = _pedir(cliente, "SELECT valor FROM rh.salarios LIMIT 10", {LIG: ["encomendas"]})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "sem_acesso"
    assert cliente.fonte.sql_recebido == []


def test_sem_lista_de_tabelas_nada_passa(cliente):
    """Fail-closed: sem autorizações não se decide «tudo», decide-se «nada»."""
    r = _pedir(cliente, "SELECT regiao FROM vendas.encomendas LIMIT 10", {})
    assert r.status_code == 403
    assert cliente.fonte.sql_recebido == []


def test_juncao_em_memoria_de_varias_fontes_nao_se_reexecuta(cliente):
    """O SQL do merger (DuckDB) lê `dataset_1`, que não existe em fonte
    nenhuma: 422, e o cliente mostra a resposta sem tabela."""
    r = _pedir(
        cliente,
        "SELECT a.x FROM dataset_1 a JOIN dataset_2 b ON a.k = b.k",
        {LIG: ["encomendas"]},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "nao_reexecutavel"


def test_sql_que_le_duas_ligacoes_nao_corre_numa_so(cliente):
    r = _pedir(
        cliente,
        "SELECT e.id FROM vendas.encomendas e JOIN public.clientes c ON c.id = e.id",
        {LIG: ["encomendas"], OUTRA: ["clientes"]},
        connection_ids=[OUTRA],
    )
    assert r.status_code == 422
    assert cliente.fonte.sql_recebido == []


@pytest.mark.parametrize(
    "sql",
    ["DELETE FROM vendas.encomendas", "SELECT 1; DROP TABLE x", "UPDATE x SET a=1"],
)
def test_so_leitura(cliente, sql):
    r = _pedir(cliente, sql, {LIG: ["encomendas"]})
    assert r.status_code == 422
    assert cliente.fonte.sql_recebido == []


def test_o_tecto_de_linhas_e_aplicado_e_dito(cliente):
    r = _pedir(
        cliente,
        "SELECT regiao, total FROM vendas.encomendas LIMIT 50",
        {LIG: ["encomendas"]},
        max_rows=3,
    )
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["row_count"] == 3
    assert corpo["truncated"] is True
    # Pede n+1 à fonte, para saber se cortou sem contar a tabela toda.
    assert cliente.fonte.sql_recebido[-1].endswith("LIMIT 4")


def test_tecto_no_dialecto_certo():
    assert rr.com_tecto("SELECT a FROM t;", 5, "postgres") == (
        "SELECT * FROM (SELECT a FROM t) AS sky_fonte LIMIT 5"
    )
    assert rr.com_tecto("SELECT a FROM t", 5, "sqlserver").startswith("SELECT TOP 5 ")
    assert "ROWNUM <= 5" in rr.com_tecto("SELECT a FROM t", 5, "oracle")


def test_catalogo_permitido_e_por_ligacao():
    todas, permitidas = rr.catalogo_permitido(
        CATALOGO, {LIG: None, OUTRA: None}, {LIG: ["encomendas"]}
    )
    assert permitidas[LIG] == {"vendas.encomendas"}
    assert permitidas[OUTRA] == set()  # sem entrada na lista = nada
    assert todas[LIG] == {"vendas.encomendas", "rh.salarios"}


def test_celulas_compridas_sao_cortadas():
    colunas, linhas, cortou = rr.compactar([{"t": "x" * 5000}], 10)
    assert colunas == ["t"]
    assert len(linhas[0][0]) == rr.TECTO_CELULA + 1
    assert cortou is False


# ── A regra de segurança chega como JSON (13/10/2026) ───────────────────
#
# O backend manda o `security_config` no corpo, como dict. A rota passava-o
# assim ao `inject_row_filters_in_sql`, que lê `.tables`: TODAS as
# reexecuções com regra davam 500 em produção e a fonte aparecia sem dados.


def test_com_regra_de_seguranca_em_json_as_linhas_vem_filtradas(cliente):
    r = _pedir(
        cliente,
        "SELECT regiao, total FROM vendas.encomendas LIMIT 50",
        {LIG: ["encomendas"]},
        security_config={
            "tables": {"vendas.encomendas": {"row_filter": "regiao = 'Norte'"}},
            "global_blocked_columns": [],
        },
    )
    assert r.status_code == 200, r.text
    assert "regiao = 'Norte'" in cliente.fonte.sql_recebido[-1]


def test_regra_que_bloqueia_uma_coluna_leva_403(cliente):
    r = _pedir(
        cliente,
        "SELECT regiao, total FROM vendas.encomendas LIMIT 50",
        {LIG: ["encomendas"]},
        security_config={"global_blocked_columns": ["total"]},
    )
    assert r.status_code == 403, r.text
    assert cliente.fonte.sql_recebido == []
