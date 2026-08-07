from dataclasses import replace
from decimal import Decimal

import pytest

from metis.pricing import (
    CoefficientModel,
    CompetitorOffer,
    ConfidenceAggregation,
    EvidenceState,
    PricingPolicy,
    PriorityScoreType,
    ProductPricingContext,
    ProductTier,
    RecommendationAction,
    StockStatus,
    TierCoefficient,
    recommend_price,
    verified_comparison_evidence,
)


CATEGORY = "brakes"


def coefficient(
    tier: ProductTier = ProductTier.OEM,
    multiplier: str = "2",
    confidence: str = "0.95",
    validated: bool = True,
) -> TierCoefficient:
    return TierCoefficient(
        category=CATEGORY,
        tier=tier,
        multiplier=Decimal(multiplier),
        model=CoefficientModel.SHRINKAGE,
        method_version="test-v1",
        sample_size=20,
        effective_sample_size=Decimal("20"),
        confidence=Decimal(confidence),
        validated=validated,
        log_effect=Decimal("0.693147"),
    )


BUDGET_COEFFICIENTS = {
    (CATEGORY, ProductTier.BUDGET): coefficient(ProductTier.BUDGET, multiplier="1")
}


def offer(
    index: int,
    price: str,
    *,
    tier: ProductTier = ProductTier.BUDGET,
    seller_id: str | None = None,
    age_hours: str = "0",
    is_kemp: bool = False,
    is_dumping: bool = False,
    **overrides,
) -> CompetitorOffer:
    values = {
        "observation_id": f"obs-{index}",
        "seller_id": seller_id or f"seller-{index}",
        "seller_name": f"Seller {index}",
        "price": Decimal(price),
        "currency": "UAH",
        "is_available": True,
        "age_hours": Decimal(age_hours),
        "match_confidence": Decimal("0.95"),
        "tier": tier,
        "tier_confidence": Decimal("0.95"),
        "source_confidence": Decimal("1"),
        "currency_raw": "UAH",
        "semantic_gate_current": True,
        "automatic_eligible": True,
        "is_kemp": is_kemp,
        "is_dumping": is_dumping,
    }
    values.update(overrides)
    if "comparison_evidence" not in overrides:
        stable_seller_id = str(values["seller_id"])
        values["comparison_evidence"] = verified_comparison_evidence(
            stable_seller_id=stable_seller_id,
            source_record_id=str(values["observation_id"]),
        )
    return CompetitorOffer(**values)


def context(price: str = "800", **overrides) -> ProductPricingContext:
    values = {
        "sku": "SKU-1",
        "category": CATEGORY,
        "current_price": Decimal(price),
    }
    values.update(overrides)
    return ProductPricingContext(**values)


def market_prices(start: int = 1000) -> list[CompetitorOffer]:
    return [offer(index, str(start + index * 50)) for index in range(5)]


def test_stale_semantic_gate_snapshot_is_excluded_from_pricing_cohort() -> None:
    offers = market_prices()
    offers[0] = replace(offers[0], semantic_gate_current=False)

    result = recommend_price(
        context(),
        offers,
        BUDGET_COEFFICIENTS,
    )

    assert all(value.observation_id != "obs-0" for value in result.evidence)
    assert any(
        value.observation_id == "obs-0"
        and value.reason == "SEMANTIC_GATE_NOT_CURRENT"
        for value in result.excluded
    )


def test_persisted_automatic_ineligible_offer_is_excluded_from_pricing_cohort() -> None:
    offers = market_prices()
    offers[0] = replace(offers[0], automatic_eligible=False)

    result = recommend_price(
        context(),
        offers,
        BUDGET_COEFFICIENTS,
    )

    assert all(value.observation_id != "obs-0" for value in result.evidence)
    assert any(
        value.observation_id == "obs-0"
        and value.reason == "PERSISTED_AUTOMATIC_ELIGIBILITY_REQUIRED"
        for value in result.excluded
    )


def test_oem_prices_are_normalized_to_kemp_equivalent() -> None:
    offers = [
        offer(index, str(2000 + index * 100), tier=ProductTier.OEM)
        for index in range(5)
    ]

    result = recommend_price(
        context(),
        offers,
        {(CATEGORY, ProductTier.OEM): coefficient()},
    )

    assert result.fair_price == Decimal("1100")
    assert all(item.multiplier == Decimal("2") for item in result.evidence)


def test_raise_is_capped_by_maximum_single_step() -> None:
    result = recommend_price(context(), market_prices(), BUDGET_COEFFICIENTS)

    assert result.action == RecommendationAction.RAISE
    assert result.recommended_price == Decimal("1000")
    assert result.recommended_price <= Decimal("800") * Decimal("1.25")
    assert "STEP_CAPPED" in result.reasons


def test_fresh_product_below_market_is_never_advised_downward() -> None:
    """A selling item is never told to cut: the tool only shows headroom.

    The customer accepted the asymmetry explicitly — the worst thing the
    system may do is stay silent.
    """

    result = recommend_price(context("1500"), market_prices(), BUDGET_COEFFICIENTS)

    assert result.action == RecommendationAction.HOLD
    assert result.recommended_price is None
    assert "PRICE_ALREADY_AT_OR_ABOVE_TARGET" in result.reasons


def test_two_competitors_are_insufficient() -> None:
    result = recommend_price(context(), market_prices()[:2], BUDGET_COEFFICIENTS)

    assert result.action == RecommendationAction.INSUFFICIENT_DATA
    assert result.confidence == Decimal("0")


def test_three_competitors_require_manual_review() -> None:
    result = recommend_price(context(), market_prices()[:3], BUDGET_COEFFICIENTS)

    assert result.action == RecommendationAction.MANUAL_REVIEW
    assert "TOO_FEW_COMPETITORS_FOR_ACTION" in result.reasons


def test_iqr_removes_extreme_outlier_without_using_mean() -> None:
    offers = [offer(index, str(1000 + index * 10)) for index in range(7)]
    offers.append(offer(99, "10000"))

    result = recommend_price(context(), offers, BUDGET_COEFFICIENTS)

    assert result.fair_price == Decimal("1030")
    assert any(item.reason == "ROBUST_OUTLIER" for item in result.excluded)


def test_same_seller_does_not_receive_two_votes() -> None:
    offers = market_prices()
    offers.append(offer(99, "5000", seller_id="seller-0"))

    result = recommend_price(context(), offers, BUDGET_COEFFICIENTS)

    assert result.competitor_count == 5
    assert any(item.reason == "SELLER_DUPLICATE" for item in result.excluded)


def test_unvalidated_cross_tier_coefficient_abstains() -> None:
    offers = [
        offer(index, str(2000 + index * 100), tier=ProductTier.OEM)
        for index in range(5)
    ]

    result = recommend_price(
        context(),
        offers,
        {(CATEGORY, ProductTier.OEM): coefficient(validated=False)},
    )

    assert result.action == RecommendationAction.INSUFFICIENT_DATA
    assert all(
        item.reason == "UNVALIDATED_TIER_COEFFICIENT" for item in result.excluded
    )


def test_true_half_life_scores_half_after_one_half_life() -> None:
    offers = [
        offer(index, str(1000 + index * 50), age_hours="24") for index in range(5)
    ]
    policy = PricingPolicy(
        confidence_aggregation=ConfidenceAggregation.MINIMUM,
        factor_floor=Decimal("0.30"),
    )

    result = recommend_price(context(), offers, BUDGET_COEFFICIENTS, policy=policy)

    assert result.factor_scores["freshness"] == pytest.approx(Decimal("0.5"))


def test_low_factor_cannot_be_hidden_by_other_high_scores() -> None:
    offers = [
        offer(index, str(1000 + index * 50), match_confidence=Decimal("0.71"))
        for index in range(5)
    ]
    policy = PricingPolicy(factor_floor=Decimal("0.75"))

    result = recommend_price(context(), offers, BUDGET_COEFFICIENTS, policy=policy)

    assert result.action == RecommendationAction.MANUAL_REVIEW
    assert "LOW_MATCH" in result.reasons


def test_non_dumping_kemp_offer_is_reference_only_not_a_guardrail() -> None:
    offers = market_prices()
    offers.append(offer(10, "850", tier=ProductTier.KEMP, is_kemp=True))

    result = recommend_price(context(), offers, BUDGET_COEFFICIENTS)

    assert result.action == RecommendationAction.RAISE
    assert result.recommended_price == Decimal("1000")
    assert result.target_market_count == 5
    assert result.kemp_reference_count == 1


def test_kemp_reference_with_failed_comparability_is_not_trusted() -> None:
    offers = market_prices()
    unverified = offer(
        10,
        "850",
        tier=ProductTier.KEMP,
        is_kemp=True,
        comparison_evidence=verified_comparison_evidence(
            stable_seller_id="seller-10",
            source_record_id="obs-10",
            dimension_overrides={"condition": EvidenceState.UNKNOWN},
        ),
    )

    result = recommend_price(context(), [*offers, unverified], BUDGET_COEFFICIENTS)

    assert result.kemp_reference_count == 0
    assert any(
        item.observation_id == "obs-10"
        and item.reason == "MANUAL_MISSING_CONDITION"
        for item in result.excluded
    )


def test_kemp_reference_without_comparability_evidence_is_not_trusted() -> None:
    offers = market_prices()
    missing_evidence = offer(
        11,
        "850",
        tier=ProductTier.KEMP,
        is_kemp=True,
        comparison_evidence=None,
    )

    result = recommend_price(
        context(), [*offers, missing_evidence], BUDGET_COEFFICIENTS
    )

    assert result.kemp_reference_count == 0
    assert any(
        item.observation_id == "obs-11"
        and item.reason == "MANUAL_MISSING_COMPARABILITY_EVIDENCE"
        for item in result.excluded
    )


def test_dumping_kemp_offer_is_excluded_from_center_and_guardrail() -> None:
    offers = market_prices()
    offers.append(
        offer(10, "500", tier=ProductTier.KEMP, is_kemp=True, is_dumping=True)
    )

    result = recommend_price(context(), offers, BUDGET_COEFFICIENTS)

    assert result.recommended_price == Decimal("1000")
    assert any(item.reason == "KEMP_DUMPING" for item in result.excluded)


def test_dead_stock_markdown_is_not_floored_by_sunk_cost() -> None:
    """Liquidation still ignores what the stock cost; only dead stock reaches it."""

    result = recommend_price(
        context(
            "1500",
            stock_status=StockStatus.DEAD_STOCK,
            cost=Decimal("1200"),
            stock_qty=Decimal("10"),
            stock_age_days=Decimal("500"),
        ),
        market_prices(),
        BUDGET_COEFFICIENTS,
    )

    assert result.action == RecommendationAction.LOWER
    assert result.recommended_price < Decimal("1500")
    assert result.priority_score_type == PriorityScoreType.CLEARANCE_PRIORITY


def test_stale_stock_above_the_cheapest_offer_stays_silent() -> None:
    """A slow mover priced above the market is left alone, not marked down."""

    result = recommend_price(
        context(
            "1500",
            stock_status=StockStatus.STALE,
            cost=Decimal("1200"),
            stock_qty=Decimal("10"),
            stock_age_days=Decimal("500"),
        ),
        market_prices(),
        BUDGET_COEFFICIENTS,
    )

    assert result.action == RecommendationAction.HOLD
    assert result.recommended_price is None
    assert "STALE_NOT_BELOW_CHEAPEST_COMPETITOR" in result.reasons


def test_stale_stock_below_the_cheapest_offer_is_raised_to_it() -> None:
    result = recommend_price(
        context(
            "800",
            stock_status=StockStatus.STALE,
            stock_qty=Decimal("10"),
            stock_age_days=Decimal("500"),
        ),
        market_prices(),
        BUDGET_COEFFICIENTS,
    )

    assert result.action == RecommendationAction.RAISE
    assert result.recommended_price == Decimal("1000")
    assert "STALE_CAPPED_AT_CHEAPEST" in result.reasons


def test_dead_stock_sunk_cost_context_does_not_change_market_target() -> None:
    result = recommend_price(
        context(
            "1500",
            stock_status=StockStatus.DEAD_STOCK,
            cost=Decimal("1200"),
            stock_qty=Decimal("10"),
            stock_age_days=Decimal("800"),
        ),
        [offer(index, str(800 + index * 50)) for index in range(5)],
        BUDGET_COEFFICIENTS,
    )

    assert result.action == RecommendationAction.LOWER
    assert result.recommended_price < Decimal("1200")
    assert result.cost_floor is None


def test_stale_cost_mutation_does_not_change_recommendation() -> None:
    with_cost = recommend_price(
        context(
            "1500",
            stock_status=StockStatus.STALE,
            cost=Decimal("1200"),
        ),
        market_prices(),
        BUDGET_COEFFICIENTS,
    )
    without_cost = recommend_price(
        context("1500", stock_status=StockStatus.STALE, cost=None),
        market_prices(),
        BUDGET_COEFFICIENTS,
    )

    assert with_cost.action == without_cost.action
    assert with_cost.recommended_price == without_cost.recommended_price


def test_clearance_without_cost_remains_actionable_for_manual_operator() -> None:
    result = recommend_price(
        context("1500", stock_status=StockStatus.DEAD_STOCK),
        market_prices(),
        BUDGET_COEFFICIENTS,
    )

    assert result.action == RecommendationAction.LOWER
    assert result.recommended_price is not None


def test_raise_priority_uses_expected_monthly_units_and_confidence() -> None:
    result = recommend_price(
        context(expected_units_sold=Decimal("10")),
        market_prices(),
        BUDGET_COEFFICIENTS,
    )

    assert result.priority_score_type == PriorityScoreType.GROSS_UPLIFT_OPPORTUNITY
    assert result.priority_score > Decimal("0")
    # The step cap is 25% rather than 15%, so the same market supports a larger
    # uplift per unit and therefore a larger opportunity score.
    assert result.priority_score <= Decimal("2000")


def test_low_confidence_dead_stock_gets_separate_review_priority() -> None:
    offers = [
        offer(index, str(1000 + index * 50), match_confidence=Decimal("0.71"))
        for index in range(5)
    ]
    result = recommend_price(
        context(
            "1500",
            stock_status=StockStatus.DEAD_STOCK,
            cost=Decimal("1000"),
            stock_qty=Decimal("100"),
            stock_age_days=Decimal("800"),
        ),
        offers,
        BUDGET_COEFFICIENTS,
        policy=PricingPolicy(factor_floor=Decimal("0.75")),
    )

    assert result.action == RecommendationAction.MANUAL_REVIEW
    assert result.review_priority > Decimal("0")


def test_clearance_priority_uses_retail_inventory_value_not_cost() -> None:
    common = {
        "stock_status": StockStatus.DEAD_STOCK,
        "stock_qty": Decimal("10"),
        "stock_age_days": Decimal("800"),
    }
    low_cost = recommend_price(
        context("1500", cost=Decimal("400"), **common),
        market_prices(),
        BUDGET_COEFFICIENTS,
    )
    high_cost = recommend_price(
        context("1500", cost=Decimal("1400"), **common),
        market_prices(),
        BUDGET_COEFFICIENTS,
    )

    assert low_cost.priority_score == high_cost.priority_score
