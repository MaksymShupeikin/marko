"""Schemas for stores, listings, and catalog synchronization."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from marko.services.bulk_products import CatalogFilter
from marko.services.parser_models import Seller


class StoreFileImportResponse(BaseModel):
    store_id: UUID
    store_name: str
    imported: int
    skipped: int


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
    # Каталог оновлюється цілком, без прив'язки до одного магазину.
    store_id: UUID | None = None
    sync_run_id: UUID
    status: str


class CatalogFilterRequest(BaseModel):
    """The catalog filter a bulk action applies to; empty means everything."""

    q: str | None = Field(default=None, max_length=200)
    price_min: float | None = Field(default=None, ge=0)
    price_max: float | None = Field(default=None, ge=0)
    source: Literal["export", "scrape"] | None = None

    def to_filter(self) -> CatalogFilter:
        return CatalogFilter(
            query=self.q,
            price_min=self.price_min,
            price_max=self.price_max,
            source=self.source,
        )


class BulkDeleteResponse(BaseModel):
    deleted: int


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


class CatalogProductResponse(ProductResponse):
    """A product plus the store it came from, for the workspace-wide catalog."""

    store_id: UUID
    store_name: str | None = None
    marketplace: str = ""
    oem_numbers: list[str] = Field(default_factory=list)
    can_manage: bool = False
    # "export" — прийшов з XLSX-вивантаження, "scrape" — знятий з майданчика.
    source: Literal["export", "scrape"] = "scrape"


class ProductUpdateRequest(BaseModel):
    """Fields a catalog manager may override without changing source identity."""

    name: str | None = Field(default=None, min_length=1, max_length=1000)
    sku: str | None = Field(default=None, max_length=255)
    brand: str | None = Field(default=None, max_length=255)
    current_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    is_available: bool | None = None
    image_url: str | None = Field(default=None, max_length=2048)
    oem_numbers: list[str] | None = Field(default=None, max_length=50)

    @field_validator("name", "sku", "brand", "image_url")
    @classmethod
    def normalize_text(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if info.field_name == "name" and not normalized:
            raise ValueError("Назва товару не може бути порожньою")
        if info.field_name == "image_url" and normalized and not normalized.startswith(
            ("https://", "http://")
        ):
            raise ValueError("Посилання на зображення має починатися з http:// або https://")
        return normalized or None

    @field_validator("oem_numbers")
    @classmethod
    def normalize_oem_numbers(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = value.strip()
            key = normalized.casefold()
            if normalized and key not in seen:
                result.append(normalized)
                seen.add(key)
        return result

    @model_validator(mode="after")
    def require_change(self) -> ProductUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("Вкажіть хоча б одне поле для оновлення")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Назва товару не може бути порожньою")
        return self


class CatalogPageResponse(BaseModel):
    items: list[CatalogProductResponse]
    total: int
    limit: int
    offset: int


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
