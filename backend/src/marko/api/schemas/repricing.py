"""Request and response schemas for catalog repricing."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from marko.api.schemas.stores import CatalogFilterRequest


class RepricePreviewRequest(CatalogFilterRequest):
    mode: Literal["fresh", "resume"] = "fresh"


class CatalogSignatureResponse(BaseModel):
    """Каталог, відносно якого рахували: склад, а не ціни."""

    signature: str
    item_count: int
    store_ids: list[str] = Field(default_factory=list)


class RepricePreviewResponse(BaseModel):
    catalog: CatalogSignatureResponse
    # Скільки товарів під поточним фільтром узагалі є.
    matching: int
    # Скільки з каталогу вже пораховано під цією ж підписою.
    covered: int
    # Верхня межа повзунка.
    remaining: int
    # None — повний доступ, ліміту немає.
    checks_left: int | None = None
    last_run_signature: str | None = None
    signature_changed: bool = False


class ReconciliationResponse(BaseModel):
    """Як новий склад каталогу лягає на те, що вже пораховано."""

    signature_changed: bool
    previous_signature: str | None = None
    kept: int
    gone: int
    fresh: int


class RepriceRunRequest(CatalogFilterRequest):
    scope: Literal["full", "partial"] = "partial"
    mode: Literal["fresh", "resume"] = "fresh"
    policy: Literal["aggressive", "balanced", "hold_margin"] = "balanced"
    # Значення повзунка; для повного каталогу не потрібне.
    count: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_count_for_partial(self) -> "RepriceRunRequest":
        if self.scope == "partial" and self.count is None:
            raise ValueError(
                "Для часткової переоцінки вкажіть кількість товарів"
            )
        return self


class RepriceRunResponse(BaseModel):
    id: UUID
    sync_run_id: UUID | None
    scope: str
    mode: str
    policy: str
    engine: str
    requested_count: int | None
    catalog: CatalogSignatureResponse
    # Чи збігається каталог прогону з нинішнім складом каталогу.
    catalog_is_current: bool = True
    status: str
    progress_current: int = 0
    progress_total: int | None = None
    error: str | None = None
    changed_count: int = 0
    unchanged_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RepriceRunPageResponse(BaseModel):
    items: list[RepriceRunResponse]
    total: int
    limit: int
    offset: int


class RepriceItemResponse(BaseModel):
    listing_id: UUID
    position: int
    name: str
    sku: str | None = None
    brand: str | None = None
    store_name: str | None = None
    image_url: str | None = None
    url: str = ""
    currency: str = "UAH"

    status: str
    outcome: str | None = None
    reason: str | None = None

    old_price: Decimal | None = None
    new_price: Decimal | None = None
    delta_abs: Decimal | None = None
    delta_pct: Decimal | None = None
    # Ціна поїхала після розрахунку — рядок застарів, але не помилковий.
    price_changed_since: bool = False

    zone: str | None = None
    tier: str | None = None
    method: str | None = None
    confidence: Decimal | None = None
    offers_total: int = 0
    evidence: dict[str, Any] | None = None
    computed_at: datetime | None = None
    dismissed: bool = False


class RepriceItemPageResponse(BaseModel):
    items: list[RepriceItemResponse]
    total: int
    limit: int
    offset: int


class RepriceItemDismissResponse(BaseModel):
    listing_id: UUID
    dismissed: bool
