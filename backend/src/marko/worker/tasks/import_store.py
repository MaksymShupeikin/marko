"""Celery entry point for store catalog imports."""
from __future__ import annotations

from uuid import UUID

from marko.services.catalog_import import import_store_catalog
from marko.worker.celery_app import celery_app
from marko.worker.tasks import run_async


@celery_app.task(name="marko.worker.import_store_catalog", bind=True)
def import_store_catalog_task(self, sync_run_id: str) -> int:
    return run_async(
        import_store_catalog(UUID(sync_run_id), task_id=self.request.id)
    )
