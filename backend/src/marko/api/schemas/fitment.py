"""HTTP schemas for distributed fitment intelligence."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from metis.fitment import (
    Availability,
    Condition,
    EvidencePolarity,
    FitmentFeature,
    FeedbackReason,
    PricingStrategy,
    SellerRelation,
    SourceTier,
    StatementStatus,
)
from metis.pricing.types import ProductTier


class PartIdentityInput(BaseModel):
    category: str | None = Field(default=None, max_length=255)
    axle: str | None = Field(default=None, max_length=80)
    side: str | None = Field(default=None, max_length=80)
    vehicle_make: str | None = Field(default=None, max_length=120)
    vehicle_model: str | None = Field(default=None, max_length=120)
    generation: str | None = Field(default=None, max_length=120)
    year_from: int | None = Field(default=None, ge=1886, le=2200)
    year_to: int | None = Field(default=None, ge=1886, le=2200)
    engine: str | None = Field(default=None, max_length=120)
    body: str | None = Field(default=None, max_length=120)
    vehicle_market: str | None = Field(default=None, max_length=80)
    technical_specs: dict[str, str] = Field(default_factory=dict, max_length=50)
    manufacturer_article: str | None = Field(default=None, max_length=255)
    manufacturer_brand: str | None = Field(default=None, max_length=255)
    oe_numbers: list[str] = Field(default_factory=list, max_length=100)
    side_specific: bool = False

    @field_validator("year_to")
    @classmethod
    def validate_year_range(cls, value: int | None, info):
        year_from = info.data.get("year_from")
        if value is not None and year_from is not None and value < year_from:
            raise ValueError("year_to must be greater than or equal to year_from")
        return value


class CommercialContextInput(BaseModel):
    condition: Condition = Condition.UNKNOWN
    package_quantity: Decimal | None = Field(default=None, gt=0)
    unit_basis: str | None = Field(default=None, max_length=80)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    tier: ProductTier = ProductTier.UNKNOWN
    availability: Availability = Availability.UNKNOWN
    seller_relation: SellerRelation = SellerRelation.UNKNOWN
    stable_seller_id_verified: bool = False
    seller_group_id: str | None = Field(default=None, max_length=255)
    product_identity_key: str | None = Field(default=None, max_length=255)
    vat_included: bool | None = True


class EvidenceClaimInput(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=200)
    source_document_id: UUID | None = None
    feature: FitmentFeature
    value: Decimal
    source_id: str = Field(default="registered-source", min_length=1, max_length=255)
    source_type: str = Field(default="registered_source", min_length=1, max_length=80)
    source_tier: SourceTier = SourceTier.D
    source_reliability: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    extraction_confidence: Decimal = Field(ge=0, le=1)
    directness: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    independence_factor: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    freshness_factor: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    correlation_group: str = Field(min_length=1, max_length=255)
    polarity: EvidencePolarity
    statement_status: StatementStatus
    claim_value: dict[str, Any]
    retrieved_at: datetime
    source_url: str | None = Field(default=None, max_length=4000)
    raw_fragment: str | None = Field(default=None, max_length=2000)
    source_document_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("value")
    @classmethod
    def validate_evidence_value(cls, value: Decimal) -> Decimal:
        if value not in {
            Decimal("-1"),
            Decimal("-0.5"),
            Decimal("0"),
            Decimal("0.5"),
            Decimal("1"),
        }:
            raise ValueError("value must be one of -1, -0.5, 0, 0.5, 1")
        return value


class CandidateAnalysisInput(BaseModel):
    market_observation_id: UUID
    identity: PartIdentityInput
    commercial_context: CommercialContextInput
    evidence: list[EvidenceClaimInput] = Field(default_factory=list, max_length=250)


class FitmentAnalyzeRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=64)
    pricing_run_id: UUID | None = None
    target_identity: PartIdentityInput
    target_commercial_context: CommercialContextInput
    candidates: list[CandidateAnalysisInput] = Field(min_length=1, max_length=100)
    source_policy_snapshot: dict[str, Any] = Field(default_factory=dict)


class FitmentAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    catalog_item_id: UUID
    pricing_run_id: UUID | None
    requested_by: UUID | None
    idempotency_key: str
    status: str
    workflow_state: str
    target_identity: dict[str, Any]
    target_commercial_context: dict[str, Any]
    source_policy_snapshot: dict[str, Any]
    contract_version: str
    scoring_version: str
    request_sha256: str
    dispatch_task_id: str | None
    owner_task_id: str | None
    attempt_count: int
    candidate_count: int
    completed_candidate_count: int
    failed_candidate_count: int
    error: str | None
    lease_expires_at: datetime | None
    last_attempt_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FitmentEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    evidence_key: str
    feature: str
    evidence_value: Decimal
    source_external_id: str
    source_type: str
    source_tier: str
    source_reliability: Decimal
    extraction_confidence: Decimal
    directness: Decimal
    independence_factor: Decimal
    freshness_factor: Decimal
    correlation_group: str
    polarity: str
    statement_status: str
    claim_value: dict[str, Any]
    source_url: str | None
    raw_fragment: str | None
    source_document_sha256: str | None
    retrieved_at: datetime


class FitmentCandidateResponse(BaseModel):
    id: UUID
    analysis_id: UUID
    market_observation_id: UUID
    seller_relation_record_id: UUID | None
    seller_id: str
    seller_name: str
    title: str
    brand: str | None
    url: str
    price: Decimal
    reference_price: Decimal | None
    currency: str
    observed_at: datetime
    candidate_identity: dict[str, Any]
    candidate_commercial_context: dict[str, Any]
    compatibility_status: str
    compatibility_probability: Decimal
    positive_evidence: Decimal
    negative_evidence: Decimal
    coverage: Decimal
    contradiction_rate: Decimal
    missing_critical_ratio: Decimal
    hard_rejections: list[str]
    reason_codes: list[str]
    missing_critical_fields: list[str]
    feature_consensus: dict[str, Any]
    authoritative_confirmation: bool
    requires_manual_review: bool
    evidence_ids: list[str]
    evidence_claim_ids: list[UUID]
    evidence: list[FitmentEvidenceResponse]
    price_comparability_status: str
    price_eligible: bool
    competitor_weight: Decimal
    normalized_unit_price: Decimal | None
    price_unit_status: str
    price_unit_certainty: Decimal
    price_factor_trace: dict[str, Any]
    price_reason_codes: list[str]
    automatic_price_change_allowed: bool
    contract_version: str
    scoring_version: str
    assessed_at: datetime


class FitmentCandidatePageResponse(BaseModel):
    items: list[FitmentCandidateResponse]
    total: int
    analysis_id: UUID | None
    limit: int
    offset: int


class SellerRelationRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=64)
    seller_name: str | None = Field(default=None, max_length=255)
    confidence: Decimal = Field(ge=0, le=1)
    evidence: list[dict[str, Any]] = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=3, max_length=2000)


class SellerRelationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    marketplace: str
    seller_external_id: str
    seller_name: str | None
    relation: str
    confidence: Decimal
    evidence: list[dict[str, Any]]
    reason: str
    idempotency_key: str
    supersedes_id: UUID | None
    created_by: UUID | None
    created_at: datetime


class FitmentReviewRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=64)
    decision: Literal[
        "mark_candidate_compatible",
        "mark_candidate_incompatible",
        "postpone",
        "request_additional_check",
    ]
    reason_code: str = Field(min_length=2, max_length=80)
    comment: str | None = Field(default=None, max_length=2000)
    evidence_verdicts: list["EvidenceVerdictInput"] = Field(
        default_factory=list, max_length=100
    )


class EvidenceVerdictInput(BaseModel):
    evidence_claim_id: UUID
    verdict: Literal["confirmed", "rejected"]


class FitmentReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    assessment_id: UUID
    reviewer_id: UUID | None
    idempotency_key: str
    decision: str
    reason_code: str
    comment: str | None
    system_status_snapshot: str
    system_probability_snapshot: Decimal
    evidence_snapshot_sha256: str
    created_at: datetime


class FitmentSourceRequest(BaseModel):
    source_key: str = Field(min_length=2, max_length=160)
    source_type: str = Field(min_length=2, max_length=80)
    source_tier: SourceTier
    base_reliability: Decimal = Field(ge=0, le=1)
    domain: str = Field(min_length=3, max_length=255)
    access_method: str = Field(min_length=2, max_length=80)
    access_status: Literal[
        "PERMITTED", "OWNER_RISK_ACCEPTED", "NOT_PERMITTED", "UNKNOWN"
    ]
    access_reference: str = Field(default="", max_length=255)
    robots_checked: bool
    terms_checked: bool
    rate_limit: str = Field(min_length=1, max_length=120)
    cache_policy: str = Field(min_length=1, max_length=120)
    policy_version: str = Field(min_length=1, max_length=80)
    reviewed_at: datetime
    capabilities: list["SourceCapabilityInput"] = Field(
        default_factory=list, max_length=20
    )


class SourceCapabilityInput(BaseModel):
    capability: Literal[
        "search_by_article", "search_by_oe", "search_fitment", "fetch_document"
    ]
    enabled: bool
    authentication_required: bool = False
    rate_limit: str = Field(min_length=1, max_length=120)
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    cache_policy: dict[str, Any] = Field(default_factory=dict)


class FitmentSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID | None
    source_key: str
    source_type: str
    source_tier: str
    base_reliability: Decimal
    domain: str
    access_method: str
    access_status: str
    access_reference: str
    robots_checked: bool
    terms_checked: bool
    rate_limit: str
    cache_policy: str
    policy_version: str
    reviewed_at: datetime
    created_at: datetime


class FitmentSourceCapabilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: UUID
    capability: str
    enabled: bool
    authentication_required: bool
    rate_limit: str
    retry_policy: dict[str, Any]
    cache_policy: dict[str, Any]
    policy_version: str
    created_at: datetime


class FitmentSourceReliabilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: UUID
    claim_type: str
    source_tier: str
    prior_alpha: Decimal
    prior_beta: Decimal
    confirmed_count: int
    rejected_count: int
    reliability: Decimal
    label_event_key: str
    method_version: str
    supersedes_id: UUID | None
    created_at: datetime


class SourceDocumentRequest(BaseModel):
    source_url: str = Field(min_length=8, max_length=4000)
    retrieval_query: str = Field(min_length=1, max_length=2000)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_locator: str | None = Field(default=None, max_length=2000)
    response_metadata: dict[str, Any] = Field(default_factory=dict)
    retrieved_at: datetime
    expires_at: datetime | None = None


class SourceDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: UUID
    source_url: str
    retrieval_query: str
    content_sha256: str
    content_locator: str | None
    response_metadata: dict[str, Any]
    retrieved_at: datetime
    expires_at: datetime | None
    created_at: datetime


class CrossReferenceRequest(BaseModel):
    brand: str = Field(min_length=1, max_length=255)
    article: str = Field(min_length=1, max_length=255)
    oe: str = Field(min_length=1, max_length=255)
    installation_position: str | None = Field(default=None, max_length=80)
    vehicle_key: str | None = Field(default=None, max_length=255)
    confidence: Decimal = Field(ge=0, le=1)
    evidence_ids: list[UUID] = Field(
        min_length=1,
        max_length=250,
        description="Persisted fitment_evidence_claims UUIDs; counts are derived server-side.",
    )
    supersedes_id: UUID | None = None


class CrossReferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    brand: str
    normalized_brand: str
    article: str
    normalized_article: str
    oe: str
    normalized_oe: str
    installation_position: str | None
    vehicle_key: str | None
    relation_status: str
    confidence: Decimal
    evidence_ids: list[str]
    source_count: int
    human_feedback_count: int
    record_fingerprint: str
    method_version: str
    valid_from: datetime
    last_verified_at: datetime
    supersedes_id: UUID | None
    created_by: UUID | None
    created_at: datetime


class CrossReferencePageResponse(BaseModel):
    items: list[CrossReferenceResponse]
    total: int
    limit: int
    offset: int


class SourceRouteResponse(BaseModel):
    brand: str | None
    preferred_sources: list[dict[str, Any]]
    fallback_sources: list[dict[str, Any]]
    retrieval_mode: str
    automatic_access_authorized: bool


class SellerResolutionRequest(BaseModel):
    known_own_registry_match: bool = False
    matches: dict[str, Decimal] = Field(default_factory=dict, max_length=50)


class SellerResolutionResponse(BaseModel):
    relation: str
    relation_score: Decimal
    strong_identifier_present: bool
    deterministic_match: bool
    contributions: dict[str, Decimal]
    reason_codes: list[str]
    version: str


class FitmentRecommendationCreateRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=64)
    analysis_id: UUID
    strategy: PricingStrategy = PricingStrategy.BALANCED
    approved_price_floor: Decimal | None = Field(default=None, gt=0)
    absolute_buffer: Decimal = Field(default=Decimal("0"), ge=0)
    percentage_buffer: Decimal = Field(default=Decimal("0.02"), ge=0, le=1)
    max_decrease_rate: Decimal = Field(default=Decimal("0.15"), ge=0, le=1)
    max_increase_rate: Decimal = Field(default=Decimal("0.20"), ge=0, le=1)
    deadband: Decimal = Field(default=Decimal("0.04"), ge=0, lt=1)
    minimum_confidence: Decimal = Field(default=Decimal("0.65"), ge=0, le=1)
    price_tick: Decimal = Field(default=Decimal("1"), gt=0)
    custom_anchor: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_custom_strategy(self):
        if self.strategy == PricingStrategy.CUSTOM and self.custom_anchor is None:
            raise ValueError("custom strategy requires custom_anchor")
        return self


class FitmentRecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    analysis_id: UUID
    catalog_item_id: UUID
    created_by: UUID | None
    idempotency_key: str
    input_fingerprint: str
    action: str
    strategy: str
    current_price: Decimal
    recommended_price: Decimal | None
    recommended_range_min: Decimal | None
    recommended_range_max: Decimal | None
    absolute_change: Decimal | None
    relative_change: Decimal | None
    market_anchor: Decimal | None
    approved_price_floor: Decimal | None
    currency: str
    confidence: Decimal
    confidence_factors: dict[str, Any]
    market_summary: dict[str, Any]
    price_statistics: dict[str, Any]
    candidate_decisions: list[dict[str, Any]]
    reason_codes: list[str]
    warnings: list[str]
    configuration_snapshot: dict[str, Any]
    contract_version: str
    recommendation_version: str
    automatic_price_change_allowed: bool
    created_at: datetime


class FitmentRecommendationReviewRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=64)
    approved_price: Decimal | None = Field(default=None, gt=0)
    reason_code: FeedbackReason = FeedbackReason.OTHER
    comment: str | None = Field(default=None, max_length=2000)
    accept_with_modification: bool = False
    allow_below_floor: bool = False
    below_floor_warning_confirmed: bool = False


class FitmentRecommendationReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    recommendation_id: UUID
    reviewer_id: UUID | None
    idempotency_key: str
    decision: str
    approved_price: Decimal | None
    reason_code: str
    comment: str | None
    recommendation_snapshot: dict[str, Any]
    created_at: datetime


class FitmentNotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    recommendation_id: UUID
    notification_type: str
    group_key: str
    payload: dict[str, Any]
    status: str
    created_at: datetime


class FitmentNotificationPageResponse(BaseModel):
    items: list[FitmentNotificationResponse]
    total: int
    limit: int
    offset: int
