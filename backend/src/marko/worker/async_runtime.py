"""Process-local asyncio runtime for synchronous Celery task entry points.

SQLAlchemy's asyncpg pool binds connections to the event loop that opened them.
Creating a fresh loop with ``asyncio.run`` for every service call therefore
leaves pooled connections attached to closed loops.  Celery prefork workers
execute tasks synchronously, so one persistent runner per worker process keeps
all async database work on the same loop.
"""

from __future__ import annotations

import asyncio
import atexit
from collections.abc import Coroutine
import os
import threading
from typing import Any, TypeVar


T = TypeVar("T")

_runner: asyncio.Runner | None = None
_runner_pid: int | None = None
_runner_lock = threading.Lock()


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine on the current Celery worker process's persistent loop."""

    with _runner_lock:
        runner = _get_runner()
        return runner.run(coro)


def close_async_runtime() -> None:
    """Close the runner owned by this process, if one has been created."""

    global _runner, _runner_pid

    with _runner_lock:
        runner = _runner
        owner_pid = _runner_pid
        _runner = None
        _runner_pid = None
        if runner is not None and owner_pid == os.getpid():
            runner.close()


def _get_runner() -> asyncio.Runner:
    global _runner, _runner_pid

    current_pid = os.getpid()
    if _runner is None or _runner_pid != current_pid:
        # A runner copied by ``fork`` belongs to the parent process. Discard it
        # and lazily create a clean loop in the child on its first task.
        _runner = asyncio.Runner()
        _runner_pid = current_pid
    return _runner


atexit.register(close_async_runtime)
