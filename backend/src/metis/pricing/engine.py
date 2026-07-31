"""Deterministic Metis KEMP-normalized pricing decision engine."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from collections.abc import Iterable, Mapping

from .comparability import (
    COMPARABILITY_POLICY_HASH,
    COMPARABILITY_POLICY_ID,
    ComparabilityDecision,
    evaluate_comparison_evidence,
)
from .raise_policy import (
    RaiseOutcome,
    RaiseStrategy,
    decide_raise,
    default_raise_policy,
)
from .numeric import decimal_exp, decimal_ln, decimal_pow
from .statistics import (
    clamp01,
    effective_sample_size,
    geometric_mean,
    iqr_fences,
    log_price_cluster_diagnostic,
    log_coverage,
    mad,
    median,
    percentile,
    robust_price_dispersion,
    round_to_tick,
    winsorize,
)
from .types import (
    CoefficientModel,
    CohortRole,
    ClusterDiagnostic,
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
    HardGateResult,
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
    legacy_replay: bool = False,
) -> PricingResult:
    """Evaluate one SKU without HTTP, ORM, queue, or mutable global state.

    ``legacy_replay`` exists only so an already persisted pre-comparability trace
    can be verified without granting that legacy input new automatic authority.
    """
    policy = policy or PricingPolicy()
    collected_offers = tuple(offers)
    candidate = _recommend_price_core(
        context,
        collected_offers,
        coefficients,
        policy=policy,
        legacy_replay=legacy_replay,
    )
    if (
        policy.version != "pricing-v3.1-heterogeneity-gated"
        or not policy.robust_non_relaxation_enabled
        or legacy_replay
    ):
        return candidate

    baseline_policy = replace(
        policy,
        version=policy.robust_baseline_policy_version,
        dispersion_method=RobustScaleMethod.LEGACY_MAD,
        robust_non_relaxation_enabled=False,
    )
    baseline = _recommend_price_core(
        context,
        collected_offers,
        coefficients,
        policy=baseline_policy,
        legacy_replay=False,
    )
    automatic = {
        RecommendationAction.RAISE,
        RecommendationAction.HOLD,
        RecommendationAction.LOWER,
    }
    abstentions = {
        RecommendationAction.MANUAL_REVIEW,
        RecommendationAction.INSUFFICIENT_DATA,
    }
    if baseline.action in abstentions and candidate.action in automatic:
        return replace(
            candidate,
            action=RecommendationAction.MANUAL_REVIEW,
            recommended_price=None,
            confidence_grade="MANUAL",
            action_gates_passed=False,
            automatic_eligible=False,
            reasons=tuple(
                dict.fromkeys(
                    candidate.reasons
                    + (
                        "ROBUST_BASELINE_ABSTENTION_NOT_RELAXABLE",
                        "MANUAL_REVIEW_REQUIRED",
                    )
                )
            ),
        )
    return candidate


def _recommend_price_core(
    context: ProductPricingContext,
    collected_offers: tuple[CompetitorOffer, ...],
    coefficients: Mapping[tuple[str, ProductTier], TierCoefficient],
    *,
    policy: PricingPolicy,
    legacy_replay: bool,
) -> PricingResult:
    """Core implementation shared by the candidate and baseline policies."""
    raise_policy = policy.raise_policy or default_raise_policy()
    budget_floor_mode = raise_policy.strategy is RaiseStrategy.BUDGET_FLOOR
    if not context.current_price.is_finite() or context.current_price <= ZERO:
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
    kemp_reference: list[NormalizedOffer] = []
    excluded: list[ExcludedOffer] = []
    comparability_decisions: list[ComparabilityDecision] = []
    semantic_required_count = 0
    semantic_positive_count = 0
    semantic_negative_count = 0
    semantic_insufficient_count = 0
    owned_store_count = 0
    for offer in collected_offers:
        if offer.is_owned or offer.cohort_role == CohortRole.OWNED_STORE:
            owned_store_count += 1
            excluded.append(
                _excluded(
                    offer,
                    "OWNED_SELLER",
                    "cohort_partition",
                    CohortRole.OWNED_STORE,
                )
            )
            continue
        if offer.cohort_role == CohortRole.USED_REJECTED:
            excluded.append(
                _excluded(
                    offer,
                    "USED_OR_REFURBISHED",
                    "cohort_partition",
                    CohortRole.USED_REJECTED,
                )
            )
            continue
        if offer.cohort_role == CohortRole.DUMPING_DIAGNOSTIC:
            excluded.append(
                _excluded(
                    offer,
                    "KEMP_DUMPING",
                    "cohort_partition",
                    CohortRole.DUMPING_DIAGNOSTIC,
                )
            )
            continue
        if offer.cohort_role in {
            CohortRole.MANUAL_REVIEW,
            CohortRole.HARD_REJECTED,
        }:
            excluded.append(
                _excluded(
                    offer,
                    "PERSISTED_COHORT_NOT_TARGET_ELIGIBLE",
                    "cohort_partition",
                    offer.cohort_role,
                )
            )
            continue
        if (
            offer.is_kemp
            or offer.tier == ProductTier.KEMP
            or offer.cohort_role == CohortRole.KEMP_REFERENCE
        ):
            diagnostic_rejection = _kemp_reference_rejection(context, offer, policy)
            if diagnostic_rejection is not None:
                role = (
                    CohortRole.USED_REJECTED
                    if diagnostic_rejection == "USED_OR_REFURBISHED"
                    else CohortRole.DUMPING_DIAGNOSTIC
                    if diagnostic_rejection == "KEMP_DUMPING"
                    else CohortRole.HARD_REJECTED
                )
                excluded.append(
                    _excluded(offer, diagnostic_rejection, "kemp_reference", role)
                )
            else:
                kemp_reference.append(
                    _reference_offer(
                        offer,
                        ProductTier.KEMP,
                        cohort_role=CohortRole.KEMP_REFERENCE,
                    )
                )
            continue
        if offer.semantic_review_required:
            semantic_required_count += 1
            if offer.semantic_review_verdict == "COMPARABLE":
                semantic_positive_count += 1
            elif offer.semantic_review_verdict == "NOT_COMPARABLE":
                semantic_negative_count += 1
            else:
                semantic_insufficient_count += 1
        rejection, comparability = _hard_rejection(
            context,
            offer,
            policy,
            legacy_replay=legacy_replay,
            ignore_tier=budget_floor_mode and raise_policy.tier_agnostic,
        )
        if comparability is not None:
            comparability_decisions.append(comparability)
        if rejection:
            semantic_rejection = rejection in {
                "REJECTED_LLM_NOT_COMPARABLE",
                "MANUAL_LLM_COMPARABILITY_INSUFFICIENT",
                "MANUAL_LLM_COMPARABILITY_MISSING",
            }
            stage = (
                "comparability"
                if semantic_rejection
                or (comparability is not None and not comparability.automatic_eligible)
                else "eligibility"
            )
            role = (
                CohortRole.USED_REJECTED
                if rejection == "USED_OR_REFURBISHED"
                else CohortRole.MANUAL_REVIEW
                if rejection
                in {
                    "MANUAL_LLM_COMPARABILITY_INSUFFICIENT",
                    "MANUAL_LLM_COMPARABILITY_MISSING",
                }
                or (comparability is not None and not comparability.automatic_eligible)
                else CohortRole.HARD_REJECTED
            )
            excluded.append(_excluded(offer, rejection, stage, role))
            continue

        if budget_floor_mode and raise_policy.tier_agnostic:
            eligible.append(
                NormalizedOffer(
                    observation_id=offer.observation_id,
                    seller_id=offer.seller_id,
                    seller_name=offer.seller_name,
                    tier=offer.tier,
                    raw_price=offer.price,
                    normalized_price=offer.price,
                    multiplier=ONE,
                    coefficient_confidence=ONE,
                    age_hours=offer.age_hours,
                    match_confidence=offer.match_confidence,
                    tier_confidence=ONE,
                    source_confidence=offer.source_confidence,
                    coefficient_model=CoefficientModel.SIMPLE_MEDIAN,
                    coefficient_version="owner-tier-agnostic-v1",
                    coefficient_sample_size=0,
                    coefficient_effective_sample_size=ZERO,
                    coefficient_dataset_hash="",
                    source=offer.source,
                    listing_url=offer.listing_url,
                    comparison_evidence=offer.comparison_evidence,
                    cohort_role=CohortRole.TARGET_MARKET,
                )
            )
            continue

        coefficient = coefficients.get((context.category, offer.tier))
        if coefficient is None or not coefficient.validated:
            excluded.append(
                _excluded(
                    offer,
                    "UNVALIDATED_TIER_COEFFICIENT",
                    "normalization",
                    CohortRole.MANUAL_REVIEW,
                )
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
                comparison_evidence=offer.comparison_evidence,
                cohort_role=CohortRole.TARGET_MARKET,
            )
        )

    deduplicated, duplicates = _deduplicate_sellers(
        eligible, legacy_name_fallback=legacy_replay
    )
    excluded.extend(duplicates)
    unique_count = len(deduplicated)
    hard_gate_results, failed_hard_gates, unknown_hard_fields = (
        _summarize_comparability(comparability_decisions, legacy_replay=legacy_replay)
    )
    if semantic_required_count:
        hard_gate_results = {
            **hard_gate_results,
            "llm_comparability": int(
                semantic_positive_count == semantic_required_count
            ),
        }
        if semantic_negative_count:
            failed_hard_gates = tuple(
                dict.fromkeys((*failed_hard_gates, "llm_comparability"))
            )
        if semantic_insufficient_count:
            unknown_hard_fields = tuple(
                dict.fromkeys((*unknown_hard_fields, "llm_comparability"))
            )
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
            hard_gate_results=hard_gate_results,
            failed_hard_gates=failed_hard_gates,
            unknown_hard_fields=unknown_hard_fields,
            kemp_reference=kemp_reference,
            owned_store_count=owned_store_count,
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
            hard_gate_results=hard_gate_results,
            failed_hard_gates=failed_hard_gates,
            unknown_hard_fields=unknown_hard_fields,
            kemp_reference=kemp_reference,
            owned_store_count=owned_store_count,
        )

    pre_clean_profile = robust_price_dispersion(
        [offer.normalized_price for offer in deduplicated],
        selected_method=selected_dispersion_method,
        sample_stage="pre_clean",
        finite_sample_correction=policy.finite_sample_scale_correction,
        profile_version=policy.robust_dispersion_profile_version,
        correction_profile_version=(policy.robust_scale_correction_profile_version),
    )
    cluster_diagnostic: ClusterDiagnostic | None = None
    if policy.version == "pricing-v3.1-heterogeneity-gated":
        cluster_diagnostic = log_price_cluster_diagnostic(
            [offer.normalized_price for offer in deduplicated],
            min_cluster_size=policy.robust_cluster_min_size,
            improvement_threshold=policy.robust_cluster_improvement_threshold,
            balance_threshold=policy.robust_cluster_balance_threshold,
            separation_threshold=policy.robust_cluster_separation_threshold,
            gap_threshold=policy.robust_cluster_gap_threshold,
            sigma_floor=policy.robust_cluster_sigma_floor,
            version=policy.robust_cluster_diagnostic_version,
        )

    if budget_floor_mode:
        # The owner's target is explicitly the minimum. A statistically unusual
        # price may still be the valid market floor; hard product-comparability,
        # seller, condition and source gates above remain mandatory.
        cleaned = list(deduplicated)
        outliers: list[ExcludedOffer] = []
        # Persisted as VARCHAR(24); keep this stable identifier compact while the
        # calculation trace carries the full owner-policy explanation.
        outlier_method = "owner_minimum_raw"
    else:
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
            cluster_diagnostic=cluster_diagnostic,
            hard_gate_results=hard_gate_results,
            failed_hard_gates=failed_hard_gates,
            unknown_hard_fields=unknown_hard_fields,
            kemp_reference=kemp_reference,
            owned_store_count=owned_store_count,
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
    budget_floor_decision = (
        decide_raise(
            current_price=context.current_price,
            prices=prices,
            stock_status=context.stock_status,
            policy=raise_policy,
            # Positional against ``prices``: the floor may not rest on one shop.
            sellers=[offer.seller_id for offer in cleaned],
        )
        if budget_floor_mode
        else None
    )
    if budget_floor_decision is not None:
        # Keep every verified comparable offer in evidence, but use the same
        # plausibility-filtered minimum for the result, advisory and action.
        # A diagnostic fallback is needed only for confidence math when every
        # observed price is below the floor; the persisted fair price remains
        # null in that case.
        fair_price = budget_floor_decision.fair_price or min(prices)
        lower_bound = budget_floor_decision.target_band_low
        upper_bound = budget_floor_decision.target_band_high
    else:
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
    if budget_floor_mode:
        factors["tier"] = ONE
        factors["dispersion"] = ONE
    confidence, weakest = _aggregate_confidence(factors, policy)
    confidence_grade = _confidence_grade(confidence, factors, policy)

    reasons: list[str] = (
        list(budget_floor_decision.reasons + budget_floor_decision.flags)
        if budget_floor_decision is not None
        else []
    )
    data_health_issues: list[str] = []
    if context.severe_data_health_issue:
        data_health_issues.append("SEVERE_DATA_HEALTH_ISSUE")
    if fair_price <= ZERO or not fair_price.is_finite():
        data_health_issues.append("INVALID_FAIR_PRICE")
    if not budget_floor_mode and sensitivity > policy.sensitivity_tolerance:
        reasons.append("ESTIMATOR_SENSITIVITY")
    robust_scale_gate_blocked = (
        selected_dispersion_method != RobustScaleMethod.LEGACY_MAD
        and post_clean_profile.partial_scale_degeneracy
    )
    if robust_scale_gate_blocked and not budget_floor_mode:
        reasons.append("ROBUST_SCALE_PARTIAL_DEGENERACY")
    robust_zero_scale_with_variation = bool(
        pre_clean_profile.all_zero_with_variation
        or post_clean_profile.all_zero_with_variation
    )
    if robust_zero_scale_with_variation and not budget_floor_mode:
        reasons.append("ROBUST_SCALE_ALL_ZERO_WITH_VARIATION")
    robust_estimator_disagreement = bool(
        policy.version == "pricing-v3.1-heterogeneity-gated"
        and post_clean_profile.cv_relative_span is not None
        and post_clean_profile.cv_relative_span > policy.robust_disagreement_threshold
    )
    if robust_estimator_disagreement and not budget_floor_mode:
        reasons.append("ROBUST_ESTIMATOR_DISAGREEMENT")
    robust_cluster_blocked = bool(
        cluster_diagnostic is not None and cluster_diagnostic.flagged
    )
    if robust_cluster_blocked and not budget_floor_mode:
        reasons.append("ROBUST_MULTIMODAL_COHORT")
    robust_diagnostic_unavailable = bool(
        policy.version == "pricing-v3.1-heterogeneity-gated"
        and cluster_diagnostic is not None
        and not cluster_diagnostic.available
    )
    if robust_diagnostic_unavailable and not budget_floor_mode:
        reasons.append("ROBUST_DIAGNOSTIC_UNAVAILABLE")
    action_min_competitors = (
        raise_policy.min_evidence if budget_floor_mode else policy.min_competitors
    )
    manual_review_below = (
        raise_policy.min_evidence if budget_floor_mode else policy.manual_review_below
    )
    if len(cleaned) < action_min_competitors:
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
        and len(cleaned) >= action_min_competitors
        and n_effective >= policy.min_effective_competitors
        and confidence >= policy.confidence_min
        and not failed_factors
        and (budget_floor_mode or sensitivity <= policy.sensitivity_tolerance)
        and (budget_floor_mode or not robust_scale_gate_blocked)
        and (budget_floor_mode or not robust_zero_scale_with_variation)
        and (budget_floor_mode or not robust_estimator_disagreement)
        and (budget_floor_mode or not robust_cluster_blocked)
        and (budget_floor_mode or not robust_diagnostic_unavailable)
    )
    common = {
        "context": context,
        "policy": policy,
        "fair_price": (
            budget_floor_decision.fair_price
            if budget_floor_decision is not None
            else fair_price
        ),
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
        "cluster_diagnostic": cluster_diagnostic,
        "hard_gate_results": hard_gate_results,
        "failed_hard_gates": failed_hard_gates,
        "unknown_hard_fields": unknown_hard_fields,
        "kemp_reference": kemp_reference,
        "owned_store_count": owned_store_count,
    }
    if unique_count < manual_review_below or not action_gates_pass:
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

    # The owner-approved budget-floor strategy explicitly ignores stock age and
    # stock status. Legacy strategies retain the separate clearance branch.
    if context.stock_status is StockStatus.DEAD_STOCK and not (
        budget_floor_mode and raise_policy.ignore_stock_status
    ):
        action, recommended, mode_reasons, cost_floor = _clearance_recommendation(
            context, prices, policy
        )
    elif budget_floor_decision is not None:
        if budget_floor_decision.outcome is RaiseOutcome.RAISE:
            action = RecommendationAction.RAISE
        elif budget_floor_decision.outcome is RaiseOutcome.LOWER:
            action = RecommendationAction.LOWER
        elif budget_floor_decision.outcome is RaiseOutcome.SHOW_BUT_FLAG:
            action = RecommendationAction.MANUAL_REVIEW
        else:
            action = RecommendationAction.HOLD
        recommended = budget_floor_decision.recommended_price
        mode_reasons = ()
        cost_floor = None
    else:
        action, recommended, mode_reasons = _raise_recommendation(
            context,
            fair_price,
            lower_bound,
            cleaned,
            policy,
        )
        cost_floor = None
        if context.stock_status == StockStatus.UNKNOWN and not budget_floor_mode:
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
    offer: CompetitorOffer,
    tier: ProductTier,
    *,
    cohort_role: CohortRole,
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
        is_direct_kemp=tier == ProductTier.KEMP,
        source=offer.source,
        listing_url=offer.listing_url,
        comparison_evidence=offer.comparison_evidence,
        cohort_role=cohort_role,
    )


def _kemp_reference_rejection(
    context: ProductPricingContext,
    offer: CompetitorOffer,
    policy: PricingPolicy,
) -> str | None:
    """Validate a diagnostic KEMP lane without granting target-market authority."""

    if not offer.price.is_finite() or offer.price <= ZERO:
        return "NON_POSITIVE_PRICE"
    if offer.is_used or offer.tier == ProductTier.USED:
        return "USED_OR_REFURBISHED"
    if offer.is_dumping:
        return "KEMP_DUMPING"
    currency = (offer.currency or "").strip().upper()
    if currency != context.currency.strip().upper() or currency != policy.currency:
        return "CURRENCY_MISMATCH"
    if offer.is_available is not True:
        return "NOT_AVAILABLE"
    if offer.age_hours < ZERO or offer.age_hours > policy.max_age_hours:
        return "STALE_SOURCE"
    return None


def _hard_rejection(
    context: ProductPricingContext,
    offer: CompetitorOffer,
    policy: PricingPolicy,
    *,
    legacy_replay: bool,
    ignore_tier: bool = False,
) -> tuple[str | None, ComparabilityDecision | None]:
    if not offer.price.is_finite() or offer.price <= ZERO:
        return "NON_POSITIVE_PRICE", None
    if not legacy_replay:
        comparability = evaluate_comparison_evidence(
            offer.comparison_evidence,
            seller_id=offer.seller_id,
            currency_raw=offer.currency_raw,
            currency_normalized=offer.currency,
            required_currency=policy.currency,
            category=context.category,
        )
        if not comparability.automatic_eligible:
            return comparability.reason_codes[0], comparability
    else:
        comparability = None
    if offer.semantic_review_required:
        if not offer.semantic_review_id:
            return "MANUAL_LLM_COMPARABILITY_MISSING", comparability
        if offer.semantic_review_verdict == "NOT_COMPARABLE":
            return "REJECTED_LLM_NOT_COMPARABLE", comparability
        if (
            offer.semantic_review_verdict != "COMPARABLE"
            or offer.semantic_review_match_level not in {"EXACT", "ACCEPTABLE_ANALOGUE"}
        ):
            return "MANUAL_LLM_COMPARABILITY_INSUFFICIENT", comparability
    currency = (offer.currency or "").strip().upper()
    if currency != context.currency.strip().upper() or currency != policy.currency:
        return "CURRENCY_MISMATCH", comparability
    if offer.is_available is not True:
        return "NOT_AVAILABLE", comparability
    if offer.age_hours < ZERO or offer.age_hours > policy.max_age_hours:
        return "STALE_SOURCE", comparability
    if offer.is_used or offer.tier == ProductTier.USED:
        return "USED_OR_REFURBISHED", comparability
    if offer.severe_conflict:
        return offer.conflict_reason or "COMMERCIAL_CONFLICT", comparability
    if offer.match_confidence < policy.match_confidence_min:
        return "LOW_MATCH_CONFIDENCE", comparability
    if not ignore_tier:
        if offer.tier == ProductTier.UNKNOWN:
            return "UNKNOWN_TIER", comparability
        if offer.tier_confidence < policy.tier_confidence_min:
            return "LOW_TIER_CONFIDENCE", comparability
    if offer.source_confidence < policy.source_confidence_min:
        return "LOW_SOURCE_CONFIDENCE", comparability
    return None, comparability


def _excluded(
    offer: CompetitorOffer,
    reason: str,
    stage: str,
    cohort_role: CohortRole = CohortRole.HARD_REJECTED,
) -> ExcludedOffer:
    return ExcludedOffer(
        observation_id=offer.observation_id,
        reason=reason,
        seller_id=offer.seller_id,
        raw_price=offer.price,
        tier=offer.tier,
        stage=stage,
        cohort_role=cohort_role,
    )


def _deduplicate_sellers(
    offers: Iterable[NormalizedOffer],
    *,
    legacy_name_fallback: bool = False,
) -> tuple[list[NormalizedOffer], list[ExcludedOffer]]:
    representatives: dict[str, NormalizedOffer] = {}
    excluded: list[ExcludedOffer] = []
    for offer in sorted(offers, key=lambda item: item.observation_id):
        stable_id = (offer.seller_id or "").strip()
        key = stable_id or (
            offer.seller_name.casefold().strip() if legacy_name_fallback else ""
        )
        if not key:
            excluded.append(
                ExcludedOffer(
                    offer.observation_id,
                    "MANUAL_MISSING_STABLE_SELLER_ID",
                    offer.seller_id,
                    offer.raw_price,
                    offer.tier,
                    "seller_deduplication",
                )
            )
            continue
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


def _summarize_comparability(
    decisions: list[ComparabilityDecision],
    *,
    legacy_replay: bool,
) -> tuple[dict[str, int], tuple[str, ...], tuple[str, ...]]:
    if legacy_replay:
        return {"legacy_replay_only": 1}, (), ()
    verified = [
        decision
        for decision in decisions
        if decision.hard_gate_result == HardGateResult.PASS
    ]
    gates: dict[str, int] = {"comparability_contract": int(bool(verified))}
    gate_names = sorted(
        {name for decision in verified for name in decision.hard_gate_results}
    )
    for name in gate_names:
        gates[name] = int(
            all(decision.hard_gate_results.get(name, 0) == 1 for decision in verified)
        )
    failed = tuple(
        dict.fromkeys(
            gate
            for decision in decisions
            if not decision.automatic_eligible
            for gate in decision.failed_hard_gates
        )
    )
    unknown = tuple(
        dict.fromkeys(
            field
            for decision in decisions
            if not decision.automatic_eligible
            for field in decision.unknown_hard_fields
        )
    )
    return dict(sorted(gates.items())), failed, unknown


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
        decimal_pow(
            Decimal("2"),
            -(offer.age_hours / policy.freshness_half_life_hours),
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
    """Propose a higher price, or stay silent.

    Legacy strategies are raise-only. The owner-approved budget-floor strategy
    may advise either direction to restore the 2–5% below-market position.
    """

    del fair_price, lower_bound
    decision = decide_raise(
        current_price=context.current_price,
        prices=[offer.normalized_price for offer in cleaned_offers],
        stock_status=context.stock_status,
        policy=policy.raise_policy or default_raise_policy(),
        sellers=[offer.seller_id for offer in cleaned_offers],
    )
    reasons = decision.reasons + decision.flags
    if decision.outcome is RaiseOutcome.RAISE:
        return RecommendationAction.RAISE, decision.recommended_price, reasons
    if decision.outcome is RaiseOutcome.LOWER:
        return RecommendationAction.LOWER, decision.recommended_price, reasons
    if decision.outcome is RaiseOutcome.SHOW_BUT_FLAG:
        return RecommendationAction.MANUAL_REVIEW, None, reasons
    return RecommendationAction.HOLD, None, reasons


def _clearance_recommendation(
    context: ProductPricingContext,
    prices: list[Decimal],
    policy: PricingPolicy,
) -> tuple[RecommendationAction, Decimal | None, tuple[str, ...], Decimal | None]:
    lower_market = percentile(prices, policy.lower_market_quantile)
    base_beta = (
        policy.dead_stock_markdown_beta
        if context.stock_status == StockStatus.DEAD_STOCK
        else policy.stale_markdown_beta
    )
    threshold_days = (
        policy.dead_stock_age_threshold_days
        if context.stock_status == StockStatus.DEAD_STOCK
        else policy.stale_age_threshold_days
    )
    half_life_days = (
        policy.dead_stock_age_half_life_days
        if context.stock_status == StockStatus.DEAD_STOCK
        else policy.stale_age_half_life_days
    )
    reasons = [
        "CLEARANCE_MARKDOWN",
        "AGE_POLICY_ENGINEERING_ASSUMPTION",
        "AGE_POLICY_VERSION_APPLIED",
    ]
    if context.stock_age_days is None:
        beta_age = ZERO
        reasons.append("STOCK_AGE_UNKNOWN_BASE_POLICY_ONLY")
    else:
        excess_age = max(ZERO, context.stock_age_days - threshold_days)
        beta_age = ONE - decimal_exp(
            -decimal_ln(Decimal("2")) * (excess_age / half_life_days)
        )
    beta = clamp01(max(base_beta, beta_age, context.liquidity_target, context.urgency))
    target = (ONE - beta) * context.current_price + beta * min(
        context.current_price, lower_market
    )
    rounded_target = round_to_tick(target, policy.price_tick)
    recommended = min(context.current_price, rounded_target)
    if recommended > context.current_price * (ONE - policy.min_action_change):
        return (
            RecommendationAction.HOLD,
            None,
            tuple(reasons + ["CLEARANCE_TARGET_NOT_ACTIONABLE"]),
            None,
        )
    return RecommendationAction.LOWER, recommended, tuple(reasons), None


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
    urgency = context.urgency if context.urgency > ZERO else ONE
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
        recency = decimal_pow(
            Decimal("2"),
            -(context.days_since_last_sale / policy.sales_recency_half_life_days),
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
    # Cost-dependent ranking is disabled until Yuri selects and approves a
    # privacy architecture.  Retail inventory exposure remains available.
    return None


def _priced_result(
    *,
    context: ProductPricingContext,
    policy: PricingPolicy,
    action: RecommendationAction,
    recommended_price: Decimal | None,
    fair_price: Decimal | None,
    lower_bound: Decimal | None,
    upper_bound: Decimal | None,
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
    cluster_diagnostic: ClusterDiagnostic | None,
    hard_gate_results: Mapping[str, int],
    failed_hard_gates: tuple[str, ...],
    unknown_hard_fields: tuple[str, ...],
    kemp_reference: list[NormalizedOffer],
    owned_store_count: int,
) -> PricingResult:
    priority, score_type, review_priority, cost_basis, priority_inputs = _priorities(
        context,
        action,
        context.current_price,
        recommended_price,
        confidence,
        policy,
    )
    absolute_change, percentage_change = _recommended_change_metrics(
        context.current_price, recommended_price
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
        automatic_eligible=action_gates_passed,
        verified_seller_count=unique_seller_count,
        comparability_policy_id=COMPARABILITY_POLICY_ID,
        comparability_policy_hash=COMPARABILITY_POLICY_HASH,
        hard_gate_results=dict(hard_gate_results),
        failed_hard_gates=failed_hard_gates,
        unknown_hard_fields=unknown_hard_fields,
        cluster_diagnostic=cluster_diagnostic,
        robust_policy_fingerprint=_robust_policy_fingerprint(policy),
        target_market_count=len(evidence),
        kemp_reference_count=len(kemp_reference),
        owned_store_count=owned_store_count,
        rejected_count=len(excluded),
        kemp_reference_evidence=tuple(kemp_reference),
        absolute_recommended_change=absolute_change,
        percentage_recommended_change=percentage_change,
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
    cluster_diagnostic: ClusterDiagnostic | None = None,
    hard_gate_results: Mapping[str, int] | None = None,
    failed_hard_gates: tuple[str, ...] = (),
    unknown_hard_fields: tuple[str, ...] = (),
    kemp_reference: list[NormalizedOffer] | None = None,
    owned_store_count: int = 0,
) -> PricingResult:
    kemp_reference = kemp_reference or []
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
        reasons=tuple(
            dict.fromkeys(
                (reason,)
                + tuple(
                    item.reason for item in excluded if item.stage == "comparability"
                )
            )
        ),
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
        automatic_eligible=False,
        verified_seller_count=unique_seller_count,
        comparability_policy_id=COMPARABILITY_POLICY_ID,
        comparability_policy_hash=COMPARABILITY_POLICY_HASH,
        hard_gate_results=dict(hard_gate_results or {}),
        failed_hard_gates=failed_hard_gates,
        unknown_hard_fields=unknown_hard_fields,
        cluster_diagnostic=cluster_diagnostic,
        robust_policy_fingerprint=_robust_policy_fingerprint(policy),
        target_market_count=len(evidence),
        kemp_reference_count=len(kemp_reference),
        owned_store_count=owned_store_count,
        rejected_count=len(excluded),
        kemp_reference_evidence=tuple(kemp_reference),
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


def _recommended_change_metrics(
    current_price: Decimal,
    recommended_price: Decimal | None,
) -> tuple[Decimal | None, Decimal | None]:
    if recommended_price is None or current_price <= ZERO:
        return None, None
    absolute = abs(recommended_price - current_price)
    return absolute, absolute / current_price


def _robust_policy_fingerprint(policy: PricingPolicy) -> dict[str, str]:
    return {
        "policy_version": policy.version,
        "selected_scale_method": (
            policy.dispersion_method or RobustScaleMethod.LEGACY_MAD
        ).value,
        "profile_version": policy.robust_dispersion_profile_version,
        "correction_profile_version": (policy.robust_scale_correction_profile_version),
        "cluster_diagnostic_version": policy.robust_cluster_diagnostic_version,
        "disagreement": str(policy.robust_disagreement_threshold),
        "improvement": str(policy.robust_cluster_improvement_threshold),
        "balance": str(policy.robust_cluster_balance_threshold),
        "separation": str(policy.robust_cluster_separation_threshold),
        "gap": str(policy.robust_cluster_gap_threshold),
        "sigma_floor": str(policy.robust_cluster_sigma_floor),
        "baseline_policy_version": policy.robust_baseline_policy_version,
        "non_relaxation_enabled": str(policy.robust_non_relaxation_enabled).lower(),
        "code_commit": "NOT_AVAILABLE",
    }


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
        result.action in {RecommendationAction.RAISE, RecommendationAction.LOWER}
        and not result.action_gates_passed
    ):
        issues.append("INVARIANT_ACTION_WITHOUT_GATES")
    if any(offer.cohort_role != CohortRole.TARGET_MARKET for offer in result.evidence):
        issues.append("INVARIANT_NON_TARGET_IN_FAIR_COHORT")
    if any(
        offer.cohort_role != CohortRole.KEMP_REFERENCE
        for offer in result.kemp_reference_evidence
    ):
        issues.append("INVARIANT_INVALID_KEMP_REFERENCE_ROLE")
    target_ids = {offer.observation_id for offer in result.evidence}
    kemp_ids = {offer.observation_id for offer in result.kemp_reference_evidence}
    if target_ids & kemp_ids:
        issues.append("INVARIANT_COHORT_OVERLAP")
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
