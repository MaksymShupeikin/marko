"""Periodic refresh admission for connected owned stores."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from celery import Celery
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.core.config import Settings, get_settings
from marko.infrastructure.db.models import (
    MarketplaceStore,
    StoreKind,
    SyncRun,
    WorkspaceStore,
)
from marko.services.source_access import source_access_status
from marko.services.stores import queue_store_sync


@dataclass(frozen=True)
class StoreMonitoringScheduleReport:
    enabled: bool
    live_collection_allowed: bool
    due: int
    scheduled: int

    def as_dict(self) -> dict[str, bool | int]:
        return {
            "enabled": self.enabled,
            "live_collection_allowed": self.live_collection_allowed,
            "due": self.due,
            "scheduled": self.scheduled,
        }


async def schedule_due_store_monitoring(
    session: AsyncSession,
    *,
    celery_app: Celery,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> StoreMonitoringScheduleReport:
    """Queue one bounded refresh batch without duplicating active store runs."""

    resolved = settings or get_settings()
    access = source_access_status(resolved)
    if not resolved.store_monitoring_enabled or not access.live_collection_allowed:
        return StoreMonitoringScheduleReport(
            enabled=resolved.store_monitoring_enabled,
            live_collection_allowed=access.live_collection_allowed,
            due=0,
            scheduled=0,
        )

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    cutoff = current - timedelta(
        seconds=resolved.store_monitoring_refresh_interval_seconds
    )

    # Pace from the latest terminal attempt, not only the latest success. A
    # broken source must remain retryable, but a five-minute scheduler scan
    # must not turn a permanent parser/access failure into a request storm.
    last_attempt = (
        select(
            SyncRun.workspace_id.label("workspace_id"),
            SyncRun.store_id.label("store_id"),
            func.max(SyncRun.finished_at).label("last_finished_at"),
        )
        .where(
            SyncRun.kind == "catalog_import",
            SyncRun.workspace_id.is_not(None),
            SyncRun.store_id.is_not(None),
            SyncRun.finished_at.is_not(None),
        )
        .group_by(SyncRun.workspace_id, SyncRun.store_id)
        .subquery()
    )
    active_run = exists(
        select(SyncRun.id).where(
            SyncRun.workspace_id == WorkspaceStore.workspace_id,
            SyncRun.store_id == WorkspaceStore.store_id,
            SyncRun.kind == "catalog_import",
            SyncRun.scrape_state.in_(("queued", "running", "retry_wait")),
        )
    )
    statement = (
        select(WorkspaceStore.workspace_id, WorkspaceStore.store_id)
        .join(MarketplaceStore, MarketplaceStore.id == WorkspaceStore.store_id)
        .outerjoin(
            last_attempt,
            and_(
                last_attempt.c.workspace_id == WorkspaceStore.workspace_id,
                last_attempt.c.store_id == WorkspaceStore.store_id,
            ),
        )
        .where(
            WorkspaceStore.kind == StoreKind.owned,
            MarketplaceStore.marketplace == "prom",
            or_(
                last_attempt.c.last_finished_at.is_(None),
                last_attempt.c.last_finished_at <= cutoff,
            ),
            ~active_run,
        )
        .order_by(
            last_attempt.c.last_finished_at.asc().nulls_first(),
            WorkspaceStore.created_at.asc(),
        )
        .limit(resolved.store_monitoring_batch_size)
    )
    due_pairs = list((await session.execute(statement)).all())
    scheduled = 0
    for workspace_id, store_id in due_pairs:
        await queue_store_sync(
            session,
            store_id=store_id,
            workspace_id=workspace_id,
            celery_app=celery_app,
        )
        scheduled += 1
    return StoreMonitoringScheduleReport(
        enabled=True,
        live_collection_allowed=True,
        due=len(due_pairs),
        scheduled=scheduled,
    )


__all__ = [
    "StoreMonitoringScheduleReport",
    "schedule_due_store_monitoring",
]
