from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from marko.api.routers.v1 import operations
from marko.api.schemas.operations import ClientErrorEventRequest


def _event() -> ClientErrorEventRequest:
    return ClientErrorEventRequest(
        event_id="evt-0123456789abcdef",
        kind="zone",
        exception_type="StateError",
        message_fingerprint="a" * 64,
        stack_frames=["main.dart:10:3"],
        route="/pricing/recommendations",
        correlation_id="request-123",
        release="1.0.0+1",
        occurred_at="2026-07-30T12:00:00Z",
    )


def test_client_error_contract_rejects_raw_exception_payloads() -> None:
    with pytest.raises(ValidationError):
        ClientErrorEventRequest.model_validate(
            {**_event().model_dump(), "raw_message": "cost=1234.56"}
        )


@pytest.mark.asyncio
async def test_client_error_endpoint_emits_only_bounded_safe_fields(monkeypatch) -> None:
    captured: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        operations,
        "pricing_event",
        lambda name, **fields: captured.append((name, fields)),
    )
    current = SimpleNamespace(
        workspace_id=uuid4(),
        user=SimpleNamespace(id=uuid4()),
    )

    response = await operations.record_client_error(_event(), current)

    assert response.status == "accepted"
    assert captured[0][0] == "client_unhandled_error"
    assert captured[0][1]["message_fingerprint"] == "a" * 64
    assert "raw_message" not in captured[0][1]
