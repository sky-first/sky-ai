"""Tenant context for sky-poc-ai (Projeto A — PR #9).

The AI service is a downstream of the backend. It receives one
``X-Tenant-Slug`` header per request, looks the tenant up in the
shared ``tenant_registry`` table (which physically lives in the
same Postgres instance as sky-poc-backend), and exposes that context
to the LangGraph agent state and to the Bedrock provider.

This module is intentionally smaller than the backend's twin:

* No middleware — the FastAPI dependency in ``api/dependencies.py``
  reads the header and calls ``lookup_tenant_by_slug``.
* No registry mutation — sky-ai only reads.
* No connection-pool routing yet — that piece ships when sky-ai
  starts owning its own tenant-scoped DB connections (out of scope
  for PR #9/#10; tracked for Phase 5).

The default context preserves the legacy single-tenant behaviour:
when no header is supplied, or when ``MULTI_TENANT_ENABLED`` is False,
``current_tenant()`` returns ``DEFAULT_TENANT_CONTEXT`` and the
Bedrock provider keeps using its env-driven model IDs.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from uuid import UUID

_NIL_UUID = UUID(int=0)


@dataclass(frozen=True)
class TenantContext:
    """Per-request tenant view used by the AI service."""

    slug: str
    id: UUID
    tier: str
    display_name: str
    bedrock_inference_profile_arn: Optional[str] = None
    rate_limit_rpm: int = 60
    rate_limit_tpm: int = 50_000
    is_active: bool = True
    feature_flags: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_default(self) -> bool:
        return self.id == _NIL_UUID


DEFAULT_TENANT_CONTEXT = TenantContext(
    slug="default",
    id=_NIL_UUID,
    tier="pilot",
    display_name="Default (single-tenant mode)",
)


_current_tenant: ContextVar[TenantContext] = ContextVar(
    "skyfirst_ai_current_tenant", default=DEFAULT_TENANT_CONTEXT
)


def current_tenant() -> TenantContext:
    return _current_tenant.get()


def set_current_tenant(ctx: TenantContext):
    return _current_tenant.set(ctx)


def reset_current_tenant(token) -> None:
    _current_tenant.reset(token)


def multi_tenant_enabled() -> bool:
    """Feature flag — mirrors the backend's ``MULTI_TENANT_ENABLED``.

    Read from the same env var name so the two services flip together.
    ``"true"`` / ``"1"`` / ``"yes"`` (case-insensitive) all enable it.
    """
    value = (os.getenv("MULTI_TENANT_ENABLED") or "").strip().lower()
    return value in {"true", "1", "yes", "on"}
