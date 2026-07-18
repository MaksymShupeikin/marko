"""Small task used to verify broker/worker connectivity."""
from __future__ import annotations

import asyncio

from marko.core.config import get_settings
from marko.infrastructure.db.session import async_session_factory
from marko.services.scrape_journal import delete_orphaned_evidence_blobs
from marko.services.scraper_outbox import reconcile_dispatch_outbox
from marko.worker.celery_app import celery_app


@celery_app.task(name="marko.worker.healthcheck")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


async def _cleanup_scrape_evidence() -> int:
    async with async_session_factory() as session:
        return await delete_orphaned_evidence_blobs(
            session,
            limit=max(1, get_settings().scrape_evidence_gc_batch_size),
        )


@celery_app.task(name="marko.worker.cleanup_scrape_evidence")
def cleanup_scrape_evidence() -> int:
    return asyncio.run(_cleanup_scrape_evidence())


async def _reconcile_scrape_outbox() -> int:
    async with async_session_factory() as session:
        outcomes = await reconcile_dispatch_outbox(
            session,
            celery_app=celery_app,
            limit=max(1, get_settings().scrape_outbox_reconcile_batch_size),
        )
        return sum(outcome.published for outcome in outcomes)


@celery_app.task(name="marko.worker.reconcile_scrape_outbox")
def reconcile_scrape_outbox() -> int:
    return asyncio.run(_reconcile_scrape_outbox())
