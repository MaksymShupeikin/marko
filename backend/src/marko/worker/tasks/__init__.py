"""Celery tasks."""
from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from marko.infrastructure.db import session as db_session


def run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a task coroutine on a fresh event loop, resetting the DB pool after.

    Celery запускає кожну задачу через новий event loop, а пул asyncpg тримає
    з'єднання, прив'язані до попереднього loop'а — без dispose друга задача
    падає з "got Future attached to a different loop".
    """

    async def _run() -> Any:
        try:
            return await coro
        finally:
            await db_session.engine.dispose()

    return asyncio.run(_run())
