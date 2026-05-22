"""Scan schedule configuration endpoints — item 24.

PUT /spaces/{space_id}/scan-schedule  — configure scan frequency
GET /spaces/{space_id}/scan-schedule  — read current config
DELETE /spaces/{space_id}/scan-schedule  — disable scheduled scans
POST /spaces/{space_id}/scan-schedule/trigger  — manual one-off trigger
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db

router = APIRouter(prefix="/spaces", tags=["Scan Schedule"])
logger = logging.getLogger(__name__)


class ScanScheduleRequest(BaseModel):
    interval_hours: int = Field(
        ...,
        description="Scan frequency in hours. Allowed values: 1, 6, 12, 24.",
        ge=1,
        le=24,
    )
    enabled: bool = Field(default=True)


class ScanScheduleResponse(BaseModel):
    space_id: str
    interval_hours: Optional[int] = None
    enabled: bool = False
    last_scan_at: Optional[str] = None
    configured: bool = False


@router.put("/{space_id}/scan-schedule", response_model=ScanScheduleResponse)
async def set_scan_schedule(
    space_id: str,
    body: ScanScheduleRequest,
    db: AsyncSession = Depends(get_db),
) -> ScanScheduleResponse:
    """Configure how often the proactive scan agent runs for a space."""
    from core.agents.scan_schedule import set_scan_schedule as _set, get_scan_schedule

    try:
        await _set(
            db, space_id, interval_hours=body.interval_hours, enabled=body.enabled
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    config = await get_scan_schedule(db, space_id) or {}
    return ScanScheduleResponse(
        space_id=space_id,
        interval_hours=config.get("interval_hours"),
        enabled=config.get("enabled", False),
        last_scan_at=config.get("last_scan_at"),
        configured=True,
    )


@router.get("/{space_id}/scan-schedule", response_model=ScanScheduleResponse)
async def get_scan_schedule_route(
    space_id: str,
    db: AsyncSession = Depends(get_db),
) -> ScanScheduleResponse:
    """Return the current scan schedule config for a space."""
    from core.agents.scan_schedule import get_scan_schedule

    config = await get_scan_schedule(db, space_id)
    if not config:
        return ScanScheduleResponse(space_id=space_id, configured=False)

    return ScanScheduleResponse(
        space_id=space_id,
        interval_hours=config.get("interval_hours"),
        enabled=config.get("enabled", False),
        last_scan_at=config.get("last_scan_at"),
        configured=True,
    )


@router.delete("/{space_id}/scan-schedule", status_code=204, response_class=Response)
async def disable_scan_schedule(
    space_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Disable scheduled scans for a space (keeps config, sets enabled=False)."""
    from core.agents.scan_schedule import get_scan_schedule, set_scan_schedule as _set

    config = await get_scan_schedule(db, space_id)
    if not config:
        return Response(status_code=204)

    try:
        await _set(
            db,
            space_id,
            interval_hours=config.get("interval_hours", 24),
            enabled=False,
        )
    except ValueError:
        pass  # existing config has valid interval — this won't fail
    return Response(status_code=204)


@router.post("/{space_id}/scan-schedule/trigger", status_code=202)
async def trigger_scan_now(
    space_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually trigger an immediate scan for a space (one-off, ignores schedule)."""
    from core.agents.scan_schedule import get_spaces_due_for_scan
    from sqlalchemy import text

    # Get any active connection for the space
    try:
        result = await db.execute(
            text(
                "SELECT connection_id FROM space_connections WHERE space_id = CAST(:sid AS uuid) LIMIT 1"
            ),
            {"sid": space_id},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(
                status_code=404, detail="No connections found for this space"
            )
        connection_id = str(row[0])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load connections: {exc}"
        )

    try:
        from worker.scan_tasks import run_scan_for_space

        task = run_scan_for_space.delay(space_id=space_id, connection_id=connection_id)
        return {
            "queued": True,
            "task_id": task.id,
            "space_id": space_id,
            "connection_id": connection_id,
        }
    except Exception as exc:
        logger.error(
            "trigger_scan_now: failed to enqueue for space %s: %s", space_id, exc
        )
        raise HTTPException(status_code=500, detail=f"Failed to enqueue scan: {exc}")


# ─── Item 32: OKR suggestions endpoint ───────────────────────────────────────


@router.get("/{space_id}/okr-suggestions")
async def get_okr_suggestions(
    space_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return LLM-generated OKR suggestions for a space whose brain is empty.

    Suggestions are generated and persisted during /discover when no brain
    documents exist. This endpoint retrieves the stored suggestions.

    Returns {"space_id": ..., "suggestions": [...], "brain_is_empty": bool}
    """
    from core.agents.strategic_onboarding import is_brain_empty, load_okr_suggestions

    brain_empty = await is_brain_empty(db, space_id)
    suggestions = await load_okr_suggestions(db, space_id)

    return {
        "space_id": space_id,
        "brain_is_empty": brain_empty,
        "suggestions": suggestions,
    }


# ─── Item 35: Dataset coverage dashboard ──────────────────────────────────────


@router.get("/{space_id}/dataset-coverage")
async def get_dataset_coverage(
    space_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return per-dataset scan coverage stats for the given space.

    Aggregates data from three sources in the embeddings table:
      - scan_insight records → last_queried_at, times_queried per table
      - depth_tracker records → combos_explored per table
      - row_count_snapshot records → latest row count per table

    Response:
      {
        "space_id": "...",
        "total_datasets": N,
        "coverage": [
          {
            "logical_name": "orders",
            "last_queried_at": "2024-01-01T00:00:00+00:00" | null,
            "times_queried": 3,
            "combos_explored": 5,
            "latest_row_count": 12000 | null,
            "depth_remaining_pct": 75   // 100=pristine, 0=saturated
          }, ...
        ]
      }
    Results are ordered by recency (most recently queried first),
    then alphabetically for datasets never queried.
    """
    from core.agents.coverage_report import build_coverage_report

    coverage = await build_coverage_report(db, space_id)

    return {
        "space_id": space_id,
        "total_datasets": len(coverage),
        "coverage": coverage,
    }
