from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from marko.infrastructure.db.models import SyncStatus
from marko.services import stores


def _run(status: SyncStatus, task_id: str | None = "task-1") -> SimpleNamespace:
    return SimpleNamespace(status=status, task_id=task_id, finished_at=None)


async def test_cancel_revokes_running_task(monkeypatch):
    sync_run = _run(SyncStatus.running)
    session = AsyncMock()
    celery = MagicMock()
    monkeypatch.setattr(stores, "get_sync_run", AsyncMock(return_value=sync_run))

    result = await stores.cancel_sync_run(
        session, sync_run_id=uuid4(), workspace_id=uuid4(), celery_app=celery
    )

    celery.control.revoke.assert_called_once_with("task-1", terminate=True)
    assert result.status == SyncStatus.cancelled
    assert result.finished_at is not None
    session.commit.assert_awaited_once()


async def test_cancel_finished_run_is_noop(monkeypatch):
    sync_run = _run(SyncStatus.completed)
    session = AsyncMock()
    celery = MagicMock()
    monkeypatch.setattr(stores, "get_sync_run", AsyncMock(return_value=sync_run))

    result = await stores.cancel_sync_run(
        session, sync_run_id=uuid4(), workspace_id=uuid4(), celery_app=celery
    )

    celery.control.revoke.assert_not_called()
    assert result.status == SyncStatus.completed
    session.commit.assert_not_awaited()
