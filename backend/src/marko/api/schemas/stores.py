"""Schemas for stores, listings, and catalog synchronization."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from marko.services.parser_models import Seller


class StoreCreateRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def validate_prom_store_url(cls, value: str) -> str:
        normalized = value.strip()
        Seller.from_url(normalized)
        return normalized


class StoreResponse(BaseModel):
    id: UUID
    marketplace: str
    external_id: str
    name: str | None
    url: str
    kind: str
    product_count: int
    last_synced_at: datetime | None


class StoreSyncResponse(BaseModel):
    store_id: UUID
    sync_run_id: UUID
    status: str


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    external_id: str
    name: str
    url: str
    sku: str | None
    model_id: str | None
    brand: str | None
    currency: str
    current_price: Decimal | None
    is_available: bool | None
    last_seen_at: datetime


class ProductPageResponse(BaseModel):
    items: list[ProductResponse]
    total: int
    limit: int
    offset: int


class SyncRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID | None
    store_id: UUID | None
    kind: str
    status: str
    progress_current: int
    progress_total: int | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
