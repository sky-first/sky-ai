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
    """User context with permissions."""
    user: User
    space_id: Optional[UUID] = None
    crew_id: Optional[UUID] = None
    permissions: List[str] = []  # List of permission strings (e.g., ["read", "write"])
    
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

