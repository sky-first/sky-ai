"""Celery application configuration."""

from celery import Celery
from celery.schedules import crontab
from config.settings import settings

celery_app = Celery(
    "ia_poc_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes
    task_soft_time_limit=240,  # 4 minutes
)

# Beat schedule — dispatcher checks for due scans every 15 minutes.
# Actual per-space frequency is controlled by scan_schedule.interval_hours (item 24).
celery_app.conf.beat_schedule = {
    "proactive-scan-dispatcher": {
        "task": "scan.dispatch_scheduled_scans",
        "schedule": crontab(minute="*/15"),
    },
}

# Register scan tasks so Beat can find them
celery_app.autodiscover_tasks(["worker"])
