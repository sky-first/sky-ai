"""``POST /privacidade/retencao`` — retenção da auditoria numa base (RGPD).

Chamado uma vez por dia e por base pela tarefa do backend
(``src/workers/rgpd_worker.py`` no sky-backend), com ``X-Tenant-Slug`` para
os clientes e sem ele para a plataforma. O sky-ai não tem beat próprio em
produção; o agendamento vive num só sítio.

Regras:

- **Os dias vêm do ambiente deste serviço** (``RETENCAO_AUDITORIA_DIAS``),
  nunca do pedido. Quem chega aqui só escolhe se é dry-run.
- **Base estrita.** Se veio ``X-Tenant-Slug`` e não resolveu para esse
  cliente, responde 409 — o middleware cai na plataforma em silêncio, e
  correr lá a pensar que era o cliente dava contagens de outra base. Se a
  base do cliente não abre, 503: nunca se troca pela da plataforma.
- **Resposta só com contagens** (nada de perguntas, SQL ou ids de pessoas).

O serviço não está exposto fora do cluster (``ingress.enabled: false``).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from config.settings import settings

logger = logging.getLogger("dataassistant")

router = APIRouter(prefix="/privacidade", tags=["privacidade"])


@router.post("/retencao")
async def retencao(request: Request, dry_run: bool = Query(True)):
    from core.privacidade.retencao import aplicar_retencao
    from core.security.audit import _routes_to_tenant
    from core.tenant_context import current_tenant

    ctx = current_tenant()
    pedido = (request.headers.get("x-tenant-slug") or "").strip().lower()
    if pedido and pedido != ctx.slug:
        return JSONResponse(
            status_code=409,
            content={"erro": "cliente_nao_resolvido", "base": ctx.slug},
        )

    if _routes_to_tenant(ctx):
        from core.tenant_db import tenant_connection_manager

        sessao = tenant_connection_manager.async_session_or_none(ctx)
        if sessao is None:
            return JSONResponse(
                status_code=503,
                content={"erro": "base_do_cliente_indisponivel", "base": ctx.slug},
            )
    else:
        from db.session import AsyncSessionLocal

        sessao = AsyncSessionLocal()

    try:
        async with sessao as db:
            res = await aplicar_retencao(
                db,
                ctx.slug,
                dias=int(settings.retencao_auditoria_dias),
                a_serio=not dry_run,
            )
    except ValueError as exc:
        return JSONResponse(
            status_code=422, content={"erro": str(exc), "base": ctx.slug}
        )

    logger.info(
        "retencao_auditoria base=%s dry_run=%s %s falhas=%s",
        res.base,
        res.dry_run,
        res.contagens,
        res.falhas,
    )
    return res.como_dict()
