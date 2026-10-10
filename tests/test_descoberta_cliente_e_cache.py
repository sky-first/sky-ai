"""Descoberta: o cliente certo, a porta fechada quando falta, e a cache limpa.

Produção, 10/10/2026, ligação «Operaciones» (passou de 2 para 14 tabelas):

1. TODAS as descobertas em segundo plano davam
   ``discover_auto_embed_error … DataConnection <id> not found`` — depois de
   o pedido já ter respondido 200 «scheduled». Os pedidos vinham sem
   ``X-Tenant-Slug`` (semeadores do backend fora de um pedido HTTP), e o
   sky-ai abria a base da plataforma, onde a ligação não existe.
2. Depois da descoberta, o ``/query`` continuava a responder em 0,0 s com
   respostas de ANTES das tabelas novas: o ``semantic_cache`` nunca era
   limpo.

Estes testes correm o endpoint a sério (FastAPI + middleware de cliente +
tarefa de fundo) contra uma base falsa que só regista o que lhe pedem.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from core.tenant_context import (
    DEFAULT_TENANT_CONTEXT,
    TenantContext,
    current_tenant,
    reset_current_tenant,
    set_current_tenant,
)

CID = "e2b868f6-49aa-5ee9-b784-67a9ffa330b2"
ACME = TenantContext(
    slug="acme",
    id=uuid4(),
    tier="pro",
    display_name="Acme",
    db_host="db.acme",
    db_name="tenant_acme",
)


class _Resultado:
    def __init__(self, linha=None, rowcount=0):
        self._linha = linha
        self.rowcount = rowcount

    def first(self):
        return self._linha

    def mappings(self):
        return self

    def scalar(self):
        return 0

    def scalar_one_or_none(self):
        return []


class BaseFalsa:
    """Uma base de um cliente: tem (ou não) a ligação, e regista tudo."""

    def __init__(self, nome: str, tem_a_ligacao: bool, cache_rows: int = 3):
        self.nome = nome
        self.tem_a_ligacao = tem_a_ligacao
        self.cache_rows = cache_rows
        self.sql: list[str] = []
        self.cache_apagada_para: list[str] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.sql.append(sql)
        params = params or {}
        if "FROM data_connections" in sql:
            return _Resultado((1,) if self.tem_a_ligacao else None)
        if "DELETE FROM semantic_cache" in sql:
            self.cache_apagada_para.append(params.get("cid"))
            n, self.cache_rows = self.cache_rows, 0
            return _Resultado(rowcount=n)
        if "last_metadata_update" in sql and "EXTRACT" in sql:
            return _Resultado(None)  # nunca descoberta → não salta
        return _Resultado(None)

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def close(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.fixture
def mundo(monkeypatch):
    """Duas bases: a da plataforma (sem a ligação) e a do cliente `acme`."""
    plataforma = BaseFalsa("plataforma", tem_a_ligacao=False)
    acme = BaseFalsa("acme", tem_a_ligacao=True)
    chamadas: list[tuple[str, str]] = []

    def base_de(ctx=None):
        ctx = ctx or current_tenant()
        return acme if ctx.slug == "acme" else plataforma

    from core import tenant_db

    monkeypatch.setattr(
        tenant_db.tenant_connection_manager, "async_session_for", base_de
    )

    # A ingestão verdadeira falha como em produção quando a ligação não
    # está na base — e regista em que base e com que cliente correu.
    from core.ingestion import service, enrichment
    from core.llm import factory

    async def ingestao(db, connection_id, **kw):
        chamadas.append(("ingestao", db.nome, current_tenant().slug))
        if not db.tem_a_ligacao:
            raise service.ConnectionNotFoundError(
                f"DataConnection {connection_id} not found"
            )
        return 14

    async def embeddings(db, connection_id, **kw):
        chamadas.append(("embeddings", db.nome, current_tenant().slug))
        return 14

    async def zero(*a, **kw):
        return 0

    monkeypatch.setattr(service, "run_metadata_ingestion", ingestao)
    monkeypatch.setattr(service, "run_metadata_embeddings", embeddings)
    monkeypatch.setattr(service, "run_dataset_description_embeddings", zero)
    monkeypatch.setattr(enrichment, "enrich_table_date_ranges", zero)
    monkeypatch.setattr(factory, "create_embedding_provider", lambda: object())

    from api.routes import connection_discover
    from db.session import get_db

    app = FastAPI()
    app.include_router(connection_discover.router)

    async def _get_db():
        yield base_de()

    app.dependency_overrides[get_db] = _get_db

    # O mesmo contrato do middleware de `api/main.py`: liga o cliente ao
    # contexto durante o pedido e DESLIGA-O no fim — antes de a tarefa de
    # fundo acabar.
    @app.middleware("http")
    async def cliente(request, call_next):
        slug = request.headers.get("x-tenant-slug")
        token = set_current_tenant(ACME if slug == "acme" else DEFAULT_TENANT_CONTEXT)
        try:
            return await call_next(request)
        finally:
            reset_current_tenant(token)

    return app, plataforma, acme, chamadas


async def _post(app, headers=None, **params):
    params.setdefault("space_id", None)
    params = {k: v for k, v in params.items() if v is not None}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://sky-ai"
    ) as c:
        return await c.post(
            f"/connections/{CID}/discover", params=params, headers=headers or {}
        )


# ── 1. O cliente chega à tarefa de fundo ──────────────────────────────


async def test_em_segundo_plano_a_descoberta_corre_na_base_do_cliente_do_pedido(
    mundo,
):
    app, plataforma, acme, chamadas = mundo
    r = await _post(app, headers={"X-Tenant-Slug": "acme"}, run_in_background="true")
    assert r.status_code == 200, r.text
    # A tarefa de fundo correu depois de o middleware repor o contexto — e
    # mesmo assim abriu a base do cliente, com o cliente no contexto.
    assert ("ingestao", "acme", "acme") in chamadas
    assert ("embeddings", "acme", "acme") in chamadas
    assert not any(base == "plataforma" for _, base, _ in chamadas)


# ── 2. Sem cliente, a porta fecha — não «scheduled» e falha depois ────


async def test_sem_cabecalho_do_cliente_a_descoberta_e_recusada_a_porta(mundo):
    app, plataforma, acme, chamadas = mundo
    r = await _post(app, run_in_background="true")
    assert r.status_code == 404
    assert "X-Tenant-Slug" in r.json()["detail"]
    # Nada foi agendado: nenhuma ingestão, em base nenhuma.
    assert chamadas == []


async def test_sem_cabecalho_tambem_recusa_a_descoberta_sincrona(mundo):
    app, plataforma, acme, chamadas = mundo
    r = await _post(app, run_in_background="false")
    assert r.status_code == 404
    assert chamadas == []


# ── 3. Descoberta bem-sucedida limpa as respostas guardadas ───────────


async def test_descoberta_sincrona_limpa_a_cache_semantica_da_ligacao(mundo):
    app, plataforma, acme, chamadas = mundo
    r = await _post(app, headers={"X-Tenant-Slug": "acme"}, run_in_background="false")
    assert r.status_code == 200, r.text
    assert acme.cache_apagada_para == [CID]
    assert r.json()["semantic_cache_invalidated"] == 3


async def test_descoberta_em_segundo_plano_limpa_a_cache_semantica_da_ligacao(
    mundo,
):
    app, plataforma, acme, chamadas = mundo
    r = await _post(app, headers={"X-Tenant-Slug": "acme"}, run_in_background="true")
    assert r.status_code == 200
    assert acme.cache_apagada_para == [CID]
    assert plataforma.cache_apagada_para == []


async def test_descoberta_que_falha_nao_limpa_a_cache(mundo, monkeypatch):
    """Se a ingestão falhou, o catálogo do `/query` não mudou — as respostas
    guardadas continuam certas e apagá-las só custaria tempo."""
    app, plataforma, acme, chamadas = mundo
    from core.ingestion import service

    async def rebenta(*a, **kw):
        raise RuntimeError("introspecção falhou")

    monkeypatch.setattr(service, "run_metadata_ingestion", rebenta)
    r = await _post(app, headers={"X-Tenant-Slug": "acme"}, run_in_background="false")
    assert r.status_code == 200
    assert acme.cache_apagada_para == []


async def test_descoberta_saltada_por_ser_recente_nao_limpa_a_cache(mundo, monkeypatch):
    app, plataforma, acme, chamadas = mundo

    original = acme.execute

    async def recente(stmt, params=None):
        if "EXTRACT" in str(stmt):
            return _Resultado({"age": 10, "linhas": 50})
        return await original(stmt, params)

    acme.execute = recente
    r = await _post(app, headers={"X-Tenant-Slug": "acme"}, run_in_background="false")
    assert r.json().get("skipped_reason") == "recent_metadata"
    assert acme.cache_apagada_para == []
