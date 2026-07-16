"""Celery entry point for store catalog imports."""
from __future__ import annotations

import asyncio
from uuid import UUID

from marko.core.config import get_settings
from marko.services.catalog_import import (
    RetryableCatalogImportError,
    TerminalCatalogImportError,
    fail_store_sync_task,
    import_store_catalog,
)
from marko.worker.celery_app import celery_app

settings = get_settings()


@celery_app.task(
    name="marko.worker.import_store_catalog",
    bind=True,
    max_retries=max(0, settings.store_sync_max_task_executions - 1),
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=settings.store_sync_task_soft_time_limit_seconds,
    time_limit=settings.store_sync_task_time_limit_seconds,
)
def import_store_catalog_task(self, sync_run_id: str) -> int:
    redelivered = bool(
        self.request.retries
        or (self.request.delivery_info or {}).get("redelivered")
    )
    reason = (
        "bounded_retry"
        if self.request.retries
        else ("broker_redelivery" if redelivered else None)
    )
    try:
        return asyncio.run(
            import_store_catalog(
                UUID(sync_run_id),
                task_id=self.request.id,
                is_redelivery=redelivered,
                redelivery_reason=reason,
            )
        )
    except RetryableCatalogImportError as exc:
        if self.request.retries >= self.max_retries:
            asyncio.run(
                fail_store_sync_task(
                    UUID(sync_run_id),
                    task_id=self.request.id,
                    error=exc,
                )
            )
            raise
        countdown = min(
            900,
            settings.store_sync_retry_base_delay_seconds
            * (2**self.request.retries),
        )
        raise self.retry(exc=exc, countdown=countdown)
    except TerminalCatalogImportError:
        raise
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            asyncio.run(
                fail_store_sync_task(
                    UUID(sync_run_id),
                    task_id=self.request.id,
                    error=exc,
                )
            )
            raise
        countdown = min(
            900,
            settings.store_sync_retry_base_delay_seconds
            * (2**self.request.retries),
        )
        raise self.retry(exc=exc, countdown=countdown)
