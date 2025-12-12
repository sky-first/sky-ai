"""Crew domain logic."""
from typing import Optional, List
from uuid import UUID
from sqlalchemy.orm import Session
from db.models import Crew as CrewModel


def get_crew(db: Session, crew_id: UUID) -> Optional[CrewModel]:
    """Get crew by ID."""
    return db.query(CrewModel).filter(CrewModel.id == crew_id).first()


def list_crews(
    db: Session,
    space_id: Optional[UUID] = None,
    skip: int = 0,
    limit: int = 100
) -> List[CrewModel]:
    """List crews, optionally filtered by space."""
    query = db.query(CrewModel).filter(CrewModel.is_active == True)
    
    if space_id:
        query = query.filter(CrewModel.space_id == space_id)
    
    return query.offset(skip).limit(limit).all()


def create_crew(
    db: Session,
    space_id: UUID,
    name: str,
    description: Optional[str] = None
) -> CrewModel:
    """Create a new crew."""
    crew = CrewModel(space_id=space_id, name=name, description=description)
    db.add(crew)
    db.commit()
    db.refresh(crew)
    return crew


def update_crew(
    db: Session,
    crew_id: UUID,
    name: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None
) -> Optional[CrewModel]:
    """Update a crew."""
    crew = get_crew(db, crew_id)
    if not crew:
        return None
    
    if name is not None:
        crew.name = name
    if description is not None:
        crew.description = description
    if is_active is not None:
        crew.is_active = is_active
    
    db.commit()
    db.refresh(crew)
    return crew

