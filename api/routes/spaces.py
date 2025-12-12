"""Spaces routes."""
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db.session import get_db
from api.schemas import SpaceCreate, SpaceUpdate, SpaceResponse
from api.dependencies import get_current_user
from core.auth.models import UserContext
from core.domain.spaces import get_space, list_spaces, create_space, update_space

router = APIRouter(prefix="/spaces", tags=["spaces"])


@router.get("", response_model=List[SpaceResponse])
async def list_spaces_endpoint(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    user_context: UserContext = Depends(get_current_user)
):
    """List all spaces."""
    spaces = list_spaces(db, skip=skip, limit=limit)
    return spaces


@router.get("/{space_id}", response_model=SpaceResponse)
async def get_space_endpoint(
    space_id: UUID,
    db: Session = Depends(get_db),
    user_context: UserContext = Depends(get_current_user)
):
    """Get a space by ID."""
    space = get_space(db, space_id)
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    return space


@router.post("", response_model=SpaceResponse, status_code=201)
async def create_space_endpoint(
    space_data: SpaceCreate,
    db: Session = Depends(get_db),
    user_context: UserContext = Depends(get_current_user)
):
    """Create a new space."""
    # Check admin permission
    if not user_context.has_permission("admin"):
        raise HTTPException(status_code=403, detail="Admin permission required")
    
    space = create_space(db, name=space_data.name, description=space_data.description)
    return space


@router.patch("/{space_id}", response_model=SpaceResponse)
async def update_space_endpoint(
    space_id: UUID,
    space_data: SpaceUpdate,
    db: Session = Depends(get_db),
    user_context: UserContext = Depends(get_current_user)
):
    """Update a space."""
    # Check admin permission
    if not user_context.has_permission("admin"):
        raise HTTPException(status_code=403, detail="Admin permission required")
    
    space = update_space(
        db,
        space_id,
        name=space_data.name,
        description=space_data.description,
        is_active=space_data.is_active
    )
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    return space

