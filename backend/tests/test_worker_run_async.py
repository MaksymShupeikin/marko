"""run_async must reset the DB pool so the next task's loop starts clean."""
from unittest.mock import AsyncMock, MagicMock

import pytest

import marko.infrastructure.db.session as db_session
from marko.worker.tasks import run_async


@pytest.fixture()
def disposed(monkeypatch):
    engine = MagicMock()
    engine.dispose = AsyncMock()
    monkeypatch.setattr(db_session, "engine", engine)
    return engine.dispose


def test_returns_result_and_disposes_engine(disposed):
    async def work():
        return 42

    assert run_async(work()) == 42
    disposed.assert_awaited_once()


def test_disposes_engine_on_failure(disposed):
    async def work():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        run_async(work())
    disposed.assert_awaited_once()
