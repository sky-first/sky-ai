"""Space domain logic."""
from typing import Optional, List
from uuid import UUID
from sqlalchemy.orm import Session
from db.models import Space as SpaceModel


def get_space(db: Session, space_id: UUID) -> Optional[SpaceModel]:
    """Get space by ID."""
    return db.query(SpaceModel).filter(SpaceModel.id == space_id).first()


def list_spaces(db: Session, skip: int = 0, limit: int = 100) -> List[SpaceModel]:
    """List all active spaces."""
    return (
        db.query(SpaceModel)
        .filter(SpaceModel.is_active == True)
        .offset(skip)
        .limit(limit)
        .all()
    )


def create_space(
    db: Session,
    name: str,
    description: Optional[str] = None
) -> SpaceModel:
    """Create a new space."""
    space = SpaceModel(name=name, description=description)
    db.add(space)
    db.commit()
    db.refresh(space)
    return space


def update_space(
    db: Session,
    space_id: UUID,
    name: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None
) -> Optional[SpaceModel]:
    """Update a space."""
    space = get_space(db, space_id)
    if not space:
        return None
    
    if name is not None:
        space.name = name
    if description is not None:
        space.description = description
    if is_active is not None:
        space.is_active = is_active
    
    db.commit()
    db.refresh(space)
    return space

