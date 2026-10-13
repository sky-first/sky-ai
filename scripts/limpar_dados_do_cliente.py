"""Tira das nossas bases os dados do cliente que lá ficaram (uma vez).

Princípio (13/10/2026): nunca guardamos linhas do cliente. O código deixou de
as gravar; isto limpa o que já estava gravado, em TODAS as bases — a da
plataforma e a de cada cliente (via ``tenant_connection_manager``). O que faz
em cada base está em ``core/privacidade/limpeza.py``.

Idempotente: correr duas vezes é seguro, a segunda não encontra nada.

Ordem recomendada: primeiro o ``scripts/limpar_valores_das_colunas.py`` do
sky-backend (limpa ``connection_metadata`` e pede nova descoberta), depois este.

Uso (num pod do sky-ai, com ``DATABASE_URL`` da plataforma e IRSA para ler os
segredos dos clientes)::

    python scripts/limpar_dados_do_cliente.py              # só conta (dry-run)
    python scripts/limpar_dados_do_cliente.py --apply      # limpa
    python scripts/limpar_dados_do_cliente.py --apply --slug sandbox
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def _contextos(slug: str | None):
    """Os ``TenantContext`` dos clientes activos com base própria."""
    from sqlalchemy import text

    from core.tenant_registry_lookup import lookup_tenant_by_slug
    from db.session import DATABASE_URL, AsyncSessionLocal

    nome_da_plataforma = DATABASE_URL.rsplit("/", 1)[-1].split("?")[0]
    async with AsyncSessionLocal() as s:
        slugs = (
            (
                await s.execute(
                    text("SELECT slug FROM tenant_registry WHERE is_active IS TRUE")
                )
            )
            .scalars()
            .all()
        )
        saida = []
        for sl in slugs:
            if slug and sl != slug:
                continue
            ctx = await lookup_tenant_by_slug(s, sl)
            if ctx is None or not ctx.db_host or not ctx.db_name:
                print(f"  {sl}: sem base dedicada, ignorado")
                continue
            if ctx.db_name == nome_da_plataforma:
                print(f"  {sl}: é a base da plataforma, tratada à parte")
                continue
            saida.append(ctx)
    return saida


async def _embedder(textos):
    from core.llm.factory import create_embedding_provider

    return await create_embedding_provider().embed_async(list(textos))


async def principal() -> int:
    from core.privacidade.limpeza import limpar_base
    from core.tenant_db import tenant_connection_manager
    from db.session import AsyncSessionLocal

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="limpar a sério")
    parser.add_argument("--slug", help="só este cliente (e não a plataforma)")
    args = parser.parse_args()
    a_serio = args.apply
    print("A LIMPAR" if a_serio else "DRY-RUN (só conta; --apply para limpar)")

    falharam: list[str] = []

    if not args.slug:
        try:
            async with AsyncSessionLocal() as db:
                print(
                    await limpar_base(
                        db, "plataforma", a_serio=a_serio, embedder=_embedder
                    )
                )
        except Exception as e:  # noqa: BLE001
            print(f"  plataforma: FALHOU — {type(e).__name__}: {str(e)[:200]}")
            falharam.append("plataforma")

    for ctx in await _contextos(args.slug):
        # SEM fallback: uma base de cliente que não abre não pode virar a da
        # plataforma (limparia a base errada e diria que correu bem).
        sessao = tenant_connection_manager.async_session_or_none(ctx)
        if sessao is None:
            print(f"  {ctx.slug}: FALHOU — base do cliente não abre")
            falharam.append(ctx.slug)
            continue
        try:
            async with sessao as db:
                print(
                    await limpar_base(db, ctx.slug, a_serio=a_serio, embedder=_embedder)
                )
        except Exception as e:  # noqa: BLE001
            print(f"  {ctx.slug}: FALHOU — {type(e).__name__}: {str(e)[:200]}")
            falharam.append(ctx.slug)

    if falharam:
        print(f"\nFalharam: {falharam}")
        return 1
    print("\nFeito." if a_serio else "\nNada mudou (dry-run).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(principal()))
