"""Versioned contracts for evidence-first automotive fitment intelligence.

The contracts in this package deliberately do not retrieve web pages and do not
mutate marketplace prices.  They consume immutable, provenance-bearing facts
and produce a deterministic decision for a human reviewer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping

from metis.pricing.types import ProductTier


ZERO = Decimal("0")
ONE = Decimal("1")


class StatementStatus(StrEnum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    ASSUMPTION = "ASSUMPTION"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class SourceTier(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class EvidencePolarity(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class FitmentFeature(StrEnum):
    ARTICLE_IDENTITY = "article_identity"
    OE_EXACT = "oe_exact"
    OE_SUPERSESSION = "oe_supersession"
    CROSS_CONFIRMED = "cross_confirmed"
    PART_CATEGORY = "part_category"
    AXLE = "axle"
    SIDE = "side"
    VEHICLE_MAKE_MODEL = "vehicle_make_model"
    GENERATION = "generation"
    YEAR_OVERLAP = "year_overlap"
    ENGINE = "engine"
    BODY = "body"
    VEHICLE_MARKET = "vehicle_market"
    TECHNICAL_SPECS = "technical_specs"


class CompatibilityStatus(StrEnum):
    CONFIRMED_COMPATIBLE = "confirmed_compatible"
    LIKELY_COMPATIBLE = "likely_compatible"
    UNCERTAIN = "uncertain"
    NOT_COMPATIBLE = "not_compatible"


class SellerRelation(StrEnum):
    OWN = "own"
    RELATED = "related"
    POSSIBLY_RELATED = "possibly_related"
    INDEPENDENT = "independent"
    UNKNOWN = "unknown"


class Condition(StrEnum):
    NEW = "new"
    USED = "used"
    REMANUFACTURED = "remanufactured"
    UNKNOWN = "unknown"


class Availability(StrEnum):
    IN_STOCK = "in_stock"
    PREORDER = "preorder"
    UNKNOWN = "unknown"
    OUT_OF_STOCK = "out_of_stock"


class PriceComparabilityStatus(StrEnum):
    COMPARABLE = "comparable"
    MANUAL_REVIEW = "manual_review"
    NOT_COMPARABLE = "not_comparable"


@dataclass(frozen=True, slots=True)
class PartIdentity:
    """Normalized identity fields used only for deterministic hard rules."""

    category: str | None = None
    axle: str | None = None
    side: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    generation: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    engine: str | None = None
    body: str | None = None
    vehicle_market: str | None = None
    technical_specs: Mapping[str, str] = field(default_factory=dict)
    manufacturer_article: str | None = None
    manufacturer_brand: str | None = None
    oe_numbers: tuple[str, ...] = field(default_factory=tuple)
    side_specific: bool = False


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    """One independently auditable claim about one compatibility feature."""

    evidence_id: str
    feature: FitmentFeature
    value: Decimal
    source_id: str
    source_type: str
    source_tier: SourceTier
    source_reliability: Decimal
    extraction_confidence: Decimal
    independence_factor: Decimal
    freshness_factor: Decimal
    correlation_group: str
    polarity: EvidencePolarity
    statement_status: StatementStatus
    claim_value: Mapping[str, Any]
    retrieved_at: datetime
    source_url: str | None = None
    raw_fragment: str | None = None
    source_document_sha256: str | None = None
    directness: Decimal = ONE

    def __post_init__(self) -> None:
        if self.value not in {
            Decimal("-1"),
            Decimal("-0.5"),
            ZERO,
            Decimal("0.5"),
            ONE,
        }:
            raise ValueError("evidence value must be one of -1, -0.5, 0, 0.5, 1")
        for name in (
            "source_reliability",
            "extraction_confidence",
            "directness",
            "independence_factor",
            "freshness_factor",
        ):
            candidate = getattr(self, name)
            if candidate < ZERO or candidate > ONE:
                raise ValueError(f"{name} must be in [0, 1]")
        expected_polarity = (
            EvidencePolarity.SUPPORTS
            if self.value > ZERO
            else EvidencePolarity.CONTRADICTS
            if self.value < ZERO
            else self.polarity
        )
        if self.value != ZERO and self.polarity != expected_polarity:
            raise ValueError("evidence polarity must agree with signed value")
        if self.value == ZERO and self.polarity in {
            EvidencePolarity.SUPPORTS,
            EvidencePolarity.CONTRADICTS,
        }:
            raise ValueError("zero evidence cannot support or contradict")
        if self.value != ZERO and self.statement_status == StatementStatus.UNKNOWN:
            raise ValueError("UNKNOWN evidence must have value zero")
        for name in ("evidence_id", "source_id", "source_type", "correlation_group"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")

    @property
    def effective_weight(self) -> Decimal:
        return (
            self.source_reliability
            * self.extraction_confidence
            * self.directness
            * self.independence_factor
            * self.freshness_factor
        )


@dataclass(frozen=True, slots=True)
class FeatureConsensus:
    feature: FitmentFeature
    consensus: Decimal
    positive_support: Decimal
    negative_support: Decimal
    conflict_mass: Decimal
    coverage: bool
    evidence_present: bool
    contradiction: bool
    independent_group_count: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompatibilityAssessment:
    contract_version: str
    scoring_version: str
    status: CompatibilityStatus
    probability: Decimal
    positive_evidence: Decimal
    negative_evidence: Decimal
    coverage: Decimal
    contradiction_rate: Decimal
    missing_critical_ratio: Decimal
    hard_rejections: tuple[str, ...]
    reason_codes: tuple[str, ...]
    missing_critical_fields: tuple[str, ...]
    feature_consensus: Mapping[FitmentFeature, FeatureConsensus]
    authoritative_confirmation: bool
    requires_manual_review: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CommercialContext:
    condition: Condition = Condition.UNKNOWN
    package_quantity: Decimal | None = None
    unit_basis: str | None = None
    currency: str | None = None
    tier: ProductTier = ProductTier.UNKNOWN
    availability: Availability = Availability.UNKNOWN
    seller_relation: SellerRelation = SellerRelation.UNKNOWN
    stable_seller_id_verified: bool = False
    seller_group_id: str | None = None
    product_identity_key: str | None = None
    vat_included: bool | None = True

    def __post_init__(self) -> None:
        if self.package_quantity is not None and self.package_quantity <= ZERO:
            raise ValueError("package_quantity must be positive")


@dataclass(frozen=True, slots=True)
class PriceComparabilityAssessment:
    status: PriceComparabilityStatus
    eligible_for_pricing: bool
    competitor_weight: Decimal
    compatibility_factor: Decimal
    source_quality_factor: Decimal
    seller_independence_factor: Decimal
    availability_factor: Decimal
    freshness_factor: Decimal
    tier_factor: Decimal
    condition_factor: Decimal
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ComparableOffer:
    offer_id: str
    price: Decimal
    assessment: PriceComparabilityAssessment
    brand_article_key: str
    seller_group_id: str

    def __post_init__(self) -> None:
        if self.price <= ZERO:
            raise ValueError("offer price must be positive")


@dataclass(frozen=True, slots=True)
class MarketEnvelope:
    eligible_offer_count: int
    independent_seller_count: int
    effective_weight: Decimal
    weighted_q20: Decimal | None
    weighted_q25: Decimal | None
    weighted_q35: Decimal | None
    weighted_median: Decimal | None
    weighted_q75: Decimal | None
    weighted_q80: Decimal | None
    evidence_sufficient: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PriceAdvice:
    """Advisory-only result. ``requires_manual_approval`` is invariantly true."""

    action: str
    current_price: Decimal
    recommended_price: Decimal | None
    recommended_range_min: Decimal | None
    recommended_range_max: Decimal | None
    absolute_change: Decimal | None
    relative_change: Decimal | None
    market: MarketEnvelope
    requires_manual_approval: bool = True
