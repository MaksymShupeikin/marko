"""Celery entry point for catalog-wide product refreshes."""
from __future__ import annotations

from uuid import UUID

from marko.services.bulk_products import CatalogFilter, refresh_matching
from marko.worker.celery_app import celery_app
from marko.worker.tasks import run_async


@celery_app.task(name="marko.worker.refresh_catalog", bind=True)
def refresh_catalog_task(self, sync_run_id: str, catalog_filter: dict | None) -> int:
    return run_async(
        refresh_matching(UUID(sync_run_id), CatalogFilter.from_json(catalog_filter))
    )
