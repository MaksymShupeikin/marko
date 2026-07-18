"""Operational API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


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
