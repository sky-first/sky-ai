"""Planets routes."""
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from db.session import get_db
from api.schemas import PlanetCreate, PlanetUpdate, PlanetResponse
from api.dependencies import get_current_user
from core.auth.models import UserContext
from core.domain.planets import get_planet, list_planets, create_planet, update_planet

router = APIRouter(prefix="/planets", tags=["planets"])


@router.get("", response_model=List[PlanetResponse])
async def list_planets_endpoint(
    space_id: Optional[UUID] = Query(None),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    user_context: UserContext = Depends(get_current_user)
):
    """List planets, optionally filtered by space."""
    planets = list_planets(db, space_id=space_id, skip=skip, limit=limit)
    return planets


@router.get("/{planet_id}", response_model=PlanetResponse)
async def get_planet_endpoint(
    planet_id: UUID,
    db: Session = Depends(get_db),
    user_context: UserContext = Depends(get_current_user)
):
    """Get a planet by ID."""
    planet = get_planet(db, planet_id)
    if not planet:
        raise HTTPException(status_code=404, detail="Planet not found")
    return planet


@router.post("", response_model=PlanetResponse, status_code=201)
async def create_planet_endpoint(
    planet_data: PlanetCreate,
    db: Session = Depends(get_db),
    user_context: UserContext = Depends(get_current_user)
):
    """Create a new planet."""
    # Check write permission
    if not user_context.has_any_permission(["write", "admin"]):
        raise HTTPException(status_code=403, detail="Write permission required")
    
    planet = create_planet(
        db,
        space_id=planet_data.space_id,
        name=planet_data.name,
        description=planet_data.description,
        required_scopes=planet_data.required_scopes
    )
    return planet


@router.patch("/{planet_id}", response_model=PlanetResponse)
async def update_planet_endpoint(
    planet_id: UUID,
    planet_data: PlanetUpdate,
    db: Session = Depends(get_db),
    user_context: UserContext = Depends(get_current_user)
):
    """Update a planet."""
    # Check write permission
    if not user_context.has_any_permission(["write", "admin"]):
        raise HTTPException(status_code=403, detail="Write permission required")
    
    planet = update_planet(
        db,
        planet_id,
        name=planet_data.name,
        description=planet_data.description,
        required_scopes=planet_data.required_scopes,
        is_active=planet_data.is_active
    )
    if not planet:
        raise HTTPException(status_code=404, detail="Planet not found")
    return planet

