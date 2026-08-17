"""API contracts for immutable XLSX catalog snapshots."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CatalogDataEvidenceResponse(BaseModel):
    """Provenance of customer catalog evidence, never an identity override."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["OE_CONFIRMED", "MPN_ONLY", "CANDIDATE_REVIEW", "NO_OE_REVIEW"] = (
        "NO_OE_REVIEW"
    )
    review_only: bool = True
    internal_code: str | None = None
    oe_sources: list[str] = Field(default_factory=list)
    evidence_url: str | None = None
    confirmed_cross_numbers: list[str] = Field(default_factory=list)
    candidate_numbers: list[str] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)
    no_oe_reason: str | None = None


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


class CatalogTerminalRowResponse(BaseModel):
    source_ordinal: int
    source_row: int
    terminal_status: str
    catalog_item_id: UUID | None = None
    sku: str | None = None
    oe_norm: str | None = None
    reason_codes: list[str]
    details: list[str]
    pricing_run_item_id: UUID | None = None
    pricing_terminal_status: str | None = None
    pricing_terminal: bool | None = None
    pricing_terminal_reason: str | None = None
    pricing_error: str | None = None
    recommendation_id: UUID | None = None
    recommendation_action: str | None = None


class CatalogTerminalManifestResponse(BaseModel):
    manifest_version: str
    batch_id: UUID
    pricing_run_id: UUID | None = None
    pricing_run_status: str | None = None
    catalog_content_sha256: str
    row_outcomes_contract_version: str | None
    source: str
    expected_rows: int
    manifest_rows: int
    import_manifest_complete: bool
    pricing_replay_complete: bool | None = None
    pricing_terminal_rows: int | None = None
    pricing_nonterminal_rows: int | None = None
    pricing_missing_run_items: int | None = None
    complete: bool
    verification_status: str
    row_outcomes_sha256: str | None
    recomputed_sha256: str
    hash_verified: bool
    silent_loss_count: int
    replay_manifest_sha256: str | None = None
    rows: list[CatalogTerminalRowResponse]


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
    search_identity: str | None = None
    identity_status: str = "UNRESOLVED"
    catalog_data_evidence: CatalogDataEvidenceResponse = Field(
        default_factory=CatalogDataEvidenceResponse
    )
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


class CatalogKempLinkRowResponse(BaseModel):
    catalog_item_id: str
    source_row: int
    internal_code_norm: str
    listing_ids: list[str]
    store_ids: list[str]
    ambiguous_listing_ids: list[str]
    catalog_code_count: int
    evidence_missing_listing_ids: list[str]
    status: str
    requires_single_card_consumer_stop: bool


class CatalogKempLinkReportResponse(BaseModel):
    report_version: str
    generated_at: str
    catalog_positions: int
    catalog_positions_with_code: int
    catalog_positions_without_code: int
    matched_catalog_positions: int
    matched_listing_cards: int
    unmatched_catalog_positions: int
    ambiguous_catalog_positions: int
    owned_listing_count: int
    snapshots_without_part_numbers: int
    listings_with_one_internal_code: int
    listings_with_multiple_internal_codes: int
    bootstrap_evidence_rows: int = 0
    bootstrap_source_sha256: str | None = None
    rows: list[CatalogKempLinkRowResponse]
    interpretation: dict[str, Any]


class CatalogKempLinkRebuildRequest(BaseModel):
    max_items: int | None = Field(default=None, ge=1, le=100_000)


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
    listing_id: UUID | None = None
    source_listing_id: str | None = None
    snapshot_at: datetime | None = None


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
    mpn: str | None = None
    model_id: str | None
    brand: str | None
    image_url: str | None
    price_min: Decimal | None
    price_max: Decimal | None
    currency: str | None
    listing_count: int
    stores: list[OwnedCatalogStoreResponse]
    internal_code: str | None = None
    kemp_link_status: str | None = None
    identity_status: str | None = None
    catalog_data_evidence: dict[str, Any] | None = None
    owned_listings: list[OwnedCatalogStoreResponse] = Field(default_factory=list)
    recommended_price: Decimal | None = None
    recommendation_currency: str | None = None
    recommendation_action: str | None = None
    recommendation_computed_at: datetime | None = None


class OwnedCatalogPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    automatic_eligible: bool = False
    hard_gate_result: str = "MANUAL_REVIEW"
    oe_verification_status: str = "UNKNOWN"
    reason_codes: list[str] = Field(default_factory=list)


class CatalogDiscoveredOfferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    discovery_offer_id: UUID
    source_listing_id: str
    seller_id: str
    seller_name: str
    title: str
    url: str
    sku: str | None
    mpn: str | None = None
    oe_raw: str | None = None
    part_numbers: list[str] = Field(default_factory=list)
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
    mpn: str | None = Field(default=None, max_length=255)
    brand: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=2000)
    current_price: Decimal | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    category: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def require_identifier(self) -> CatalogDiscoveryRequest:
        if not any((value or "").strip() for value in (self.sku, self.oe, self.mpn)):
            raise ValueError("sku, oe or mpn is required")
        return self


class CatalogOeEnrichmentRequest(BaseModel):
    store_id: UUID
    external_id: str = Field(max_length=100)


class CatalogOeEnrichmentResponse(BaseModel):
    oe: str | None


class CatalogIdentifierEnrichmentResponse(BaseModel):
    oe: str | None
    mpn: str | None
    status: str


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
    # Discovery rows are never admitted to a fair-price calculation. Actual
    # price evidence is the recommendation's persisted ``items`` set.
    pricing_evidence: list[CatalogDiscoveredOfferResponse]
    # Same part, level unknown or unconvertible: shown with a link, never
    # priced against.
    reference_only: list[CatalogDiscoveredOfferResponse]
    candidate_items: list[CatalogCompetitorOfferResponse] = Field(default_factory=list)
    collection_status: str | None = None
