"""Celery entry point for store catalog imports."""

from __future__ import annotations

import logging
from uuid import UUID

from marko.core.config import get_settings
from marko.infrastructure.db.session import async_session_factory
from marko.services.catalog_import import (
    RetryableCatalogImportError,
    TerminalCatalogImportError,
    fail_store_sync_task,
    import_store_catalog,
)
from marko.services.scraper_outbox import publish_dispatch
from marko.worker.async_runtime import run_async
from marko.worker.celery_app import celery_app

settings = get_settings()
log = logging.getLogger(__name__)


async def _publish_continuation(dispatch_id: UUID) -> None:
    async with async_session_factory() as session:
        await publish_dispatch(
            session,
            event_id=dispatch_id,
            celery_app=celery_app,
        )


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
        self.request.retries or (self.request.delivery_info or {}).get("redelivered")
    )
    reason = (
        "bounded_retry"
        if self.request.retries
        else ("broker_redelivery" if redelivered else None)
    )
    try:
        outcome = run_async(
            import_store_catalog(
                UUID(sync_run_id),
                task_id=self.request.id,
                is_redelivery=redelivered,
                redelivery_reason=reason,
            )
        )
        if outcome.continuation_dispatch_id is not None:
            try:
                run_async(
                    _publish_continuation(outcome.continuation_dispatch_id)
                )
            except Exception:
                # The transactionally persisted outbox event is the source of
                # truth; the periodic reconciler will publish it after a
                # transient broker/DB failure here.
                log.exception(
                    "Immediate store-sync continuation publish failed; "
                    "durable outbox reconciliation will retry"
                )
        return outcome.persisted_products
    except RetryableCatalogImportError as exc:
        if self.request.retries >= self.max_retries:
            run_async(
                fail_store_sync_task(
                    UUID(sync_run_id),
                    task_id=self.request.id,
                    error=exc,
                )
            )
            raise
        countdown = min(
            900,
            settings.store_sync_retry_base_delay_seconds * (2**self.request.retries),
        )
        raise self.retry(exc=exc, countdown=countdown)
    except TerminalCatalogImportError:
        raise
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            run_async(
                fail_store_sync_task(
                    UUID(sync_run_id),
                    task_id=self.request.id,
                    error=exc,
                )
            )
            raise
        countdown = min(
            900,
            settings.store_sync_retry_base_delay_seconds * (2**self.request.retries),
        )
        raise self.retry(exc=exc, countdown=countdown)
