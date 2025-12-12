"""Planet domain logic."""
from typing import Optional, List
from uuid import UUID
from sqlalchemy.orm import Session
from db.models import Planet as PlanetModel


def get_planet(db: Session, planet_id: UUID) -> Optional[PlanetModel]:
    """Get planet by ID."""
    return db.query(PlanetModel).filter(PlanetModel.id == planet_id).first()


def list_planets(
    db: Session,
    space_id: Optional[UUID] = None,
    skip: int = 0,
    limit: int = 100
) -> List[PlanetModel]:
    """List planets, optionally filtered by space."""
    query = db.query(PlanetModel).filter(PlanetModel.is_active == True)
    
    if space_id:
        query = query.filter(PlanetModel.space_id == space_id)
    
    return query.offset(skip).limit(limit).all()


def create_planet(
    db: Session,
    space_id: UUID,
    name: str,
    description: Optional[str] = None,
    required_scopes: Optional[List[str]] = None
) -> PlanetModel:
    """Create a new planet."""
    planet = PlanetModel(
        space_id=space_id,
        name=name,
        description=description,
        required_scopes=required_scopes or []
    )
    db.add(planet)
    db.commit()
    db.refresh(planet)
    return planet


def update_planet(
    db: Session,
    planet_id: UUID,
    name: Optional[str] = None,
    description: Optional[str] = None,
    required_scopes: Optional[List[str]] = None,
    is_active: Optional[bool] = None
) -> Optional[PlanetModel]:
    """Update a planet."""
    planet = get_planet(db, planet_id)
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
    
    db.commit()
    db.refresh(planet)
    return planet

