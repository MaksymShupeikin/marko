"""Idempotent Celery tasks for pricing-run fan-out and item processing."""

from __future__ import annotations

import asyncio
from uuid import UUID

from marko.core.config import get_settings
from marko.infrastructure.db.session import async_session_factory
from marko.services.market_collection import (
    PermanentCollectionError,
    calculate_pricing_item,
    calibrate_run_and_prepare_calculations,
    claim_collection_finalization,
    enqueue_collection_finalizer_dispatch,
    fail_collection_finalization,
    fail_pricing_item,
    fail_pricing_run_dispatch,
    finalize_pricing_run,
    get_pricing_item_run_id,
    mark_run_calculating,
    prepare_run_dispatch,
    process_pricing_item,
    reset_pricing_calculation_for_retry,
    reset_pricing_item_for_retry,
)
from marko.services.scraper_outbox import publish_dispatch
from marko.worker.celery_app import celery_app

settings = get_settings()


@celery_app.task(
    name="marko.worker.start_pricing_run",
    bind=True,
    max_retries=3,
)
def start_pricing_run_task(self, run_id: str) -> int:
    parsed_run_id = UUID(run_id)
    try:
        event_ids = asyncio.run(prepare_run_dispatch(parsed_run_id))
        batch_size = max(1, get_settings().pricing_dispatch_batch_size)
        dispatched = 0
        for start in range(0, len(event_ids), batch_size):
            dispatched += asyncio.run(
                _publish_dispatch_events(event_ids[start : start + batch_size])
            )
        if not event_ids:
            event_id = asyncio.run(
                enqueue_collection_finalizer_dispatch(
                    parsed_run_id,
                    trigger_key="empty-start",
                )
            )
            dispatched += asyncio.run(_publish_dispatch_events([event_id]))
        return dispatched
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            asyncio.run(fail_pricing_run_dispatch(parsed_run_id, exc))
            raise
        raise self.retry(
            exc=exc,
            countdown=min(120, 5 * (2**self.request.retries)),
        )


@celery_app.task(
    name="marko.worker.process_pricing_item",
    bind=True,
    max_retries=max(0, settings.pricing_collection_max_task_executions - 1),
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=settings.pricing_collection_task_soft_time_limit_seconds,
    time_limit=settings.pricing_collection_task_time_limit_seconds,
)
def process_pricing_item_task(self, run_item_id: str) -> str:
    item_id = UUID(run_item_id)
    is_redelivery = bool(
        self.request.retries
        or (self.request.delivery_info or {}).get("redelivered")
    )
    try:
        run_id = asyncio.run(
            process_pricing_item(
                item_id,
                task_id=self.request.id,
                is_redelivery=is_redelivery,
            )
        )
        if run_id is not None:
            _enqueue_collection_finalizer(run_id, trigger_id=item_id)
        return "skipped" if run_id is None else str(run_id)
    except PermanentCollectionError as exc:
        run_id = asyncio.run(get_pricing_item_run_id(item_id))
        asyncio.run(fail_pricing_item(item_id, exc))
        if run_id is not None:
            _enqueue_collection_finalizer(run_id, trigger_id=item_id)
        raise
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            run_id = asyncio.run(get_pricing_item_run_id(item_id))
            asyncio.run(fail_pricing_item(item_id, exc))
            if run_id is not None:
                _enqueue_collection_finalizer(run_id, trigger_id=item_id)
            raise
        asyncio.run(reset_pricing_item_for_retry(item_id, exc))
        raise self.retry(exc=exc, countdown=min(300, 10 * (2**self.request.retries)))


@celery_app.task(
    name="marko.worker.finalize_pricing_collection",
    bind=True,
    max_retries=5,
)
def finalize_pricing_collection_task(self, run_id: str) -> int:
    parsed_run_id = UUID(run_id)
    try:
        claimed = asyncio.run(
            claim_collection_finalization(parsed_run_id, task_id=self.request.id)
        )
        if not claimed:
            return 0
        event_ids = asyncio.run(
            calibrate_run_and_prepare_calculations(parsed_run_id)
        )
        asyncio.run(mark_run_calculating(parsed_run_id, task_id=self.request.id))
        asyncio.run(_publish_dispatch_events(event_ids))
        if not event_ids:
            asyncio.run(finalize_pricing_run(parsed_run_id))
        return len(event_ids)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            asyncio.run(
                fail_collection_finalization(
                    parsed_run_id, task_id=self.request.id, error=exc
                )
            )
            raise
        raise self.retry(exc=exc, countdown=min(300, 10 * (2**self.request.retries)))


@celery_app.task(
    name="marko.worker.calculate_pricing_item",
    bind=True,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def calculate_pricing_item_task(self, run_item_id: str) -> str:
    item_id = UUID(run_item_id)
    try:
        run_id = asyncio.run(calculate_pricing_item(item_id, task_id=self.request.id))
        return "skipped" if run_id is None else str(run_id)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            asyncio.run(fail_pricing_item(item_id, exc))
            raise
        asyncio.run(reset_pricing_calculation_for_retry(item_id, exc))
        raise self.retry(exc=exc, countdown=min(120, 5 * (2**self.request.retries)))


def _enqueue_collection_finalizer(run_id: UUID, *, trigger_id: UUID) -> None:
    event_id = asyncio.run(
        enqueue_collection_finalizer_dispatch(
            run_id,
            trigger_key=str(trigger_id),
        )
    )
    asyncio.run(_publish_dispatch_events([event_id]))


async def _publish_dispatch_events(event_ids: list[UUID]) -> int:
    published = 0
    async with async_session_factory() as session:
        for event_id in event_ids:
            outcome = await publish_dispatch(
                session,
                event_id=event_id,
                celery_app=celery_app,
            )
            published += int(outcome.published)
    return published
