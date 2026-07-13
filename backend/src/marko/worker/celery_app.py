"""Celery application shared by workers and scheduler."""
from __future__ import annotations

from celery import Celery

from marko.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "marko",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["marko.worker.tasks.import_store", "marko.worker.tasks.system"],
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
)
