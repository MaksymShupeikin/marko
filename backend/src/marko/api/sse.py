"""Звіт про ціни конкурентів як потік подій: стадії, потім готовий результат."""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi.responses import StreamingResponse

from marko.services.competitor_prices import (
    PartSearchQuery,
    competitor_prices_for_query,
)


def competitor_price_stream(
    query: PartSearchQuery, *, refresh: bool = False
) -> StreamingResponse:
    """SSE: `{stage, message}` поки джерела збираються, наприкінці `{stage: done, report}`.

    Запит до бази має бути зроблений ДО виклику: генератор працює вже після
    того, як FastAPI закрив залежності, і сесії тут вже немає.
    """

    async def events() -> AsyncIterator[str]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def run() -> None:
            try:
                payload = await competitor_prices_for_query(
                    query,
                    refresh=refresh,
                    on_event=lambda stage, message: queue.put_nowait(
                        {"stage": stage, "message": message}
                    ),
                )
                queue.put_nowait({"stage": "done", "report": payload})
            except Exception as exc:  # noqa: BLE001 — клієнт має побачити причину
                queue.put_nowait({"stage": "error", "message": str(exc)})
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(run())
        try:
            while (event := await queue.get()) is not None:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            task.cancel()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
