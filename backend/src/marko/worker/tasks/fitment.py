"""Idempotent worker for durable distributed-fitment analysis jobs."""

from __future__ import annotations

from uuid import UUID

from marko.infrastructure.db.session import async_session_factory
from marko.services.fitment_intelligence import (
    fail_fitment_analysis_job,
    process_fitment_analysis_job,
)
from marko.worker.async_runtime import run_async
from marko.worker.celery_app import celery_app


async def _process(analysis_id: UUID, task_id: str) -> str:
    async with async_session_factory() as session:
        result = await process_fitment_analysis_job(
            session,
            analysis_id=analysis_id,
            task_id=task_id,
        )
    return "leased_elsewhere" if result is None else result.status


async def _fail(analysis_id: UUID, task_id: str, error: Exception) -> None:
    async with async_session_factory() as session:
        await fail_fitment_analysis_job(
            session,
            analysis_id=analysis_id,
            task_id=task_id,
            error=error,
        )


@celery_app.task(
    name="marko.worker.process_fitment_analysis",
    bind=True,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=240,
    time_limit=300,
)
def process_fitment_analysis_task(self, analysis_id: str) -> str:
    parsed_id = UUID(analysis_id)
    task_id = str(self.request.id)
    try:
        return run_async(_process(parsed_id, task_id))
    except Exception as exc:
        run_async(_fail(parsed_id, task_id, exc))
        if self.request.retries >= self.max_retries:
            raise
        raise self.retry(
            exc=exc,
            countdown=min(120, 5 * (2**self.request.retries)),
        )
