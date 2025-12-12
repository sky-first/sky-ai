"""API dependencies for FastAPI."""
from typing import Optional
from uuid import UUID
from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session
from db.session import get_db
from core.auth.service import get_user_context, check_access
from core.auth.models import UserContext
from core.domain.spaces import get_space
from core.domain.crews import get_crew
from core.agents.factory import AgentConfig


# Placeholder for authentication - replace with actual JWT/OAuth implementation
async def get_current_user(
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    db: Session = Depends(get_db)
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
    
    return get_user_context(db, user_id)


async def get_space_dependency(
    space_id: UUID,
    user_context: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Resolve space and check access."""
    space = get_space(db, space_id)
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    
    # Check access
    if not check_access(user_context, "read", space_id=space_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    return space


async def get_crew_dependency(
    crew_id: UUID,
    user_context: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Resolve crew and check access."""
    crew = get_crew(db, crew_id)
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
    db: Session = Depends(get_db)
) -> Optional[AgentConfig]:
    """
    Get agent configuration based on space/crew context.
    
    This is a placeholder - implement actual agent config resolution.
    """
    # TODO: Implement agent config resolution from agent_registry
    return None

