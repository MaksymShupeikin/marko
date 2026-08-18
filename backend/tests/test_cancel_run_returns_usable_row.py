"""Cancelling a run must hand back a row the response model can read.

``session.commit()`` expires every attribute of the instance it just wrote. The
cancel endpoint returned that expired instance straight to
``PricingRunResponse.model_validate``, which then tried to reload it outside the
async context: the operator pressed «Отменить расчёт», the server accepted the
cancellation, and the UI showed ``ClientException: Failed to fetch`` over a
``MissingGreenlet`` 500. Observed live on 2026-08-18.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from marko.services import pricing_runs


class _RecordingSession:
    """Records the order of the two calls that decide whether the row is usable."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def commit(self) -> None:
        self.calls.append("commit")

    async def refresh(self, instance: object) -> None:
        self.calls.append("refresh")


@pytest.fixture
def run() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), status="collecting", cancel_requested=False)


async def test_cancellation_refreshes_the_row_after_committing(
    monkeypatch: pytest.MonkeyPatch, run: SimpleNamespace
) -> None:
    session = _RecordingSession()

    async def _get_pricing_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return run

    monkeypatch.setattr(pricing_runs, "get_pricing_run", _get_pricing_run)

    result = await pricing_runs.cancel_pricing_run(
        session,  # type: ignore[arg-type]
        workspace_id=uuid4(),
        run_id=run.id,
    )

    assert result is run
    assert run.cancel_requested is True
    assert session.calls == ["commit", "refresh"], (
        "an expired instance reaches the response model and the operator sees a 500"
    )


@pytest.mark.parametrize("status", ["completed", "partial", "failed", "cancelled"])
async def test_a_terminal_run_is_returned_without_touching_the_session(
    monkeypatch: pytest.MonkeyPatch, run: SimpleNamespace, status: str
) -> None:
    """Nothing was written, so there is nothing to refresh."""

    run.status = status
    session = _RecordingSession()

    async def _get_pricing_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return run

    monkeypatch.setattr(pricing_runs, "get_pricing_run", _get_pricing_run)

    result = await pricing_runs.cancel_pricing_run(
        session,  # type: ignore[arg-type]
        workspace_id=uuid4(),
        run_id=run.id,
    )

    assert result is run
    assert run.cancel_requested is False
    assert session.calls == []
