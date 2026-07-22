"""Deterministic human-in-the-loop market and pricing mathematics.

This module is deliberately pure: it neither retrieves third-party pages nor
publishes a marketplace price.  It converts already persisted, provenance-
bearing facts into reproducible seller, reliability, market and advisory-price
results.  Every price result requires an explicit human decision downstream.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from enum import StrEnum
import math

from .types import SellerRelation, SourceTier


ZERO = Decimal("0")
ONE = Decimal("1")
HITL_MARKET_CONTRACT_VERSION = "metis-hitl-market-v1"
HITL_RECOMMENDATION_VERSION = "metis-hitl-recommendation-v1"
SOURCE_RELIABILITY_VERSION = "metis-source-beta-v1"
SELLER_RESOLUTION_VERSION = "metis-seller-noisy-or-v1"


class PriceUnitStatus(StrEnum):
    VERIFIED_PIECE = "verified_piece"
    NORMALIZED_PAIR = "normalized_pair"
    NORMALIZED_AXLE_SET = "normalized_axle_set"
    NORMALIZED_KIT = "normalized_kit"
    UNKNOWN = "unknown"
    INCOMPATIBLE = "incompatible"


class PricingStrategy(StrEnum):
    AGGRESSIVE = "aggressive"
    BALANCED = "balanced"
    MARGIN_FIRST = "margin_first"
    INVENTORY_CLEARANCE = "inventory_clearance"
    CUSTOM = "custom"


class RecommendationAction(StrEnum):
    CONSIDER_RAISE = "consider_raise"
    HOLD = "hold"
    CONSIDER_REDUCE = "consider_reduce"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    MANUAL_RESEARCH_REQUIRED = "manual_research_required"


class RecommendationDecision(StrEnum):
    ACCEPTED = "accepted"
    ACCEPTED_WITH_MODIFICATION = "accepted_with_modification"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    RESEARCH_REQUESTED = "research_requested"


class FeedbackReason(StrEnum):
    WRONG_SIDE = "wrong_side"
    WRONG_AXLE = "wrong_axle"
    WRONG_GENERATION = "wrong_generation"
    WRONG_YEAR = "wrong_year"
    WRONG_ENGINE = "wrong_engine"
    WRONG_BODY = "wrong_body"
    WRONG_PART_CATEGORY = "wrong_part_category"
    WRONG_CONDITION = "wrong_condition"
    WRONG_QUANTITY = "wrong_quantity"
    INCORRECT_OE = "incorrect_oe"
    INCORRECT_CROSS = "incorrect_cross"
    SAME_OWNER = "same_owner"
    RELATED_SELLER = "related_seller"
    PRICE_NOT_REPRESENTATIVE = "price_not_representative"
    OUT_OF_STOCK = "out_of_stock"
    SOURCE_ERROR = "source_error"
    OTHER = "other"


SOURCE_TIER_BETA_PRIORS: Mapping[SourceTier, tuple[Decimal, Decimal]] = {
    SourceTier.A: (Decimal("19"), Decimal("1")),
    SourceTier.B: (Decimal("8"), Decimal("2")),
    SourceTier.C: (Decimal("6"), Decimal("4")),
    SourceTier.D: (Decimal("4"), Decimal("6")),
    SourceTier.E: (Decimal("2"), Decimal("8")),
}


SELLER_SIGNAL_WEIGHTS: Mapping[str, Decimal] = {
    "same_legal_entity": Decimal("1.00"),
    "same_platform_owner_id": Decimal("1.00"),
    "same_payout_details": Decimal("1.00"),
    "same_verified_phone": Decimal("0.90"),
    "same_verified_email": Decimal("0.85"),
    "same_official_domain": Decimal("0.80"),
    "same_return_address": Decimal("0.65"),
    "same_support_contacts": Decimal("0.65"),
    "same_catalog_sku_pattern": Decimal("0.30"),
    "same_description_template": Decimal("0.18"),
    "same_image_set": Decimal("0.15"),
    "synchronized_prices": Decimal("0.10"),
}

_DETERMINISTIC_SELLER_SIGNALS = frozenset(
    {"same_legal_entity", "same_platform_owner_id", "same_payout_details"}
)
_STRONG_SELLER_SIGNALS = frozenset(
    {
        *_DETERMINISTIC_SELLER_SIGNALS,
        "same_verified_phone",
        "same_verified_email",
        "same_official_domain",
    }
)
_CORRELATED_WEAK_SIGNAL_GROUPS: Mapping[str, str] = {
    "same_catalog_sku_pattern": "copied_catalog",
    "same_description_template": "copied_catalog",
    "same_image_set": "copied_catalog",
    "synchronized_prices": "copied_catalog",
}
_CORRELATED_GROUP_CAPS: Mapping[str, Decimal] = {
    "copied_catalog": Decimal("0.30"),
}


@dataclass(frozen=True, slots=True)
class SourceReliability:
    source_tier: SourceTier
    claim_type: str
    prior_alpha: Decimal
    prior_beta: Decimal
    confirmed_count: int
    rejected_count: int
    reliability: Decimal
    version: str = SOURCE_RELIABILITY_VERSION


@dataclass(frozen=True, slots=True)
class SellerResolution:
    relation: SellerRelation
    relation_score: Decimal
    strong_identifier_present: bool
    deterministic_match: bool
    contributions: Mapping[str, Decimal]
    reason_codes: tuple[str, ...]
    version: str = SELLER_RESOLUTION_VERSION


@dataclass(frozen=True, slots=True)
class NormalizedPriceUnit:
    listing_price: Decimal
    quantity_in_offer: Decimal | None
    raw_unit_basis: str | None
    normalized_unit_basis: str | None
    normalized_price_per_piece: Decimal | None
    status: PriceUnitStatus
    certainty_factor: Decimal
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WeightedMarketOffer:
    offer_id: str
    normalized_unit_price: Decimal
    fitment_score: Decimal
    price_comparability: Decimal
    source_quality: Decimal
    availability_factor: Decimal
    freshness_factor: Decimal
    seller_independence_factor: Decimal
    unit_certainty: Decimal
    part_identity_key: str
    seller_group_id: str
    preserve_if_outlier: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.offer_id.strip() or not self.part_identity_key.strip():
            raise ValueError("offer and part identity keys are required")
        if not self.seller_group_id.strip():
            raise ValueError("seller_group_id is required")
        if self.normalized_unit_price <= ZERO:
            raise ValueError("normalized_unit_price must be positive")
        for name in (
            "fitment_score",
            "price_comparability",
            "source_quality",
            "availability_factor",
            "freshness_factor",
            "seller_independence_factor",
            "unit_certainty",
        ):
            value = getattr(self, name)
            if value < ZERO or value > ONE:
                raise ValueError(f"{name} must be in [0, 1]")

    @property
    def raw_weight(self) -> Decimal:
        return (
            self.fitment_score**2
            * self.price_comparability
            * self.source_quality
            * self.availability_factor
            * self.freshness_factor
            * self.seller_independence_factor
            * self.unit_certainty
        )


@dataclass(frozen=True, slots=True)
class MarketOfferDecision:
    offer_id: str
    normalized_unit_price: Decimal
    raw_weight: Decimal
    capped_weight: Decimal
    included: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RobustMarketStatistics:
    contract_version: str
    collected_offer_count: int
    eligible_offer_count: int
    included_offer_count: int
    outlier_count: int
    independent_seller_groups: int
    unique_part_identities: int
    total_weight: Decimal
    effective_sample_size: Decimal
    weighted_min: Decimal | None
    weighted_q20: Decimal | None
    weighted_q25: Decimal | None
    weighted_q35: Decimal | None
    weighted_median: Decimal | None
    weighted_q75: Decimal | None
    weighted_q80: Decimal | None
    weighted_max: Decimal | None
    log_price_iqr: Decimal | None
    weighted_log_mad: Decimal | None
    mean_fitment_quality: Decimal
    mean_source_quality: Decimal
    mean_freshness: Decimal
    completeness: Decimal
    decisions: tuple[MarketOfferDecision, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecommendationConfidence:
    value: Decimal
    fitment: Decimal
    source: Decimal
    freshness: Decimal
    sample: Decimal
    diversity: Decimal
    stability: Decimal
    completeness: Decimal


@dataclass(frozen=True, slots=True)
class HumanPriceRecommendation:
    contract_version: str
    recommendation_version: str
    action: RecommendationAction
    strategy: PricingStrategy
    current_price: Decimal
    currency: str
    recommended_price: Decimal | None
    recommended_range_min: Decimal | None
    recommended_range_max: Decimal | None
    absolute_change: Decimal | None
    relative_change: Decimal | None
    market_anchor: Decimal | None
    price_floor: Decimal | None
    confidence: RecommendationConfidence
    market: RobustMarketStatistics
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    requires_manual_approval: bool = True
    automatic_price_change_allowed: bool = False


def posterior_source_reliability(
    source_tier: SourceTier,
    claim_type: str,
    *,
    confirmed_count: int = 0,
    rejected_count: int = 0,
) -> SourceReliability:
    """Return a Beta posterior mean for one source and one claim type."""

    if confirmed_count < 0 or rejected_count < 0:
        raise ValueError("source reliability counters cannot be negative")
    normalized_claim = claim_type.strip().casefold()
    if not normalized_claim:
        raise ValueError("claim_type is required")
    alpha, beta = SOURCE_TIER_BETA_PRIORS[source_tier]
    reliability = (
        (alpha + Decimal(confirmed_count))
        / (alpha + beta + Decimal(confirmed_count + rejected_count))
    ).quantize(Decimal("0.0001"))
    return SourceReliability(
        source_tier=source_tier,
        claim_type=normalized_claim,
        prior_alpha=alpha,
        prior_beta=beta,
        confirmed_count=confirmed_count,
        rejected_count=rejected_count,
        reliability=reliability,
    )


def resolve_seller_relation(
    matches: Mapping[str, Decimal | int | float | str],
    *,
    known_own_registry_match: bool = False,
) -> SellerResolution:
    """Resolve seller ownership using deterministic identifiers and noisy-OR.

    Copied images/descriptions/prices share one capped contribution and can
    never classify a seller as ``own`` without a strong identifier.
    """

    normalized: dict[str, Decimal] = {}
    for signal, raw_value in matches.items():
        if signal not in SELLER_SIGNAL_WEIGHTS:
            raise ValueError(f"unknown seller signal: {signal}")
        value = Decimal(str(raw_value))
        if value < ZERO or value > ONE:
            raise ValueError(f"seller signal {signal} must be in [0, 1]")
        normalized[signal] = value

    deterministic = known_own_registry_match or any(
        normalized.get(signal, ZERO) == ONE
        for signal in _DETERMINISTIC_SELLER_SIGNALS
    )
    strong = deterministic or any(
        normalized.get(signal, ZERO) > ZERO for signal in _STRONG_SELLER_SIGNALS
    )
    contributions: dict[str, Decimal] = {}
    grouped: dict[str, list[Decimal]] = defaultdict(list)
    for signal, match in normalized.items():
        contribution = SELLER_SIGNAL_WEIGHTS[signal] * match
        group = _CORRELATED_WEAK_SIGNAL_GROUPS.get(signal)
        if group:
            grouped[group].append(contribution)
        else:
            contributions[signal] = contribution
    for group, values in grouped.items():
        group_noisy_or = ONE
        for contribution in values:
            group_noisy_or *= ONE - contribution
        contributions[group] = min(
            ONE - group_noisy_or,
            _CORRELATED_GROUP_CAPS[group],
        )

    if known_own_registry_match:
        contributions["known_own_registry"] = ONE
    product = ONE
    for contribution in contributions.values():
        product *= ONE - contribution
    score = (ONE - product).quantize(Decimal("0.0001"))

    reasons: list[str] = []
    if deterministic:
        relation = SellerRelation.OWN
        reasons.append("DETERMINISTIC_OWN_IDENTIFIER")
    elif score >= Decimal("0.95") and strong:
        relation = SellerRelation.OWN
        reasons.append("HIGH_RELATION_SCORE_WITH_STRONG_IDENTIFIER")
    elif score >= Decimal("0.80"):
        relation = SellerRelation.RELATED
        reasons.append("RELATED_SELLER_SCORE")
    elif score >= Decimal("0.55"):
        relation = SellerRelation.POSSIBLY_RELATED
        reasons.append("POSSIBLY_RELATED_SELLER_SCORE")
    else:
        # Low evidence is not proof of independence.
        relation = SellerRelation.UNKNOWN
        reasons.append("INDEPENDENCE_NOT_PROVEN")
    if grouped:
        reasons.append("CORRELATED_WEAK_SIGNALS_CAPPED")
    return SellerResolution(
        relation=relation,
        relation_score=score,
        strong_identifier_present=strong,
        deterministic_match=deterministic,
        contributions=dict(sorted(contributions.items())),
        reason_codes=tuple(reasons),
    )


def normalize_price_unit(
    listing_price: Decimal,
    *,
    quantity_in_offer: Decimal | None,
    unit_basis: str | None,
    homogeneous_kit: bool = False,
) -> NormalizedPriceUnit:
    """Normalize a listing price to one comparable piece when proven."""

    if listing_price <= ZERO:
        raise ValueError("listing_price must be positive")
    if quantity_in_offer is not None and quantity_in_offer <= ZERO:
        raise ValueError("quantity_in_offer must be positive")
    basis = " ".join((unit_basis or "").casefold().strip().split()) or None
    piece_aliases = {"piece", "one piece", "pc", "pcs", "шт", "штука", "одна штука"}
    pair_aliases = {"pair", "пара", "комплект 2", "set of 2"}
    axle_aliases = {"axle set", "комплект на ось", "на ось"}
    kit_aliases = {"kit", "комплект", "set"}

    status = PriceUnitStatus.UNKNOWN
    certainty = Decimal("0.30")
    normalized_quantity = quantity_in_offer
    reasons: list[str] = []
    if basis in piece_aliases:
        normalized_quantity = quantity_in_offer or ONE
        status = PriceUnitStatus.VERIFIED_PIECE
        certainty = ONE
    elif basis in pair_aliases:
        normalized_quantity = quantity_in_offer or Decimal("2")
        if normalized_quantity == Decimal("2"):
            status = PriceUnitStatus.NORMALIZED_PAIR
            certainty = Decimal("0.95")
        else:
            status = PriceUnitStatus.INCOMPATIBLE
            certainty = ZERO
            reasons.append("PAIR_QUANTITY_CONFLICT")
    elif basis in axle_aliases:
        normalized_quantity = quantity_in_offer or Decimal("2")
        if normalized_quantity == Decimal("2"):
            status = PriceUnitStatus.NORMALIZED_AXLE_SET
            certainty = Decimal("0.90")
        else:
            status = PriceUnitStatus.INCOMPATIBLE
            certainty = ZERO
            reasons.append("AXLE_SET_QUANTITY_CONFLICT")
    elif basis in kit_aliases and homogeneous_kit and quantity_in_offer is not None:
        status = PriceUnitStatus.NORMALIZED_KIT
        certainty = Decimal("0.85")
    elif basis in kit_aliases:
        reasons.append("HETEROGENEOUS_OR_UNPROVEN_KIT")
    else:
        reasons.append("PRICE_UNIT_UNKNOWN")

    normalized_price = None
    if status not in {PriceUnitStatus.UNKNOWN, PriceUnitStatus.INCOMPATIBLE}:
        if normalized_quantity is None or normalized_quantity <= ZERO:
            raise RuntimeError("normalizable unit must have positive quantity")
        normalized_price = (listing_price / normalized_quantity).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        reasons.append("PRICE_NORMALIZED_PER_PIECE")
    return NormalizedPriceUnit(
        listing_price=listing_price,
        quantity_in_offer=normalized_quantity,
        raw_unit_basis=unit_basis,
        normalized_unit_basis="piece" if normalized_price is not None else None,
        normalized_price_per_piece=normalized_price,
        status=status,
        certainty_factor=certainty,
        reason_codes=tuple(reasons),
    )


def freshness_decay(age_days: Decimal, *, tau_days: Decimal = Decimal("30")) -> Decimal:
    if age_days < ZERO:
        raise ValueError("age_days cannot be negative")
    if tau_days <= ZERO:
        raise ValueError("tau_days must be positive")
    return Decimal(str(math.exp(-float(age_days / tau_days)))).quantize(
        Decimal("0.0001")
    )


def weighted_quantile(
    values: Sequence[tuple[Decimal, Decimal]], quantile: Decimal
) -> Decimal | None:
    if quantile < ZERO or quantile > ONE:
        raise ValueError("quantile must be in [0, 1]")
    positive = sorted(
        ((value, weight) for value, weight in values if weight > ZERO),
        key=lambda item: (item[0], item[1]),
    )
    if not positive:
        return None
    total = sum((weight for _, weight in positive), ZERO)
    threshold = total * quantile
    cumulative = ZERO
    for value, weight in positive:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return positive[-1][0]


def _cap_group_weights(
    offers: Sequence[WeightedMarketOffer],
    weights: dict[str, Decimal],
    *,
    key_name: str,
    cap: Decimal,
) -> None:
    groups: dict[str, list[WeightedMarketOffer]] = defaultdict(list)
    for offer in offers:
        groups[getattr(offer, key_name)].append(offer)
    for group in groups.values():
        total = sum((weights[item.offer_id] for item in group), ZERO)
        if total > cap:
            scale = cap / total
            for item in group:
                weights[item.offer_id] *= scale


def _weighted_average(
    offers: Sequence[WeightedMarketOffer],
    weights: Mapping[str, Decimal],
    attribute: str,
) -> Decimal:
    total = sum((weights[offer.offer_id] for offer in offers), ZERO)
    if total <= ZERO:
        return ZERO
    return (
        sum(
            (
                getattr(offer, attribute) * weights[offer.offer_id]
                for offer in offers
            ),
            ZERO,
        )
        / total
    ).quantize(Decimal("0.0001"))


def build_robust_market_statistics(
    offers: Iterable[WeightedMarketOffer],
    *,
    article_weight_cap: Decimal = Decimal("1.5"),
    seller_group_weight_cap: Decimal = ONE,
    outlier_z: Decimal = Decimal("3.5"),
) -> RobustMarketStatistics:
    """Build a capped, outlier-audited weighted market distribution."""

    collected = tuple(offers)
    if article_weight_cap <= ZERO or seller_group_weight_cap <= ZERO:
        raise ValueError("market influence caps must be positive")
    if outlier_z <= ZERO:
        raise ValueError("outlier_z must be positive")
    eligible = tuple(offer for offer in collected if offer.raw_weight > ZERO)
    weights = {offer.offer_id: offer.raw_weight for offer in eligible}
    if len(weights) != len(eligible):
        raise ValueError("offer_id must be unique within a market snapshot")
    _cap_group_weights(
        eligible,
        weights,
        key_name="part_identity_key",
        cap=article_weight_cap,
    )
    _cap_group_weights(
        eligible,
        weights,
        key_name="seller_group_id",
        cap=seller_group_weight_cap,
    )

    log_values = [
        (Decimal(str(math.log(float(offer.normalized_unit_price)))), weights[offer.offer_id])
        for offer in eligible
    ]
    log_median = weighted_quantile(log_values, Decimal("0.5"))
    log_mad = None
    outlier_ids: set[str] = set()
    if log_median is not None and len(log_values) >= 3:
        deviations = [(abs(value - log_median), weight) for value, weight in log_values]
        log_mad = weighted_quantile(deviations, Decimal("0.5"))
        if log_mad is not None:
            threshold = outlier_z * Decimal("1.4826") * log_mad
            for offer, (log_value, _) in zip(eligible, log_values, strict=True):
                if (
                    abs(log_value - log_median) > threshold
                    and not offer.preserve_if_outlier
                ):
                    outlier_ids.add(offer.offer_id)

    included = tuple(offer for offer in eligible if offer.offer_id not in outlier_ids)
    weighted_prices = [
        (offer.normalized_unit_price, weights[offer.offer_id]) for offer in included
    ]
    total_weight = sum((weight for _, weight in weighted_prices), ZERO)
    sum_squares = sum((weight**2 for _, weight in weighted_prices), ZERO)
    effective_sample = (
        (total_weight**2 / sum_squares).quantize(Decimal("0.0001"))
        if sum_squares > ZERO
        else ZERO
    )
    quantiles = {
        quantile: weighted_quantile(weighted_prices, quantile)
        for quantile in (
            ZERO,
            Decimal("0.20"),
            Decimal("0.25"),
            Decimal("0.35"),
            Decimal("0.50"),
            Decimal("0.75"),
            Decimal("0.80"),
            ONE,
        )
    }
    q25 = quantiles[Decimal("0.25")]
    q75 = quantiles[Decimal("0.75")]
    log_iqr = None
    if q25 is not None and q75 is not None:
        log_iqr = Decimal(str(math.log(float(q75 / q25)))).quantize(
            Decimal("0.0001")
        )

    decision_rows: list[MarketOfferDecision] = []
    for offer in collected:
        if offer.raw_weight <= ZERO:
            reasons = ("ZERO_EVIDENCE_WEIGHT",)
            capped = ZERO
            included_flag = False
        elif offer.offer_id in outlier_ids:
            reasons = ("LOG_MAD_PRICE_OUTLIER",)
            capped = weights[offer.offer_id]
            included_flag = False
        else:
            capped = weights[offer.offer_id]
            included_flag = True
            reasons = (
                ("INCLUDED_WITH_INFLUENCE_CAP",)
                if capped < offer.raw_weight
                else ("INCLUDED",)
            )
        decision_rows.append(
            MarketOfferDecision(
                offer_id=offer.offer_id,
                normalized_unit_price=offer.normalized_unit_price,
                raw_weight=offer.raw_weight.quantize(Decimal("0.000001")),
                capped_weight=capped.quantize(Decimal("0.000001")),
                included=included_flag,
                reason_codes=reasons,
            )
        )

    sellers = {offer.seller_group_id for offer in included}
    identities = {offer.part_identity_key for offer in included}
    completeness = (
        Decimal(len(eligible)) / Decimal(len(collected)) if collected else ZERO
    ).quantize(Decimal("0.0001"))
    reasons: list[str] = []
    if effective_sample < Decimal("2"):
        reasons.append("INSUFFICIENT_EFFECTIVE_SAMPLE_SIZE")
    if len(sellers) < 2:
        reasons.append("INSUFFICIENT_INDEPENDENT_SELLER_GROUPS")
    if outlier_ids:
        reasons.append("PRICE_OUTLIERS_RETAINED_IN_AUDIT_ONLY")
    if not reasons:
        reasons.append("ROBUST_MARKET_EVIDENCE_AVAILABLE")
    return RobustMarketStatistics(
        contract_version=HITL_MARKET_CONTRACT_VERSION,
        collected_offer_count=len(collected),
        eligible_offer_count=len(eligible),
        included_offer_count=len(included),
        outlier_count=len(outlier_ids),
        independent_seller_groups=len(sellers),
        unique_part_identities=len(identities),
        total_weight=total_weight.quantize(Decimal("0.000001")),
        effective_sample_size=effective_sample,
        weighted_min=quantiles[ZERO],
        weighted_q20=quantiles[Decimal("0.20")],
        weighted_q25=q25,
        weighted_q35=quantiles[Decimal("0.35")],
        weighted_median=quantiles[Decimal("0.50")],
        weighted_q75=q75,
        weighted_q80=quantiles[Decimal("0.80")],
        weighted_max=quantiles[ONE],
        log_price_iqr=log_iqr,
        weighted_log_mad=(
            log_mad.quantize(Decimal("0.0001")) if log_mad is not None else None
        ),
        mean_fitment_quality=_weighted_average(included, weights, "fitment_score"),
        mean_source_quality=_weighted_average(included, weights, "source_quality"),
        mean_freshness=_weighted_average(included, weights, "freshness_factor"),
        completeness=completeness,
        decisions=tuple(decision_rows),
        reason_codes=tuple(reasons),
    )


def calculate_contribution_floor(
    cost_of_goods: Decimal,
    *,
    fixed_cost_per_order: Decimal = ZERO,
    variable_rate: Decimal = ZERO,
    target_contribution_margin_rate: Decimal = ZERO,
) -> Decimal:
    if cost_of_goods <= ZERO or fixed_cost_per_order < ZERO:
        raise ValueError("cost and fixed order cost are invalid")
    if variable_rate < ZERO or target_contribution_margin_rate < ZERO:
        raise ValueError("rates cannot be negative")
    denominator = ONE - variable_rate - target_contribution_margin_rate
    if denominator <= ZERO:
        raise ValueError("1 - variable_rate - margin_rate must be positive")
    return ((cost_of_goods + fixed_cost_per_order) / denominator).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def recommendation_confidence(
    market: RobustMarketStatistics,
) -> RecommendationConfidence:
    sample = min(ONE, market.effective_sample_size / Decimal("5"))
    diversity = min(ONE, Decimal(market.independent_seller_groups) / Decimal("4"))
    stability = (
        Decimal(str(math.exp(-float(market.log_price_iqr / Decimal("0.35")))))
        if market.log_price_iqr is not None
        else ZERO
    )
    value = (
        Decimal("0.25") * market.mean_fitment_quality
        + Decimal("0.15") * market.mean_source_quality
        + Decimal("0.15") * market.mean_freshness
        + Decimal("0.15") * sample
        + Decimal("0.15") * diversity
        + Decimal("0.10") * stability
        + Decimal("0.05") * market.completeness
    ).quantize(Decimal("0.0001"))
    return RecommendationConfidence(
        value=_clamp(value),
        fitment=market.mean_fitment_quality,
        source=market.mean_source_quality,
        freshness=market.mean_freshness,
        sample=sample.quantize(Decimal("0.0001")),
        diversity=diversity.quantize(Decimal("0.0001")),
        stability=stability.quantize(Decimal("0.0001")),
        completeness=market.completeness,
    )


def recommend_market_price(
    *,
    current_price: Decimal,
    currency: str,
    market: RobustMarketStatistics,
    strategy: PricingStrategy = PricingStrategy.BALANCED,
    absolute_buffer: Decimal = ZERO,
    percentage_buffer: Decimal = Decimal("0.02"),
    approved_price_floor: Decimal | None = None,
    cost_of_goods: Decimal | None = None,
    fixed_cost_per_order: Decimal = ZERO,
    variable_rate: Decimal = ZERO,
    target_contribution_margin_rate: Decimal = ZERO,
    max_decrease_rate: Decimal = Decimal("0.15"),
    max_increase_rate: Decimal = Decimal("0.20"),
    deadband: Decimal = Decimal("0.04"),
    minimum_confidence: Decimal = Decimal("0.65"),
    price_tick: Decimal = ONE,
    custom_anchor: Decimal | None = None,
) -> HumanPriceRecommendation:
    if current_price <= ZERO or price_tick <= ZERO:
        raise ValueError("current_price and price_tick must be positive")
    if not currency.strip():
        raise ValueError("currency is required")
    for name, value in (
        ("absolute_buffer", absolute_buffer),
        ("percentage_buffer", percentage_buffer),
        ("max_decrease_rate", max_decrease_rate),
        ("max_increase_rate", max_increase_rate),
        ("deadband", deadband),
        ("minimum_confidence", minimum_confidence),
    ):
        if value < ZERO:
            raise ValueError(f"{name} cannot be negative")
    if minimum_confidence > ONE or deadband >= ONE:
        raise ValueError("confidence and deadband are outside valid range")

    confidence = recommendation_confidence(market)
    reasons = list(market.reason_codes)
    warnings: list[str] = []
    price_floor = approved_price_floor
    if price_floor is not None and price_floor <= ZERO:
        raise ValueError("approved_price_floor must be positive")
    if cost_of_goods is not None:
        calculated_floor = calculate_contribution_floor(
            cost_of_goods,
            fixed_cost_per_order=fixed_cost_per_order,
            variable_rate=variable_rate,
            target_contribution_margin_rate=target_contribution_margin_rate,
        )
        price_floor = max(price_floor or ZERO, calculated_floor)
    elif price_floor is None:
        warnings.append("MARGIN_SAFETY_UNKNOWN")

    evidence_sufficient = (
        market.effective_sample_size >= Decimal("2")
        and market.independent_seller_groups >= 2
        and confidence.value >= minimum_confidence
    )
    if not evidence_sufficient:
        if confidence.value < minimum_confidence:
            reasons.append("RECOMMENDATION_CONFIDENCE_BELOW_THRESHOLD")
        return HumanPriceRecommendation(
            contract_version=HITL_MARKET_CONTRACT_VERSION,
            recommendation_version=HITL_RECOMMENDATION_VERSION,
            action=RecommendationAction.INSUFFICIENT_EVIDENCE,
            strategy=strategy,
            current_price=current_price,
            currency=currency.strip().upper(),
            recommended_price=None,
            recommended_range_min=market.weighted_q20,
            recommended_range_max=market.weighted_q80,
            absolute_change=None,
            relative_change=None,
            market_anchor=None,
            price_floor=price_floor,
            confidence=confidence,
            market=market,
            reason_codes=tuple(dict.fromkeys(reasons)),
            warnings=tuple(warnings),
        )

    anchor_by_strategy = {
        PricingStrategy.AGGRESSIVE: market.weighted_q20,
        PricingStrategy.BALANCED: market.weighted_q35,
        PricingStrategy.MARGIN_FIRST: market.weighted_median,
        PricingStrategy.INVENTORY_CLEARANCE: market.weighted_q20,
        PricingStrategy.CUSTOM: custom_anchor,
    }
    anchor = anchor_by_strategy[strategy]
    if anchor is None:
        raise ValueError("selected pricing strategy has no market anchor")
    buffer = max(absolute_buffer, percentage_buffer * anchor)
    market_target = anchor - buffer
    raw_target = max(market_target, price_floor) if price_floor is not None else market_target
    limited = min(
        current_price * (ONE + max_increase_rate),
        max(current_price * (ONE - max_decrease_rate), raw_target),
    )
    rounded = (limited / price_tick).quantize(ZERO, rounding=ROUND_HALF_UP) * price_tick
    if price_floor is not None and rounded < price_floor:
        # The approved floor is a hard economic safety boundary.  It outranks
        # a rate-of-change guardrail; otherwise the system could literally
        # recommend a price it declares impermissible.  Publication is still
        # impossible without the separate human decision endpoint.
        rounded = (
            (price_floor / price_tick).quantize(ZERO, rounding=ROUND_CEILING)
            * price_tick
        )
        warnings.append("PRICE_FLOOR_OVERRIDES_CHANGE_GUARDRAIL")
        if current_price < price_floor:
            warnings.append("CURRENT_PRICE_BELOW_APPROVED_FLOOR")
    relative_change = ((rounded - current_price) / current_price).quantize(
        Decimal("0.0001")
    )
    if abs(relative_change) < deadband:
        action = RecommendationAction.HOLD
        rounded = current_price
        relative_change = ZERO
        reasons.append("PRICE_CHANGE_WITHIN_DEADBAND")
    elif relative_change > ZERO:
        action = RecommendationAction.CONSIDER_RAISE
        reasons.append("CURRENT_PRICE_BELOW_GUARDRAILED_MARKET_TARGET")
    else:
        action = RecommendationAction.CONSIDER_REDUCE
        reasons.append("CURRENT_PRICE_ABOVE_GUARDRAILED_MARKET_TARGET")
    change = rounded - current_price
    return HumanPriceRecommendation(
        contract_version=HITL_MARKET_CONTRACT_VERSION,
        recommendation_version=HITL_RECOMMENDATION_VERSION,
        action=action,
        strategy=strategy,
        current_price=current_price,
        currency=currency.strip().upper(),
        recommended_price=rounded,
        recommended_range_min=market.weighted_q20,
        recommended_range_max=market.weighted_q80,
        absolute_change=change,
        relative_change=relative_change,
        market_anchor=anchor,
        price_floor=price_floor,
        confidence=confidence,
        market=market,
        reason_codes=tuple(dict.fromkeys(reasons)),
        warnings=tuple(warnings),
    )


def internal_price_spread(prices: Iterable[Decimal]) -> Decimal | None:
    values = tuple(price for price in prices if price > ZERO)
    if not values:
        return None
    minimum = min(values)
    return ((max(values) - minimum) / minimum).quantize(Decimal("0.0001"))


def calculate_review_priority(
    *,
    current_price: Decimal,
    recommended_price: Decimal | None,
    expected_sales_volume: Decimal,
    model_uncertainty: Decimal,
    expected_information_gain: Decimal,
    product_importance: Decimal,
) -> Decimal:
    if min(
        current_price,
        expected_sales_volume,
        model_uncertainty,
        expected_information_gain,
        product_importance,
    ) < ZERO:
        raise ValueError("review priority inputs cannot be negative")
    if recommended_price is None:
        financial_impact = current_price * expected_sales_volume
    else:
        financial_impact = (
            abs(recommended_price - current_price) * expected_sales_volume
        )
    return (
        financial_impact
        * model_uncertainty
        * expected_information_gain
        * product_importance
    ).quantize(Decimal("0.0001"))


def _clamp(value: Decimal, minimum: Decimal = ZERO, maximum: Decimal = ONE) -> Decimal:
    return max(minimum, min(value, maximum))


__all__ = [
    "FeedbackReason",
    "HITL_MARKET_CONTRACT_VERSION",
    "HITL_RECOMMENDATION_VERSION",
    "HumanPriceRecommendation",
    "MarketOfferDecision",
    "NormalizedPriceUnit",
    "PriceUnitStatus",
    "PricingStrategy",
    "RecommendationAction",
    "RecommendationConfidence",
    "RecommendationDecision",
    "RobustMarketStatistics",
    "SELLER_RESOLUTION_VERSION",
    "SELLER_SIGNAL_WEIGHTS",
    "SOURCE_RELIABILITY_VERSION",
    "SOURCE_TIER_BETA_PRIORS",
    "SellerResolution",
    "SourceReliability",
    "WeightedMarketOffer",
    "build_robust_market_statistics",
    "calculate_contribution_floor",
    "calculate_review_priority",
    "freshness_decay",
    "internal_price_spread",
    "normalize_price_unit",
    "posterior_source_reliability",
    "recommend_market_price",
    "recommendation_confidence",
    "resolve_seller_relation",
    "weighted_quantile",
]
