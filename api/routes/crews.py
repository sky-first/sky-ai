"""Crews routes."""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from db.session import get_db
from api.schemas import CrewCreate, CrewUpdate, CrewResponse
from api.dependencies import get_current_user
from core.auth.models import UserContext
from core.domain.crews import get_crew, list_crews, create_crew, update_crew

router = APIRouter(prefix="/crews", tags=["crews"])


@router.get("", response_model=List[CrewResponse])
async def list_crews_endpoint(
    space_id: Optional[UUID] = Query(None),
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    user_context: UserContext = Depends(get_current_user),
):
    """List crews, optionally filtered by space."""
    crews = await list_crews(db, space_id=space_id, skip=skip, limit=limit)
    return crews


@router.get("/{crew_id}", response_model=CrewResponse)
async def get_crew_endpoint(
    crew_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_context: UserContext = Depends(get_current_user),
):
    """Get a crew by ID."""
    crew = await get_crew(db, crew_id)
    if not crew:
        raise HTTPException(status_code=404, detail="Crew not found")
    return crew


@router.post("", response_model=CrewResponse, status_code=201)
async def create_crew_endpoint(
    crew_data: CrewCreate,
    db: AsyncSession = Depends(get_db),
    user_context: UserContext = Depends(get_current_user),
):
    """Create a new crew."""
    # Check write permission
    if not user_context.has_any_permission(["write", "admin"]):
        raise HTTPException(status_code=403, detail="Write permission required")

    crew = await create_crew(
        db,
        space_id=crew_data.space_id,
        name=crew_data.name,
        description=crew_data.description,
    )
    return crew


@router.patch("/{crew_id}", response_model=CrewResponse)
async def update_crew_endpoint(
    crew_id: UUID,
    crew_data: CrewUpdate,
    db: AsyncSession = Depends(get_db),
    user_context: UserContext = Depends(get_current_user),
):
    """Update a crew."""
    # Check write permission
    if not user_context.has_any_permission(["write", "admin"]):
        raise HTTPException(status_code=403, detail="Write permission required")

    crew = await update_crew(
        db,
        crew_id,
        name=crew_data.name,
        description=crew_data.description,
        is_active=crew_data.is_active,
    )
    if not crew:
        raise HTTPException(status_code=404, detail="Crew not found")
    return crew
