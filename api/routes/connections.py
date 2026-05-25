"""Connections routes."""

from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.session import get_db
from api.schemas import ConnectionCreate, ConnectionResponse
from api.dependencies import get_current_user
from core.auth.models import UserContext
from db.models import DataConnection

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("", response_model=List[ConnectionResponse])
async def list_connections(
    space_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_context: UserContext = Depends(get_current_user),
):
    """List connections for a space."""
    result = await db.execute(
        select(DataConnection)
        .filter(DataConnection.space_id == space_id)
        .filter(DataConnection.is_active == True)
    )
    connections = list(result.scalars().all())
    return connections


@router.get("/{connection_id}", response_model=ConnectionResponse)
async def get_connection(
    connection_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_context: UserContext = Depends(get_current_user),
):
    """Get a connection by ID."""
    result = await db.execute(
        select(DataConnection).filter(DataConnection.id == connection_id)
    )
    connection = result.scalar_one_or_none()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


@router.post("", response_model=ConnectionResponse, status_code=201)
async def create_connection(
    connection_data: ConnectionCreate,
    db: AsyncSession = Depends(get_db),
    user_context: UserContext = Depends(get_current_user),
):
    """Create a new data connection."""
    # Check write permission
    if not user_context.has_any_permission(["write", "admin"]):
        raise HTTPException(status_code=403, detail="Write permission required")

    connection = DataConnection(
        space_id=connection_data.space_id,
        name=connection_data.name,
        connection_type=connection_data.connection_type,
        config=connection_data.config,
    )
    db.add(connection)
    await db.commit()
    await db.refresh(connection)
    return connection
