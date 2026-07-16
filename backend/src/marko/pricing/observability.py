"""Low-cardinality structured events for pricing operations."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from typing import Any


logger = logging.getLogger("marko.pricing")


def pricing_event(event: str, **fields: Any) -> None:
    payload = {
        "event": event,
        "at": datetime.now(UTC).isoformat(),
        **{key: value for key, value in fields.items() if value is not None},
    }
    logger.info(json.dumps(payload, sort_keys=True, default=str))


__all__ = ["pricing_event"]
