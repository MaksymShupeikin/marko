"""Versioned API contracts for pricing runs, calibration, and decisions."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from metis.pricing import (
    CoefficientModel,
    CompetitorOffer,
    ProductPricingContext,
    ProductTier,
    StockStatus,
    TierCoefficient,
)


class PricingRunCreateRequest(BaseModel):
    import_batch_id: UUID
    policy: dict[str, Any] | None = None


class PricingRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    import_batch_id: UUID
    status: str
    policy_version: str
    policy_config: dict[str, Any]
    parser_version: str
    classifier_version: str
    coefficient_model: str
    coefficient_version: str | None
    calibration_dataset_hash: str | None
    calibration_started_at: datetime | None
    calibration_completed_at: datetime | None
    total_items: int
    completed_items: int
    failed_items: int
    manual_review_items: int
    cancel_requested: bool
    finalizer_task_id: str | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PricingRunPageResponse(BaseModel):
    items: list[PricingRunResponse]
    total: int
    limit: int
    offset: int


class ScraperMetricsResponse(BaseModel):
    generated_at: datetime
    scope_id: UUID
    item_kind: str
    item_version: str
    configuration_fingerprint: str
    dataset_fingerprint: str | None
    item_lifecycle: dict[str, Any]
    reconciliation: dict[str, Any]
    retry: dict[str, Any]
    capacity: dict[str, Any]
    latency_seconds: dict[str, Any]
    requests: dict[str, Any]
    queue_workers: dict[str, Any]
    domain_output: dict[str, Any]
    rates: dict[str, Any]
    storage: dict[str, Any]
    resources_dependencies: dict[str, Any]
    compatibility_metrics: dict[str, Any] | None = None
    warnings: list[str]


class CalibrationPairInput(BaseModel):
    oe_norm: str = Field(min_length=3, max_length=255)
    category: str = Field(min_length=1, max_length=255)
    tier: ProductTier
    tier_price: Decimal = Field(gt=0)
    reference_price: Decimal = Field(gt=0)
    quality_weight: Decimal = Field(default=Decimal("1"), gt=0, le=1)
    tier_observation_ids: tuple[str, ...] = ()
    reference_observation_ids: tuple[str, ...] = ()


class CalibrationRequest(BaseModel):
    model: CoefficientModel = CoefficientModel.SHRINKAGE
    pairs: list[CalibrationPairInput] = Field(min_length=1, max_length=100_000)
    shrinkage_k: Decimal = Field(default=Decimal("10"), gt=0)
    min_category_pairs: int = Field(default=8, ge=3, le=1000)
    min_global_pairs: int = Field(default=20, ge=3, le=100_000)
    min_effective_pairs: Decimal = Field(default=Decimal("5"), gt=0)
    max_interval_ratio: Decimal = Field(default=Decimal("3"), gt=1)


class TierCoefficientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category: str
    tier: str
    model: str
    multiplier: Decimal
    sample_size: int
    effective_sample_size: Decimal
    confidence: Decimal
    interval_low: Decimal | None
    interval_high: Decimal | None
    shrinkage_weight: Decimal | None
    validated: bool
    dataset_hash: str
    method_version: str
    coefficient_version: str
    policy_version: str
    validation_reasons: list[str]
    is_selected: bool
    pricing_run_id: UUID | None
    computed_at: datetime


class TierCoefficientPageResponse(BaseModel):
    items: list[TierCoefficientResponse]
    total: int
    limit: int
    offset: int


class CatalogItemOverrideRequest(BaseModel):
    stock_status: Literal["fresh", "stale", "dead_stock", "unknown"] | None = None
    cost: Decimal | None = Field(default=None, gt=0)
    stock_qty: Decimal | None = Field(default=None, ge=0)
    stock_age_days: Decimal | None = Field(default=None, ge=0)
    expected_units_sold: Decimal | None = Field(default=None, ge=0)
    units_sold_30d: Decimal | None = Field(default=None, ge=0)
    units_sold_60d: Decimal | None = Field(default=None, ge=0)
    units_sold_90d: Decimal | None = Field(default=None, ge=0)
    days_since_last_sale: Decimal | None = Field(default=None, ge=0)
    historical_monthly_units: Decimal | None = Field(default=None, ge=0)
    views_30d: Decimal | None = Field(default=None, ge=0)
    conversion_rate_proxy: Decimal | None = Field(default=None, ge=0, le=1)
    manual_priority: Decimal | None = Field(default=None, gt=0)
    liquidity_target: Decimal | None = Field(default=None, ge=0, le=1)
    urgency: Decimal | None = Field(default=None, ge=0, le=1)
    allow_below_cost: bool = False
    below_cost_floor: Decimal | None = Field(default=None, ge=0)
    below_cost_warning_confirmed: bool = False
    reason: str = Field(min_length=3, max_length=2000)

    @model_validator(mode="after")
    def validate_below_cost_override(self):
        if self.allow_below_cost and self.below_cost_floor is None:
            raise ValueError("below_cost_floor is required when allow_below_cost=true")
        if self.allow_below_cost and not self.below_cost_warning_confirmed:
            raise ValueError("below-cost warning confirmation is required")
        return self


class CatalogItemOverrideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    catalog_item_id: UUID
    user_id: UUID | None
    stock_status: str | None
    cost: Decimal | None
    stock_qty: Decimal | None
    stock_age_days: Decimal | None
    expected_units_sold: Decimal | None
    units_sold_30d: Decimal | None
    units_sold_60d: Decimal | None
    units_sold_90d: Decimal | None
    days_since_last_sale: Decimal | None
    historical_monthly_units: Decimal | None
    views_30d: Decimal | None
    conversion_rate_proxy: Decimal | None
    manual_priority: Decimal | None
    liquidity_target: Decimal | None
    urgency: Decimal | None
    allow_below_cost: bool
    below_cost_floor: Decimal | None
    below_cost_warning_confirmed: bool
    reason: str
    created_at: datetime


class RecommendationResponse(BaseModel):
    id: UUID
    pricing_run_id: UUID
    catalog_snapshot_id: UUID
    catalog_item_id: UUID
    sku: str
    oe_norm: str
    name: str
    category: str
    stock_status: str
    context_snapshot: dict[str, Any]
    calculation_trace: dict[str, Any]
    action: str
    current_price: Decimal
    fair_price: Decimal | None
    recommended_price: Decimal | None
    lower_bound: Decimal | None
    upper_bound: Decimal | None
    confidence: Decimal
    confidence_grade: str
    weakest_factor: str | None
    factor_scores: dict[str, Any]
    competitor_count: int
    raw_competitor_count: int
    unique_seller_count: int
    clean_competitor_count: int
    effective_competitor_count: Decimal
    dispersion: Decimal | None
    dispersion_method: str
    dispersion_profile: dict[str, Any] | None
    outlier_method: str
    outlier_count: int
    sensitivity: Decimal | None
    action_gates_passed: bool
    cost_floor: Decimal | None
    cost_basis_inventory_value: Decimal | None
    priority_score: Decimal
    priority_score_type: str
    review_priority: Decimal
    reason_codes: list[str]
    evidence_observation_ids: list[str]
    excluded_observations: list[dict[str, str]]
    policy_version: str
    parser_version: str
    classifier_version: str
    coefficient_version: str | None
    calibration_dataset_hash: str | None
    currency: str
    price_tick: Decimal
    price_tick_version: str
    computed_at: datetime


class RecommendationPageResponse(BaseModel):
    items: list[RecommendationResponse]
    total: int
    run_id: UUID | None
    limit: int
    offset: int


class RecommendationReplayResponse(BaseModel):
    recommendation_id: UUID
    replay_contract_version: str
    calculated_at: datetime
    exact_match: bool
    mismatches: dict[str, dict[str, Any]]
    replayed: dict[str, Any]


class RecommendationDecisionRequest(BaseModel):
    decision: Literal["accepted", "rejected", "overridden"]
    new_price: Decimal | None = Field(default=None, gt=0)
    allow_below_cost: bool = False
    warning_confirmed: bool = False
    reason: str = Field(min_length=3, max_length=2000)


class RecommendationDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    recommendation_id: UUID
    user_id: UUID | None
    decision: str
    old_price: Decimal
    new_price: Decimal | None
    cost_snapshot: Decimal | None
    recommended_price_snapshot: Decimal | None
    approved_floor: Decimal | None
    allow_below_cost: bool
    warning_confirmed: bool
    warning_confirmed_at: datetime | None
    context_snapshot: dict[str, Any]
    reason: str
    policy_version: str
    decided_at: datetime


class RecommendationEvidenceResponse(BaseModel):
    observation_id: UUID
    seller_id: str
    seller_name: str
    title: str
    brand: str | None
    url: str
    price: Decimal
    currency: str
    is_available: bool | None
    match_confidence: Decimal
    source_confidence: Decimal
    age_hours: Decimal
    tier: str
    tier_confidence: Decimal
    is_used: bool
    is_kemp: bool
    is_owned: bool
    is_dumping: bool
    exclusion_reason: str | None
    normalized_price: Decimal
    multiplier: Decimal
    coefficient_model: str
    coefficient_version: str
    coefficient_confidence: Decimal
    observed_at: datetime


class ObservationTierOverrideRequest(BaseModel):
    tier: ProductTier
    reason: str = Field(min_length=3, max_length=1000)


class ObservationTierOverrideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    market_observation_id: UUID
    tier: str
    tier_confidence: Decimal
    is_used: bool
    is_kemp: bool
    is_owned: bool
    is_dumping: bool
    exclusion_reason: str | None
    reason_codes: list[str]
    method_version: str
    override_user_id: UUID | None
    classified_at: datetime


class CompetitorOfferInput(BaseModel):
    observation_id: str
    seller_id: str
    seller_name: str
    price: Decimal
    currency: str = "UAH"
    is_available: bool | None = True
    age_hours: Decimal = Field(ge=0)
    match_confidence: Decimal = Field(ge=0, le=1)
    tier: ProductTier
    tier_confidence: Decimal = Field(ge=0, le=1)
    source_confidence: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    is_used: bool = False
    is_kemp: bool = False
    is_owned: bool = False
    is_dumping: bool = False
    severe_conflict: bool = False
    conflict_reason: str | None = None

    def to_domain(self) -> CompetitorOffer:
        return CompetitorOffer(**self.model_dump())


class TierCoefficientInput(BaseModel):
    category: str
    tier: ProductTier
    multiplier: Decimal = Field(gt=0)
    model: CoefficientModel = CoefficientModel.SHRINKAGE
    method_version: str = "api-input-v1"
    sample_size: int = Field(default=10, ge=0)
    effective_sample_size: Decimal = Field(default=Decimal("10"), ge=0)
    confidence: Decimal = Field(default=Decimal("0.8"), ge=0, le=1)
    validated: bool = True
    log_effect: Decimal = Decimal("0")
    global_log_effect: Decimal | None = None
    shrinkage_weight: Decimal | None = None
    interval_low: Decimal | None = None
    interval_high: Decimal | None = None
    dataset_hash: str = ""
    coefficient_version: str = "api-input-v1"
    validation_reasons: tuple[str, ...] = ()
    excluded_oe_norm: str | None = None

    def to_domain(self) -> TierCoefficient:
        return TierCoefficient(**self.model_dump())


class PricingContextInput(BaseModel):
    sku: str
    category: str
    current_price: Decimal = Field(gt=0)
    currency: str = "UAH"
    stock_status: Literal["fresh", "stale", "dead_stock", "unknown"] = "unknown"
    cost: Decimal | None = Field(default=None, gt=0)
    stock_qty: Decimal | None = Field(default=None, ge=0)
    stock_age_days: Decimal | None = Field(default=None, ge=0)
    expected_units_sold: Decimal | None = Field(default=None, ge=0)
    units_sold_30d: Decimal | None = Field(default=None, ge=0)
    units_sold_60d: Decimal | None = Field(default=None, ge=0)
    units_sold_90d: Decimal | None = Field(default=None, ge=0)
    days_since_last_sale: Decimal | None = Field(default=None, ge=0)
    historical_monthly_units: Decimal | None = Field(default=None, ge=0)
    views_30d: Decimal | None = Field(default=None, ge=0)
    conversion_rate_proxy: Decimal | None = Field(default=None, ge=0, le=1)
    liquidity_target: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    urgency: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    manual_priority: Decimal = Field(default=Decimal("1"), gt=0)
    allow_below_cost: bool = False
    below_cost_floor: Decimal | None = Field(default=None, ge=0)
    severe_data_health_issue: bool = False
    below_cost_authorization_id: str | None = None
    below_cost_authorized_by: str | None = None
    below_cost_authorized_at: datetime | None = None
    below_cost_reason: str | None = None
    below_cost_warning_confirmed: bool = False

    def to_domain(self) -> ProductPricingContext:
        data = self.model_dump()
        data["stock_status"] = StockStatus(data["stock_status"])
        return ProductPricingContext(**data)


class PricingEvaluateRequest(BaseModel):
    context: PricingContextInput
    offers: list[CompetitorOfferInput]
    coefficients: list[TierCoefficientInput] = Field(default_factory=list)
    policy: dict[str, Any] | None = None


class PricingEvaluateResponse(BaseModel):
    sku: str
    action: str
    current_price: Decimal
    fair_price: Decimal | None
    recommended_price: Decimal | None
    lower_bound: Decimal | None
    upper_bound: Decimal | None
    confidence: Decimal
    confidence_grade: str
    weakest_factor: str | None
    factor_scores: dict[str, Decimal]
    competitor_count: int
    raw_competitor_count: int
    unique_seller_count: int
    clean_competitor_count: int
    effective_competitor_count: Decimal
    dispersion: Decimal | None
    dispersion_method: str
    dispersion_profile: dict[str, Any] | None
    outlier_method: str
    outlier_count: int
    sensitivity: Decimal | None
    action_gates_passed: bool
    cost_floor: Decimal | None
    cost_basis_inventory_value: Decimal | None
    priority_score: Decimal
    priority_score_type: str
    review_priority: Decimal
    reasons: list[str]
    evidence: list[dict[str, Any]]
    excluded: list[dict[str, Any]]
    policy_version: str
