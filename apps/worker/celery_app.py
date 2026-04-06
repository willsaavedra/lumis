"""Celery application configuration."""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from apps.api.core.config import settings


@worker_process_init.connect
def _configure_worker_logging(**kwargs):
    from apps.worker.core.logging import configure_logging
    configure_logging()

celery_app = Celery(
    "lumis",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "apps.worker.tasks",
        "apps.agent.tasks.ingest_global_docs",
        "apps.agent.tasks.ingest_tenant_standards",
        "apps.agent.tasks.ingest_analysis_history",
        "apps.agent.tasks.aggregate_cross_repo",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=600,   # 10 minutes
    task_time_limit=720,         # 12 minutes hard limit
    beat_schedule={
        "run-scheduled-analyses": {
            "task": "apps.worker.tasks.run_scheduled_analyses",
            "schedule": crontab(minute="*/15"),  # Check every 15 minutes
        },
        "ingest-global-docs": {
            "task": "apps.agent.tasks.ingest_global_docs",
            "schedule": crontab(hour=2, minute=0, day_of_week="monday"),  # Every Monday at 02:00 UTC
        },
        "aggregate-cross-repo-patterns": {
            "task": "apps.agent.tasks.aggregate_cross_repo_patterns",
            "schedule": crontab(hour=3, minute=0, day_of_week="sunday"),  # Every Sunday at 03:00 UTC
        },
    },
)
