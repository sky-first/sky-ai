"""Crew domain logic."""

from typing import Optional, List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import Crew as CrewModel


async def get_crew(db: AsyncSession, crew_id: UUID) -> Optional[CrewModel]:
    """Get crew by ID."""
    result = await db.execute(select(CrewModel).filter(CrewModel.id == crew_id))
    return result.scalar_one_or_none()


async def list_crews(
    db: AsyncSession, space_id: Optional[UUID] = None, skip: int = 0, limit: int = 100
) -> List[CrewModel]:
    """List crews, optionally filtered by space."""
    query = select(CrewModel).filter(CrewModel.is_active == True)

    if space_id:
        query = query.filter(CrewModel.space_id == space_id)

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def create_crew(
    db: AsyncSession, space_id: UUID, name: str, description: Optional[str] = None
) -> CrewModel:
    """Create a new crew."""
    crew = CrewModel(space_id=space_id, name=name, description=description)
    db.add(crew)
    await db.commit()
    await db.refresh(crew)
    return crew


async def update_crew(
    db: AsyncSession,
    crew_id: UUID,
    name: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Optional[CrewModel]:
    """Update a crew."""
    crew = await get_crew(db, crew_id)
    if not crew:
        return None

    if name is not None:
        crew.name = name
    if description is not None:
        crew.description = description
    if is_active is not None:
        crew.is_active = is_active

    await db.commit()
    await db.refresh(crew)
    return crew
