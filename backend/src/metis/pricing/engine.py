"""Deterministic Metis KEMP-normalized pricing decision engine."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import math
from collections.abc import Iterable, Mapping

from .statistics import (
    clamp01,
    effective_sample_size,
    geometric_mean,
    iqr_fences,
    log_coverage,
    mad,
    median,
    percentile,
    robust_price_dispersion,
    round_down_to_tick,
    round_to_tick,
    round_up_to_tick,
    winsorize,
)
from .types import (
    CoefficientModel,
    CompetitorOffer,
    ConfidenceAggregation,
    ExcludedOffer,
    NormalizedOffer,
    PricingPolicy,
    PricingResult,
    PriorityScoreType,
    ProductPricingContext,
    ProductTier,
    RecommendationAction,
    RobustDispersionProfile,
    RobustScaleMethod,
    StockStatus,
    TierCoefficient,
)


ZERO = Decimal("0")
ONE = Decimal("1")


def recommend_price(
    context: ProductPricingContext,
    offers: Iterable[CompetitorOffer],
    coefficients: Mapping[tuple[str, ProductTier], TierCoefficient],
    *,
    policy: PricingPolicy | None = None,
) -> PricingResult:
    """Evaluate one SKU without HTTP, ORM, queue, or mutable global state."""
    policy = policy or PricingPolicy()
    collected_offers = tuple(offers)
    if context.current_price <= ZERO or not context.current_price.is_finite():
        return _empty_result(
            context,
            policy,
            RecommendationAction.MANUAL_REVIEW,
            "INVALID_CURRENT_PRICE",
            raw_competitor_count=len(collected_offers),
        )
    if context.currency.strip().upper() != policy.currency:
        return _empty_result(
            context,
            policy,
            RecommendationAction.MANUAL_REVIEW,
            "CONTEXT_CURRENCY_MISMATCH",
            raw_competitor_count=len(collected_offers),
        )

    eligible: list[NormalizedOffer] = []
    excluded: list[ExcludedOffer] = []
    for offer in collected_offers:
        rejection = _hard_rejection(context, offer, policy)
        if rejection:
            excluded.append(_excluded(offer, rejection, "eligibility"))
            continue

        if offer.is_kemp or offer.tier == ProductTier.KEMP:
            if offer.is_dumping:
                excluded.append(_excluded(offer, "KEMP_DUMPING", "eligibility"))
                continue
            eligible.append(_reference_offer(offer, ProductTier.KEMP, is_kemp=True))
            continue
        if offer.tier == ProductTier.BUDGET:
            eligible.append(_reference_offer(offer, ProductTier.BUDGET))
            continue

        coefficient = coefficients.get((context.category, offer.tier))
        if coefficient is None or not coefficient.validated:
            excluded.append(
                _excluded(offer, "UNVALIDATED_TIER_COEFFICIENT", "normalization")
            )
            continue
        if coefficient.multiplier <= ZERO or not coefficient.multiplier.is_finite():
            excluded.append(
                _excluded(offer, "INVALID_TIER_COEFFICIENT", "normalization")
            )
            continue
        if policy.exclude_lower_tier_coefficients and coefficient.multiplier < ONE:
            excluded.append(_excluded(offer, "LOWER_TIER_EXCLUDED", "normalization"))
            continue
        normalized_price = offer.price / coefficient.multiplier
        if normalized_price <= ZERO or not normalized_price.is_finite():
            excluded.append(
                _excluded(offer, "INVALID_NORMALIZED_PRICE", "normalization")
            )
            continue
        eligible.append(
            NormalizedOffer(
                observation_id=offer.observation_id,
                seller_id=offer.seller_id,
                seller_name=offer.seller_name,
                tier=offer.tier,
                raw_price=offer.price,
                normalized_price=normalized_price,
                multiplier=coefficient.multiplier,
                coefficient_confidence=coefficient.confidence,
                age_hours=offer.age_hours,
                match_confidence=offer.match_confidence,
                tier_confidence=offer.tier_confidence,
                source_confidence=offer.source_confidence,
                coefficient_model=coefficient.model,
                coefficient_version=(
                    coefficient.coefficient_version or coefficient.method_version
                ),
                coefficient_sample_size=coefficient.sample_size,
                coefficient_effective_sample_size=coefficient.effective_sample_size,
                coefficient_dataset_hash=coefficient.dataset_hash,
                source=offer.source,
                listing_url=offer.listing_url,
            )
        )

    eligible, inferred_dumping = _exclude_inferred_kemp_dumping(eligible, policy)
    excluded.extend(inferred_dumping)
    deduplicated, duplicates = _deduplicate_sellers(eligible)
    excluded.extend(duplicates)
    unique_count = len(deduplicated)
    if unique_count < 3:
        return _result_without_market_action(
            context,
            policy,
            evidence=deduplicated,
            excluded=excluded,
            action=RecommendationAction.INSUFFICIENT_DATA,
            reason="TOO_FEW_COMPETITORS",
            raw_competitor_count=len(collected_offers),
            unique_seller_count=unique_count,
        )

    selected_dispersion_method = (
        policy.dispersion_method or RobustScaleMethod.LEGACY_MAD
    )
    if unique_count > policy.robust_scale_max_cohort_size:
        return _result_without_market_action(
            context,
            policy,
            evidence=deduplicated,
            excluded=excluded,
            action=RecommendationAction.MANUAL_REVIEW,
            reason="ROBUST_SCALE_CAPACITY_EXCEEDED",
            raw_competitor_count=len(collected_offers),
            unique_seller_count=unique_count,
            dispersion_method=selected_dispersion_method,
        )

    pre_clean_profile = robust_price_dispersion(
        [offer.normalized_price for offer in deduplicated],
        selected_method=selected_dispersion_method,
        sample_stage="pre_clean",
        finite_sample_correction=policy.finite_sample_scale_correction,
        profile_version=policy.robust_dispersion_profile_version,
        correction_profile_version=(policy.robust_scale_correction_profile_version),
    )

    cleaned, outliers, outlier_method = _clean_outliers(deduplicated, policy)
    excluded.extend(outliers)
    if len(cleaned) < 3:
        return _result_without_market_action(
            context,
            policy,
            evidence=cleaned,
            excluded=excluded,
            action=RecommendationAction.INSUFFICIENT_DATA,
            reason="TOO_FEW_COMPETITORS_AFTER_CLEANING",
            raw_competitor_count=len(collected_offers),
            unique_seller_count=unique_count,
            outlier_method=outlier_method,
            outlier_count=len(outliers),
            dispersion_method=selected_dispersion_method,
            pre_clean_dispersion_profile=pre_clean_profile,
        )

    prices = [offer.normalized_price for offer in cleaned]
    post_clean_profile = robust_price_dispersion(
        prices,
        selected_method=selected_dispersion_method,
        sample_stage="post_clean",
        finite_sample_correction=policy.finite_sample_scale_correction,
        profile_version=policy.robust_dispersion_profile_version,
        correction_profile_version=(policy.robust_scale_correction_profile_version),
    )
    fair_price = post_clean_profile.center
    lower_bound = percentile(prices, Decimal("0.25"))
    upper_bound = percentile(prices, Decimal("0.75"))
    dispersion = post_clean_profile.robust_cv
    winsorized_prices = winsorize(
        [offer.normalized_price for offer in deduplicated],
        lower=policy.winsor_lower_quantile,
        upper=policy.winsor_upper_quantile,
    )
    winsorized_fair_price = median(winsorized_prices)
    sensitivity = (
        abs(fair_price - winsorized_fair_price) / fair_price
        if fair_price > ZERO
        else Decimal("Infinity")
    )
    factors, n_effective = _confidence_factors(cleaned, fair_price, dispersion, policy)
    confidence, weakest = _aggregate_confidence(factors, policy)
    confidence_grade = _confidence_grade(confidence, factors, policy)

    reasons: list[str] = []
    data_health_issues: list[str] = []
    if context.severe_data_health_issue:
        data_health_issues.append("SEVERE_DATA_HEALTH_ISSUE")
    if fair_price <= ZERO or not fair_price.is_finite():
        data_health_issues.append("INVALID_FAIR_PRICE")
    if sensitivity > policy.sensitivity_tolerance:
        reasons.append("ESTIMATOR_SENSITIVITY")
    robust_scale_gate_blocked = (
        selected_dispersion_method != RobustScaleMethod.LEGACY_MAD
        and post_clean_profile.partial_scale_degeneracy
    )
    if robust_scale_gate_blocked:
        reasons.append("ROBUST_SCALE_PARTIAL_DEGENERACY")
    if len(cleaned) < policy.min_competitors:
        reasons.append("TOO_FEW_COMPETITORS_FOR_ACTION")
    if n_effective < policy.min_effective_competitors:
        reasons.append("LOW_EFFECTIVE_SAMPLE_SIZE")
    failed_factors = [
        name for name, score in factors.items() if score < policy.floor_for(name)
    ]
    reasons.extend(_factor_reason(name) for name in failed_factors)
    if confidence < policy.confidence_min:
        reasons.append("LOW_CONFIDENCE")
    if data_health_issues:
        reasons.extend(data_health_issues)
        confidence = ZERO
        confidence_grade = "MANUAL"

    action_gates_pass = (
        not data_health_issues
        and len(cleaned) >= policy.min_competitors
        and n_effective >= policy.min_effective_competitors
        and confidence >= policy.confidence_min
        and not failed_factors
        and sensitivity <= policy.sensitivity_tolerance
        and not robust_scale_gate_blocked
    )
    common = {
        "context": context,
        "policy": policy,
        "fair_price": fair_price,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "confidence": confidence,
        "confidence_grade": confidence_grade,
        "weakest": weakest,
        "factors": factors,
        "n_effective": n_effective,
        "dispersion": dispersion,
        "evidence": cleaned,
        "excluded": excluded,
        "raw_competitor_count": len(collected_offers),
        "unique_seller_count": unique_count,
        "outlier_method": outlier_method,
        "outlier_count": len(outliers),
        "sensitivity": sensitivity,
        "winsorized_fair_price": winsorized_fair_price,
        "data_health_issues": tuple(data_health_issues),
        "dispersion_method": selected_dispersion_method,
        "pre_clean_dispersion_profile": pre_clean_profile,
        "dispersion_profile": post_clean_profile,
    }
    if unique_count < policy.manual_review_below or not action_gates_pass:
        reasons.append("MANUAL_REVIEW_REQUIRED")
        result = _priced_result(
            **common,
            action=RecommendationAction.MANUAL_REVIEW,
            recommended_price=None,
            reasons=reasons,
            action_gates_passed=False,
            cost_floor=None,
        )
        return _enforce_invariants(result, context)

    if context.stock_status in {StockStatus.STALE, StockStatus.DEAD_STOCK}:
        action, recommended, mode_reasons, cost_floor = _clearance_recommendation(
            context, prices, policy
        )
    else:
        action, recommended, mode_reasons = _raise_recommendation(
            context,
            fair_price,
            lower_bound,
            cleaned,
            policy,
        )
        cost_floor = None
        if context.stock_status == StockStatus.UNKNOWN:
            mode_reasons = mode_reasons + ("UNKNOWN_STOCK_STATUS",)
    reasons.extend(mode_reasons)
    result = _priced_result(
        **common,
        action=action,
        recommended_price=recommended,
        reasons=reasons,
        action_gates_passed=(
            action_gates_pass
            and action
            not in {
                RecommendationAction.MANUAL_REVIEW,
                RecommendationAction.INSUFFICIENT_DATA,
            }
        ),
        cost_floor=cost_floor,
    )
    return _enforce_invariants(result, context)


def _reference_offer(
    offer: CompetitorOffer, tier: ProductTier, *, is_kemp: bool = False
) -> NormalizedOffer:
    return NormalizedOffer(
        observation_id=offer.observation_id,
        seller_id=offer.seller_id,
        seller_name=offer.seller_name,
        tier=tier,
        raw_price=offer.price,
        normalized_price=offer.price,
        multiplier=ONE,
        coefficient_confidence=ONE,
        age_hours=offer.age_hours,
        match_confidence=offer.match_confidence,
        tier_confidence=offer.tier_confidence,
        source_confidence=offer.source_confidence,
        coefficient_model=CoefficientModel.SIMPLE_MEDIAN,
        coefficient_version="reference-tier-v1",
        is_direct_kemp=is_kemp,
        source=offer.source,
        listing_url=offer.listing_url,
    )


def _hard_rejection(
    context: ProductPricingContext, offer: CompetitorOffer, policy: PricingPolicy
) -> str | None:
    if offer.price <= ZERO or not offer.price.is_finite():
        return "NON_POSITIVE_PRICE"
    if (
        offer.currency.strip().upper() != context.currency.strip().upper()
        or offer.currency.strip().upper() != policy.currency
    ):
        return "CURRENCY_MISMATCH"
    if offer.is_available is not True:
        return "NOT_AVAILABLE"
    if offer.age_hours < ZERO or offer.age_hours > policy.max_age_hours:
        return "STALE_SOURCE"
    if offer.is_used or offer.tier == ProductTier.USED:
        return "USED_OR_REFURBISHED"
    if offer.is_owned:
        return "OWNED_SELLER"
    if offer.severe_conflict:
        return offer.conflict_reason or "COMMERCIAL_CONFLICT"
    if offer.match_confidence < policy.match_confidence_min:
        return "LOW_MATCH_CONFIDENCE"
    if offer.tier == ProductTier.UNKNOWN:
        return "UNKNOWN_TIER"
    if offer.tier_confidence < policy.tier_confidence_min:
        return "LOW_TIER_CONFIDENCE"
    if offer.source_confidence < policy.source_confidence_min:
        return "LOW_SOURCE_CONFIDENCE"
    return None


def _excluded(offer: CompetitorOffer, reason: str, stage: str) -> ExcludedOffer:
    return ExcludedOffer(
        observation_id=offer.observation_id,
        reason=reason,
        seller_id=offer.seller_id,
        raw_price=offer.price,
        tier=offer.tier,
        stage=stage,
    )


def _deduplicate_sellers(
    offers: Iterable[NormalizedOffer],
) -> tuple[list[NormalizedOffer], list[ExcludedOffer]]:
    representatives: dict[str, NormalizedOffer] = {}
    excluded: list[ExcludedOffer] = []
    for offer in sorted(offers, key=lambda item: item.observation_id):
        key = offer.seller_id.strip() or offer.seller_name.casefold().strip()
        current = representatives.get(key)
        candidate_key = (offer.normalized_price, offer.observation_id)
        current_key = (
            (current.normalized_price, current.observation_id)
            if current is not None
            else None
        )
        if current is None or candidate_key < current_key:
            if current is not None:
                excluded.append(
                    ExcludedOffer(
                        current.observation_id,
                        "SELLER_DUPLICATE",
                        current.seller_id,
                        current.raw_price,
                        current.tier,
                        "seller_deduplication",
                    )
                )
            representatives[key] = offer
        else:
            excluded.append(
                ExcludedOffer(
                    offer.observation_id,
                    "SELLER_DUPLICATE",
                    offer.seller_id,
                    offer.raw_price,
                    offer.tier,
                    "seller_deduplication",
                )
            )
    return sorted(
        representatives.values(),
        key=lambda item: (item.normalized_price, item.observation_id),
    ), excluded


def _exclude_inferred_kemp_dumping(
    offers: list[NormalizedOffer], policy: PricingPolicy
) -> tuple[list[NormalizedOffer], list[ExcludedOffer]]:
    """Infer dumping only from independent normalized market evidence.

    Explicit source classifications remain authoritative.  For otherwise valid
    direct KEMP offers, a price is called dumping only when at least three
    independent direct-KEMP sellers provide their own robust comparison cohort.
    Cross-tier prices and the customer's price never define this label.
    """
    benchmark_prices = [
        offer.normalized_price for offer in offers if offer.is_direct_kemp
    ]
    if len(benchmark_prices) < 3:
        return offers, []
    floor = median(benchmark_prices) * policy.kemp_dumping_ratio
    kept: list[NormalizedOffer] = []
    excluded: list[ExcludedOffer] = []
    for offer in offers:
        if offer.is_direct_kemp and offer.normalized_price < floor:
            excluded.append(
                ExcludedOffer(
                    observation_id=offer.observation_id,
                    reason="KEMP_DUMPING",
                    seller_id=offer.seller_id,
                    raw_price=offer.raw_price,
                    tier=offer.tier,
                    stage="kemp_guardrail",
                )
            )
        else:
            kept.append(offer)
    return kept, excluded


def _clean_outliers(
    offers: list[NormalizedOffer], policy: PricingPolicy
) -> tuple[list[NormalizedOffer], list[ExcludedOffer], str]:
    prices = [offer.normalized_price for offer in offers]
    center = median(prices)
    if len(offers) >= policy.iqr_min_competitors:
        method = "iqr"
        low, high = iqr_fences(prices)
        cleaned = [offer for offer in offers if low <= offer.normalized_price <= high]
    elif len(offers) >= policy.min_competitors:
        method = "mad"
        spread = mad(prices)
        if spread == ZERO:
            tolerance = max(
                policy.minimum_absolute_tolerance,
                center * policy.mad_zero_tolerance,
            )
            cleaned = [
                offer
                for offer in offers
                if abs(offer.normalized_price - center) <= tolerance
            ]
        else:
            cleaned = [
                offer
                for offer in offers
                if Decimal("0.6745") * abs(offer.normalized_price - center) / spread
                <= policy.mad_outlier_threshold
            ]
    else:
        method = "none"
        cleaned = list(offers)
    retained = {offer.observation_id for offer in cleaned}
    excluded = [
        ExcludedOffer(
            offer.observation_id,
            "ROBUST_OUTLIER",
            offer.seller_id,
            offer.raw_price,
            offer.tier,
            "robust_cleaning",
        )
        for offer in offers
        if offer.observation_id not in retained
    ]
    return cleaned, excluded, method


def _confidence_factors(
    offers: list[NormalizedOffer],
    fair_price: Decimal,
    dispersion: Decimal,
    policy: PricingPolicy,
) -> tuple[dict[str, Decimal], Decimal]:
    freshness = [
        Decimal(
            str(math.pow(2, -float(offer.age_hours / policy.freshness_half_life_hours)))
        )
        for offer in offers
    ]
    quality_weights = [
        offer.match_confidence
        * offer.tier_confidence
        * offer.coefficient_confidence
        * offer.source_confidence
        * fresh
        for offer, fresh in zip(offers, freshness, strict=True)
    ]
    n_effective = effective_sample_size(quality_weights)
    dispersion_score = (
        ZERO
        if fair_price <= ZERO or policy.max_dispersion <= ZERO
        else clamp01(ONE - dispersion / policy.max_dispersion)
    )
    factors = {
        "coverage": log_coverage(n_effective, policy.reference_competitors),
        "dispersion": dispersion_score,
        "freshness": percentile(freshness, Decimal("0.25")),
        "match": percentile(
            [offer.match_confidence for offer in offers], Decimal("0.25")
        ),
        "tier": percentile(
            [offer.tier_confidence * offer.coefficient_confidence for offer in offers],
            Decimal("0.25"),
        ),
        "source": percentile(
            [offer.source_confidence for offer in offers], Decimal("0.25")
        ),
    }
    return {name: clamp01(value) for name, value in factors.items()}, n_effective


def _aggregate_confidence(
    factors: Mapping[str, Decimal], policy: PricingPolicy
) -> tuple[Decimal, str | None]:
    if not factors:
        return ZERO, None
    weakest = min(factors, key=lambda name: (factors[name], name))
    if policy.confidence_aggregation == ConfidenceAggregation.MINIMUM:
        return factors[weakest], weakest
    return (
        geometric_mean(
            factors,
            weights=policy.confidence_weights,
            epsilon=policy.confidence_epsilon,
        ),
        weakest,
    )


def _confidence_grade(
    confidence: Decimal,
    factors: Mapping[str, Decimal],
    policy: PricingPolicy,
) -> str:
    if not factors or any(
        value < policy.floor_for(name) for name, value in factors.items()
    ):
        return "MANUAL"
    if confidence >= Decimal("0.80"):
        return "A"
    if confidence >= Decimal("0.65"):
        return "B"
    if confidence >= policy.confidence_min:
        return "C"
    return "MANUAL"


def _factor_reason(name: str) -> str:
    return {
        "coverage": "LOW_COVERAGE",
        "dispersion": "HIGH_DISPERSION",
        "freshness": "LOW_FRESHNESS",
        "match": "LOW_MATCH",
        "tier": "LOW_TIER",
        "source": "LOW_SOURCE",
    }.get(name, f"LOW_{name.upper()}")


def _raise_recommendation(
    context: ProductPricingContext,
    fair_price: Decimal,
    lower_bound: Decimal,
    cleaned_offers: list[NormalizedOffer],
    policy: PricingPolicy,
) -> tuple[RecommendationAction, Decimal | None, tuple[str, ...]]:
    threshold = context.current_price * (ONE + policy.min_raise_threshold)
    if fair_price <= threshold:
        return RecommendationAction.HOLD, None, ("MARKET_NOT_ABOVE_RAISE_THRESHOLD",)
    targets = [
        fair_price * policy.safety_discount,
        context.current_price * (ONE + policy.max_raise_step),
    ]
    if policy.lower_market_support_enabled:
        targets.append(lower_bound)
    direct_kemp_prices = [
        offer.normalized_price for offer in cleaned_offers if offer.is_direct_kemp
    ]
    if direct_kemp_prices:
        targets.append(
            percentile(direct_kemp_prices, policy.direct_kemp_ceiling_quantile)
        )
    recommended = round_down_to_tick(min(targets), policy.price_tick)
    if recommended < context.current_price * (ONE + policy.min_action_change):
        return RecommendationAction.HOLD, None, ("CONSERVATIVE_TARGET_NOT_ACTIONABLE",)
    return RecommendationAction.RAISE, recommended, ("MARKET_SUPPORTS_RAISE",)


def _clearance_recommendation(
    context: ProductPricingContext,
    prices: list[Decimal],
    policy: PricingPolicy,
) -> tuple[RecommendationAction, Decimal | None, tuple[str, ...], Decimal | None]:
    if context.allow_below_cost and context.stock_status != StockStatus.DEAD_STOCK:
        return (
            RecommendationAction.MANUAL_REVIEW,
            None,
            ("BELOW_COST_ONLY_FOR_DEAD_STOCK",),
            None,
        )
    lower_market = percentile(prices, policy.lower_market_quantile)
    base_beta = (
        policy.dead_stock_markdown_beta
        if context.stock_status == StockStatus.DEAD_STOCK
        else policy.stale_markdown_beta
    )
    beta = clamp01(max(base_beta, context.liquidity_target))
    target = (ONE - beta) * context.current_price + beta * min(
        context.current_price, lower_market
    )
    if context.allow_below_cost:
        missing_authorization = not all(
            (
                context.below_cost_floor is not None,
                context.below_cost_authorization_id,
                context.below_cost_authorized_by,
                context.below_cost_authorized_at,
                context.below_cost_reason,
                context.below_cost_warning_confirmed,
            )
        )
        if missing_authorization:
            return (
                RecommendationAction.MANUAL_REVIEW,
                None,
                ("MISSING_BELOW_COST_AUTHORIZATION",),
                context.below_cost_floor,
            )
        floor = context.below_cost_floor
    else:
        if context.cost is None:
            return RecommendationAction.MANUAL_REVIEW, None, ("MISSING_COST",), None
        floor = context.cost * (ONE + policy.minimum_margin)
    if floor is None or floor < ZERO:
        return RecommendationAction.MANUAL_REVIEW, None, ("INVALID_PRICE_FLOOR",), floor

    rounded_floor = round_up_to_tick(floor, policy.price_tick)
    rounded_target = round_to_tick(target, policy.price_tick)
    recommended = min(context.current_price, max(rounded_floor, rounded_target))
    if recommended > context.current_price * (ONE - policy.min_action_change):
        return (
            RecommendationAction.HOLD,
            None,
            ("CLEARANCE_TARGET_NOT_ACTIONABLE",),
            floor,
        )
    reasons = ["CLEARANCE_MARKDOWN"]
    if (
        context.allow_below_cost
        and context.cost is not None
        and recommended < context.cost
    ):
        reasons.append("EXPLICIT_BELOW_COST_OVERRIDE")
    return RecommendationAction.LOWER, recommended, tuple(reasons), floor


def _priorities(
    context: ProductPricingContext,
    action: RecommendationAction,
    current_price: Decimal,
    recommended_price: Decimal | None,
    confidence: Decimal,
    policy: PricingPolicy,
) -> tuple[
    Decimal,
    PriorityScoreType,
    Decimal,
    Decimal | None,
    dict[str, str],
]:
    urgency = max(ZERO, context.urgency)
    manual_priority = max(ZERO, context.manual_priority)
    inputs: dict[str, str] = {}

    if action == RecommendationAction.RAISE and recommended_price is not None:
        uplift = max(ZERO, recommended_price - current_price)
        monthly_units, source = _monthly_units(context, policy)
        if monthly_units is not None:
            score = uplift * monthly_units * confidence * urgency * manual_priority
            inputs.update(
                {
                    "uplift": str(uplift),
                    "monthly_units": str(monthly_units),
                    "monthly_units_source": source,
                    "unit": "UAH_PER_MONTH_CONFIDENCE_ADJUSTED",
                }
            )
            return (
                score,
                PriorityScoreType.GROSS_UPLIFT_OPPORTUNITY,
                ZERO,
                _cost_basis_inventory_value(context),
                inputs,
            )
        relative_gap = uplift / current_price if current_price > ZERO else ZERO
        if context.stock_qty is not None and context.stock_qty > ZERO:
            stock_exposure = context.stock_qty * _age_weight(
                context.stock_age_days, policy
            )
            inputs.update(
                {
                    "relative_gap": str(relative_gap),
                    "stock_exposure": str(stock_exposure),
                    "unit": "STOCK_EXPOSURE_PROXY",
                }
            )
            return (
                relative_gap * confidence * manual_priority * stock_exposure,
                PriorityScoreType.RETAIL_EXPOSURE_PROXY,
                ZERO,
                _cost_basis_inventory_value(context),
                inputs,
            )
        inputs.update(
            {
                "relative_gap": str(relative_gap),
                "unit": "DIMENSIONLESS_GAP_CONFIDENCE_PROXY",
            }
        )
        return (
            relative_gap * confidence * manual_priority,
            PriorityScoreType.GAP_CONFIDENCE_PROXY,
            ZERO,
            _cost_basis_inventory_value(context),
            inputs,
        )

    if context.stock_status in {StockStatus.STALE, StockStatus.DEAD_STOCK}:
        quantity = context.stock_qty or ZERO
        inventory_value = current_price * quantity
        age_weight = _age_weight(context.stock_age_days, policy)
        deadstock_factor = (
            policy.deadstock_factor
            if context.stock_status == StockStatus.DEAD_STOCK
            else ONE
        )
        capital_lock = inventory_value * age_weight
        review_priority = (
            capital_lock * (ONE - confidence) * deadstock_factor * manual_priority
        )
        score = capital_lock * confidence * deadstock_factor * manual_priority
        inputs.update(
            {
                "inventory_value": str(inventory_value),
                "age_weight": str(age_weight),
                "capital_lock": str(capital_lock),
                "unit": "UAH_LOCKED_INVENTORY_CONFIDENCE_ADJUSTED",
            }
        )
        return (
            score,
            PriorityScoreType.CLEARANCE_PRIORITY,
            review_priority,
            _cost_basis_inventory_value(context),
            inputs,
        )

    return (
        ZERO,
        PriorityScoreType.NONE,
        ZERO,
        _cost_basis_inventory_value(context),
        inputs,
    )


def _monthly_units(
    context: ProductPricingContext, policy: PricingPolicy
) -> tuple[Decimal | None, str]:
    candidates = (
        (context.units_sold_30d, ONE, "units_sold_30d"),
        (context.units_sold_60d, Decimal("2"), "units_sold_60d"),
        (context.units_sold_90d, Decimal("3"), "units_sold_90d"),
        (context.expected_units_sold, ONE, "expected_units_sold"),
    )
    for value, divisor, source in candidates:
        if value is not None and value >= ZERO:
            return value / divisor, source
    if (
        context.historical_monthly_units is not None
        and context.historical_monthly_units >= ZERO
        and context.days_since_last_sale is not None
        and context.days_since_last_sale >= ZERO
    ):
        recency = Decimal(
            str(
                math.pow(
                    2,
                    -float(
                        context.days_since_last_sale
                        / policy.sales_recency_half_life_days
                    ),
                )
            )
        )
        return context.historical_monthly_units * recency, "historical_recency"
    if (
        context.views_30d is not None
        and context.views_30d >= ZERO
        and context.conversion_rate_proxy is not None
        and ZERO <= context.conversion_rate_proxy <= ONE
    ):
        return context.views_30d * context.conversion_rate_proxy, "views_conversion"
    return None, "unavailable"


def _age_weight(age_days: Decimal | None, policy: PricingPolicy) -> Decimal:
    if age_days is None or age_days <= ZERO:
        return policy.age_weight_min
    return min(
        policy.age_weight_max,
        max(policy.age_weight_min, age_days / policy.age_reference_days),
    )


def _cost_basis_inventory_value(context: ProductPricingContext) -> Decimal | None:
    if context.cost is None or context.stock_qty is None:
        return None
    return context.cost * context.stock_qty


def _priced_result(
    *,
    context: ProductPricingContext,
    policy: PricingPolicy,
    action: RecommendationAction,
    recommended_price: Decimal | None,
    fair_price: Decimal,
    lower_bound: Decimal,
    upper_bound: Decimal,
    confidence: Decimal,
    confidence_grade: str,
    weakest: str | None,
    factors: Mapping[str, Decimal],
    n_effective: Decimal,
    dispersion: Decimal,
    evidence: list[NormalizedOffer],
    excluded: list[ExcludedOffer],
    reasons: list[str],
    raw_competitor_count: int,
    unique_seller_count: int,
    outlier_method: str,
    outlier_count: int,
    sensitivity: Decimal,
    winsorized_fair_price: Decimal,
    action_gates_passed: bool,
    cost_floor: Decimal | None,
    data_health_issues: tuple[str, ...],
    dispersion_method: RobustScaleMethod,
    pre_clean_dispersion_profile: RobustDispersionProfile,
    dispersion_profile: RobustDispersionProfile,
) -> PricingResult:
    priority, score_type, review_priority, cost_basis, priority_inputs = _priorities(
        context,
        action,
        context.current_price,
        recommended_price,
        confidence,
        policy,
    )
    return PricingResult(
        sku=context.sku,
        action=action,
        current_price=context.current_price,
        fair_price=fair_price,
        recommended_price=recommended_price,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        confidence=clamp01(confidence),
        confidence_grade=confidence_grade,
        weakest_factor=weakest,
        factor_scores=dict(factors),
        competitor_count=len(evidence),
        effective_competitor_count=n_effective,
        dispersion=dispersion,
        priority_score=priority,
        priority_score_type=score_type,
        review_priority=review_priority,
        reasons=tuple(dict.fromkeys(reasons)),
        evidence=tuple(evidence),
        excluded=tuple(excluded),
        policy_version=policy.version,
        raw_competitor_count=raw_competitor_count,
        unique_seller_count=unique_seller_count,
        clean_competitor_count=len(evidence),
        outlier_method=outlier_method,
        outlier_count=outlier_count,
        sensitivity=sensitivity,
        winsorized_fair_price=winsorized_fair_price,
        action_gates_passed=action_gates_passed,
        cost_floor=cost_floor,
        cost_basis_inventory_value=cost_basis,
        priority_inputs=priority_inputs,
        data_health_issues=data_health_issues,
        dispersion_method=dispersion_method,
        pre_clean_dispersion_profile=pre_clean_dispersion_profile,
        dispersion_profile=dispersion_profile,
        robust_dispersion_profile_version=policy.robust_dispersion_profile_version,
        robust_scale_correction_profile_version=(
            policy.robust_scale_correction_profile_version
        ),
        finite_sample_scale_correction=policy.finite_sample_scale_correction,
    )


def _result_without_market_action(
    context: ProductPricingContext,
    policy: PricingPolicy,
    evidence: list[NormalizedOffer],
    excluded: list[ExcludedOffer],
    action: RecommendationAction,
    reason: str,
    *,
    raw_competitor_count: int,
    unique_seller_count: int,
    outlier_method: str = "none",
    outlier_count: int = 0,
    dispersion_method: RobustScaleMethod | None = None,
    pre_clean_dispersion_profile: RobustDispersionProfile | None = None,
    dispersion_profile: RobustDispersionProfile | None = None,
) -> PricingResult:
    priority, score_type, review_priority, cost_basis, priority_inputs = _priorities(
        context, action, context.current_price, None, ZERO, policy
    )
    result = PricingResult(
        sku=context.sku,
        action=action,
        current_price=context.current_price,
        fair_price=None,
        recommended_price=None,
        lower_bound=None,
        upper_bound=None,
        confidence=ZERO,
        confidence_grade="MANUAL",
        weakest_factor=None,
        factor_scores={},
        competitor_count=len(evidence),
        effective_competitor_count=ZERO,
        dispersion=None,
        priority_score=priority,
        priority_score_type=score_type,
        review_priority=review_priority,
        reasons=(reason,),
        evidence=tuple(evidence),
        excluded=tuple(excluded),
        policy_version=policy.version,
        raw_competitor_count=raw_competitor_count,
        unique_seller_count=unique_seller_count,
        clean_competitor_count=len(evidence),
        outlier_method=outlier_method,
        outlier_count=outlier_count,
        action_gates_passed=False,
        cost_basis_inventory_value=cost_basis,
        priority_inputs=priority_inputs,
        dispersion_method=(
            dispersion_method
            or policy.dispersion_method
            or RobustScaleMethod.LEGACY_MAD
        ),
        pre_clean_dispersion_profile=pre_clean_dispersion_profile,
        dispersion_profile=dispersion_profile,
        robust_dispersion_profile_version=policy.robust_dispersion_profile_version,
        robust_scale_correction_profile_version=(
            policy.robust_scale_correction_profile_version
        ),
        finite_sample_scale_correction=policy.finite_sample_scale_correction,
    )
    return _enforce_invariants(result, context)


def _empty_result(
    context: ProductPricingContext,
    policy: PricingPolicy,
    action: RecommendationAction,
    reason: str,
    *,
    raw_competitor_count: int,
) -> PricingResult:
    return _result_without_market_action(
        context,
        policy,
        [],
        [],
        action,
        reason,
        raw_competitor_count=raw_competitor_count,
        unique_seller_count=0,
    )


def _enforce_invariants(
    result: PricingResult, context: ProductPricingContext
) -> PricingResult:
    issues: list[str] = []
    if result.fair_price is not None and result.fair_price <= ZERO:
        issues.append("INVARIANT_FAIR_PRICE_NON_POSITIVE")
    if result.confidence < ZERO or result.confidence > ONE:
        issues.append("INVARIANT_CONFIDENCE_OUT_OF_RANGE")
    if result.effective_competitor_count < ZERO:
        issues.append("INVARIANT_EFFECTIVE_SAMPLE_NEGATIVE")
    if result.recommended_price is not None and result.recommended_price <= ZERO:
        issues.append("INVARIANT_RECOMMENDED_PRICE_NON_POSITIVE")
    if result.action == RecommendationAction.RAISE and (
        result.recommended_price is None
        or result.recommended_price <= result.current_price
    ):
        issues.append("INVARIANT_RAISE_NOT_ABOVE_CURRENT")
    if result.action == RecommendationAction.LOWER and (
        result.recommended_price is None
        or result.recommended_price >= result.current_price
    ):
        issues.append("INVARIANT_LOWER_NOT_BELOW_CURRENT")
    if (
        context.stock_status == StockStatus.FRESH
        and result.action == RecommendationAction.LOWER
    ):
        issues.append("INVARIANT_FRESH_LOWER")
    if (
        result.action in {RecommendationAction.RAISE, RecommendationAction.LOWER}
        and not result.action_gates_passed
    ):
        issues.append("INVARIANT_ACTION_WITHOUT_GATES")
    if (
        result.recommended_price is not None
        and context.cost is not None
        and result.recommended_price < context.cost
    ):
        if not (
            context.stock_status == StockStatus.DEAD_STOCK
            and context.allow_below_cost
            and context.below_cost_authorization_id
            and context.below_cost_authorized_by
            and context.below_cost_authorized_at
            and context.below_cost_reason
            and context.below_cost_warning_confirmed
            and context.below_cost_floor is not None
            and result.recommended_price >= context.below_cost_floor
        ):
            issues.append("INVARIANT_UNAUTHORIZED_BELOW_COST")
    evidence_ids = [offer.observation_id for offer in result.evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        issues.append("INVARIANT_DUPLICATE_EVIDENCE")
    if not issues:
        return result
    return replace(
        result,
        action=RecommendationAction.MANUAL_REVIEW,
        recommended_price=None,
        confidence=ZERO,
        confidence_grade="MANUAL",
        action_gates_passed=False,
        reasons=tuple(
            dict.fromkeys(
                result.reasons
                + ("SEVERE_DATA_HEALTH_ISSUE", "MANUAL_REVIEW_REQUIRED")
                + tuple(issues)
            )
        ),
        data_health_issues=tuple(
            dict.fromkeys(result.data_health_issues + tuple(issues))
        ),
    )


__all__ = ["recommend_price"]
