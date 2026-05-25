"""Space domain logic."""

from typing import Optional, List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import Space as SpaceModel


async def get_space(db: AsyncSession, space_id: UUID) -> Optional[SpaceModel]:
    """Get space by ID."""
    result = await db.execute(select(SpaceModel).filter(SpaceModel.id == space_id))
    return result.scalar_one_or_none()


async def list_spaces(
    db: AsyncSession, skip: int = 0, limit: int = 100
) -> List[SpaceModel]:
    """List all active spaces."""
    result = await db.execute(
        select(SpaceModel)
        .filter(SpaceModel.is_active == True)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def create_space(
    db: AsyncSession, name: str, description: Optional[str] = None
) -> SpaceModel:
    """Create a new space."""
    space = SpaceModel(name=name, description=description)
    db.add(space)
    await db.commit()
    await db.refresh(space)
    return space


async def update_space(
    db: AsyncSession,
    space_id: UUID,
    name: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Optional[SpaceModel]:
    """Update a space."""
    space = await get_space(db, space_id)
    if not space:
        return None

    if name is not None:
        space.name = name
    if description is not None:
        space.description = description
    if is_active is not None:
        space.is_active = is_active

    await db.commit()
    await db.refresh(space)
    return space
