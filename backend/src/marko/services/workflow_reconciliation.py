"""Bounded terminalization of workflow rows abandoned by dead workers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    CatalogDiscoveryRun,
    CatalogImportBatch,
    FitmentAnalysis,
    PricingRun,
    PricingRunItem,
    ScrapeAttempt,
    ScrapeTarget,
    StoreSyncTaskExecution,
    SyncRun,
    SyncStatus,
)


_PRICING_ACTIVE = (
    "running",
    "collecting",
    "classifying",
    "calibrating",
    "calculating",
)
_PRICING_ITEM_ACTIVE = (
    "queued",
    "collecting",
    "collected",
    "classified",
    "calculating",
)
_TARGET_ACTIVE = ("queued", "collecting", "retryable_failure")


@dataclass(frozen=True)
class StaleWorkflowReport:
    sync_runs_failed: int = 0
    store_executions_worker_lost: int = 0
    catalog_imports_failed: int = 0
    catalog_discoveries_failed: int = 0
    pricing_runs_failed: int = 0
    pricing_items_failed: int = 0
    scrape_targets_failed: int = 0
    scrape_attempts_worker_lost: int = 0
    fitment_analyses_failed: int = 0

    @property
    def terminalized_total(self) -> int:
        return sum(asdict(self).values())

    def as_dict(self) -> dict[str, int]:
        return {
            **asdict(self),
            "terminalized_total": self.terminalized_total,
        }


async def reconcile_stale_workflows(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = 3600,
    limit: int = 100,
) -> StaleWorkflowReport:
    """Move expired ``running`` work to explicit failure states.

    Rows are locked with ``SKIP LOCKED`` so this task cannot fight a healthy
    worker that is currently finalizing the same object.  The global ``limit``
    bounds top-level workflows per invocation; child rows are necessarily
    bounded by those selected parents.
    """

    if stale_after_seconds < 1:
        raise ValueError("stale_after_seconds must be positive")
    if limit < 1:
        raise ValueError("limit must be positive")
    current = _aware(now or datetime.now(UTC))
    cutoff = current - timedelta(seconds=stale_after_seconds)
    remaining = limit
    counts = {
        field: 0
        for field in StaleWorkflowReport.__dataclass_fields__
    }

    sync_runs = list(
        (
            await session.scalars(
                select(SyncRun)
                .where(
                    SyncRun.scrape_state == "running",
                    or_(
                        SyncRun.scrape_lease_expires_at <= current,
                        (
                            SyncRun.scrape_lease_expires_at.is_(None)
                            & (SyncRun.started_at <= cutoff)
                        ),
                    ),
                )
                .order_by(SyncRun.started_at, SyncRun.id)
                .limit(remaining)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    remaining -= len(sync_runs)
    for run in sync_runs:
        detail = "worker_lost: store-sync lease expired"
        run.status = SyncStatus.failed
        run.scrape_state = "failed"
        run.scrape_owner_task_id = None
        run.scrape_lease_expires_at = None
        run.error = detail
        run.finished_at = current
        run.scrape_checkpoint = {
            "stage": "terminal_failure",
            "reason": "worker_lost",
            "next_page": run.scrape_catalog_pages + 1,
            "products_persisted": run.scrape_products_persisted,
            "at": current.isoformat(),
        }
        running_executions = list(
            (
                await session.scalars(
                    select(StoreSyncTaskExecution)
                    .where(
                        StoreSyncTaskExecution.sync_run_id == run.id,
                        StoreSyncTaskExecution.outcome == "running",
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for execution in running_executions:
            execution.outcome = "worker_lost"
            execution.error_category = "worker_lost"
            execution.error_detail = detail
            execution.finished_at = current
            if execution.wall_time_ms == 0:
                execution.wall_time_ms = max(
                    0,
                    round(
                        (
                            current - _aware(execution.started_at)
                        ).total_seconds()
                        * 1000
                    ),
                )
        counts["store_executions_worker_lost"] += len(running_executions)
    counts["sync_runs_failed"] = len(sync_runs)

    if remaining:
        imports = list(
            (
                await session.scalars(
                    select(CatalogImportBatch)
                    .where(
                        CatalogImportBatch.status == "running",
                        func.coalesce(
                            CatalogImportBatch.started_at,
                            CatalogImportBatch.created_at,
                        )
                        <= cutoff,
                    )
                    .order_by(CatalogImportBatch.started_at, CatalogImportBatch.id)
                    .limit(remaining)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        remaining -= len(imports)
        for batch in imports:
            batch.status = "failed"
            batch.finished_at = current
            batch.error_log = [
                *(batch.error_log or []),
                {
                    "code": "WORKER_LOST",
                    "detail": "Import remained running beyond the stale timeout",
                },
            ][-100:]
        counts["catalog_imports_failed"] = len(imports)

    if remaining:
        discoveries = list(
            (
                await session.scalars(
                    select(CatalogDiscoveryRun)
                    .where(
                        CatalogDiscoveryRun.status == "running",
                        CatalogDiscoveryRun.created_at <= cutoff,
                    )
                    .order_by(
                        CatalogDiscoveryRun.created_at,
                        CatalogDiscoveryRun.id,
                    )
                    .limit(remaining)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        remaining -= len(discoveries)
        for discovery in discoveries:
            discovery.status = "failed"
            discovery.error_code = "WORKER_LOST"
            discovery.error_detail = (
                "Discovery remained running beyond the stale timeout"
            )
            discovery.completed_at = current
        counts["catalog_discoveries_failed"] = len(discoveries)

    if remaining:
        pricing_runs = list(
            (
                await session.scalars(
                    select(PricingRun)
                    .where(
                        PricingRun.status.in_(_PRICING_ACTIVE),
                        func.coalesce(
                            PricingRun.updated_at,
                            PricingRun.started_at,
                            PricingRun.created_at,
                        )
                        <= cutoff,
                    )
                    .order_by(PricingRun.started_at, PricingRun.id)
                    .limit(remaining)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        remaining -= len(pricing_runs)
        for run in pricing_runs:
            detail = "worker_lost: pricing workflow exceeded stale timeout"
            targets = list(
                (
                    await session.scalars(
                        select(ScrapeTarget)
                        .where(
                            ScrapeTarget.pricing_run_id == run.id,
                            ScrapeTarget.status.in_(_TARGET_ACTIVE),
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            target_ids = [target.id for target in targets]
            for target in targets:
                target.status = "terminal_failure"
                target.execution_status = "TERMINAL_FAILED"
                target.owner_task_id = None
                target.lease_expires_at = None
                target.error_category = "worker_lost"
                target.error_detail = detail
                target.finished_at = current
            attempts = (
                list(
                    (
                        await session.scalars(
                            select(ScrapeAttempt)
                            .where(
                                ScrapeAttempt.scrape_target_id.in_(target_ids),
                                ScrapeAttempt.status == "running",
                            )
                            .with_for_update(skip_locked=True)
                        )
                    ).all()
                )
                if target_ids
                else []
            )
            for attempt in attempts:
                attempt.status = "worker_lost"
                attempt.error_category = "worker_lost"
                attempt.error_detail = detail
                attempt.finished_at = current
                if attempt.wall_time_ms == 0:
                    attempt.wall_time_ms = max(
                        0,
                        round(
                            (
                                current - _aware(attempt.started_at)
                            ).total_seconds()
                            * 1000
                        ),
                    )
            items = list(
                (
                    await session.scalars(
                        select(PricingRunItem)
                        .where(
                            PricingRunItem.pricing_run_id == run.id,
                            PricingRunItem.status.in_(_PRICING_ITEM_ACTIVE),
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for item in items:
                item.status = "failed"
                item.error = detail
                item.finished_at = current
                item.checkpoint = {
                    "stage": "failed",
                    "reason": "worker_lost",
                    "at": current.isoformat(),
                }
            run.status = "failed"
            run.failed_items = max(run.failed_items, len(items))
            run.error = detail
            run.finished_at = current
            counts["scrape_targets_failed"] += len(targets)
            counts["scrape_attempts_worker_lost"] += len(attempts)
            counts["pricing_items_failed"] += len(items)
        counts["pricing_runs_failed"] = len(pricing_runs)

    if remaining:
        fitment = list(
            (
                await session.scalars(
                    select(FitmentAnalysis)
                    .where(
                        FitmentAnalysis.status == "running",
                        or_(
                            FitmentAnalysis.lease_expires_at <= current,
                            (
                                FitmentAnalysis.lease_expires_at.is_(None)
                                & (
                                    func.coalesce(
                                        FitmentAnalysis.started_at,
                                        FitmentAnalysis.created_at,
                                    )
                                    <= cutoff
                                )
                            ),
                        ),
                    )
                    .order_by(FitmentAnalysis.started_at, FitmentAnalysis.id)
                    .limit(remaining)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for analysis in fitment:
            analysis.status = "failed"
            analysis.workflow_state = "FAILED"
            analysis.owner_task_id = None
            analysis.lease_expires_at = None
            analysis.error = "worker_lost: fitment analysis lease expired"
            analysis.failed_candidate_count = analysis.candidate_count
            analysis.finished_at = current
        counts["fitment_analyses_failed"] = len(fitment)

    await session.commit()
    return StaleWorkflowReport(**counts)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = ["StaleWorkflowReport", "reconcile_stale_workflows"]
