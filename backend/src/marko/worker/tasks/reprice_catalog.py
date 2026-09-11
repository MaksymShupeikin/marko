"""Celery entry point for catalog-wide repricing runs."""
from __future__ import annotations

from uuid import UUID

from marko.services.repricing import run_reprice
from marko.worker.celery_app import celery_app
from marko.worker.tasks import run_async


@celery_app.task(name="marko.worker.reprice_catalog", bind=True)
def reprice_catalog_task(self, sync_run_id: str) -> int:
    return run_async(run_reprice(UUID(sync_run_id)))
