"""API dependencies for FastAPI."""

from typing import Optional
from uuid import UUID
from fastapi import Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from db.session import get_db
from core.auth.service import get_user_context, check_access
from core.auth.models import UserContext
from core.domain.spaces import get_space
from core.domain.crews import get_crew
from core.agents.factory import AgentConfig
from core.tenant_context import (
    DEFAULT_TENANT_CONTEXT,
    TenantContext,
    multi_tenant_enabled,
    set_current_tenant,
)
from core.tenant_registry_lookup import lookup_tenant_by_slug


async def get_tenant_context(
    x_tenant_slug: Optional[str] = Header(None, alias="X-Tenant-Slug"),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    """Resolve the tenant for the current request (Projeto A — PR #9).

    The backend forwards the resolved slug to sky-ai via the
    ``X-Tenant-Slug`` header. When the header is missing or the
    multi-tenant flag is off, the default context is returned and
    nothing else in the pipeline changes.

    Side-effect: also sets the contextvar so downstream non-FastAPI
    code (LangGraph nodes, async tasks spawned from the handler) can
    read ``current_tenant()`` without needing the FastAPI dependency
    re-injected.
    """
    if not multi_tenant_enabled() or not x_tenant_slug:
        set_current_tenant(DEFAULT_TENANT_CONTEXT)
        return DEFAULT_TENANT_CONTEXT

    ctx = await lookup_tenant_by_slug(db, x_tenant_slug.strip().lower())
    if ctx is None:
        # Spec: when the flag is ON and a slug was supplied but does
        # not resolve, return 404 — matches backend resolver behaviour.
        raise HTTPException(status_code=404, detail="Tenant not found")

    set_current_tenant(ctx)
    return ctx


# Placeholder for authentication - replace with actual JWT/OAuth implementation
async def get_current_user(
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    db: AsyncSession = Depends(get_db),
) -> UserContext:
    """
    Get current user context from headers.

    In production, this should validate JWT tokens or OAuth credentials.
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="User ID required")

    try:
        user_id = UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    return await get_user_context(db, user_id)


async def get_space_dependency(
    space_id: UUID,
    user_context: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resolve space and check access."""
    space = await get_space(db, space_id)
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    # Check access
    if not check_access(user_context, "read", space_id=space_id):
        raise HTTPException(status_code=403, detail="Access denied")

    return space


async def get_crew_dependency(
    crew_id: UUID,
    user_context: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resolve crew and check access."""
    crew = await get_crew(db, crew_id)
    if not crew:
        raise HTTPException(status_code=404, detail="Crew not found")

    # Check access
    if not check_access(user_context, "read", crew_id=crew_id):
        raise HTTPException(status_code=403, detail="Access denied")

    return crew


async def get_agent_config(
    space_id: Optional[UUID] = None,
    crew_id: Optional[UUID] = None,
    user_context: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Optional[AgentConfig]:
    """
    Get agent configuration based on space/crew context.

    This is a placeholder - implement actual agent config resolution.
    """
    # TODO: Implement agent config resolution from agent_registry
    return None
