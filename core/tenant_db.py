"""Tenant-scoped DB engines for the AI service (Model B / Phase 5).

Mirror of sky-poc-backend's ``TenantConnectionManager``. Given the
current :class:`TenantContext` (resolved from the ``X-Tenant-Slug``
header by the tenant middleware), this opens an **async** (asyncpg) and
a **sync** (psycopg2, for LangGraph checkpoints) engine pointed at the
tenant's own database, caching them per slug.

For the default context — single-tenant mode, or any request without a
tenant slug — it hands back the process-wide engines from ``db.session``
/ ``db.base``, so existing behaviour is byte-for-byte unchanged. That
default fallback is what makes wiring this into ``get_db`` safe to ship
before every tenant DB is fully provisioned.

Credentials come from the AWS Secrets Manager secret named in the
registry row (``db_credentials_secret_arn``). Reading it requires the
sky-ai pod's IRSA role to allow ``secretsmanager:GetSecretValue`` on
``sky/staging/tenant-*/db`` (provisioned in PR-4). If the secret read or
the connection fails, the caller falls back to the default engine and
logs — a tenant misconfiguration must not 500 the whole AI service.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from urllib.parse import quote_plus, unquote, urlparse

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from core.tenant_context import TenantContext, current_tenant

logger = logging.getLogger(__name__)


@dataclass
class _TenantEngines:
    async_maker: async_sessionmaker
    sync_maker: sessionmaker


class TenantConnectionManager:
    """Lazily-instantiated cache of per-tenant async + sync engines."""

    def __init__(self) -> None:
        self._pools: Dict[str, _TenantEngines] = {}
        self._lock = threading.Lock()

    # ── Public API ─────────────────────────────────────────────

    def async_session_for(self, ctx: Optional[TenantContext] = None) -> AsyncSession:
        """Return a fresh async session bound to ``ctx``'s database.

        Falls back to the global async session for the default context
        or when the tenant engine cannot be built.
        """
        ctx = ctx or current_tenant()
        pool = self._maybe_pool(ctx)
        if pool is None:
            from db.session import AsyncSessionLocal

            return AsyncSessionLocal()
        return pool.async_maker()

    def sync_session_for(self, ctx: Optional[TenantContext] = None):
        """Return a fresh sync session bound to ``ctx``'s database.

        Used by LangGraph checkpoint storage and other sync paths. Falls
        back to the global sync session for the default context.
        """
        ctx = ctx or current_tenant()
        pool = self._maybe_pool(ctx)
        if pool is None:
            from db.base import SyncSessionLocal

            return SyncSessionLocal()
        return pool.sync_maker()

    def known_slugs(self) -> list[str]:
        return list(self._pools.keys())

    # ── Internals ──────────────────────────────────────────────

    def _maybe_pool(self, ctx: Optional[TenantContext]) -> Optional[_TenantEngines]:
        """Resolve (and cache) the engines for ``ctx``, or None for the
        default context / on any build failure (caller then uses the
        global engine)."""
        if ctx is None or ctx.is_default or not ctx.db_name or not ctx.db_host:
            return None
        pool = self._pools.get(ctx.slug)
        if pool is not None:
            return pool
        with self._lock:
            pool = self._pools.get(ctx.slug)
            if pool is None:
                try:
                    pool = self._build(ctx)
                except Exception as exc:  # noqa: BLE001 — never block the request
                    logger.warning(
                        "ai_tenant_engine_build_failed",
                        extra={"slug": ctx.slug, "error": str(exc)[:200]},
                    )
                    return None
                self._pools[ctx.slug] = pool
        return pool

    def _build(self, ctx: TenantContext) -> _TenantEngines:
        user, password = self._fetch_secret(ctx.db_credentials_secret_arn)
        creds = f"{quote_plus(user)}:{quote_plus(password)}@{ctx.db_host}:5432/{ctx.db_name}"
        async_engine = create_async_engine(
            f"postgresql+asyncpg://{creds}",
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False,
        )
        sync_engine = create_engine(
            f"postgresql+psycopg2://{creds}",
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False,
        )
        self._ensure_schema(sync_engine, ctx)
        logger.info(
            "ai_tenant_engine_created",
            extra={"slug": ctx.slug, "db_name": ctx.db_name},
        )
        return _TenantEngines(
            async_maker=async_sessionmaker(
                async_engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
                autocommit=False,
            ),
            sync_maker=sessionmaker(
                bind=sync_engine, autoflush=False, autocommit=False
            ),
        )

    @staticmethod
    def _ensure_schema(sync_engine, ctx: TenantContext) -> None:
        """Idempotently provision the AI-service schema in the tenant DB.

        The onboard flow + backend alembic create spaces/crews/connections
        /semantic_cache in each tenant DB, but NOT the AI-service-specific
        tables (``embeddings``, ``table_metadata``) nor the
        ``semantic_cache.locale`` column. ``create_all(checkfirst=True)``
        adds only the missing tables (never alters existing ones); the
        ALTER adds the column. pgvector is installed by the onboard flow.

        Runs once per tenant per process (inside ``_build`` under the
        lock). Never raises — a provisioning hiccup must not break the
        engine; the worst case is the same FK/undefined-column error we
        had before, surfaced in logs.
        """
        try:
            from sqlalchemy import text

            from db import models  # noqa: WPS433 — lazy, keeps import graph light

            models.Base.metadata.create_all(bind=sync_engine, checkfirst=True)
            with sync_engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE IF EXISTS semantic_cache "
                        "ADD COLUMN IF NOT EXISTS locale VARCHAR(10) "
                        "NOT NULL DEFAULT 'en'"
                    )
                )
            logger.info(
                "ai_tenant_schema_ensured", extra={"slug": ctx.slug}
            )
        except Exception as exc:  # noqa: BLE001 — never break engine build
            logger.warning(
                "ai_tenant_schema_ensure_failed",
                extra={"slug": ctx.slug, "error": str(exc)[:200]},
            )

    @staticmethod
    def _fetch_secret(arn: str) -> Tuple[str, str]:
        """Return (username, password) from the tenant DB secret.

        Accepts both the ``{username, password}`` shape and the
        ``{url: "postgresql://user:pw@host:port/db"}`` shape that the
        onboard-client workflow writes.
        """
        if not arn:
            raise KeyError("empty db_credentials_secret_arn")
        import boto3  # lazy — tests / local dev never reach here

        client = boto3.client("secretsmanager")
        blob = json.loads(client.get_secret_value(SecretId=arn)["SecretString"])
        if blob.get("username") and blob.get("password") is not None:
            return blob["username"], blob["password"]
        url = blob.get("url")
        if url:
            parsed = urlparse(url)
            if parsed.username and parsed.password is not None:
                return unquote(parsed.username), unquote(parsed.password)
        raise KeyError(f"tenant DB secret {arn!r} has no usable credentials")


# Module-level singleton — same lifetime as the FastAPI app.
tenant_connection_manager = TenantConnectionManager()
