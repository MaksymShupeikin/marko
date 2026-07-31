"""API contracts for immutable XLSX catalog snapshots."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CatalogImportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    content_sha256: str
    request_fingerprint: str | None
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


class CatalogSheetPreviewResponse(BaseModel):
    name: str
    row_count: int
    headers: list[str]
    suggested_mapping: dict[str, str]
    mapping_error: str | None
    sample_rows: list[dict[str, Any]]
    is_catalog_candidate: bool


class CatalogImportPreviewResponse(BaseModel):
    filename: str
    content_sha256: str
    content_size: int
    sheets: list[CatalogSheetPreviewResponse]
    requires_sheet_choice: bool
    max_size_bytes: int


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
    is_owned: bool
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


class OwnedCatalogStoreOptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    store_id: UUID
    external_id: str
    name: str


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
    recommended_price: Decimal | None = None
    recommendation_currency: str | None = None
    recommendation_action: str | None = None
    recommendation_computed_at: datetime | None = None


class OwnedCatalogPageResponse(BaseModel):
    items: list[OwnedCatalogProductResponse]
    total: int
    catalog_total: int
    listing_total: int
    duplicates_removed: int
    store_total: int
    stores: list[OwnedCatalogStoreOptionResponse]
    limit: int
    offset: int


class CatalogCompetitorOfferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    observation_id: UUID
    seller_id: str
    seller_name: str
    title: str
    url: str
    price: Decimal
    currency: str
    is_available: bool | None
    normalized_price: Decimal | None
    tier: str
    match_confidence: Decimal
    observed_at: datetime


class CatalogDiscoveredOfferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    discovery_offer_id: UUID
    source_listing_id: str
    seller_id: str
    seller_name: str
    title: str
    url: str
    sku: str | None
    brand: str | None
    sale_price: Decimal
    reference_price: Decimal | None
    currency: str
    measure_unit: str | None
    is_available: bool | None
    title_contains_query: bool
    identity_status: str
    source_confidence: Decimal
    reason_codes: list[str]
    selection_status: str
    selection_reason: str
    passed_gates: list[str]
    selection_flags: list[str]
    selection_details: dict[str, Any]
    predicted_tier: str
    tier_confidence: Decimal


class CatalogDiscoveryRequest(BaseModel):
    sku: str | None = Field(default=None, max_length=255)
    oe: str | None = Field(default=None, max_length=255)
    brand: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=2000)
    current_price: Decimal | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    category: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def require_identifier(self) -> CatalogDiscoveryRequest:
        if not (self.sku or "").strip() and not (self.oe or "").strip():
            raise ValueError("sku or oe is required")
        return self


class CatalogOeEnrichmentRequest(BaseModel):
    store_id: UUID
    external_id: str = Field(max_length=100)


class CatalogOeEnrichmentResponse(BaseModel):
    oe: str | None


class CatalogCompetitorComparisonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recommendation_id: UUID | None
    compared_at: datetime | None
    current_price: Decimal | None
    fair_price: Decimal | None
    recommended_price: Decimal | None
    currency: str | None
    # How trustworthy the basis was, and how widely it was spread, so the
    # card can show the arithmetic instead of only its conclusion.
    confidence_grade: str | None
    dispersion: Decimal | None
    reason_codes: list[str]
    items: list[CatalogCompetitorOfferResponse]
    discovery_run_id: UUID | None
    discovered_at: datetime | None
    discovery_query: str | None
    discovery_status: str | None
    prom_reported_total: int | None
    discovered_total: int
    discovery_retrieved_count: int
    discovery_persisted_count: int
    owned_excluded_count: int
    discovery_rejected_count: int
    pricing_evidence_count: int
    reference_only_count: int
    rejected_candidate_count: int
    selection_histogram: dict[str, int]
    search_pages_fetched: int
    search_page_limit: int
    unfetched_count: int
    coverage_ratio: Decimal | None
    coverage_reason: str | None
    selection_method_version: str | None
    selection_config_sha256: str | None
    brand_rules_dataset_id: str | None
    discovery_items: list[CatalogDiscoveredOfferResponse]
    # Counts towards the fair price.
    pricing_evidence: list[CatalogDiscoveredOfferResponse]
    # Same part, level unknown or unconvertible: shown with a link, never
    # priced against.
    reference_only: list[CatalogDiscoveredOfferResponse]
