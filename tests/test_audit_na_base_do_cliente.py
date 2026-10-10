"""O trilho de auditoria vai para a base do cliente, não para a da plataforma.

Medido em produção a 10/10/2026: ``query_audit_log`` (pergunta, SQL gerado e
executado, utilizador, ligação…) e ``prompt_security_audit`` (texto do prompt)
de TODOS os clientes eram gravados na base partilhada da plataforma
(``skyaisaas``) — ~1.900 e ~8.300 linhas em 7 dias — e as bases dos clientes
tinham 0. Quebra o isolamento do Modelo B e tira esses dados da quota do
cliente.

A causa: o flush corre numa tarefa de fundo criada no arranque, cujo
``current_tenant()`` é sempre o contexto por omissão; e abria sempre
``db.base.SessionLocal`` (plataforma). Estes testes fixam o comportamento:

  · uma pergunta no contexto do cliente A cai na sessão de A, não na da
    plataforma;
  · o contexto por omissão continua a ir para a plataforma;
  · dois clientes intercalados na mesma fila vão cada um para a sua base;
  · uma falha de auditoria nunca rebenta a pergunta, e um cliente com a base
    em baixo não leva as linhas dele para a plataforma nem trava os outros.

As sessões são falsas (registam os INSERT): o que interessa é o destino.
"""

from __future__ import annotations

import os
from uuid import UUID

import pytest

os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")

from core.security import audit  # noqa: E402
from core.tenant_context import (  # noqa: E402
    DEFAULT_TENANT_CONTEXT,
    TenantContext,
    reset_current_tenant,
    set_current_tenant,
)

CONN = "afdf5872-e58e-4015-925b-a2f940df701c"


def _tenant(slug: str, n: int) -> TenantContext:
    return TenantContext(
        slug=slug,
        id=UUID(int=n),
        tier="pro",
        display_name=slug,
        db_host=f"{slug}.db.internal",
        db_name=f"tenant_{slug}",
        db_credentials_secret_arn=f"arn:aws:secretsmanager:::sky/{slug}/db",
    )


TENANT_A = _tenant("acme", 1)
TENANT_B = _tenant("globex", 2)


class FakeSession:
    """Sessão assíncrona que regista os INSERT de auditoria."""

    def __init__(self, name: str, fail_on_insert: bool = False):
        self.name = name
        self.fail_on_insert = fail_on_insert
        self.inserts: list[tuple[str, dict]] = []
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "INSERT INTO" in sql:
            if self.fail_on_insert:
                raise RuntimeError(f"{self.name}: connection refused")
            table = sql.split("INSERT INTO", 1)[1].split("(", 1)[0].strip()
            self.inserts.append((table, dict(params or {})))

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    def rows(self, table: str) -> list[dict]:
        return [p for t, p in self.inserts if t == table]


@pytest.fixture
def dbs(monkeypatch):
    """Uma sessão falsa por destino; regista quem abriu o quê."""
    sessions = {
        "platform": FakeSession("platform"),
        "acme": FakeSession("acme"),
        "globex": FakeSession("globex"),
    }
    unavailable: set[str] = set()

    import core.tenant_db as tenant_db
    import db.base as db_base

    monkeypatch.setattr(db_base, "SessionLocal", lambda: sessions["platform"])

    def _tenant_session(ctx=None):
        if ctx.slug in unavailable:
            return None
        return sessions[ctx.slug]

    monkeypatch.setattr(
        tenant_db.tenant_connection_manager, "async_session_or_none", _tenant_session
    )

    audit._audit_buffer.clear()
    audit._backoff_until.clear()
    audit._last_ensure_attempt.clear()
    sessions["unavailable"] = unavailable
    yield sessions
    audit._audit_buffer.clear()
    audit._backoff_until.clear()
    audit._last_ensure_attempt.clear()


def _ask(question: str, ctx: TenantContext | None = None) -> None:
    token = set_current_tenant(ctx) if ctx is not None else None
    try:
        audit.log_query_audit(
            connection_id=CONN,
            user_id="u-1",
            space_id=None,
            crew_ids=[],
            thread_id="t-1",
            question=question,
            sql_generated="SELECT 1",
            sql_executed="SELECT 1",
        )
        audit.log_prompt_security_audit(
            connection_id=CONN,
            user_id="u-1",
            prompt_text_redacted=question,
            security_status="ALLOWED",
            blocked_by=None,
            risk_score=0.0,
            scan_details={},
        )
    finally:
        if token is not None:
            reset_current_tenant(token)


async def _drain():
    for _ in range(5):
        await audit._flush_audit_buffer_async()


async def test_pergunta_do_cliente_cai_na_base_do_cliente(dbs):
    _ask("faturação de setembro da acme", TENANT_A)

    await _drain()

    acme, platform = dbs["acme"], dbs["platform"]
    assert [r["question"] for r in acme.rows("query_audit_log")] == [
        "faturação de setembro da acme"
    ]
    assert [r["prompt_text_redacted"] for r in acme.rows("prompt_security_audit")] == [
        "faturação de setembro da acme"
    ]
    assert platform.inserts == [], "dados do cliente na base da plataforma"
    assert acme.commits >= 1


async def test_contexto_por_omissao_continua_na_plataforma(dbs):
    _ask("pergunta sem cliente")  # contexto por omissão
    _ask("também sem cliente", DEFAULT_TENANT_CONTEXT)

    await _drain()

    assert [r["question"] for r in dbs["platform"].rows("query_audit_log")] == [
        "pergunta sem cliente",
        "também sem cliente",
    ]
    assert len(dbs["platform"].rows("prompt_security_audit")) == 2
    assert dbs["acme"].inserts == [] and dbs["globex"].inserts == []


async def test_cliente_sem_base_dedicada_usa_a_plataforma(dbs):
    """Mesma regra do TenantConnectionManager: sem db_host/db_name não há
    base própria para onde ir."""
    shared = TenantContext(
        slug="legacy", id=UUID(int=9), tier="pilot", display_name="x"
    )
    _ask("cliente antigo", shared)

    await _drain()

    assert [r["question"] for r in dbs["platform"].rows("query_audit_log")] == [
        "cliente antigo"
    ]


async def test_dois_clientes_intercalados_na_fila_vao_cada_um_para_a_sua(dbs):
    _ask("A1", TENANT_A)
    _ask("B1", TENANT_B)
    _ask("plataforma")
    _ask("A2", TENANT_A)
    _ask("B2", TENANT_B)

    # O contexto de quem chama o flush é irrelevante: aqui é o B, e as
    # linhas do A têm de ir na mesma para o A.
    token = set_current_tenant(TENANT_B)
    try:
        await _drain()
    finally:
        reset_current_tenant(token)

    def questions(name):
        return [r["question"] for r in dbs[name].rows("query_audit_log")]

    assert questions("acme") == ["A1", "A2"]
    assert questions("globex") == ["B1", "B2"]
    assert questions("platform") == ["plataforma"]
    assert [
        r["prompt_text_redacted"] for r in dbs["acme"].rows("prompt_security_audit")
    ] == [
        "A1",
        "A2",
    ]
    assert [
        r["prompt_text_redacted"] for r in dbs["globex"].rows("prompt_security_audit")
    ] == ["B1", "B2"]


async def test_o_flush_numa_tarefa_de_fundo_respeita_o_cliente_do_pedido(dbs):
    """Reproduz a produção: o flusher é uma tarefa criada fora do pedido."""
    import asyncio

    flusher = asyncio.get_running_loop().create_task(_drain())
    _ask("dentro do pedido da acme", TENANT_A)
    await flusher
    await _drain()

    assert [r["question"] for r in dbs["acme"].rows("query_audit_log")] == [
        "dentro do pedido da acme"
    ]
    assert dbs["platform"].inserts == []


async def test_falha_na_escrita_nao_rebenta_e_nao_trava_os_outros(dbs):
    dbs["acme"].fail_on_insert = True
    _ask("A1", TENANT_A)
    _ask("B1", TENANT_B)

    await audit._flush_audit_buffer_async()  # não levanta

    assert dbs["acme"].rollbacks >= 1
    assert [r["question"] for r in dbs["globex"].rows("query_audit_log")] == ["B1"]
    assert dbs["platform"].inserts == []
    # Backoff só para o destino que falhou.
    assert "acme" in audit._backoff_until
    assert "globex" not in audit._backoff_until


async def test_base_do_cliente_indisponivel_nao_desvia_para_a_plataforma(dbs):
    dbs["unavailable"].add("acme")
    _ask("A1", TENANT_A)

    await audit._flush_audit_buffer_async()  # não levanta

    assert dbs["platform"].inserts == [], "fallback para a plataforma = fuga"
    # As linhas esperam pela base do cliente em vez de se perderem.
    waiting = [e for e in audit._audit_buffer if e.get("_tenant") == TENANT_A]
    assert len(waiting) == 2

    # Quando a base volta (e o backoff passa), chegam ao destino certo.
    dbs["unavailable"].clear()
    audit._backoff_until.clear()
    await _drain()
    assert [r["question"] for r in dbs["acme"].rows("query_audit_log")] == ["A1"]
    assert dbs["platform"].inserts == []


def test_registar_nunca_rebenta_mesmo_sem_contexto(monkeypatch, dbs):
    import core.tenant_context as tc

    def boom():
        raise RuntimeError("contextvar partido")

    monkeypatch.setattr(tc, "current_tenant", boom)
    _ask("sem contexto legível")  # não levanta

    assert len(audit._audit_buffer) == 2


async def test_audit_manager_regista_no_cliente_do_pedido(dbs):
    from core.security.audit_manager import AuditManager, SecurityAuditReport

    token = set_current_tenant(TENANT_B)
    try:
        await AuditManager._log_audit(
            "u-1", CONN, SecurityAuditReport(redacted_prompt="prompt da globex")
        )
    finally:
        reset_current_tenant(token)

    await _drain()

    assert [
        r["prompt_text_redacted"] for r in dbs["globex"].rows("prompt_security_audit")
    ] == ["prompt da globex"]
    assert dbs["platform"].inserts == []


def test_a_migracao_cria_as_tabelas_de_auditoria_nos_clientes():
    """O sync_tenants corre db/migrations/*.sql em cada base de cliente; é
    por aí que prompt_security_audit e as colunas de PII lá chegam."""
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[1]
        / "db"
        / "migrations"
        / "007_audit_na_base_do_cliente.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS prompt_security_audit" in sql
    assert "CREATE TABLE IF NOT EXISTS security_alerts" in sql
    for col in ("platform_role", "crew_role", "pii_blocked", "pii_types"):
        assert f"ADD COLUMN IF NOT EXISTS {col}" in sql
