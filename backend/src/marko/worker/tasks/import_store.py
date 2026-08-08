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
from marko.services.attention import (
    mark_source_monitoring_failed,
    start_store_monitoring_run,
)
from marko.services.scraper_outbox import publish_dispatch
from marko.services.unified_catalog import SOURCE_PROM_STORE
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


async def _mark_monitoring_failed(sync_run_id: UUID) -> None:
    async with async_session_factory() as session:
        from marko.infrastructure.db.models import SyncRun

        sync_run = await session.get(SyncRun, sync_run_id)
        if (
            sync_run is None
            or sync_run.workspace_id is None
            or sync_run.store_id is None
        ):
            return
        await mark_source_monitoring_failed(
            session,
            workspace_id=sync_run.workspace_id,
            source_kind=SOURCE_PROM_STORE,
            source_id=sync_run.store_id,
        )
        await session.commit()


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
        elif outcome.completed:
            try:
                pricing_run_id = run_async(
                    start_store_monitoring_run(UUID(sync_run_id), celery_app)
                )
                if pricing_run_id is None:
                    log.warning(
                        "Automatic attention pricing had no eligible products "
                        "for store sync %s",
                        sync_run_id,
                    )
                    run_async(_mark_monitoring_failed(UUID(sync_run_id)))
            except Exception:
                # Store synchronization is already committed. A market run is
                # follow-up work and must not rewrite a successful source sync
                # as failed; the attention queue keeps the products visible as
                # processing/reviewable and an operator can retry collection.
                log.exception(
                    "Automatic attention pricing could not be started for store sync %s",
                    sync_run_id,
                )
                try:
                    run_async(_mark_monitoring_failed(UUID(sync_run_id)))
                except Exception:
                    log.exception(
                        "Failed to move store sync %s from processing to review",
                        sync_run_id,
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
