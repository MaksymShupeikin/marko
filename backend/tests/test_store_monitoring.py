from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from marko.services import store_monitoring
from marko.services.store_monitoring import schedule_due_store_monitoring


class _Rows:
    def __init__(self, values) -> None:
        self.values = values

    def all(self):
        return self.values


class _Session:
    def __init__(self, pairs) -> None:
        self.pairs = pairs
        self.execute_calls = 0

    async def execute(self, _statement):
        self.execute_calls += 1
        return _Rows(self.pairs)


def _settings(*, permitted: bool = True, enabled: bool = True):
    return SimpleNamespace(
        prom_marketplace_source_access_verdict=(
            "PERMITTED_LIMITED" if permitted else "NOT_PERMITTED"
        ),
        prom_marketplace_source_access_reference=("owner-consent" if permitted else ""),
        store_monitoring_enabled=enabled,
        store_monitoring_refresh_interval_seconds=3600,
        store_monitoring_batch_size=10,
    )


@pytest.mark.asyncio
async def test_periodic_store_monitoring_is_fail_closed_without_source_access() -> None:
    session = _Session([(uuid4(), uuid4())])

    report = await schedule_due_store_monitoring(
        session,  # type: ignore[arg-type]
        celery_app=object(),  # type: ignore[arg-type]
        settings=_settings(permitted=False),  # type: ignore[arg-type]
    )

    assert report.enabled is True
    assert report.live_collection_allowed is False
    assert report.scheduled == 0
    assert session.execute_calls == 0


@pytest.mark.asyncio
async def test_periodic_store_monitoring_queues_each_due_owned_store(
    monkeypatch,
) -> None:
    pairs = [(uuid4(), uuid4()), (uuid4(), uuid4())]
    session = _Session(pairs)
    queued = []

    async def fake_queue_store_sync(
        _session,
        *,
        store_id,
        workspace_id,
        celery_app,
    ) -> None:
        queued.append((workspace_id, store_id, celery_app))

    monkeypatch.setattr(store_monitoring, "queue_store_sync", fake_queue_store_sync)
    celery = object()

    report = await schedule_due_store_monitoring(
        session,  # type: ignore[arg-type]
        celery_app=celery,  # type: ignore[arg-type]
        settings=_settings(),  # type: ignore[arg-type]
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )

    assert report.due == 2
    assert report.scheduled == 2
    assert queued == [
        (pairs[0][0], pairs[0][1], celery),
        (pairs[1][0], pairs[1][1], celery),
    ]


# Решение заказчика 2026-08-21: прогоны проверки цен не стартуют сами.
# Обе точки автозапуска обязаны молча выйти до первого обращения к базе.


class _ExplodingSessionFactory:
    def __call__(self):
        raise AssertionError("attention run must not touch the database when disabled")


class _ExplodingSession:
    def __getattr__(self, name):
        raise AssertionError("attention run must not touch the session when disabled")


@pytest.mark.asyncio
async def test_store_monitoring_run_is_silenced_by_attention_flag(monkeypatch) -> None:
    from marko.services import attention

    monkeypatch.setattr(
        attention,
        "get_settings",
        lambda: SimpleNamespace(attention_monitoring_enabled=False),
    )
    monkeypatch.setattr(
        attention, "async_session_factory", _ExplodingSessionFactory()
    )

    result = await attention.start_store_monitoring_run(uuid4(), object())

    assert result is None


@pytest.mark.asyncio
async def test_import_monitoring_run_is_silenced_by_attention_flag(monkeypatch) -> None:
    from marko.services import attention

    monkeypatch.setattr(
        attention,
        "get_settings",
        lambda: SimpleNamespace(attention_monitoring_enabled=False),
    )
    batch = SimpleNamespace(
        status="completed",
        imported_rows=5,
        id=uuid4(),
        workspace_id=uuid4(),
    )

    result = await attention.start_import_monitoring_run(
        _ExplodingSession(),  # type: ignore[arg-type]
        batch=batch,  # type: ignore[arg-type]
        celery_app=object(),  # type: ignore[arg-type]
    )

    assert result is None


@pytest.mark.asyncio
async def test_import_monitoring_gate_is_the_only_thing_stopping_the_run(
    monkeypatch,
) -> None:
    """With the flag on, the same call must get past the gate (and hit the DB)."""

    from marko.services import attention

    monkeypatch.setattr(
        attention,
        "get_settings",
        lambda: SimpleNamespace(attention_monitoring_enabled=True),
    )
    batch = SimpleNamespace(
        status="completed",
        imported_rows=5,
        id=uuid4(),
        workspace_id=uuid4(),
    )

    with pytest.raises(AssertionError, match="must not touch the session"):
        await attention.start_import_monitoring_run(
            _ExplodingSession(),  # type: ignore[arg-type]
            batch=batch,  # type: ignore[arg-type]
            celery_app=object(),  # type: ignore[arg-type]
        )
