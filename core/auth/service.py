"""Authentication and authorization service."""
from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from db.models import User, UserPermission, Crew, Space
from core.auth.models import UserContext, User as UserModel


def resolve_user_permissions(
    db: Session,
    user_id: UUID,
    space_id: Optional[UUID] = None,
    crew_id: Optional[UUID] = None
) -> List[str]:
    """
    Resolve user permissions for a given space and/or crew.
    
    Args:
        db: Database session
        user_id: User ID
        space_id: Optional space ID
        crew_id: Optional crew ID
    
    Returns:
        List of permission strings
    """
    query = db.query(UserPermission).filter(UserPermission.user_id == user_id)
    
    if crew_id:
        query = query.filter(UserPermission.crew_id == crew_id)
    elif space_id:
        # Get all crews in the space and check permissions
        crews = db.query(Crew).filter(Crew.space_id == space_id).all()
        crew_ids = [crew.id for crew in crews]
        query = query.filter(UserPermission.crew_id.in_(crew_ids))
    
    permissions = query.all()
    return [p.permission for p in permissions]


def get_user_context(
    db: Session,
    user_id: UUID,
    space_id: Optional[UUID] = None,
    crew_id: Optional[UUID] = None
) -> UserContext:
    """
    Get user context with permissions.
    
    Args:
        db: Database session
        user_id: User ID
        space_id: Optional space ID
        crew_id: Optional crew ID
    
    Returns:
        UserContext with permissions
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError(f"User {user_id} not found")
    
    permissions = resolve_user_permissions(db, user_id, space_id, crew_id)
    
    user_model = UserModel(
        id=user.id,
        email=user.email,
        name=user.name,
        is_active=user.is_active
    )
    
    return UserContext(
        user=user_model,
        space_id=space_id,
        crew_id=crew_id,
        permissions=permissions
    )


def check_access(
    user_context: UserContext,
    required_permission: str,
    space_id: Optional[UUID] = None,
    crew_id: Optional[UUID] = None
) -> bool:
    """
    Check if user has access with required permission.
    
    Args:
        user_context: User context
        required_permission: Required permission (read, write, admin)
        space_id: Optional space ID to check
        crew_id: Optional crew ID to check
    
    Returns:
        True if user has access, False otherwise
    """
    # Admin always has access
    if user_context.has_permission("admin"):
        return True
    
    # Check specific permission
    if required_permission == "read":
        return user_context.has_any_permission(["read", "write", "admin"])
    elif required_permission == "write":
        return user_context.has_any_permission(["write", "admin"])
    elif required_permission == "admin":
        return user_context.has_permission("admin")
    
    return False

