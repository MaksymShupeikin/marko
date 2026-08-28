"""Черга імпортів: магазини завантажуються по одному, а не навперейми."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from marko.infrastructure.db.models import SyncStatus
from marko.services import stores


def queued_run(workspace_id, *, task_id=None):
    return SimpleNamespace(
        id=uuid4(),
        workspace_id=workspace_id,
        status=SyncStatus.queued,
        task_id=task_id,
        error=None,
        finished_at=None,
    )


def celery_stub(task_id="task-1"):
    app = MagicMock()
    app.send_task.return_value = SimpleNamespace(id=task_id)
    return app


async def test_second_store_waits_while_the_first_imports(monkeypatch):
    """Зайнята черга — запуск лишається queued без task_id."""
    workspace_id = uuid4()
    sync_run = queued_run(workspace_id)
    session = AsyncMock()
    celery = celery_stub()
    monkeypatch.setattr(
        stores.stores_repo,
        "count_dispatched_sync_runs",
        AsyncMock(return_value=1),
    )

    await stores._dispatch_if_idle(session, sync_run, celery)

    celery.send_task.assert_not_called()
    assert sync_run.task_id is None
    assert sync_run.status == SyncStatus.queued


async def test_first_store_starts_immediately(monkeypatch):
    workspace_id = uuid4()
    sync_run = queued_run(workspace_id)
    session = AsyncMock()
    celery = celery_stub("task-abc")
    monkeypatch.setattr(
        stores.stores_repo,
        "count_dispatched_sync_runs",
        AsyncMock(return_value=0),
    )

    await stores._dispatch_if_idle(session, sync_run, celery)

    celery.send_task.assert_called_once_with(
        "marko.worker.import_store_catalog", args=[str(sync_run.id)]
    )
    assert sync_run.task_id == "task-abc"


async def test_finished_import_releases_the_next_one(monkeypatch):
    workspace_id = uuid4()
    waiting = queued_run(workspace_id)
    session = AsyncMock()
    celery = celery_stub("task-next")
    monkeypatch.setattr(
        stores.stores_repo,
        "count_dispatched_sync_runs",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        stores.stores_repo,
        "lock_next_queued_sync_run",
        AsyncMock(return_value=waiting),
    )

    started = await stores.dispatch_next_queued(session, workspace_id, celery)

    assert started is waiting
    assert waiting.task_id == "task-next"


async def test_busy_queue_is_not_double_dispatched(monkeypatch):
    """Поки хтось виконується, черга стоїть — навіть якщо в ній є охочі."""
    workspace_id = uuid4()
    session = AsyncMock()
    celery = celery_stub()
    monkeypatch.setattr(
        stores.stores_repo,
        "count_dispatched_sync_runs",
        AsyncMock(return_value=1),
    )
    locker = AsyncMock()
    monkeypatch.setattr(stores.stores_repo, "lock_next_queued_sync_run", locker)

    assert await stores.dispatch_next_queued(session, workspace_id, celery) is None
    locker.assert_not_awaited()
    celery.send_task.assert_not_called()


async def test_dead_task_does_not_freeze_the_queue(monkeypatch):
    """Запуск, який не став у чергу Celery, позначається збоєм — беремо наступний."""
    workspace_id = uuid4()
    broken = queued_run(workspace_id)
    healthy = queued_run(workspace_id)
    session = AsyncMock()
    celery = MagicMock()
    celery.send_task.side_effect = [
        RuntimeError("broker down"),
        SimpleNamespace(id="task-ok"),
    ]
    monkeypatch.setattr(
        stores.stores_repo,
        "count_dispatched_sync_runs",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        stores.stores_repo,
        "lock_next_queued_sync_run",
        AsyncMock(side_effect=[broken, healthy]),
    )

    started = await stores.dispatch_next_queued(session, workspace_id, celery)

    assert started is healthy
    assert healthy.task_id == "task-ok"
    assert broken.status == SyncStatus.failed


async def test_empty_queue_returns_nothing(monkeypatch):
    session = AsyncMock()
    monkeypatch.setattr(
        stores.stores_repo,
        "count_dispatched_sync_runs",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        stores.stores_repo,
        "lock_next_queued_sync_run",
        AsyncMock(return_value=None),
    )

    assert await stores.dispatch_next_queued(session, uuid4(), celery_stub()) is None


async def test_cancelling_a_run_starts_the_next_store(monkeypatch):
    workspace_id = uuid4()
    running = SimpleNamespace(
        id=uuid4(),
        workspace_id=workspace_id,
        status=SyncStatus.running,
        task_id="task-running",
        finished_at=None,
    )
    session = AsyncMock()
    celery = MagicMock()
    monkeypatch.setattr(
        stores, "get_sync_run", AsyncMock(return_value=running)
    )
    following = AsyncMock(return_value=None)
    monkeypatch.setattr(stores, "dispatch_next_queued", following)

    await stores.cancel_sync_run(
        session,
        sync_run_id=running.id,
        workspace_id=workspace_id,
        celery_app=celery,
    )

    assert running.status == SyncStatus.cancelled
    following.assert_awaited_once_with(session, workspace_id, celery)


async def test_active_runs_are_listed_in_queue_order(monkeypatch):
    """Перший у списку — той, що виконується; далі — за часом створення."""
    workspace_id = uuid4()
    first = queued_run(workspace_id, task_id="task-1")
    second = queued_run(workspace_id)
    store = SimpleNamespace(name="kemp", logo_url="https://cdn/logo.png")
    session = AsyncMock()
    monkeypatch.setattr(
        stores.stores_repo,
        "list_active_sync_runs",
        AsyncMock(return_value=[(first, store), (second, None)]),
    )

    views = await stores.list_active_sync_runs(session, workspace_id)

    assert [view.sync_run for view in views] == [first, second]
    assert views[0].store_name == "kemp"
    assert views[0].store_logo_url == "https://cdn/logo.png"
    assert views[1].store_name is None


async def test_listing_active_runs_heals_a_stalled_queue(monkeypatch):
    """Ніхто не виконується, а в черзі є охочі — зрушуємо на опитуванні фронта."""
    workspace_id = uuid4()
    session = AsyncMock()
    celery = celery_stub()
    healer = AsyncMock(return_value=None)
    monkeypatch.setattr(stores, "dispatch_next_queued", healer)
    monkeypatch.setattr(
        stores.stores_repo, "list_active_sync_runs", AsyncMock(return_value=[])
    )

    await stores.list_active_sync_runs(session, workspace_id, celery)

    healer.assert_awaited_once_with(session, workspace_id, celery)
