"""API contracts for immutable XLSX catalog snapshots."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CatalogImportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    content_sha256: str
    content_size: int
    status: str
    column_mapping: dict[str, str]
    total_rows: int
    imported_rows: int
    rejected_rows: int
    error_log: list[dict[str, Any]]
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class CatalogImportPageResponse(BaseModel):
    items: list[CatalogImportResponse]
    total: int
    limit: int
    offset: int


class CatalogItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    import_batch_id: UUID
    source_row: int
    sku: str
    oe_raw: str
    oe_norm: str
    mpn_raw: str
    mpn_norm: str
    name: str
    category: str
    brand: str | None
    description: str | None
    product_url: str | None
    current_price: Decimal
    currency: str
    is_available: bool | None
    stock_status: str
    stock_qty: Decimal | None
    stock_age_days: Decimal | None
    expected_units_sold: Decimal | None
    cost_configured: bool
    cost_privacy_mode: str
    manual_priority: Decimal
    raw_row: dict[str, Any]
    created_at: datetime


class CatalogItemPageResponse(BaseModel):
    items: list[CatalogItemResponse]
    total: int
    limit: int
    offset: int


class OwnedCatalogStoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    store_id: UUID
    external_id: str
    name: str
    url: str
    listing_url: str
    listing_count: int
    price: Decimal | None
    currency: str
    is_available: bool | None


class OwnedCatalogProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    identity_kind: str
    name: str
    sku: str | None
    oe: str | None
    model_id: str | None
    brand: str | None
    image_url: str | None
    price_min: Decimal | None
    price_max: Decimal | None
    currency: str | None
    listing_count: int
    stores: list[OwnedCatalogStoreResponse]


class OwnedCatalogPageResponse(BaseModel):
    items: list[OwnedCatalogProductResponse]
    total: int
    catalog_total: int
    listing_total: int
    duplicates_removed: int
    store_total: int
    limit: int
    offset: int
