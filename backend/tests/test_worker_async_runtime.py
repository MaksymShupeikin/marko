"""Regression tests for the synchronous Celery-to-async bridge."""

from __future__ import annotations

import asyncio

from marko.worker.async_runtime import close_async_runtime, run_async


def test_run_async_reuses_one_event_loop_per_worker_process() -> None:
    async def current_loop() -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()

    try:
        first = run_async(current_loop())
        second = run_async(current_loop())

        assert first is second
        assert not first.is_closed()
    finally:
        close_async_runtime()


def test_close_async_runtime_allows_clean_reinitialization() -> None:
    async def current_loop() -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()

    first = run_async(current_loop())
    close_async_runtime()
    second = run_async(current_loop())

    try:
        assert first.is_closed()
        assert second is not first
        assert not second.is_closed()
    finally:
        close_async_runtime()
