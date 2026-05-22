"""Celery tasks for the proactive scan agent — items 23-24.

Two tasks:
  dispatch_scheduled_scans  — Beat task, runs every 15 min, finds due spaces
  run_scan_for_space        — Worker task, calls the AI /query endpoint for one space
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from worker.celery_app import celery_app

logger = logging.getLogger(__name__)

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ─── Dispatcher (Beat entry point, item 23) ───────────────────────────────────


@celery_app.task(name="scan.dispatch_scheduled_scans", bind=True, max_retries=0)
def dispatch_scheduled_scans(self) -> Dict[str, Any]:
    """Periodic Beat task — finds all spaces due for a scan and enqueues them.

    Runs every 15 minutes. Actual scan frequency per space is controlled
    by scan_schedule.interval_hours (item 24).
    """

    async def _dispatch():
        from db.session import AsyncSessionLocal
        from core.agents.scan_schedule import get_spaces_due_for_scan

        async with AsyncSessionLocal() as db:
            due = await get_spaces_due_for_scan(db)

        if not due:
            logger.debug("dispatch_scheduled_scans: no spaces due")
            return {"dispatched": 0}

        dispatched = 0
        for entry in due:
            try:
                run_scan_for_space.delay(
                    space_id=entry["space_id"],
                    connection_id=entry["connection_id"],
                )
                dispatched += 1
                logger.info(
                    "dispatch_scheduled_scans: enqueued scan for space %s (conn %s)",
                    entry["space_id"],
                    entry["connection_id"],
                )
            except Exception as exc:
                logger.warning(
                    "dispatch_scheduled_scans: failed to enqueue space %s: %s",
                    entry["space_id"],
                    exc,
                )

        return {"dispatched": dispatched, "spaces": [e["space_id"] for e in due]}

    return _run_async(_dispatch())


# ─── Per-space scan runner (item 23) ─────────────────────────────────────────


@celery_app.task(
    name="scan.run_scan_for_space",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    time_limit=600,
    soft_time_limit=540,
)
def run_scan_for_space(self, space_id: str, connection_id: str) -> Dict[str, Any]:
    """Run one proactive scan for a space via internal HTTP POST to /query.

    Uses the AI service's own endpoint so the full scorer + briefing + agent
    pipeline runs without duplicating logic. Marks last_scan_at on success.
    """

    async def _run():
        import httpx
        from config.settings import settings
        from db.session import AsyncSessionLocal
        from core.agents.scan_schedule import update_last_scan_at
        from core.clients.backend_client import _generate_service_token

        url = f"{settings.ai_service_url}/connections/{connection_id}/query"
        token = _generate_service_token()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        payload = {
            "question": "Scan for insights",
            "space_id": space_id,
            "agent_mode": "scan",
            "connection_ids": [connection_id],
            "response_format": "text",
        }

        try:
            async with httpx.AsyncClient(timeout=540) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                result = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "run_scan_for_space: HTTP %s for space %s: %s",
                exc.response.status_code,
                space_id,
                exc.response.text[:300],
            )
            raise self.retry(exc=exc)
        except Exception as exc:
            logger.error(
                "run_scan_for_space: request failed for space %s: %s", space_id, exc
            )
            raise self.retry(exc=exc)

        # Mark the scan as done regardless of whether an insight was generated
        async with AsyncSessionLocal() as db:
            await update_last_scan_at(db, space_id)
            await db.commit()

        logger.info(
            "run_scan_for_space: completed for space %s — silent=%s",
            space_id,
            result.get("scan_silent", True),
        )
        return {
            "space_id": space_id,
            "connection_id": connection_id,
            "silent": result.get("scan_silent", True),
            "insight_title": result.get("scan_insight_title"),
        }

    return _run_async(_run())
