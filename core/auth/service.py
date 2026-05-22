"""Authentication and authorization service."""

from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select

from db.models import User
from core.auth.models import UserContext, User as UserModel


async def resolve_user_permissions(
    db: AsyncSession,
    user_id: UUID,
    space_id: Optional[UUID] = None,
    crew_id: Optional[UUID] = None,
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
    # NOTE:
    # The product DB schema does NOT necessarily contain `user_permissions` in the AI Engine context.
    # We keep this function for compatibility, but resolve permissions in a best-effort way
    # without relying on legacy tables/columns.
    try:
        # If a crew_id is provided, check membership in crew_members as a proxy for "read".
        if crew_id:
            result = await db.execute(
                text("""
                    SELECT 1
                    FROM crew_members
                    WHERE user_id = :user_id
                      AND crew_id = :crew_id
                    LIMIT 1
                    """),
                {"user_id": str(user_id), "crew_id": str(crew_id)},
            )
            row = result.first()
            return ["read"] if row else []

        # If a space_id is provided, check membership in any crew within that space.
        if space_id:
            result = await db.execute(
                text("""
                    SELECT 1
                    FROM crew_members cm
                    JOIN crews c ON c.id = cm.crew_id
                    WHERE cm.user_id = :user_id
                      AND c.space_id = :space_id
                      AND c.deleted_at IS NULL
                    LIMIT 1
                    """),
                {"user_id": str(user_id), "space_id": str(space_id)},
            )
            row = result.first()
            return ["read"] if row else []

        # No scope provided; return empty.
        return []
    except Exception:
        return []


async def get_user_context(
    db: AsyncSession,
    user_id: UUID,
    space_id: Optional[UUID] = None,
    crew_id: Optional[UUID] = None,
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
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError(f"User {user_id} not found")

    permissions = await resolve_user_permissions(db, user_id, space_id, crew_id)

    # Our DB schema uses soft-delete instead of `is_active`.
    # Treat active as "not deleted".
    is_active = getattr(user, "is_active", None)
    if is_active is None:
        is_active = getattr(user, "deleted_at", None) is None

    user_model = UserModel(
        id=user.id,
        email=user.email,
        name=user.name,
        is_active=bool(is_active),
    )

    return UserContext(
        user=user_model, space_id=space_id, crew_id=crew_id, permissions=permissions
    )


async def get_user_crew_ids_in_space(
    db: AsyncSession, user_id: UUID, space_id: UUID
) -> List[str]:
    """
    Get crew IDs where user has permissions in a specific space.

    Args:
        db: Database session
        user_id: User ID
        space_id: Space ID

    Returns:
        List[str]: List of crew IDs as strings
    """
    # Prefer membership-based access (crew_members) which exists in the current schema.
    result = await db.execute(
        text("""
            SELECT DISTINCT cm.crew_id
            FROM crew_members cm
            JOIN crews c ON c.id = cm.crew_id
            WHERE cm.user_id = :user_id
              AND c.space_id = :space_id
              AND c.deleted_at IS NULL
            """),
        {"user_id": str(user_id), "space_id": str(space_id)},
    )
    rows = result.fetchall()
    return [str(row[0]) for row in rows]


async def get_user_all_crew_ids(db: AsyncSession, user_id: UUID) -> List[str]:
    """
    Get all crew IDs where user has permissions across all spaces (personal mode).

    Args:
        db: Database session
        user_id: User ID

    Returns:
        List[str]: List of all crew IDs as strings where user has permissions
    """
    # Prefer membership-based access (crew_members) which exists in the current schema.
    result = await db.execute(
        text("""
            SELECT DISTINCT cm.crew_id
            FROM crew_members cm
            JOIN crews c ON c.id = cm.crew_id
            WHERE cm.user_id = :user_id
              AND c.deleted_at IS NULL
            """),
        {"user_id": str(user_id)},
    )
    rows = result.fetchall()
    return [str(row[0]) for row in rows]


async def resolve_crew_ids_for_context(
    db: AsyncSession,
    user_id: UUID,
    space_id: Optional[UUID],
    request_crew_ids: Optional[List[str]],
    is_personal: bool,
) -> List[str]:
    """
    Resolve crew_ids based on context (personal vs collaborative).

    Args:
        db: Database session
        user_id: User ID
        space_id: Optional space ID (for collaborative mode)
        request_crew_ids: Optional list of crew_ids from request
        is_personal: True if personal mode (all user's crews), False if collaborative (specific crew)

    Returns:
        List[str]: List of crew IDs as strings
    """
    # Se crew_ids foram fornecidos explicitamente, usar eles
    if request_crew_ids:
        return request_crew_ids

    # Modo personal: retornar todos os crew_ids do usuário em todos os spaces
    if is_personal:
        return await get_user_all_crew_ids(db, user_id)

    # Modo collaborative: retornar apenas crew_ids do space específico
    if space_id:
        return await get_user_crew_ids_in_space(db, user_id, space_id)

    # Fallback: lista vazia (apenas dados públicos)
    return []


def check_access(
    user_context: UserContext,
    required_permission: str,
    space_id: Optional[UUID] = None,
    crew_id: Optional[UUID] = None,
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
