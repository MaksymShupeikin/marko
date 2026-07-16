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
    image_url: str | None
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
    scrape_item_version: str
    scrape_state: str
    scrape_deduplicated_submissions: int
    scrape_task_executions: int
    scrape_task_redeliveries: int
    scrape_max_task_executions: int
    scrape_deadline_at: datetime | None
    scrape_owner_task_id: str | None
    scrape_lease_expires_at: datetime | None
    scrape_checkpoint: dict | None
    scrape_catalog_pages: int
    scrape_products_extracted: int
    scrape_products_persisted: int
    scrape_duplicate_products: int
    scrape_database_writes: int
    scrape_raw_evidence_bytes: int
    scrape_structured_completeness: Decimal | None
    scrape_evidence_coverage: Decimal | None
    progress_current: int
    progress_total: int | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
