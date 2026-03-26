# core/agents/universe/tasks.py
"""
Celery tasks for Universe Intelligence automation.
Contains the scheduler tick that enforces cadence.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from celery import shared_task
from sqlalchemy import select, or_

from db.base import SyncSessionLocal
from db.models import UniverseGlobalConfig
from core.agents.universe.trigger import run_discovery_background

logger = logging.getLogger(__name__)

@shared_task(name="universe.scheduler_tick")
def universe_scheduler_tick():
    """
    Check all active Universe configurations and trigger discovery if cadence reached.
    Should be called by Celery Beat (e.g., every hour).
    """
    db = SyncSessionLocal()
    try:
        # 1. Global Discovery Scheduler
        configs = db.query(UniverseGlobalConfig).filter(UniverseGlobalConfig.is_enabled == True).all()
        
        for config in configs:
            # Check if it's time to run
            # If last_run_at is None, run now.
            is_time = False
            if not config.last_run_at:
                is_time = True
            else:
                next_run = config.last_run_at + timedelta(days=config.frequency_days)
                if datetime.utcnow() >= next_run:
                    is_time = True
            
            if is_time:
                logger.info(f"[Universe Scheduler] Triggering Global Discovery for spaces: {config.target_spaces}")
                for space_id in config.target_spaces:
                    # We call the background function directly since we're already in a worker context
                    # or we could delay it as a separate task. For now, sequential per config.
                    import asyncio
                    asyncio.run(run_discovery_background(
                        space_id=space_id,
                        output_format=config.output_format,
                    ))
                
                # Update last_run_at
                config.last_run_at = datetime.utcnow()
                db.commit()

    except Exception as e:
        logger.error(f"[Universe Scheduler] Error during tick: {e}")
        db.rollback()
    finally:
        db.close()
