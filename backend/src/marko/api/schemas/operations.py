"""Operational API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ClientErrorEventRequest(BaseModel):
    event_id: str = Field(min_length=8, max_length=64, pattern=r"^evt-[0-9a-f]+$")
    kind: Literal["flutter", "platform", "zone"]
    exception_type: str = Field(min_length=1, max_length=120)
    message_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    stack_frames: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(
        max_length=8
    )
    route: str | None = Field(default=None, max_length=200)
    correlation_id: str | None = Field(
        default=None,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    release: str = Field(min_length=1, max_length=64)
    occurred_at: datetime

    model_config = ConfigDict(extra="forbid")


class ClientErrorEventResponse(BaseModel):
    status: Literal["accepted"]


class DeadLetterResponse(BaseModel):
    kind: Literal["store_sync", "pricing_target"]
    id: UUID
    parent_id: UUID | None
    error_category: str
    error_detail: str
    attempts: int
    terminal_at: datetime


class DeadLetterPageResponse(BaseModel):
    items: list[DeadLetterResponse]
    total: int
    limit: int
    offset: int


class DeadLetterReplayResponse(BaseModel):
    kind: Literal["store_sync", "pricing_target"]
    dead_letter_id: UUID
    workflow_id: UUID
    workflow_status: str


class DiscoveryFunnelResponse(BaseModel):
    generated_at: datetime
    correlation_id: str | None
    sampled_runs: int
    run_status_counts: dict[str, int]
    total_candidates: int
    status_counts: dict[str, int]
    selection_reasons: dict[str, int]
    coverage: dict[str, int | str | None]
    gates: dict[str, dict[str, int | str | None]]
    categories: list[dict[str, Any]]
