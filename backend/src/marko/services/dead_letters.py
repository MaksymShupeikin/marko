"""Workspace-scoped dead-letter registry and safe replay orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from celery import Celery
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import PricingRun, ScrapeTarget, SyncRun
import marko.repositories.stores as stores_repo
from marko.services.pricing_runs import create_pricing_run
from marko.services.stores import queue_store_sync


DeadLetterKind = Literal["store_sync", "pricing_target"]
TERMINAL_PRICING_RUN_STATUSES = frozenset(
    {"completed", "partial", "failed", "cancelled"}
)


class DeadLetterNotFoundError(LookupError):
    pass


class DeadLetterReplayError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeadLetterEntry:
    kind: DeadLetterKind
    id: UUID
    parent_id: UUID | None
    error_category: str
    error_detail: str
    attempts: int
    terminal_at: datetime


@dataclass(frozen=True)
class DeadLetterPage:
    items: list[DeadLetterEntry]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class DeadLetterReplay:
    kind: DeadLetterKind
    dead_letter_id: UUID
    workflow_id: UUID
    workflow_status: str


async def list_dead_letters(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    limit: int,
    offset: int,
) -> DeadLetterPage:
    fetch_limit = limit + offset
    store_count = int(
        await session.scalar(
            select(func.count(SyncRun.id)).where(
                SyncRun.workspace_id == workspace_id,
                SyncRun.scrape_state == "failed",
            )
        )
        or 0
    )
    pricing_count = int(
        await session.scalar(
            select(func.count(ScrapeTarget.id))
            .join(PricingRun, PricingRun.id == ScrapeTarget.pricing_run_id)
            .where(
                PricingRun.workspace_id == workspace_id,
                ScrapeTarget.status == "terminal_failure",
            )
        )
        or 0
    )
    store_rows = list(
        (
            await session.scalars(
                select(SyncRun)
                .where(
                    SyncRun.workspace_id == workspace_id,
                    SyncRun.scrape_state == "failed",
                )
                .order_by(SyncRun.finished_at.desc(), SyncRun.id.desc())
                .limit(fetch_limit)
            )
        ).all()
    )
    pricing_rows = list(
        (
            await session.execute(
                select(ScrapeTarget, PricingRun.id)
                .join(PricingRun, PricingRun.id == ScrapeTarget.pricing_run_id)
                .where(
                    PricingRun.workspace_id == workspace_id,
                    ScrapeTarget.status == "terminal_failure",
                )
                .order_by(ScrapeTarget.finished_at.desc(), ScrapeTarget.id.desc())
                .limit(fetch_limit)
            )
        ).all()
    )
    entries = [
        DeadLetterEntry(
            kind="store_sync",
            id=row.id,
            parent_id=row.store_id,
            error_category="store_sync_failed",
            error_detail=row.error or "Store synchronization failed",
            attempts=row.scrape_task_executions,
            terminal_at=_terminal_at(row.finished_at, row.updated_at),
        )
        for row in store_rows
    ]
    entries.extend(
        DeadLetterEntry(
            kind="pricing_target",
            id=target.id,
            parent_id=run_id,
            error_category=target.error_category or "terminal_failure",
            error_detail=target.error_detail or "Pricing collection target failed",
            attempts=target.network_attempts,
            terminal_at=_terminal_at(target.finished_at, target.updated_at),
        )
        for target, run_id in pricing_rows
    )
    entries.sort(key=lambda entry: (entry.terminal_at, entry.id), reverse=True)
    return DeadLetterPage(
        items=entries[offset : offset + limit],
        total=store_count + pricing_count,
        limit=limit,
        offset=offset,
    )


async def replay_dead_letter(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    kind: DeadLetterKind,
    dead_letter_id: UUID,
    celery_app: Celery,
) -> DeadLetterReplay:
    if kind == "store_sync":
        failed = await stores_repo.get_sync_run_by_id(
            session,
            dead_letter_id,
            workspace_id,
        )
        if failed is None or failed.scrape_state != "failed":
            raise DeadLetterNotFoundError(str(dead_letter_id))
        if failed.store_id is None:
            raise DeadLetterReplayError("Failed store sync has no source store")
        replay = await queue_store_sync(
            session,
            store_id=failed.store_id,
            workspace_id=workspace_id,
            celery_app=celery_app,
        )
        return DeadLetterReplay(
            kind=kind,
            dead_letter_id=dead_letter_id,
            workflow_id=replay.id,
            workflow_status=replay.scrape_state,
        )

    row = (
        await session.execute(
            select(ScrapeTarget, PricingRun)
            .join(PricingRun, PricingRun.id == ScrapeTarget.pricing_run_id)
            .where(
                ScrapeTarget.id == dead_letter_id,
                ScrapeTarget.status == "terminal_failure",
                PricingRun.workspace_id == workspace_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise DeadLetterNotFoundError(str(dead_letter_id))
    _target, failed_run = row
    if failed_run.status not in TERMINAL_PRICING_RUN_STATUSES:
        raise DeadLetterReplayError(
            "Pricing run is still active; finish or cancel it before replay"
        )
    replay = await create_pricing_run(
        session,
        workspace_id=workspace_id,
        import_batch_id=failed_run.import_batch_id,
        celery_app=celery_app,
        policy_config=failed_run.policy_config,
    )
    return DeadLetterReplay(
        kind=kind,
        dead_letter_id=dead_letter_id,
        workflow_id=replay.id,
        workflow_status=replay.status,
    )


def _terminal_at(
    finished_at: datetime | None,
    updated_at: datetime | None,
) -> datetime:
    value = finished_at or updated_at or datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "DeadLetterEntry",
    "DeadLetterKind",
    "DeadLetterNotFoundError",
    "DeadLetterPage",
    "DeadLetterReplay",
    "DeadLetterReplayError",
    "list_dead_letters",
    "replay_dead_letter",
]
