from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest

from marko.infrastructure.db.models import ScrapeDispatchOutbox
from marko.services.scraper_outbox import (
    OutboxConflict,
    deterministic_task_id,
    enqueue_dispatch,
    full_jitter_delay_seconds,
    publish_dispatch,
)


class _FakeSession:
    def __init__(self, event=None) -> None:
        self.event = event
        self.commits = 0
        self.added = []

    async def scalar(self, _statement):
        return self.event

    async def get(self, _model, _identity):
        return None

    def add(self, value) -> None:
        self.added.append(value)
        self.event = value

    async def flush(self) -> None:
        if self.event is not None and self.event.id is None:
            self.event.id = uuid4()

    async def commit(self) -> None:
        self.commits += 1


def _event(*, status: str = "pending") -> ScrapeDispatchOutbox:
    event_key = "pricing-run:1:start:v1"
    return ScrapeDispatchOutbox(
        id=uuid4(),
        event_key=event_key,
        aggregate_type="pricing_run",
        aggregate_id=uuid4(),
        task_name="marko.worker.start_pricing_run",
        task_id=deterministic_task_id(event_key),
        queue="celery",
        task_args=["run-1"],
        task_kwargs={},
        status=status,
        attempt_count=0,
        max_attempts=3,
        available_at=datetime.now(UTC) - timedelta(seconds=1),
    )


def test_outbox_task_id_and_full_jitter_are_bounded() -> None:
    key = "store-sync:abc:start:v1"
    assert deterministic_task_id(key) == deterministic_task_id(key)
    assert full_jitter_delay_seconds(3, base=2, maximum=30, random_fraction=0) == 0
    assert full_jitter_delay_seconds(3, base=2, maximum=30, random_fraction=1) == 8


@pytest.mark.asyncio
async def test_publish_uses_preallocated_task_id_before_marking_published() -> None:
    event = _event()
    session = _FakeSession(event)
    celery = Mock()
    celery.send_task = Mock(return_value=Mock(id=event.task_id))

    outcome = await publish_dispatch(
        session,
        event_id=event.id,
        celery_app=celery,
    )

    assert outcome.published is True
    assert event.status == "published"
    assert event.published_at is not None
    assert session.commits == 2
    assert celery.send_task.call_args.kwargs["task_id"] == event.task_id


@pytest.mark.asyncio
async def test_publish_failure_remains_durable_for_reconciliation() -> None:
    event = _event()
    session = _FakeSession(event)
    celery = Mock()
    celery.send_task = Mock(side_effect=ConnectionError("broker unavailable"))

    outcome = await publish_dispatch(
        session,
        event_id=event.id,
        celery_app=celery,
    )

    assert outcome.published is False
    assert event.status == "pending"
    assert event.attempt_count == 1
    assert "broker unavailable" in (event.last_error or "")
    assert event.available_at > datetime.now(UTC) - timedelta(seconds=1)


@pytest.mark.asyncio
async def test_expired_dispatch_lease_reuses_same_task_id() -> None:
    event = _event(status="dispatching")
    event.attempt_count = 1
    event.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session = _FakeSession(event)
    celery = Mock()
    celery.send_task = Mock()

    await publish_dispatch(session, event_id=event.id, celery_app=celery)

    assert event.status == "published"
    assert event.attempt_count == 2
    assert celery.send_task.call_args.kwargs["task_id"] == event.task_id


@pytest.mark.asyncio
async def test_event_key_payload_mismatch_is_terminal_contract_conflict() -> None:
    event = _event()
    session = _FakeSession(event)
    with pytest.raises(OutboxConflict, match="different payload"):
        await enqueue_dispatch(
            session,
            event_key=event.event_key,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            task_name=event.task_name,
            task_args=["different-run"],
            queue=event.queue,
        )
