"""Retenção de 12 meses da auditoria do sky-ai (RGPD, 15/10/2026).

Sem Postgres na CI: a base é falsa e guarda, por tabela, a data de cada
linha. Fixa-se o comportamento — o que passa dos 365 dias apaga, o resto
fica, a segunda passagem não faz nada, o dry-run não escreve — e as guardas
do endpoint (base estrita, dias só do ambiente).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from core.privacidade import retencao as modulo
from core.privacidade.retencao import TABELAS_COM_RETENCAO, aplicar_retencao

AGORA = datetime(2026, 10, 15, 3, 17, tzinfo=timezone.utc)


def _ha(dias: int) -> datetime:
    return AGORA - timedelta(days=dias)


class _R:
    def __init__(self, escalar=None):
        self._e = escalar

    def scalar(self):
        return self._e


class _BaseFalsa:
    def __init__(self, tabelas=None, falha_em=None):
        idades = [400, 366, 300, 1]
        self.linhas = {
            t: [_ha(d) for d in idades] for t in (tabelas or TABELAS_COM_RETENCAO)
        }
        self.falha_em = falha_em
        self.commits = 0
        self.rollbacks = 0
        self.escritas = 0

    async def execute(self, stmt, params=None):
        q, p = str(stmt), params or {}
        if q.startswith("SELECT to_regclass"):
            return _R(p["t"] in self.linhas)
        tabela = q.split(" FROM ", 1)[1].split()[0]
        if tabela == self.falha_em:
            raise PermissionError("sem permissão")
        if q.startswith("SELECT count(*)"):
            return _R(sum(1 for t in self.linhas[tabela] if t < p["corte"]))
        if q.startswith("DELETE"):
            self.escritas += 1
            self.linhas[tabela] = [t for t in self.linhas[tabela] if t >= p["corte"]]
            return _R()
        raise AssertionError(f"consulta inesperada: {q}")

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _correr(db, **kw):
    return asyncio.run(aplicar_retencao(db, "sandbox", agora=AGORA, **kw))


def test_apaga_mais_de_365_dias_e_nao_o_resto():
    db = _BaseFalsa()
    res = _correr(db, dias=365, a_serio=True)
    for t in TABELAS_COM_RETENCAO:
        assert res.contagens[f"{t}_apagados"] == 2
        assert all(d >= _ha(365) for d in db.linhas[t])
        assert len(db.linhas[t]) == 2  # 300 dias e 1 dia ficam
    assert res.falhas == []
    assert res.como_dict()["base"] == "sandbox"


def test_segunda_passagem_nao_faz_nada():
    db = _BaseFalsa()
    _correr(db, dias=365, a_serio=True)
    escritas = db.escritas
    res = _correr(db, dias=365, a_serio=True)
    assert all(v == 0 for v in res.contagens.values())
    assert db.escritas == escritas


def test_dry_run_conta_e_nao_escreve():
    db = _BaseFalsa()
    res = _correr(db, dias=365, a_serio=False)
    assert res.dry_run is True
    for t in TABELAS_COM_RETENCAO:
        assert res.contagens[f"{t}_a_apagar"] == 2
        assert len(db.linhas[t]) == 4
    assert db.escritas == 0 and db.commits == 0


def test_tabela_que_nao_existe_e_ignorada():
    db = _BaseFalsa(tabelas=("query_audit_log",))
    res = _correr(db, dias=365, a_serio=True)
    assert set(res.contagens) == {"query_audit_log_apagados"}
    assert res.falhas == []


def test_uma_tabela_que_falha_nao_trava_as_outras():
    db = _BaseFalsa(falha_em="prompt_security_audit")
    res = _correr(db, dias=365, a_serio=True)
    assert res.falhas == ["prompt_security_audit:PermissionError"]
    assert db.rollbacks == 1
    assert res.contagens["query_audit_log_apagados"] == 2
    assert res.contagens["security_alerts_apagados"] == 2


@pytest.mark.parametrize("dias", [0, 1, 29])
def test_recusa_prazos_absurdos(dias):
    # RETENCAO_AUDITORIA_DIAS=0 mal escrito apagava a auditoria toda.
    with pytest.raises(ValueError):
        _correr(_BaseFalsa(), dias=dias, a_serio=True)


def test_resultado_nao_leva_dados_pessoais():
    res = _correr(_BaseFalsa(), dias=365, a_serio=False)
    texto = json.dumps(res.como_dict())
    for proibido in ("user_id", "question", "sql", "@"):
        assert proibido not in texto


# ── O endpoint ───────────────────────────────────────────────────────────


def _pedido(slug: str | None) -> Request:
    cab = [(b"x-tenant-slug", slug.encode())] if slug else []
    return Request({"type": "http", "method": "POST", "path": "/", "headers": cab})


def _cliente(slug: str):
    from core.tenant_context import TenantContext

    return TenantContext(
        slug=slug,
        id=uuid.uuid4(),
        tier="pro",
        display_name=slug,
        db_host="h",
        db_name=f"tenant_{slug}",
    )


class _Sessao:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *a):
        return False


def _chamar(slug_pedido, ctx, dry_run=True):
    from api.routes import retencao as rota
    from core.tenant_context import reset_current_tenant, set_current_tenant

    async def _go():
        token = set_current_tenant(ctx)
        try:
            return await rota.retencao(_pedido(slug_pedido), dry_run=dry_run)
        finally:
            reset_current_tenant(token)

    return asyncio.run(_go())


def test_endpoint_corre_na_base_do_cliente_com_os_dias_do_ambiente(monkeypatch):
    from config.settings import settings
    from core import tenant_db

    db = _BaseFalsa()
    abertas = []

    def _abrir(ctx):
        abertas.append(ctx.slug)
        return _Sessao(db)

    monkeypatch.setattr(
        tenant_db.tenant_connection_manager, "async_session_or_none", _abrir
    )
    monkeypatch.setattr(settings, "retencao_auditoria_dias", 365)
    monkeypatch.setattr(modulo, "datetime", _RelogioFixo)

    r = _chamar("sandbox", _cliente("sandbox"), dry_run=True)
    assert abertas == ["sandbox"]
    assert r["base"] == "sandbox" and r["dias"] == 365 and r["dry_run"] is True
    assert r["contagens"]["query_audit_log_a_apagar"] == 2
    assert db.escritas == 0


def test_endpoint_recusa_quando_o_cliente_nao_resolveu():
    from core.tenant_context import DEFAULT_TENANT_CONTEXT

    # O middleware caiu na plataforma em silêncio: não se corre lá.
    r = _chamar("sandbox", DEFAULT_TENANT_CONTEXT)
    assert r.status_code == 409


def test_endpoint_nao_troca_a_base_do_cliente_pela_da_plataforma(monkeypatch):
    from core import tenant_db

    monkeypatch.setattr(
        tenant_db.tenant_connection_manager, "async_session_or_none", lambda ctx: None
    )
    r = _chamar("sandbox", _cliente("sandbox"))
    assert r.status_code == 503


class _RelogioFixo(datetime):
    @classmethod
    def now(cls, tz=None):
        return AGORA
