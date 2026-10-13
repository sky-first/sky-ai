"""A cache semântica não guarda linhas do cliente.

Princípio (13/10/2026): nunca guardamos linhas do cliente. A
``semantic_cache.response_json`` guardava ``data_sample`` = 15 linhas, sem
prazo. Estes testes fixam o comportamento novo, pela rota real
(``query_connection``), com a base e a fonte falsas:

* o que se GRAVA não tem linhas (só resposta, SQL, metadados e a marca);
* num acerto, as linhas vêm da fonte do cliente (SQL guardado corrido de novo)
  e nunca do que estiver na cache — nem de linhas antigas;
* se não der para as ir buscar, o acerto é descartado e a pergunta segue;
* há prazo: a procura filtra por ``created_at`` e a escrita apaga o vencido.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.schemas import QueryRequest, QueryResponse, QueryResultMeta
from core.privacidade import cache_semantico

LINHAS_DO_CLIENTE = [{"cliente": "Joana Silva", "total": 1200}]
LINHAS_NOVAS = [{"cliente": "Joana Silva", "total": 1300}]


class _Resultado:
    def __init__(self, primeira=None):
        self._primeira = primeira

    def first(self):
        return self._primeira


class _BaseFalsa:
    """Sessão async que responde à procura na cache e regista o resto."""

    def __init__(self, acerto=None):
        self.acerto = acerto  # (response_json, similaridade) ou None
        self.execucoes: list[tuple[str, dict]] = []
        self.adicionados: list = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.execucoes.append((sql, params or {}))
        if "FROM semantic_cache" in sql and "SELECT" in sql:
            return _Resultado(self.acerto)
        if "FROM data_connections" in sql:
            return _Resultado(("conn-1", "Fonte", "postgres", {}))
        return _Resultado(None)

    def add(self, obj):
        self.adicionados.append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


class _FonteFalsa:
    def __init__(self, linhas=None, erro=None):
        self.linhas = linhas
        self.erro = erro
        self.sql_corrido: list[str] = []

    def run_query(self, sql):
        self.sql_corrido.append(sql)
        if self.erro:
            raise self.erro
        return list(self.linhas or [])


class _Embeddings:
    async def embed_async(self, textos):
        return [[0.0, 0.1, 0.2] for _ in textos]


def _pedido():
    return QueryRequest(
        question="Quanto faturou cada cliente este ano?",
        user_id="u-1",
        space_id="s-1",
        locale="pt",
    )


def _resposta(linhas):
    return QueryResponse(
        answer="A Joana Silva faturou 1200.",
        data_sample=list(linhas),
        meta=QueryResultMeta(
            sql="SELECT cliente, total FROM vendas", num_rows=len(linhas)
        ),
    )


def _correr(db, *, interior=None, fonte=None):
    from api.routes import connection_query as cq

    chamadas_ao_interior = []

    async def _interior(connection_id, body, db_):
        chamadas_ao_interior.append(body.question)
        return interior or _resposta(LINHAS_DO_CLIENTE)

    fontes = {"conn-1": fonte} if fonte is not None else {}
    with patch(
        "core.llm.factory.create_embedding_provider", return_value=_Embeddings()
    ), patch.object(cq, "_query_connection_inner", _interior), patch.object(
        cq, "_dispatch_map_from_conn_rows", lambda rows: fontes
    ):
        resposta = asyncio.run(cq.query_connection("conn-1", _pedido(), db))
    return resposta, chamadas_ao_interior


# ── Escrita ───────────────────────────────────────────────────────────────


def test_a_escrita_nao_guarda_as_linhas():
    db = _BaseFalsa(acerto=None)
    resposta, interior = _correr(db)

    assert interior, "sem acerto, a pergunta tem de seguir o pipeline"
    # Quem perguntou recebe as linhas (vieram agora da fonte do cliente)…
    assert resposta.data_sample == LINHAS_DO_CLIENTE
    # …mas o que fica na nossa base não as tem.
    assert len(db.adicionados) == 1
    gravado = db.adicionados[0].response_json
    assert gravado["data_sample"] == []
    assert "Joana" not in str(gravado["data_sample"])
    assert gravado[cache_semantico.LINHAS_OMITIDAS] is True
    # O que é gerado pela plataforma fica: resposta e SQL.
    assert gravado["answer"] == "A Joana Silva faturou 1200."
    assert gravado["meta"]["sql"] == "SELECT cliente, total FROM vendas"


def test_a_escrita_apaga_o_que_passou_do_prazo():
    db = _BaseFalsa(acerto=None)
    _correr(db)
    purgas = [
        (sql, p)
        for sql, p in db.execucoes
        if sql.startswith("DELETE FROM semantic_cache")
    ]
    assert purgas, "a escrita tem de apagar as linhas vencidas da mesma ligação"
    sql, params = purgas[0]
    assert "created_at < :cache_cutoff" in sql
    assert "created_at IS NULL" in sql
    assert params["conn_id"] == "conn-1"
    esperado = datetime.utcnow() - timedelta(days=cache_semantico.DIAS_DE_VIDA)
    assert abs((params["cache_cutoff"] - esperado).total_seconds()) < 60


def test_resposta_com_linhas_bloqueadas_pela_pii_nunca_as_vai_buscar():
    """O PII bloqueou as linhas (data_sample=[]): a marca fica a False, e um
    acerto futuro não as repõe — senão a cache furava o bloqueio."""
    payload = cache_semantico.payload_para_cache(_resposta([]))
    assert payload[cache_semantico.LINHAS_OMITIDAS] is False
    assert cache_semantico.precisa_de_linhas(payload) is False


# ── Procura ───────────────────────────────────────────────────────────────


def test_a_procura_so_serve_dentro_do_prazo():
    db = _BaseFalsa(acerto=None)
    _correr(db)
    procuras = [
        (sql, p)
        for sql, p in db.execucoes
        if "FROM semantic_cache" in sql and "SELECT" in sql
    ]
    assert procuras
    for sql, params in procuras:
        assert "created_at >= :cache_cutoff" in sql
        assert "cache_cutoff" in params


def test_acerto_volta_a_correr_o_sql_na_fonte_do_cliente():
    guardado = cache_semantico.payload_para_cache(_resposta(LINHAS_DO_CLIENTE))
    db = _BaseFalsa(acerto=(guardado, 0.99))
    fonte = _FonteFalsa(linhas=LINHAS_NOVAS)

    resposta, interior = _correr(db, fonte=fonte)

    assert not interior, "num acerto o pipeline (LLM) não corre"
    assert fonte.sql_corrido == ["SELECT cliente, total FROM vendas"]
    assert resposta.data_sample == LINHAS_NOVAS
    assert resposta.answer == "A Joana Silva faturou 1200."


def test_linhas_antigas_na_cache_nunca_sao_servidas():
    """Uma linha gravada antes desta regra ainda traz ``data_sample`` cheio.
    O acerto ignora-o e vai à fonte."""
    antigo = _resposta(LINHAS_DO_CLIENTE).model_dump(mode="json")
    db = _BaseFalsa(acerto=(antigo, 0.99))
    fonte = _FonteFalsa(linhas=LINHAS_NOVAS)

    resposta, interior = _correr(db, fonte=fonte)

    assert not interior
    assert resposta.data_sample == LINHAS_NOVAS
    assert fonte.sql_corrido, "as linhas antigas não podem substituir a fonte"


def test_acerto_sem_linhas_nao_toca_na_fonte():
    guardado = cache_semantico.payload_para_cache(_resposta([]))
    db = _BaseFalsa(acerto=(guardado, 0.99))
    fonte = _FonteFalsa(linhas=LINHAS_NOVAS)

    resposta, interior = _correr(db, fonte=fonte)

    assert not interior
    assert fonte.sql_corrido == []
    assert resposta.data_sample == []


@pytest.mark.parametrize(
    "fonte",
    [None, _FonteFalsa(erro=RuntimeError("fonte em baixo"))],
    ids=["ligacao-sem-fonte", "fonte-em-baixo"],
)
def test_sem_conseguir_as_linhas_o_acerto_e_descartado(fonte):
    guardado = cache_semantico.payload_para_cache(_resposta(LINHAS_DO_CLIENTE))
    db = _BaseFalsa(acerto=(guardado, 0.99))

    resposta, interior = _correr(db, fonte=fonte)

    assert interior, "sem linhas o acerto não se serve — segue o pipeline"
    assert resposta.data_sample == LINHAS_DO_CLIENTE


def test_acerto_sem_sql_guardado_e_descartado():
    resposta_sem_sql = QueryResponse(
        answer="x", data_sample=LINHAS_DO_CLIENTE, meta=QueryResultMeta(sql=None)
    )
    guardado = cache_semantico.payload_para_cache(resposta_sem_sql)
    db = _BaseFalsa(acerto=(guardado, 0.99))

    _, interior = _correr(db, fonte=_FonteFalsa(linhas=LINHAS_NOVAS))

    assert interior


def test_repor_linhas_corta_na_amostra():
    db = _BaseFalsa()
    muitas = [{"i": i} for i in range(40)]
    from api.routes import connection_query as cq

    with patch.object(
        cq, "_dispatch_map_from_conn_rows", lambda rows: {"conn-1": _FonteFalsa(muitas)}
    ):
        linhas = asyncio.run(cache_semantico.repor_linhas(db, "conn-1", "SELECT i"))
    assert len(linhas) == cache_semantico.LINHAS_NA_AMOSTRA
