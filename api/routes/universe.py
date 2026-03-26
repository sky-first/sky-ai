# api/routes/universe.py
"""
Universe Intelligence — API Routes
Endpoints para configuração global, listagem de insights e disparo manual.
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from db.models import UniverseGlobalConfig, UniverseInsight

router = APIRouter(prefix="/universe", tags=["Universe Intelligence"])


# ================================
# Schemas (Pydantic)
# ================================

class GlobalConfigUpsertRequest(BaseModel):
    """Payload para criar ou atualizar a configuração global do Universe."""
    target_spaces: List[str] = Field(default_factory=list, description="List of Space UUIDs to investigate")
    target_crews: List[str]  = Field(default_factory=list, description="List of Crew UUIDs (empty = all crews in the selected spaces)")
    frequency_days: int      = Field(default=7, ge=1, le=90, description="Cadence in days: 1=Daily, 7=Weekly, etc.")
    output_format: str       = Field(default="text", description="Output format: 'text' | 'mix'")
    is_enabled: bool         = Field(default=True)

class GlobalConfigResponse(BaseModel):
    id: str
    target_spaces: List[str]
    target_crews: List[str]
    frequency_days: int
    output_format: str
    is_enabled: bool
    last_run_at: Optional[str] = None
    created_at: Optional[str] = None

class InsightResponse(BaseModel):
    id: str
    space_id: Optional[str]
    insight_type: str
    category: str           # insight | opportunity | risk
    title: str
    insight: str
    impact_level: str       # low | medium | high
    suggested_action: Optional[str]
    source_tables: Optional[List[str]]
    chart_data: Optional[List[dict]]
    content_hash: Optional[str]
    created_at: Optional[str]

class TriggerRequest(BaseModel):
    """Disparo manual do ciclo de descoberta."""
    space_id: str = Field(..., description="Space UUID to run discovery for")


# ================================
# Endpoints
# ================================

@router.post("/global-config", response_model=GlobalConfigResponse, summary="Create or update global config")
async def upsert_global_config(
    payload: GlobalConfigUpsertRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Creates or updates the Universe Intelligence global configuration.
    Only one active config exists in the MVP.
    """
    # Validate output_format
    if payload.output_format not in ("text", "mix"):
        raise HTTPException(status_code=400, detail="output_format must be 'text' or 'mix'")

    # Upsert: get first existing or create new
    result = await db.execute(select(UniverseGlobalConfig).limit(1))
    config = result.scalar_one_or_none()

    if config:
        config.target_spaces  = payload.target_spaces
        config.target_crews   = payload.target_crews
        config.frequency_days = payload.frequency_days
        config.output_format  = payload.output_format
        config.is_enabled     = payload.is_enabled
    else:
        config = UniverseGlobalConfig(
            target_spaces  = payload.target_spaces,
            target_crews   = payload.target_crews,
            frequency_days = payload.frequency_days,
            output_format  = payload.output_format,
            is_enabled     = payload.is_enabled,
        )
        db.add(config)

    await db.commit()
    await db.refresh(config)

    return GlobalConfigResponse(
        id             = str(config.id),
        target_spaces  = config.target_spaces or [],
        target_crews   = config.target_crews  or [],
        frequency_days = config.frequency_days,
        output_format  = config.output_format,
        is_enabled     = config.is_enabled,
        last_run_at    = config.last_run_at.isoformat() if config.last_run_at else None,
        created_at     = config.created_at.isoformat() if config.created_at else None,
    )


@router.get("/global-config", response_model=Optional[GlobalConfigResponse], summary="Get current global config")
async def get_global_config(db: AsyncSession = Depends(get_db)):
    """Returns the current Universe Intelligence global configuration."""
    result = await db.execute(select(UniverseGlobalConfig).limit(1))
    config = result.scalar_one_or_none()
    if not config:
        return None
    return GlobalConfigResponse(
        id             = str(config.id),
        target_spaces  = config.target_spaces or [],
        target_crews   = config.target_crews  or [],
        frequency_days = config.frequency_days,
        output_format  = config.output_format,
        is_enabled     = config.is_enabled,
        last_run_at    = config.last_run_at.isoformat() if config.last_run_at else None,
        created_at     = config.created_at.isoformat() if config.created_at else None,
    )


@router.get("/insights", response_model=List[InsightResponse], summary="List Universe Insights")
async def list_insights(
    space_id: Optional[str]  = Query(None, description="Filter by Space UUID"),
    category: Optional[str]  = Query(None, description="Filter: 'insight' | 'opportunity' | 'risk'"),
    insight_type: Optional[str] = Query(None, description="Filter: 'general' | 'mission'"),
    limit: int               = Query(50, ge=1, le=200),
    db: AsyncSession         = Depends(get_db),
):
    """
    Lists Universe Intelligence insights with optional filters.
    Cards in the UI should filter by category=insight, category=opportunity, category=risk.
    """
    q = select(UniverseInsight).order_by(desc(UniverseInsight.created_at))

    if space_id:
        q = q.where(UniverseInsight.space_id == UUID(space_id))
    if category:
        if category not in ("insight", "opportunity", "risk"):
            raise HTTPException(status_code=400, detail="category must be 'insight', 'opportunity', or 'risk'")
        q = q.where(UniverseInsight.category == category)
    if insight_type:
        q = q.where(UniverseInsight.insight_type == insight_type)

    q = q.limit(limit)
    result = await db.execute(q)
    rows = result.scalars().all()

    return [
        InsightResponse(
            id               = str(r.id),
            space_id         = str(r.space_id) if r.space_id else None,
            insight_type     = r.insight_type,
            category         = r.category or "insight",
            title            = r.title,
            insight          = r.insight,
            impact_level     = r.impact_level,
            suggested_action = r.suggested_action,
            source_tables    = r.source_tables,
            chart_data       = r.chart_data,
            content_hash     = r.content_hash,
            created_at       = r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]


@router.post("/trigger", summary="Manually trigger Universe discovery cycle")
async def trigger_discovery(
    payload: TriggerRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Manually triggers a Universe Intelligence discovery cycle for a given Space.
    Runs asynchronously in background — returns immediately with job status.
    """
    # Lazy import to avoid circular deps
    from core.agents.universe.trigger import run_discovery_background

    config_result = await db.execute(select(UniverseGlobalConfig).limit(1))
    config = config_result.scalar_one_or_none()
    output_format = config.output_format if config else "text"

    background_tasks.add_task(
        run_discovery_background,
        space_id      = payload.space_id,
        output_format = output_format,
    )

    return {
        "status": "triggered",
        "space_id": payload.space_id,
        "output_format": output_format,
    }
