"""Transactional outbox and recovery loop for scraper workflow dispatch.

The producer persists an outbox row in the same transaction as the admitted
job.  A preallocated deterministic Celery task id makes a crash after broker
publish safe to replay: delivery remains at-least-once, while consumers retain
their existing idempotency and fencing checks.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import secrets
import time
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid5

from celery import Celery
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import ScrapeDispatchOutbox, SyncRun


OUTBOX_CONTRACT_VERSION = "scrape-dispatch-outbox.v1"
OUTBOX_LEASE_SECONDS = 60
OUTBOX_RETRY_BASE_SECONDS = 1.0
OUTBOX_RETRY_MAX_SECONDS = 300.0


class OutboxConflict(RuntimeError):
    """An event key was reused with a different immutable task payload."""


@dataclass(frozen=True)
class DispatchOutcome:
    event_id: UUID
    status: str
    published: bool
    task_id: str
    attempt_count: int
    broker_publish_latency_seconds: float | None
    error: str | None = None


@dataclass(frozen=True)
class OutboxHealth:
    pending: int
    dispatching: int
    terminal_failed: int
    oldest_pending_age_seconds: float


def deterministic_task_id(event_key: str) -> str:
    if not event_key.strip():
        raise ValueError("outbox event_key must not be empty")
    return str(uuid5(NAMESPACE_URL, f"{OUTBOX_CONTRACT_VERSION}:{event_key}"))


def full_jitter_delay_seconds(
    attempt_no: int,
    *,
    base: float = OUTBOX_RETRY_BASE_SECONDS,
    maximum: float = OUTBOX_RETRY_MAX_SECONDS,
    random_fraction: float | None = None,
) -> float:
    if attempt_no < 1:
        raise ValueError("attempt_no must be at least one")
    if base <= 0 or maximum <= 0:
        raise ValueError("outbox retry delays must be positive")
    cap = min(maximum, base * (2 ** (attempt_no - 1)))
    if random_fraction is None:
        fraction = secrets.randbelow(1_000_001) / 1_000_000
    else:
        if not 0 <= random_fraction <= 1:
            raise ValueError("random_fraction must be in [0, 1]")
        fraction = random_fraction
    return round(cap * fraction, 6)


async def enqueue_dispatch(
    session: AsyncSession,
    *,
    event_key: str,
    aggregate_type: str,
    aggregate_id: UUID,
    task_name: str,
    task_args: list[Any],
    workspace_id: UUID | None = None,
    task_kwargs: dict[str, Any] | None = None,
    queue: str | None = None,
    max_attempts: int = 20,
    available_at: datetime | None = None,
) -> ScrapeDispatchOutbox:
    """Insert or return one immutable outbox event in the caller transaction."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least one")
    normalized_key = event_key.strip()
    normalized_name = task_name.strip()
    normalized_aggregate = aggregate_type.strip()
    if not normalized_key or not normalized_name or not normalized_aggregate:
        raise ValueError("event_key, aggregate_type, and task_name are required")
    kwargs = dict(task_kwargs or {})
    canonical_payload = _task_payload_hash(
        aggregate_type=normalized_aggregate,
        aggregate_id=aggregate_id,
        task_name=normalized_name,
        task_args=task_args,
        task_kwargs=kwargs,
        queue=queue,
    )
    existing = await session.scalar(
        select(ScrapeDispatchOutbox)
        .where(ScrapeDispatchOutbox.event_key == normalized_key)
        .with_for_update()
    )
    if existing is not None:
        existing_hash = _task_payload_hash(
            aggregate_type=existing.aggregate_type,
            aggregate_id=existing.aggregate_id,
            task_name=existing.task_name,
            task_args=list(existing.task_args),
            task_kwargs=dict(existing.task_kwargs),
            queue=existing.queue,
        )
        if existing_hash != canonical_payload:
            raise OutboxConflict(
                "outbox event_key cannot be reused with a different payload"
            )
        return existing

    event = ScrapeDispatchOutbox(
        event_key=normalized_key,
        workspace_id=workspace_id,
        aggregate_type=normalized_aggregate,
        aggregate_id=aggregate_id,
        task_name=normalized_name,
        task_id=deterministic_task_id(normalized_key),
        queue=queue,
        task_args=list(task_args),
        task_kwargs=kwargs,
        status="pending",
        attempt_count=0,
        max_attempts=max_attempts,
        available_at=_utc(available_at or datetime.now(UTC)),
    )
    session.add(event)
    await session.flush()
    return event


async def publish_dispatch(
    session: AsyncSession,
    *,
    event_id: UUID,
    celery_app: Celery,
    now: datetime | None = None,
    lease_seconds: int = OUTBOX_LEASE_SECONDS,
) -> DispatchOutcome:
    """Claim and publish one event, retaining it for crash recovery."""

    if lease_seconds < 1:
        raise ValueError("outbox lease_seconds must be at least one")
    current = _utc(now or datetime.now(UTC))
    event = await session.scalar(
        select(ScrapeDispatchOutbox)
        .where(ScrapeDispatchOutbox.id == event_id)
        .with_for_update()
    )
    if event is None:
        raise LookupError(f"Outbox event {event_id} does not exist")
    if event.status == "published":
        return _outcome(event, published=True, latency=None)
    if event.status == "terminal_failed":
        return _outcome(
            event,
            published=False,
            latency=None,
            error=event.last_error,
        )
    if event.status == "dispatching" and (
        event.lease_expires_at is not None
        and _utc(event.lease_expires_at) > current
    ):
        return _outcome(event, published=False, latency=None)
    if _utc(event.available_at) > current:
        return _outcome(event, published=False, latency=None)
    if event.attempt_count >= event.max_attempts:
        event.status = "terminal_failed"
        event.lease_expires_at = None
        event.last_error = event.last_error or "Outbox publish retry budget exhausted"
        await session.commit()
        return _outcome(
            event,
            published=False,
            latency=None,
            error=event.last_error,
        )

    event.status = "dispatching"
    event.attempt_count += 1
    event.lease_expires_at = current + timedelta(seconds=lease_seconds)
    event.last_error = None
    await session.commit()

    started = time.perf_counter()
    try:
        await asyncio.to_thread(
            celery_app.send_task,
            event.task_name,
            args=list(event.task_args),
            kwargs=dict(event.task_kwargs),
            queue=event.queue,
            task_id=event.task_id,
        )
    except Exception as exc:
        latency = round(time.perf_counter() - started, 6)
        event = await session.scalar(
            select(ScrapeDispatchOutbox)
            .where(ScrapeDispatchOutbox.id == event_id)
            .with_for_update()
        )
        if event is None:
            raise LookupError(f"Outbox event {event_id} disappeared") from exc
        event.last_error = f"{type(exc).__name__}: {exc}"[:4000]
        event.lease_expires_at = None
        if event.attempt_count >= event.max_attempts:
            event.status = "terminal_failed"
        else:
            event.status = "pending"
            event.available_at = current + timedelta(
                seconds=full_jitter_delay_seconds(event.attempt_count)
            )
        await session.commit()
        return _outcome(
            event,
            published=False,
            latency=latency,
            error=event.last_error,
        )

    latency = round(time.perf_counter() - started, 6)
    event = await session.scalar(
        select(ScrapeDispatchOutbox)
        .where(ScrapeDispatchOutbox.id == event_id)
        .with_for_update()
    )
    if event is None:
        raise LookupError(f"Outbox event {event_id} disappeared after publish")
    event.status = "published"
    event.published_at = datetime.now(UTC)
    event.lease_expires_at = None
    event.last_error = None
    if event.aggregate_type == "sync_run":
        sync_run = await session.get(SyncRun, event.aggregate_id)
        if sync_run is not None:
            sync_run.task_id = event.task_id
    await session.commit()
    return _outcome(event, published=True, latency=latency)


async def reconcile_dispatch_outbox(
    session: AsyncSession,
    *,
    celery_app: Celery,
    limit: int = 100,
    now: datetime | None = None,
) -> list[DispatchOutcome]:
    """Publish ready or lease-expired events in a bounded recovery batch."""

    if limit < 1:
        raise ValueError("outbox reconciliation limit must be at least one")
    current = _utc(now or datetime.now(UTC))
    event_ids = list(
        (
            await session.scalars(
                select(ScrapeDispatchOutbox.id)
                .where(
                    ScrapeDispatchOutbox.available_at <= current,
                    or_(
                        ScrapeDispatchOutbox.status == "pending",
                        and_(
                            ScrapeDispatchOutbox.status == "dispatching",
                            or_(
                                ScrapeDispatchOutbox.lease_expires_at.is_(None),
                                ScrapeDispatchOutbox.lease_expires_at <= current,
                            ),
                        ),
                    ),
                )
                .order_by(
                    ScrapeDispatchOutbox.available_at,
                    ScrapeDispatchOutbox.created_at,
                    ScrapeDispatchOutbox.id,
                )
                .limit(limit)
            )
        ).all()
    )
    return [
        await publish_dispatch(
            session,
            event_id=event_id,
            celery_app=celery_app,
            now=current,
        )
        for event_id in event_ids
    ]


async def outbox_health(
    session: AsyncSession,
    *,
    workspace_id: UUID | None = None,
    now: datetime | None = None,
) -> OutboxHealth:
    current = _utc(now or datetime.now(UTC))
    scope = (
        []
        if workspace_id is None
        else [ScrapeDispatchOutbox.workspace_id == workspace_id]
    )
    counts = {
        status: int(count)
        for status, count in (
            await session.execute(
                select(
                    ScrapeDispatchOutbox.status,
                    func.count(ScrapeDispatchOutbox.id),
                )
                .where(ScrapeDispatchOutbox.status != "published", *scope)
                .group_by(ScrapeDispatchOutbox.status)
            )
        ).all()
    }
    oldest = await session.scalar(
        select(func.min(ScrapeDispatchOutbox.created_at)).where(
            ScrapeDispatchOutbox.status.in_(("pending", "dispatching")),
            *scope,
        )
    )
    age = 0.0 if oldest is None else max(0.0, (current - _utc(oldest)).total_seconds())
    return OutboxHealth(
        pending=counts.get("pending", 0),
        dispatching=counts.get("dispatching", 0),
        terminal_failed=counts.get("terminal_failed", 0),
        oldest_pending_age_seconds=round(age, 6),
    )


def _outcome(
    event: ScrapeDispatchOutbox,
    *,
    published: bool,
    latency: float | None,
    error: str | None = None,
) -> DispatchOutcome:
    return DispatchOutcome(
        event_id=event.id,
        status=event.status,
        published=published,
        task_id=event.task_id,
        attempt_count=event.attempt_count,
        broker_publish_latency_seconds=latency,
        error=error,
    )


def _task_payload_hash(
    *,
    aggregate_type: str,
    aggregate_id: UUID,
    task_name: str,
    task_args: list[Any],
    task_kwargs: dict[str, Any],
    queue: str | None,
) -> str:
    canonical = json.dumps(
        {
            "contract": OUTBOX_CONTRACT_VERSION,
            "aggregate_type": aggregate_type,
            "aggregate_id": str(aggregate_id),
            "task_name": task_name,
            "task_args": task_args,
            "task_kwargs": task_kwargs,
            "queue": queue,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = [
    "DispatchOutcome",
    "OUTBOX_CONTRACT_VERSION",
    "OutboxConflict",
    "OutboxHealth",
    "deterministic_task_id",
    "enqueue_dispatch",
    "full_jitter_delay_seconds",
    "outbox_health",
    "publish_dispatch",
    "reconcile_dispatch_outbox",
]
