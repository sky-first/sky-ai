"""Planet domain logic."""

from typing import Optional, List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import Planet as PlanetModel


async def get_planet(db: AsyncSession, planet_id: UUID) -> Optional[PlanetModel]:
    """Get planet by ID."""
    result = await db.execute(select(PlanetModel).filter(PlanetModel.id == planet_id))
    return result.scalar_one_or_none()


async def list_planets(
    db: AsyncSession, space_id: Optional[UUID] = None, skip: int = 0, limit: int = 100
) -> List[PlanetModel]:
    """List planets, optionally filtered by space."""
    query = select(PlanetModel).filter(PlanetModel.is_active == True)

    if space_id:
        query = query.filter(PlanetModel.space_id == space_id)

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def create_planet(
    db: AsyncSession,
    space_id: UUID,
    name: str,
    description: Optional[str] = None,
    required_scopes: Optional[List[str]] = None,
) -> PlanetModel:
    """Create a new planet."""
    planet = PlanetModel(
        space_id=space_id,
        name=name,
        description=description,
        required_scopes=required_scopes or [],
    )
    db.add(planet)
    await db.commit()
    await db.refresh(planet)
    return planet


async def update_planet(
    db: AsyncSession,
    planet_id: UUID,
    name: Optional[str] = None,
    description: Optional[str] = None,
    required_scopes: Optional[List[str]] = None,
    is_active: Optional[bool] = None,
) -> Optional[PlanetModel]:
    """Update a planet."""
    planet = await get_planet(db, planet_id)
    if not planet:
        return None

    if name is not None:
        planet.name = name
    if description is not None:
        planet.description = description
    if required_scopes is not None:
        planet.required_scopes = required_scopes
    if is_active is not None:
        planet.is_active = is_active

    await db.commit()
    await db.refresh(planet)
    return planet
