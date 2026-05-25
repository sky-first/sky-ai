"""Authentication and authorization models."""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from uuid import UUID


class User(BaseModel):
    """User model for authentication."""

    id: UUID
    email: str
    name: str
    is_active: bool


class UserContext(BaseModel):
    """User context with permissions and roles for AI injection.

    This schema is used to inject user context into LangGraph nodes,
    enabling personalized responses and security rules.

    Attributes:
        user: Core user information (id, email, name, is_active)
        space_id: Current space context (equivalent to department)
        crew_id: Current crew context (equivalent to sub-department)
        crew_ids: All crews the user belongs to
        platform_role: Platform-level role (admin | user | viewer)
        crew_role: Crew-level role (commander | navigator | explorer | guest)
        permissions: List of permission strings
        locale: User locale for response language (fixed to "en" for now)
    """

    user: User
    space_id: Optional[UUID] = None
    crew_id: Optional[UUID] = None
    crew_ids: List[UUID] = []  # All crews the user belongs to

    # Roles
    platform_role: str = "user"  # admin | user | viewer
    crew_role: str = "guest"  # commander | navigator | explorer | guest

    # Permissions
    permissions: List[str] = []  # List of permission strings (e.g., ["read", "write"])

    # Locale
    locale: str = "en"  # Fixed to English for now

    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific permission."""
        return permission in self.permissions

    def has_any_permission(self, permissions: List[str]) -> bool:
        """Check if user has any of the specified permissions."""
        return any(p in self.permissions for p in permissions)

    def has_all_permissions(self, permissions: List[str]) -> bool:
        """Check if user has all of the specified permissions."""
        return all(p in self.permissions for p in permissions)


class UserPermissions(BaseModel):
    """User permissions model."""

    user_id: UUID
    crew_id: UUID
    permission: str  # read, write, admin
    metadata: Optional[Dict[str, Any]] = None
