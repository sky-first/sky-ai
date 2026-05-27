"""Read-only access to the shared ``tenant_registry`` table.

The table lives in the platform Postgres (the same DB sky-poc-backend
writes). sky-poc-ai consumes it via a regular SQLAlchemy session so
the request flow on the AI side can build a :class:`TenantContext`
from a slug header.

Caching: short TTL dict mirrored on the backend's pattern. Operators
that update a tenant should call ``clear_cache()`` from the Internal
Console or just wait out the 60s window.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional, Tuple

from sqlalchemy import text

from core.tenant_context import TenantContext

logger = logging.getLogger(__name__)


_CACHE_TTL_SECONDS = 60.0
_CACHE: Dict[str, Tuple[TenantContext, float]] = {}


def _cache_get(slug: str) -> Optional[TenantContext]:
    entry = _CACHE.get(slug)
    if entry is None:
        return None
    ctx, expires_at = entry
    if expires_at < time.monotonic():
        _CACHE.pop(slug, None)
        return None
    return ctx


def _cache_put(ctx: TenantContext) -> None:
    _CACHE[ctx.slug] = (ctx, time.monotonic() + _CACHE_TTL_SECONDS)


def clear_cache() -> None:
    _CACHE.clear()


async def lookup_tenant_by_slug(session, slug: str) -> Optional[TenantContext]:
    """Return the :class:`TenantContext` for ``slug`` or None.

    Inactive tenants are treated as "not found" — the caller will fall
    back to the default context and the LangGraph pipeline continues.

    Caches every successful lookup so subsequent requests in the same
    process do not re-query.
    """
    if not slug:
        return None

    cached = _cache_get(slug)
    if cached is not None:
        return cached

    # Plain ``text`` rather than the ORM model to avoid importing
    # sky-be's SQLAlchemy declarative class here. The shape we care
    # about is small enough that hand-listing the columns is fine.
    try:
        result = await session.execute(
            text(
                """
                SELECT id, slug, tier, display_name,
                       bedrock_inference_profile_arn,
                       rate_limit_rpm, rate_limit_tpm,
                       is_active, feature_flags
                FROM tenant_registry
                WHERE slug = :slug
                LIMIT 1
                """
            ),
            {"slug": slug},
        )
        row = result.mappings().one_or_none()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "sky_ai_tenant_lookup_failed",
            extra={"slug": slug, "error": str(exc)[:200]},
        )
        return None

    if row is None or not row["is_active"]:
        return None

    ctx = TenantContext(
        slug=row["slug"],
        id=row["id"],
        tier=row["tier"],
        display_name=row["display_name"],
        bedrock_inference_profile_arn=row["bedrock_inference_profile_arn"],
        rate_limit_rpm=row["rate_limit_rpm"],
        rate_limit_tpm=row["rate_limit_tpm"],
        is_active=row["is_active"],
        feature_flags=dict(row["feature_flags"] or {}),
    )
    _cache_put(ctx)
    return ctx
