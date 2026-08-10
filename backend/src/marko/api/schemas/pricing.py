"""Versioned API contracts for pricing runs, calibration, and decisions."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from marko.api.schemas.catalog import CatalogDataEvidenceResponse
from metis.pricing import (
    CoefficientModel,
    CohortRole,
    CompetitorOffer,
    ProductPricingContext,
    ProductTier,
    StockStatus,
    TierCoefficient,
    comparison_evidence_from_dict,
)


PricingRunScopeMode = Literal["FULL_CATALOG", "EXPLICIT_ITEMS"]
MAX_EXPLICIT_SCOPE_ITEMS = 10_000


class _BoundedScopeRequest(BaseModel):
    """Общая часть контракта области: предпросмотр и запуск не должны расходиться."""

    model_config = ConfigDict(extra="forbid")

    import_batch_id: UUID
    scope_mode: PricingRunScopeMode = "FULL_CATALOG"
    catalog_item_ids: list[UUID] = Field(
        default_factory=list, max_length=MAX_EXPLICIT_SCOPE_ITEMS
    )
    policy: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope_mode == "EXPLICIT_ITEMS" and not self.catalog_item_ids:
            raise ValueError("EXPLICIT_ITEMS scope requires catalog_item_ids")
        if self.scope_mode == "FULL_CATALOG" and self.catalog_item_ids:
            raise ValueError("FULL_CATALOG scope cannot carry catalog_item_ids")
        if len(set(self.catalog_item_ids)) != len(self.catalog_item_ids):
            raise ValueError("catalog_item_ids cannot repeat")
        return self


class PricingRunPreviewRequest(_BoundedScopeRequest):
    """Предпросмотр области: без побочных эффектов, без создания прогона."""


SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"


PREVIEW_TOKEN_PATTERN = r"^mrp1_[A-Za-z0-9_-]{43}$"


class PricingRunCreateRequest(_BoundedScopeRequest):
    # Полный каталог — самый дорогой и самый необратимый режим, поэтому он
    # требует отдельного подтверждения, а не молчаливого умолчания.
    confirm_full_catalog: bool = False
    # Обязательные, а не опциональные: старт через API — это предъявление
    # выданного сервером контракта предпросмотра.  Отсутствующее поле не
    # является разрешением запустить прогон, поэтому умолчаний здесь нет.
    # Системные повторы идут отдельным внутренним путём (TrustedRunStart) и
    # этой схемы не касаются.
    idempotency_key: str = Field(min_length=8, max_length=160)
    # Непрозрачный токен из ответа предпросмотра. Хеши клиент больше не
    # присылает: сервер сам публиковал их, и «подтверждение» состояло из
    # значения, которое подтверждающий получил от подтверждаемого.
    preview_token: str = Field(pattern=PREVIEW_TOKEN_PATTERN)

    @model_validator(mode="after")
    def validate_confirmation(self):
        if self.scope_mode == "FULL_CATALOG" and not self.confirm_full_catalog:
            raise ValueError(
                "FULL_CATALOG execution requires confirm_full_catalog=true"
            )
        if self.scope_mode != "FULL_CATALOG" and self.confirm_full_catalog:
            raise ValueError("confirm_full_catalog applies only to FULL_CATALOG scope")
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key must not be blank")
        return self


class PricingRunScopeEstimateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    requested_items: int
    eligible_items: int
    excluded_items: int
    unique_scrape_inputs: int
    duplicate_items: int
    worst_case_duration_seconds: int
    network_eligible_items: int = 0
    identity_blocked_items: int = 0


class PricingRunScopeExclusionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    catalog_item_id: UUID
    sku: str
    reason_code: str


class PricingRunPreviewResponse(BaseModel):
    scope_contract_version: str
    import_batch_id: UUID
    scope_mode: str
    policy_version: str
    catalog_snapshot_hash: str
    scope_hash: str
    policy_snapshot_hash: str
    requires_full_catalog_confirmation: bool
    estimate: PricingRunScopeEstimateResponse
    exclusions: list[PricingRunScopeExclusionResponse]
    exclusions_truncated: bool
    scope_manifest: dict[str, Any]
    # Контракт, выданный сервером: возвращается один раз и в базе не хранится.
    # Без него старт этой области невозможен, поэтому и срок годности здесь же
    # — «предпросмотр без срока» описывает состояние каталога навсегда, чего
    # он делать не может.
    preview_contract_version: str
    preview_token: str
    preview_expires_at: datetime
    preview_request_hash: str


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
    calibration_accounting: dict[str, Any]
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
    scope_contract_version: str | None
    scope_mode: str
    scope_confirmation_source: str
    full_catalog_confirmed: bool
    catalog_snapshot_hash: str | None
    scope_hash: str | None
    scope_manifest: dict[str, Any]
    idempotency_key: str | None
    scope_frozen_at: datetime | None


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
    model_config = ConfigDict(extra="forbid")

    stock_status: Literal["fresh", "stale", "dead_stock", "unknown"] | None = None
    cost: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    clear_cost: bool = False
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
    below_cost_warning_confirmed: bool = False
    reason: str = Field(min_length=3, max_length=2000)

    @model_validator(mode="after")
    def validate_below_cost_override(self):
        if self.cost is not None and self.clear_cost:
            raise ValueError("cost and clear_cost cannot be submitted together")
        if self.allow_below_cost and not self.below_cost_warning_confirmed:
            raise ValueError("below-cost warning confirmation is required")
        return self


class CatalogItemOverrideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    catalog_item_id: UUID
    user_id: UUID | None
    stock_status: str | None
    cost_configured: bool
    cost_privacy_mode: str
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
    mpn_norm: str | None = None
    search_identity: str | None = None
    identity_status: str = "UNRESOLVED"
    catalog_data_evidence: CatalogDataEvidenceResponse = Field(
        default_factory=CatalogDataEvidenceResponse
    )
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
    target_market_count: int
    kemp_reference_count: int
    owned_store_count: int
    rejected_count: int
    effective_competitor_count: Decimal
    dispersion: Decimal | None
    dispersion_method: str
    dispersion_profile: dict[str, Any] | None
    outlier_method: str
    outlier_count: int
    sensitivity: Decimal | None
    action_gates_passed: bool
    automatic_eligible: bool
    verified_seller_count: int
    comparability_policy_id: str | None
    comparability_policy_hash: str | None
    decision_fingerprint: str | None
    hard_gate_trace: dict[str, Any]
    robust_diagnostic: dict[str, Any] | None
    priority_score: Decimal
    priority_score_type: str
    review_priority: Decimal
    absolute_recommended_change: Decimal | None
    percentage_recommended_change: Decimal | None
    reason_codes: list[str]
    evidence_observation_ids: list[str]
    kemp_reference_observation_ids: list[str]
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


class RecommendationActionCountsResponse(BaseModel):
    """Population counts for the whole run, independent of the active queue tab."""

    raise_: int = Field(alias="raise", serialization_alias="raise")
    lower: int
    review: int
    hold: int
    total: int

    model_config = ConfigDict(populate_by_name=True)


class RecommendationPageResponse(BaseModel):
    items: list[RecommendationResponse]
    total: int
    run_id: UUID | None
    limit: int
    offset: int
    action_counts: RecommendationActionCountsResponse


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
    recommended_price_snapshot: Decimal | None
    allow_below_cost: bool
    warning_confirmed: bool
    warning_confirmed_at: datetime | None
    context_snapshot: dict[str, Any]
    reason: str
    policy_version: str
    decided_at: datetime


class ComparabilityReviewResponse(BaseModel):
    review_id: UUID
    market_observation_id: UUID
    input_hash: str
    contract_version: Literal["comparability-v1", "comparability-v2"]
    verdict: Literal["COMPARABLE", "NOT_COMPARABLE", "INSUFFICIENT_DATA"]
    match_level: Literal["EXACT", "ACCEPTABLE_ANALOGUE", "SUSPICIOUS", "NOT_APPLICABLE"]
    confidence: Decimal
    identity_verdict: Literal["MATCH", "NOT_MATCH", "MANUAL_REVIEW"]
    identity_match_level: Literal[
        "EXACT", "ACCEPTABLE_ANALOGUE", "SUSPICIOUS", "NOT_APPLICABLE"
    ]
    identity_match_score: Decimal
    decision_confidence: Decimal
    image_consistency: Literal["SUPPORTS", "CONFLICTS", "NON_DIAGNOSTIC", "UNAVAILABLE"]
    reason_codes: list[str]
    pricing_admission: Literal["ADMITTED", "EXCLUDED", "MANUAL_REVIEW"]
    pricing_reason_codes: list[str]
    rationale: str
    dimension_findings: list[dict[str, Any]]
    hard_stop_conflicts: list[dict[str, Any]]
    decision_source: str
    status: str
    provider: str
    model_id: str
    prompt_version: str
    reasoning_effort: str | None
    model_settings_hash: str | None
    reviewed_at: datetime
    cache_hit_review_id: UUID | None
    image_urls: list[str]
    provider_response_id: str | None
    usage: dict[str, Any]
    latency_ms: int
    estimated_cost: dict[str, Any]
    rate_card_version: str | None
    verified_cross_edge: dict[str, Any]
    our_product: dict[str, Any]
    candidate: dict[str, Any]
    error_code: str | None
    error_detail: str | None
    feedback_count: int
    latest_feedback_id: UUID | None
    latest_feedback_decision: str | None
    latest_feedback_reason: str | None
    pricing_eligible: bool


class ComparabilityReviewRequest(BaseModel):
    force: bool = False


class ComparabilityFeedbackEvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal[
        "OUR_PRODUCT",
        "CANDIDATE",
        "IMAGE",
        "DETERMINISTIC_GATE",
        "VERIFIED_CROSS",
    ]
    field: str = Field(min_length=1, max_length=120)
    value: str = Field(default="", max_length=1000)
    excerpt: str = Field(default="", max_length=500)


class ComparabilityFeedbackDimensionCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: Literal[
        "oe_reference",
        "part_type",
        "brand_manufacturer",
        "fitment",
        "vehicle_generation",
        "year_interval",
        "engine",
        "body_variant",
        "side",
        "position",
        "condition",
        "package_quantity",
        "unit_basis",
        "currency_presence",
    ]
    outcome: Literal["MATCH", "CONFLICT", "UNKNOWN", "NOT_APPLICABLE"]
    our_value: str = Field(default="", max_length=1000)
    candidate_value: str = Field(default="", max_length=1000)
    explanation: str = Field(min_length=1, max_length=1000)
    evidence: list[ComparabilityFeedbackEvidenceReference] = Field(
        default_factory=list,
        max_length=12,
    )


class ComparabilityFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["CONFIRM", "CORRECT"]
    corrected_verdict: (
        Literal["COMPARABLE", "NOT_COMPARABLE", "INSUFFICIENT_DATA"] | None
    ) = None
    corrected_match_level: (
        Literal["EXACT", "ACCEPTABLE_ANALOGUE", "SUSPICIOUS", "NOT_APPLICABLE"] | None
    ) = None
    corrected_identity_verdict: (
        Literal["MATCH", "NOT_MATCH", "MANUAL_REVIEW"] | None
    ) = None
    corrected_identity_match_level: (
        Literal["EXACT", "ACCEPTABLE_ANALOGUE", "SUSPICIOUS", "NOT_APPLICABLE"] | None
    ) = None
    corrected_pricing_admission: (
        Literal["ADMITTED", "EXCLUDED", "MANUAL_REVIEW"] | None
    ) = None
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    reason: str = Field(min_length=3, max_length=2000)
    evidence_corrections: list[ComparabilityFeedbackDimensionCorrection] = Field(
        default_factory=list,
        max_length=32,
    )

    @model_validator(mode="after")
    def validate_correction(self) -> ComparabilityFeedbackRequest:
        legacy_supplied = any(
            value is not None
            for value in (self.corrected_verdict, self.corrected_match_level)
        )
        v2_values = (
            self.corrected_identity_verdict,
            self.corrected_identity_match_level,
            self.corrected_pricing_admission,
        )
        v2_supplied = any(value is not None for value in v2_values)
        if self.decision == "CORRECT":
            if legacy_supplied and (
                self.corrected_verdict is None or self.corrected_match_level is None
            ):
                raise ValueError("legacy correction fields must be supplied together")
            if v2_supplied and any(value is None for value in v2_values):
                raise ValueError("v2 correction fields must be supplied together")
            if not legacy_supplied and not v2_supplied:
                raise ValueError("CORRECT requires legacy or v2 corrected labels")
        elif legacy_supplied or v2_supplied or self.evidence_corrections:
            raise ValueError("CONFIRM cannot carry corrected values")
        dimensions = [item.dimension for item in self.evidence_corrections]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("evidence corrections cannot repeat a dimension")
        return self


class ComparabilityStatusResponse(BaseModel):
    mode: Literal["off", "shadow", "required"]
    provider: str
    model: str
    reasoning_effort: str
    contract_version: Literal["comparability-v2"] = "comparability-v2"
    rate_card_version: str
    configured: bool
    automatic_price_publication: Literal[False] = False


class ComparabilityRunReportResponse(BaseModel):
    run_id: UUID
    generated_at: datetime
    run_status: str
    contract_version: Literal["comparability-v2"] = "comparability-v2"
    totals: dict[str, int]
    identity_verdict_counts: dict[str, int]
    pricing_admission_counts: dict[str, int]
    automatic_decision_coverage: Decimal
    abstention_rate: Decimal
    provider: dict[str, Any]
    parser: dict[str, Any]
    seller_integrity: dict[str, Any]
    performance: dict[str, Any]
    cost: dict[str, Any]
    accuracy: dict[str, Any]


class AiEvidenceSpendEstimateResponse(BaseModel):
    """Estimated provider spend.  Observability only -- never billing truth.

    This is *our* spend with the model provider, computed from reported token
    usage and a versioned rate snapshot.  It is unrelated to the customer's
    purchase cost, which the cost-privacy boundary governs separately.
    """

    available: bool
    reason: str | None = None
    rate_version: str | None = None
    model_id: str | None = None
    rates_effective_date: date | None = None
    currency: str | None = None
    uncached_input_usd: Decimal | None = None
    cached_input_usd: Decimal | None = None
    output_usd: Decimal | None = None
    total_usd: Decimal | None = None
    rates_per_million: dict[str, str] = Field(default_factory=dict)
    disclaimer: Literal["ESTIMATE_NOT_BILLING_TRUTH"] = "ESTIMATE_NOT_BILLING_TRUTH"


class AiEvidenceUsageResponse(BaseModel):
    input_tokens: int
    cached_input_tokens: int
    uncached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int


class AiEvidenceFieldResponse(BaseModel):
    """One extracted field with the excerpt and source path that justify it."""

    field: str
    value: str | None = None
    excerpt: str | None = None
    source_path: str | None = None
    confidence: Decimal | None = None
    verified: bool | None = None
    verification_reason: str | None = None


class AiEvidenceExtractionResponse(BaseModel):
    """Read-only projection of one persisted extraction.

    Carries evidence and verification outcomes.  It never carries hidden model
    reasoning, raw provider responses, or any secret configuration.
    """

    extraction_id: UUID | None = None
    market_observation_id: UUID | None = None
    status: str
    shadow_only: bool
    provider: str | None = None
    model_id: str | None = None
    reasoning_effort: str | None = None
    prompt_version: str | None = None
    schema_version: str | None = None
    extractor_version: str | None = None
    latency_ms: int
    usage: AiEvidenceUsageResponse | None = None
    usage_error: str | None = None
    verification_result: str | None = None
    verification_reasons: dict[str, Any] = Field(default_factory=dict)
    fields: list[AiEvidenceFieldResponse] = Field(default_factory=list)
    error_code: str | None = None
    created_at: datetime | None = None
    spend_estimate: AiEvidenceSpendEstimateResponse


class AiEvidenceStatusResponse(BaseModel):
    """Configuration and telemetry for the extractor, with no secret material."""

    mode: Literal["off", "shadow"]
    provider: str
    model: str
    reasoning_effort: str
    configured: bool
    shadow_only: bool
    automatic_price_publication: Literal[False] = False
    rate_card_available: bool
    rate_card_reason: str | None = None
    rate_version: str | None = None
    rates_effective_date: date | None = None
    rates_per_million: dict[str, str]
    estimate_disclaimer: Literal["ESTIMATE_NOT_BILLING_TRUTH"] = (
        "ESTIMATE_NOT_BILLING_TRUTH"
    )
    telemetry: dict[str, Any] = Field(default_factory=dict)


class RecommendationEvidenceResponse(BaseModel):
    observation_id: UUID
    seller_id: str
    seller_name: str
    title: str
    description: str | None
    description_available: bool
    condition_raw: str | None
    condition_state: str
    condition_reason_codes: list[str]
    cross_candidates: list[dict[str, Any]]
    brand: str | None
    search_oe_norm: str
    extracted_oe_norms: list[str]
    verified_matched_oe_norm: str | None
    comparison_identity_key: str | None
    oe_verification_status: str
    oe_evidence_summary: list[dict[str, Any]]
    oe_extractor_version: str
    oe_reenriched_at: datetime | None
    oe_reenrichment_error_code: str | None
    url: str
    url_absence_reason: str | None
    price: Decimal
    currency: str
    currency_raw: str | None
    currency_inferred: bool
    is_available: bool | None
    match_confidence: Decimal
    source_confidence: Decimal
    source_confidence_factors: dict[str, Any]
    source_confidence_method_version: str
    age_hours: Decimal | None
    tier: str
    tier_confidence: Decimal
    is_used: bool
    is_kemp: bool
    is_owned: bool
    is_dumping: bool
    cohort_role: str
    target_effect: str
    exclusion_reason: str | None
    normalized_price: Decimal | None
    multiplier: Decimal | None
    coefficient_model: str | None
    coefficient_version: str | None
    coefficient_confidence: Decimal | None
    observed_at: datetime
    automatic_eligible: bool
    comparability_hard_gate_result: str
    calibration_exclusion_codes: list[str]
    offer_outcome_counts: dict[str, int]
    comparability_policy_id: str | None
    comparability_policy_hash: str | None
    comparison_evidence: dict[str, Any] | None
    candidate_snapshot: dict[str, Any]
    llm_review_required: bool
    llm_pricing_eligible: bool
    llm_review: ComparabilityReviewResponse | None


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
    cohort_role: str
    exclusion_reason: str | None
    reason_codes: list[str]
    method_version: str
    override_user_id: UUID | None
    classified_at: datetime


class CompetitorOfferInput(BaseModel):
    observation_id: str
    seller_id: str | None = None
    seller_name: str
    price: Decimal
    currency: str | None = None
    currency_raw: str | None = None
    currency_inferred: bool = False
    currency_evidence: str | None = None
    is_available: bool | None = True
    age_hours: Decimal = Field(ge=0)
    match_confidence: Decimal = Field(ge=0, le=1)
    tier: ProductTier
    tier_confidence: Decimal = Field(ge=0, le=1)
    source_confidence: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    is_used: bool = False
    is_kemp: bool = False
    is_owned: bool = False
    is_dumping: bool = False
    severe_conflict: bool = False
    conflict_reason: str | None = None
    source: str = "unknown"
    listing_url: str | None = None
    comparison_evidence: dict[str, Any] | None = None
    cohort_role: CohortRole | None = None
    semantic_review_required: bool = False
    semantic_review_id: str | None = None
    semantic_review_verdict: (
        Literal["COMPARABLE", "NOT_COMPARABLE", "INSUFFICIENT_DATA"] | None
    ) = None
    semantic_review_match_level: (
        Literal["EXACT", "ACCEPTABLE_ANALOGUE", "SUSPICIOUS", "NOT_APPLICABLE"] | None
    ) = None
    semantic_review_confidence: Decimal | None = Field(default=None, ge=0, le=1)
    # Stateless preview/QA callers must state that the supplied offer has
    # already passed the upstream admission contract. Persisted Marko offers
    # receive the value from MarketObservation instead.
    automatic_eligible: bool = False
    semantic_gate_current: bool = False

    def to_domain(self) -> CompetitorOffer:
        values = self.model_dump()
        values["comparison_evidence"] = comparison_evidence_from_dict(
            values["comparison_evidence"]
        )
        return CompetitorOffer(**values)


class TierCoefficientInput(BaseModel):
    """Explicit, fail-closed coefficient contract for the stateless QA endpoint.

    The endpoint cannot prove a caller-supplied calibration dataset, but it must
    never manufacture validation evidence on the caller's behalf.  Every field
    that contributes to coefficient admission is therefore required.
    """

    model_config = ConfigDict(extra="forbid")

    category: str
    tier: ProductTier
    multiplier: Decimal = Field(gt=0)
    model: CoefficientModel
    method_version: str = Field(min_length=1, max_length=160)
    sample_size: int = Field(ge=0)
    effective_sample_size: Decimal = Field(ge=0)
    confidence: Decimal = Field(ge=0, le=1)
    validated: bool
    log_effect: Decimal
    global_log_effect: Decimal | None = None
    shrinkage_weight: Decimal | None = None
    interval_low: Decimal | None = None
    interval_high: Decimal | None = None
    dataset_hash: str = Field(pattern=SHA256_HEX_PATTERN)
    coefficient_version: str = Field(min_length=1, max_length=200)
    validation_reasons: tuple[str, ...] = ()
    excluded_oe_norm: str | None = None

    @model_validator(mode="after")
    def validate_calibration_evidence(self) -> TierCoefficientInput:
        if self.effective_sample_size > Decimal(self.sample_size):
            raise ValueError("effective_sample_size cannot exceed sample_size")
        interval_supplied = self.interval_low is not None or self.interval_high is not None
        if interval_supplied and (
            self.interval_low is None or self.interval_high is None
        ):
            raise ValueError("interval_low and interval_high must be supplied together")
        if self.interval_low is not None and self.interval_high is not None:
            if self.interval_low <= 0 or self.interval_high <= 0:
                raise ValueError("coefficient interval bounds must be positive")
            if not self.interval_low <= self.multiplier <= self.interval_high:
                raise ValueError("multiplier must lie inside the coefficient interval")
        if self.validated:
            if self.sample_size <= 0 or self.effective_sample_size <= 0:
                raise ValueError("validated coefficient requires positive sample support")
            if self.confidence <= 0:
                raise ValueError("validated coefficient requires positive confidence")
            if self.interval_low is None or self.interval_high is None:
                raise ValueError("validated coefficient requires a complete interval")
            if self.validation_reasons:
                raise ValueError("validated coefficient cannot carry validation failures")
        return self

    def to_domain(self) -> TierCoefficient:
        return TierCoefficient(**self.model_dump())


class PricingContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str
    category: str
    current_price: Decimal = Field(gt=0)
    currency: str = "UAH"
    stock_status: Literal["fresh", "stale", "dead_stock", "unknown"] = "unknown"
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
    urgency: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    manual_priority: Decimal = Field(default=Decimal("1"), gt=0)
    allow_below_cost: bool = False
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
    target_market_count: int
    kemp_reference_count: int
    owned_store_count: int
    rejected_count: int
    effective_competitor_count: Decimal
    dispersion: Decimal | None
    dispersion_method: str
    dispersion_profile: dict[str, Any] | None
    outlier_method: str
    outlier_count: int
    sensitivity: Decimal | None
    action_gates_passed: bool
    automatic_eligible: bool
    verified_seller_count: int
    comparability_policy_id: str
    comparability_policy_hash: str
    hard_gate_results: dict[str, int]
    failed_hard_gates: list[str]
    unknown_hard_fields: list[str]
    robust_diagnostic: dict[str, Any] | None
    robust_policy_fingerprint: dict[str, str]
    priority_score: Decimal
    priority_score_type: str
    review_priority: Decimal
    absolute_recommended_change: Decimal | None
    percentage_recommended_change: Decimal | None
    reasons: list[str]
    evidence: list[dict[str, Any]]
    kemp_reference_evidence: list[dict[str, Any]]
    excluded: list[dict[str, Any]]
    policy_version: str
