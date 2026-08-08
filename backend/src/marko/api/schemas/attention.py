"""User-facing contracts for the live price-attention queue."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AttentionSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: int
    overpriced: int
    underpriced: int
    in_market: int
    review_required: int
    no_data: int
    processing: int
    updated_at: datetime | None


class AttentionItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: UUID
    recommendation_id: UUID | None
    name: str
    sku: str | None
    oe: str | None
    brand: str | None
    source_kind: str
    source_id: UUID
    status: str
    severity: int
    our_price: Decimal | None
    market_low: Decimal | None
    market_high: Decimal | None
    suggested_price: Decimal | None
    currency: str
    difference_percent: Decimal | None
    confidence: Decimal
    evidence_count: int
    reason_codes: tuple[str, ...]
    market_checked_at: datetime | None
    updated_at: datetime


class AttentionPageResponse(BaseModel):
    items: list[AttentionItemResponse]
    total: int
    limit: int
    offset: int
