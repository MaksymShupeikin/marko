"""Small task used to verify broker/worker connectivity."""

from __future__ import annotations

from marko.core.config import get_settings
from marko.infrastructure.db.session import async_session_factory
from marko.services.scrape_journal import delete_orphaned_evidence_blobs
from marko.services.scraper_outbox import reconcile_dispatch_outbox
from marko.services.workflow_reconciliation import reconcile_stale_workflows
from marko.worker.async_runtime import run_async
from marko.worker.celery_app import celery_app


@celery_app.task(
    name="marko.worker.healthcheck",
    max_retries=0,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=10,
    time_limit=15,
)
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


async def _cleanup_scrape_evidence() -> int:
    async with async_session_factory() as session:
        return await delete_orphaned_evidence_blobs(
            session,
            limit=max(1, get_settings().scrape_evidence_gc_batch_size),
        )


@celery_app.task(
    name="marko.worker.cleanup_scrape_evidence",
    max_retries=0,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=240,
    time_limit=300,
)
def cleanup_scrape_evidence() -> int:
    return run_async(_cleanup_scrape_evidence())


async def _reconcile_scrape_outbox() -> int:
    async with async_session_factory() as session:
        outcomes = await reconcile_dispatch_outbox(
            session,
            celery_app=celery_app,
            limit=max(1, get_settings().scrape_outbox_reconcile_batch_size),
        )
        return sum(outcome.published for outcome in outcomes)


@celery_app.task(
    name="marko.worker.reconcile_scrape_outbox",
    max_retries=0,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=60,
    time_limit=90,
)
def reconcile_scrape_outbox() -> int:
    return run_async(_reconcile_scrape_outbox())


async def _reconcile_stale_workflows() -> dict[str, int]:
    settings = get_settings()
    async with async_session_factory() as session:
        report = await reconcile_stale_workflows(
            session,
            stale_after_seconds=settings.workflow_stale_after_seconds,
            limit=settings.workflow_reconcile_batch_size,
        )
        return report.as_dict()


@celery_app.task(
    name="marko.worker.reconcile_stale_workflows",
    max_retries=0,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=60,
    time_limit=90,
)
def reconcile_stale_workflows_task() -> dict[str, int]:
    return run_async(_reconcile_stale_workflows())
