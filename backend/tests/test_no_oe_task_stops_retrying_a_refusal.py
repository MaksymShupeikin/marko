"""A safety refusal must end the item, not loop on it.

``PRIVATE_KEMP_*`` is a decision about this row's own data: the row carries an
internal shelf code where a public number belongs, so the next attempt refuses
identically. The task retried it anyway — and because a worker restart resets
Celery's retry counter, run c2b9e71a still held five items in ``discovering``
four hours later, refusing and rescheduling every 60 s.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from marko.worker.tasks import pricing as pricing_tasks


class _Refused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@pytest.fixture
def task_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    calls: dict[str, list] = {"failed": [], "batch_failed": [], "retried": []}

    def _run_async(awaitable):
        # The service coroutines are replaced below; this only unwraps them.
        try:
            awaitable.close()
        except AttributeError:
            pass
        return None

    monkeypatch.setattr(pricing_tasks, "run_async", _run_async)
    monkeypatch.setattr(
        pricing_tasks, "get_pricing_item_run_id", lambda *a, **k: None
    )
    monkeypatch.setattr(
        pricing_tasks,
        "fail_pricing_item",
        lambda item_id, exc: calls["failed"].append((item_id, exc)) or None,
    )
    monkeypatch.setattr(
        pricing_tasks,
        "fail_no_oe_discovery_batch",
        lambda item_id, exc: calls["batch_failed"].append((item_id, exc)) or None,
    )
    return calls


def _invoke(monkeypatch: pytest.MonkeyPatch, error: Exception, calls: dict) -> None:
    item_id = uuid4()

    def _process(*_args: object, **_kwargs: object):
        raise error

    monkeypatch.setattr(pricing_tasks, "process_no_oe_discovery_item", _process)

    task = pricing_tasks.process_no_oe_discovery_item_task

    def _retry(**kwargs: object):
        calls["retried"].append(kwargs)
        raise RuntimeError("retry scheduled")

    monkeypatch.setattr(task, "retry", _retry)
    task.push_request(retries=0)
    try:
        with pytest.raises(Exception):
            task.run(str(item_id))
    finally:
        task.pop_request()


def test_a_private_kemp_refusal_fails_the_item_immediately(
    monkeypatch: pytest.MonkeyPatch, task_calls: dict
) -> None:
    _invoke(monkeypatch, _Refused("PRIVATE_KEMP_MODEL_INPUT_BLOCKED"), task_calls)

    assert task_calls["failed"], "the row must reach a terminal state"
    assert task_calls["retried"] == [], "a deterministic refusal was rescheduled"


def test_a_blocked_query_refusal_also_stops(
    monkeypatch: pytest.MonkeyPatch, task_calls: dict
) -> None:
    _invoke(monkeypatch, _Refused("PRIVATE_KEMP_QUERY_BLOCKED"), task_calls)

    assert task_calls["failed"]
    assert task_calls["retried"] == []


def test_a_transient_failure_is_still_retried(
    monkeypatch: pytest.MonkeyPatch, task_calls: dict
) -> None:
    """The narrowing must not turn every error into a permanent one."""

    _invoke(monkeypatch, _Refused("PROM_TIMEOUT"), task_calls)

    assert task_calls["retried"], "a transient failure lost its retry"
    assert task_calls["failed"] == []
