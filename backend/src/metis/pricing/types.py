"""Versioned Metis contracts for deterministic KEMP pricing decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping


ZERO = Decimal("0")
ONE = Decimal("1")


class ProductTier(str, Enum):
    OEM = "oem"
    OES = "oes"
    AFTERMARKET_A = "aftermarket_a"
    AFTERMARKET_B = "aftermarket_b"
    BUDGET = "budget"
    KEMP = "kemp"
    USED = "used"
    UNKNOWN = "unknown"


class StockStatus(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    DEAD_STOCK = "dead_stock"
    UNKNOWN = "unknown"


class RecommendationAction(str, Enum):
    RAISE = "RAISE"
    HOLD = "HOLD"
    LOWER = "LOWER"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class CoefficientModel(str, Enum):
    SIMPLE_MEDIAN = "simple_median"
    SHRINKAGE = "shrinkage"


class ConfidenceAggregation(str, Enum):
    MINIMUM = "minimum"
    GEOMETRIC = "geometric"


class RobustScaleMethod(str, Enum):
    """Versioned scale estimator selected for the decision dispersion."""

    LEGACY_MAD = "legacy_mad"
    IQR = "iqr"
    MAD = "mad"
    SN = "sn"
    QN = "qn"


class EvidenceState(str, Enum):
    """Four-valued evidence state; UNKNOWN is never treated as a match."""

    MATCH = "MATCH"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class HardGateResult(str, Enum):
    PASS = "PASS"
    REJECT = "REJECT"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class CohortRole(str, Enum):
    """Mutually exclusive Yuri V1 observation lanes."""

    TARGET_MARKET = "TARGET_MARKET"
    KEMP_REFERENCE = "KEMP_REFERENCE"
    OWNED_STORE = "OWNED_STORE"
    USED_REJECTED = "USED_REJECTED"
    DUMPING_DIAGNOSTIC = "DUMPING_DIAGNOSTIC"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    HARD_REJECTED = "HARD_REJECTED"


class ConditionState(str, Enum):
    NEW = "NEW"
    USED_OR_REFURBISHED = "USED_OR_REFURBISHED"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


class PriorityScoreType(str, Enum):
    ECONOMIC_ESTIMATE = "economic_estimate"
    GROSS_UPLIFT_OPPORTUNITY = "gross_uplift_opportunity"
    CLEARANCE_PRIORITY = "clearance_priority"
    RETAIL_EXPOSURE_PROXY = "retail_exposure_proxy"
    GAP_CONFIDENCE_PROXY = "gap_confidence_proxy"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class CalibrationPair:
    """One independent paired OE unit, already seller-deduplicated."""

    oe_norm: str
    category: str
    tier: ProductTier
    tier_price: Decimal
    reference_price: Decimal
    quality_weight: Decimal = ONE
    tier_observation_ids: tuple[str, ...] = field(default_factory=tuple)
    reference_observation_ids: tuple[str, ...] = field(default_factory=tuple)
    identity_evidence: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class TierCoefficient:
    category: str
    tier: ProductTier
    multiplier: Decimal
    model: CoefficientModel
    method_version: str
    sample_size: int
    effective_sample_size: Decimal
    confidence: Decimal
    validated: bool
    log_effect: Decimal
    global_log_effect: Decimal | None = None
    shrinkage_weight: Decimal | None = None
    interval_low: Decimal | None = None
    interval_high: Decimal | None = None
    dataset_hash: str = ""
    coefficient_version: str = ""
    validation_reasons: tuple[str, ...] = field(default_factory=tuple)
    excluded_oe_norm: str | None = None


@dataclass(frozen=True, slots=True)
class TierClassification:
    tier: ProductTier
    confidence: Decimal
    is_used: bool
    is_kemp: bool
    exclusion_reason: str | None
    reasons: tuple[str, ...]
    method_version: str


@dataclass(frozen=True, slots=True)
class DimensionEvidence:
    state: EvidenceState
    raw_value: str | None = None
    normalized_value: str | None = None
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    source_type: str | None = None
    source_record_id: str | None = None
    raw_evidence_sha256: str | None = None
    parser_contract_version: str | None = None
    schema_version: str = "comparison-evidence-v2"
    verified: bool = False


@dataclass(frozen=True, slots=True)
class SellerIdentityEvidence:
    stable_seller_id: str | None = None
    identity_source: str | None = None
    verified: bool = False


@dataclass(frozen=True, slots=True)
class ComparisonEvidence:
    """Immutable Marko -> Metis hard-comparability boundary."""

    dimensions: Mapping[str, DimensionEvidence]
    provenance: SourceProvenance
    seller_identity: SellerIdentityEvidence
    policy_id: str
    policy_hash: str
    retrieval_kind: str = "unknown"
    seed_product_id: str | None = None
    candidate_product_id: str | None = None
    approved_not_applicable: tuple[str, ...] = field(default_factory=tuple)
    hard_gate_result: HardGateResult = HardGateResult.MANUAL_REVIEW
    reason_codes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class CompetitorOffer:
    observation_id: str
    seller_id: str | None
    seller_name: str
    price: Decimal
    currency: str | None
    is_available: bool | None
    age_hours: Decimal
    match_confidence: Decimal
    tier: ProductTier
    tier_confidence: Decimal
    # Missing provenance confidence is fail-closed. Complete synthetic or API
    # inputs must opt in explicitly; persisted observations use the versioned
    # source-confidence assessor.
    source_confidence: Decimal = ZERO
    is_used: bool = False
    is_kemp: bool = False
    is_owned: bool = False
    is_dumping: bool = False
    severe_conflict: bool = False
    conflict_reason: str | None = None
    source: str = "unknown"
    listing_url: str | None = None
    currency_raw: str | None = None
    currency_inferred: bool = False
    currency_evidence: str | None = None
    comparison_evidence: ComparisonEvidence | None = None
    cohort_role: CohortRole | None = None


@dataclass(frozen=True, slots=True)
class ProductPricingContext:
    sku: str
    category: str
    current_price: Decimal
    currency: str = "UAH"
    stock_status: StockStatus = StockStatus.UNKNOWN
    cost: Decimal | None = None
    stock_qty: Decimal | None = None
    stock_age_days: Decimal | None = None
    expected_units_sold: Decimal | None = None
    liquidity_target: Decimal = ZERO
    urgency: Decimal = ZERO
    manual_priority: Decimal = ONE
    allow_below_cost: bool = False
    below_cost_floor: Decimal | None = None
    severe_data_health_issue: bool = False
    units_sold_30d: Decimal | None = None
    units_sold_60d: Decimal | None = None
    units_sold_90d: Decimal | None = None
    days_since_last_sale: Decimal | None = None
    historical_monthly_units: Decimal | None = None
    views_30d: Decimal | None = None
    conversion_rate_proxy: Decimal | None = None
    below_cost_authorization_id: str | None = None
    below_cost_authorized_by: str | None = None
    below_cost_authorized_at: datetime | None = None
    below_cost_reason: str | None = None
    below_cost_warning_confirmed: bool = False


def _default_factor_floors() -> dict[str, Decimal]:
    return {
        "coverage": Decimal("0.40"),
        "dispersion": Decimal("0.40"),
        "freshness": Decimal("0.40"),
        "match": Decimal("0.40"),
        "tier": Decimal("0.40"),
        "source": Decimal("0.40"),
    }


def _default_confidence_weights() -> dict[str, Decimal]:
    return {
        "coverage": ONE,
        "dispersion": ONE,
        "freshness": ONE,
        "match": ONE,
        "tier": ONE,
        "source": ONE,
    }


@dataclass(frozen=True, slots=True)
class RobustDispersionProfile:
    """Immutable, Gaussian-consistent comparison of robust scale estimators."""

    version: str
    correction_profile_version: str
    finite_sample_correction: bool
    sample_stage: str
    sample_size: int
    center: Decimal
    q1: Decimal
    q3: Decimal
    raw_iqr: Decimal
    raw_mad: Decimal
    gaussian_scales: Mapping[str, Decimal]
    robust_cvs: Mapping[str, Decimal]
    selected_method: RobustScaleMethod
    selected_scale: Decimal
    robust_cv: Decimal
    zero_scale_methods: tuple[str, ...]
    all_scales_zero: bool
    partial_scale_degeneracy: bool
    cv_min: Decimal
    cv_max: Decimal
    cv_span: Decimal
    cv_median: Decimal
    cv_relative_span: Decimal | None


@dataclass(frozen=True, slots=True)
class ClusterDiagnostic:
    """Deterministic log-price two-cluster diagnostic."""

    version: str
    available: bool
    sample_size: int
    min_cluster_size: int
    split_index: int | None
    objective_single: Decimal | None
    objective_split: Decimal | None
    improvement: Decimal | None
    balance: Decimal | None
    separation: Decimal | None
    gap: Decimal | None
    flagged: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PricingPolicy:
    version: str = "pricing-v2"
    currency: str = "UAH"
    max_age_hours: Decimal = Decimal("72")
    match_confidence_min: Decimal = Decimal("0.70")
    tier_confidence_min: Decimal = Decimal("0.60")
    source_confidence_min: Decimal = Decimal("0.50")
    min_competitors: int = 5
    manual_review_below: int = 5
    iqr_min_competitors: int = 8
    reference_competitors: int = 10
    max_dispersion: Decimal = Decimal("0.35")
    dispersion_method: RobustScaleMethod | None = None
    finite_sample_scale_correction: bool = True
    robust_dispersion_profile_version: str = "rc-scale-v1"
    robust_scale_correction_profile_version: str = "robustbase-modern-v1"
    robust_scale_max_cohort_size: int = 500
    robust_cluster_diagnostic_version: str = "log-l1-two-cluster-v1"
    robust_disagreement_threshold: Decimal = Decimal("1.0")
    robust_cluster_improvement_threshold: Decimal = Decimal("0.60")
    robust_cluster_balance_threshold: Decimal = Decimal("0.25")
    robust_cluster_separation_threshold: Decimal = Decimal("3")
    robust_cluster_gap_threshold: Decimal = Decimal("0.10")
    robust_cluster_sigma_floor: Decimal = Decimal("0.01")
    robust_cluster_min_size: int = 2
    robust_baseline_policy_version: str = "pricing-v2"
    robust_non_relaxation_enabled: bool = True
    freshness_half_life_hours: Decimal = Decimal("24")
    confidence_min: Decimal = Decimal("0.55")
    factor_floor: Decimal = Decimal("0.40")
    confidence_aggregation: ConfidenceAggregation = ConfidenceAggregation.GEOMETRIC
    mad_outlier_threshold: Decimal = Decimal("3.5")
    mad_zero_tolerance: Decimal = Decimal("0.02")
    sensitivity_tolerance: Decimal = Decimal("0.05")
    exclude_lower_tier_coefficients: bool = True
    kemp_dumping_ratio: Decimal = Decimal("0.85")
    min_raise_threshold: Decimal = Decimal("0.05")
    min_lower_threshold: Decimal = Decimal("0.05")
    safety_discount: Decimal = Decimal("0.95")
    max_raise_step: Decimal = Decimal("0.15")
    min_action_change: Decimal = Decimal("0.02")
    stale_markdown_beta: Decimal = Decimal("0.50")
    dead_stock_markdown_beta: Decimal = ONE
    stale_age_threshold_days: Decimal = Decimal("180")
    dead_stock_age_threshold_days: Decimal = ZERO
    stale_age_half_life_days: Decimal = Decimal("365")
    dead_stock_age_half_life_days: Decimal = Decimal("180")
    stock_age_policy_version: str = "yuri-v1-stock-age-assumption-v1"
    lower_market_quantile: Decimal = Decimal("0.25")
    minimum_margin: Decimal = ZERO
    price_tick: Decimal = ONE
    deadstock_factor: Decimal = Decimal("1.5")
    min_effective_competitors: Decimal = Decimal("3")
    factor_floors: Mapping[str, Decimal] = field(default_factory=_default_factor_floors)
    confidence_weights: Mapping[str, Decimal] = field(
        default_factory=_default_confidence_weights
    )
    confidence_epsilon: Decimal = Decimal("0.000001")
    minimum_absolute_tolerance: Decimal = ONE
    winsor_lower_quantile: Decimal = Decimal("0.10")
    winsor_upper_quantile: Decimal = Decimal("0.90")
    direct_kemp_ceiling_quantile: Decimal = Decimal("0.50")
    lower_market_support_enabled: bool = True
    coefficient_model: CoefficientModel = CoefficientModel.SHRINKAGE
    min_category_pairs: int = 8
    min_effective_pairs: Decimal = Decimal("5")
    min_global_pairs: int = 20
    shrinkage_k: Decimal = Decimal("10")
    max_allowed_interval_width: Decimal = Decimal("3")
    require_target_leakage_protection: bool = True
    age_weight_min: Decimal = Decimal("0.25")
    age_weight_max: Decimal = Decimal("2")
    age_reference_days: Decimal = Decimal("365")
    sales_recency_half_life_days: Decimal = Decimal("90")
    price_tick_version: str = "uah-integer-v1"

    def __post_init__(self) -> None:
        selected_method = self.dispersion_method
        if selected_method is None:
            selected_method = (
                RobustScaleMethod.QN
                if self.version
                in {"pricing-v3-robust-dispersion", "pricing-v3.1-heterogeneity-gated"}
                else RobustScaleMethod.LEGACY_MAD
            )
        else:
            try:
                selected_method = RobustScaleMethod(selected_method)
            except ValueError as exc:
                raise ValueError("unsupported dispersion_method") from exc
        if (
            self.version == "pricing-v2"
            and selected_method != RobustScaleMethod.LEGACY_MAD
        ):
            raise ValueError("pricing-v2 requires dispersion_method=legacy_mad")
        object.__setattr__(self, "dispersion_method", selected_method)

        currency = self.currency.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("currency must be a three-letter alphabetic code")
        object.__setattr__(self, "currency", currency)

        decimal_fields = (
            self.max_age_hours,
            self.match_confidence_min,
            self.tier_confidence_min,
            self.source_confidence_min,
            self.max_dispersion,
            self.robust_disagreement_threshold,
            self.robust_cluster_improvement_threshold,
            self.robust_cluster_balance_threshold,
            self.robust_cluster_separation_threshold,
            self.robust_cluster_gap_threshold,
            self.robust_cluster_sigma_floor,
            self.freshness_half_life_hours,
            self.confidence_min,
            self.factor_floor,
            self.mad_outlier_threshold,
            self.mad_zero_tolerance,
            self.sensitivity_tolerance,
            self.kemp_dumping_ratio,
            self.min_raise_threshold,
            self.min_lower_threshold,
            self.safety_discount,
            self.max_raise_step,
            self.min_action_change,
            self.stale_markdown_beta,
            self.dead_stock_markdown_beta,
            self.stale_age_threshold_days,
            self.dead_stock_age_threshold_days,
            self.stale_age_half_life_days,
            self.dead_stock_age_half_life_days,
            self.lower_market_quantile,
            self.minimum_margin,
            self.price_tick,
            self.deadstock_factor,
            self.min_effective_competitors,
            self.confidence_epsilon,
            self.minimum_absolute_tolerance,
            self.winsor_lower_quantile,
            self.winsor_upper_quantile,
            self.direct_kemp_ceiling_quantile,
            self.min_effective_pairs,
            self.shrinkage_k,
            self.max_allowed_interval_width,
            self.age_weight_min,
            self.age_weight_max,
            self.age_reference_days,
            self.sales_recency_half_life_days,
            self.stale_age_half_life_days,
            self.dead_stock_age_half_life_days,
        )
        if any(not value.is_finite() for value in decimal_fields):
            raise ValueError("pricing policy values must be finite")
        if self.min_competitors < 3 or self.manual_review_below < 3:
            raise ValueError("minimum competitor thresholds must be at least 3")
        if self.iqr_min_competitors < self.min_competitors:
            raise ValueError("iqr_min_competitors must be >= min_competitors")
        if self.reference_competitors < 1:
            raise ValueError("reference_competitors must be positive")
        if self.robust_scale_max_cohort_size < 2:
            raise ValueError("robust_scale_max_cohort_size must be at least 2")
        if self.robust_cluster_min_size < 2:
            raise ValueError("robust_cluster_min_size must be at least 2")
        if self.min_category_pairs < 3 or self.min_global_pairs < 3:
            raise ValueError("calibration sample thresholds must be at least 3")
        if not isinstance(self.finite_sample_scale_correction, bool):
            raise ValueError("finite_sample_scale_correction must be boolean")
        if self.robust_dispersion_profile_version != "rc-scale-v1":
            raise ValueError("unsupported robust_dispersion_profile_version")
        if self.robust_scale_correction_profile_version != "robustbase-modern-v1":
            raise ValueError("unsupported robust_scale_correction_profile_version")
        positive = (
            self.max_age_hours,
            self.max_dispersion,
            self.robust_cluster_separation_threshold,
            self.robust_cluster_sigma_floor,
            self.freshness_half_life_hours,
            self.price_tick,
            self.mad_outlier_threshold,
            self.deadstock_factor,
            self.min_effective_competitors,
            self.confidence_epsilon,
            self.minimum_absolute_tolerance,
            self.min_effective_pairs,
            self.shrinkage_k,
            self.max_allowed_interval_width,
            self.age_weight_max,
            self.age_reference_days,
            self.sales_recency_half_life_days,
            self.stale_age_half_life_days,
            self.dead_stock_age_half_life_days,
        )
        if any(value <= ZERO for value in positive):
            raise ValueError("positive pricing policy values must be greater than zero")
        bounded = (
            self.match_confidence_min,
            self.tier_confidence_min,
            self.source_confidence_min,
            self.confidence_min,
            self.factor_floor,
            self.kemp_dumping_ratio,
            self.min_raise_threshold,
            self.min_lower_threshold,
            self.safety_discount,
            self.max_raise_step,
            self.min_action_change,
            self.stale_markdown_beta,
            self.dead_stock_markdown_beta,
            self.lower_market_quantile,
            self.mad_zero_tolerance,
            self.sensitivity_tolerance,
            self.winsor_lower_quantile,
            self.winsor_upper_quantile,
            self.direct_kemp_ceiling_quantile,
            self.robust_cluster_improvement_threshold,
            self.robust_cluster_balance_threshold,
            self.robust_cluster_gap_threshold,
        )
        if any(value < ZERO or value > ONE for value in bounded):
            raise ValueError("pricing policy probability values must be in [0, 1]")
        if self.winsor_lower_quantile >= self.winsor_upper_quantile:
            raise ValueError("winsor quantiles must be strictly ordered")
        if self.minimum_margin < ZERO:
            raise ValueError("minimum_margin cannot be negative")
        if (
            self.stale_age_threshold_days < ZERO
            or self.dead_stock_age_threshold_days < ZERO
        ):
            raise ValueError("stock age thresholds cannot be negative")
        if self.dead_stock_markdown_beta < self.stale_markdown_beta:
            raise ValueError("dead-stock base pressure cannot be below stale pressure")
        if self.dead_stock_age_threshold_days > self.stale_age_threshold_days:
            raise ValueError("dead-stock age threshold cannot exceed stale threshold")
        if self.dead_stock_age_half_life_days > self.stale_age_half_life_days:
            raise ValueError("dead-stock age half-life cannot exceed stale half-life")
        if self.age_weight_min < ZERO:
            raise ValueError("age_weight_min cannot be negative")
        if self.age_weight_min > self.age_weight_max:
            raise ValueError("age_weight_min cannot exceed age_weight_max")

        floors = {
            name: Decimal(str(value)) for name, value in self.factor_floors.items()
        }
        weights = {
            name: Decimal(str(value)) for name, value in self.confidence_weights.items()
        }
        expected = set(_default_factor_floors())
        if set(floors) != expected or set(weights) != expected:
            raise ValueError(
                "factor_floors and confidence_weights must cover all factors"
            )
        if any(value < ZERO or value > ONE for value in floors.values()):
            raise ValueError("factor floors must be in [0, 1]")
        if any(value <= ZERO for value in weights.values()):
            raise ValueError("confidence weights must be positive")
        object.__setattr__(self, "factor_floors", floors)
        object.__setattr__(self, "confidence_weights", weights)

    def floor_for(self, factor: str) -> Decimal:
        return max(self.factor_floor, self.factor_floors.get(factor, self.factor_floor))


@dataclass(frozen=True, slots=True)
class NormalizedOffer:
    observation_id: str
    seller_id: str | None
    seller_name: str
    tier: ProductTier
    raw_price: Decimal
    normalized_price: Decimal
    multiplier: Decimal
    coefficient_confidence: Decimal
    age_hours: Decimal
    match_confidence: Decimal
    tier_confidence: Decimal
    source_confidence: Decimal
    coefficient_model: CoefficientModel | None = None
    coefficient_version: str = "reference-tier-v1"
    coefficient_sample_size: int = 0
    coefficient_effective_sample_size: Decimal = ZERO
    coefficient_dataset_hash: str = ""
    is_direct_kemp: bool = False
    source: str = "unknown"
    listing_url: str | None = None
    comparison_evidence: ComparisonEvidence | None = None
    cohort_role: CohortRole = CohortRole.TARGET_MARKET


@dataclass(frozen=True, slots=True)
class ExcludedOffer:
    observation_id: str
    reason: str
    seller_id: str | None = None
    raw_price: Decimal | None = None
    tier: ProductTier | None = None
    stage: str = "eligibility"
    cohort_role: CohortRole = CohortRole.HARD_REJECTED


@dataclass(frozen=True, slots=True)
class PricingResult:
    sku: str
    action: RecommendationAction
    current_price: Decimal
    fair_price: Decimal | None
    recommended_price: Decimal | None
    lower_bound: Decimal | None
    upper_bound: Decimal | None
    confidence: Decimal
    confidence_grade: str
    weakest_factor: str | None
    factor_scores: Mapping[str, Decimal]
    competitor_count: int
    effective_competitor_count: Decimal
    dispersion: Decimal | None
    priority_score: Decimal
    priority_score_type: PriorityScoreType
    review_priority: Decimal
    reasons: tuple[str, ...]
    evidence: tuple[NormalizedOffer, ...] = field(default_factory=tuple)
    excluded: tuple[ExcludedOffer, ...] = field(default_factory=tuple)
    policy_version: str = "pricing-v2"
    raw_competitor_count: int = 0
    unique_seller_count: int = 0
    clean_competitor_count: int = 0
    outlier_method: str = "none"
    outlier_count: int = 0
    sensitivity: Decimal | None = None
    winsorized_fair_price: Decimal | None = None
    action_gates_passed: bool = False
    cost_floor: Decimal | None = None
    cost_basis_inventory_value: Decimal | None = None
    priority_inputs: Mapping[str, str] = field(default_factory=dict)
    data_health_issues: tuple[str, ...] = field(default_factory=tuple)
    dispersion_method: RobustScaleMethod = RobustScaleMethod.LEGACY_MAD
    pre_clean_dispersion_profile: RobustDispersionProfile | None = None
    dispersion_profile: RobustDispersionProfile | None = None
    robust_dispersion_profile_version: str = "rc-scale-v1"
    robust_scale_correction_profile_version: str = "robustbase-modern-v1"
    finite_sample_scale_correction: bool = True
    automatic_eligible: bool = False
    verified_seller_count: int = 0
    comparability_policy_id: str = "yuri-v1-comparability-v2"
    comparability_policy_hash: str = ""
    hard_gate_results: Mapping[str, int] = field(default_factory=dict)
    failed_hard_gates: tuple[str, ...] = field(default_factory=tuple)
    unknown_hard_fields: tuple[str, ...] = field(default_factory=tuple)
    cluster_diagnostic: ClusterDiagnostic | None = None
    robust_policy_fingerprint: Mapping[str, str] = field(default_factory=dict)
    target_market_count: int = 0
    kemp_reference_count: int = 0
    owned_store_count: int = 0
    rejected_count: int = 0
    kemp_reference_evidence: tuple[NormalizedOffer, ...] = field(default_factory=tuple)
    absolute_recommended_change: Decimal | None = None
    percentage_recommended_change: Decimal | None = None


__all__ = [
    "CalibrationPair",
    "CoefficientModel",
    "ClusterDiagnostic",
    "CohortRole",
    "ComparisonEvidence",
    "CompetitorOffer",
    "ConfidenceAggregation",
    "ConditionState",
    "DimensionEvidence",
    "EvidenceState",
    "ExcludedOffer",
    "NormalizedOffer",
    "PricingPolicy",
    "PricingResult",
    "PriorityScoreType",
    "ProductPricingContext",
    "ProductTier",
    "RecommendationAction",
    "RobustDispersionProfile",
    "RobustScaleMethod",
    "HardGateResult",
    "SellerIdentityEvidence",
    "SourceProvenance",
    "StockStatus",
    "TierClassification",
    "TierCoefficient",
]
