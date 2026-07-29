from datetime import UTC, datetime
from decimal import Decimal

import pytest

from metis.pricing import (
    CoefficientModel,
    CompetitorOffer,
    ConfidenceAggregation,
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
NOW = datetime(2026, 7, 16, tzinfo=UTC)


def coefficient(
    tier: ProductTier,
    multiplier: str,
    *,
    validated: bool = True,
    confidence: str = "0.95",
) -> TierCoefficient:
    return TierCoefficient(
        category=CATEGORY,
        tier=tier,
        multiplier=Decimal(multiplier),
        model=CoefficientModel.SHRINKAGE,
        method_version="test-shrinkage-v1",
        coefficient_version="test-shrinkage-v1:dataset",
        sample_size=20,
        effective_sample_size=Decimal("18"),
        confidence=Decimal(confidence),
        validated=validated,
        log_effect=Decimal("0"),
        interval_low=Decimal("1"),
        interval_high=Decimal("3"),
        dataset_hash="dataset",
    )


BUDGET_COEFFICIENTS = {
    (CATEGORY, ProductTier.BUDGET): coefficient(ProductTier.BUDGET, "1")
}


def offer(
    index: int,
    price: str,
    *,
    tier: ProductTier = ProductTier.BUDGET,
    seller_id: str | None = None,
    age_hours: str = "0",
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
        "is_kemp": tier == ProductTier.KEMP,
    }
    values.update(overrides)
    if "comparison_evidence" not in overrides:
        values["comparison_evidence"] = verified_comparison_evidence(
            stable_seller_id=str(values["seller_id"]),
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


def market(prices=("1000", "1050", "1100", "1150", "1200"), **overrides):
    return [offer(index, price, **overrides) for index, price in enumerate(prices)]


def below_cost_authorization(**overrides):
    values = {
        "stock_status": StockStatus.DEAD_STOCK,
        "cost": Decimal("1200"),
        "stock_qty": Decimal("10"),
        "stock_age_days": Decimal("800"),
        "allow_below_cost": True,
        "below_cost_floor": Decimal("700"),
        "below_cost_authorization_id": "override-1",
        "below_cost_authorized_by": "operator-1",
        "below_cost_authorized_at": NOW,
        "below_cost_reason": "Approved liquidation",
        "below_cost_warning_confirmed": True,
    }
    values.update(overrides)
    return values


def test_exact_oem_normalization_2400_divided_by_2_4_is_1000() -> None:
    offers = [offer(index, "2400", tier=ProductTier.OEM) for index in range(5)]

    result = recommend_price(
        context(),
        offers,
        {(CATEGORY, ProductTier.OEM): coefficient(ProductTier.OEM, "2.4")},
    )

    assert result.fair_price == Decimal("1000")
    assert {item.normalized_price for item in result.evidence} == {Decimal("1000")}
    assert {item.multiplier for item in result.evidence} == {Decimal("2.4")}


def test_kemp_reference_is_disjoint_from_budget_target_cohort() -> None:
    offers = [offer(index, str(1000 + 10 * index)) for index in range(4)]
    offers.append(offer(9, "1020", tier=ProductTier.KEMP))

    result = recommend_price(context(), offers, BUDGET_COEFFICIENTS)

    assert result.competitor_count == 4
    assert result.target_market_count == 4
    assert result.kemp_reference_count == 1
    assert all(item.multiplier == Decimal("1") for item in result.evidence)
    assert {item.tier for item in result.evidence} == {ProductTier.BUDGET}
    assert {item.tier for item in result.kemp_reference_evidence} == {ProductTier.KEMP}


def test_lower_tier_multiplier_is_excluded_by_default() -> None:
    offers = [offer(index, "800", tier=ProductTier.AFTERMARKET_B) for index in range(5)]

    result = recommend_price(
        context(),
        offers,
        {
            (CATEGORY, ProductTier.AFTERMARKET_B): coefficient(
                ProductTier.AFTERMARKET_B, "0.8"
            )
        },
    )

    assert result.action == RecommendationAction.INSUFFICIENT_DATA
    assert {item.reason for item in result.excluded} == {"LOWER_TIER_EXCLUDED"}


@pytest.mark.parametrize("multiplier", ["0", "-1"])
def test_non_positive_multiplier_cannot_create_recommendation(multiplier: str) -> None:
    offers = [offer(index, "1000", tier=ProductTier.OEM) for index in range(5)]

    result = recommend_price(
        context(),
        offers,
        {(CATEGORY, ProductTier.OEM): coefficient(ProductTier.OEM, multiplier)},
    )

    assert result.action == RecommendationAction.INSUFFICIENT_DATA
    assert {item.reason for item in result.excluded} == {"INVALID_TIER_COEFFICIENT"}


def test_iqr_removes_extreme_low_outlier() -> None:
    prices = ("1", "1000", "1010", "1020", "1030", "1040", "1050", "1060")

    result = recommend_price(context(), market(prices), BUDGET_COEFFICIENTS)

    assert result.outlier_method == "iqr"
    assert result.fair_price == Decimal("1030")
    assert any(
        item.raw_price == Decimal("1") and item.reason == "ROBUST_OUTLIER"
        for item in result.excluded
    )


def test_mad_filters_outlier_for_five_observations() -> None:
    result = recommend_price(
        context(),
        market(("1000", "1010", "1020", "1030", "10000")),
        BUDGET_COEFFICIENTS,
    )

    assert result.outlier_method == "mad"
    assert result.fair_price == Decimal("1015")
    assert result.action == RecommendationAction.MANUAL_REVIEW
    assert any(item.reason == "ROBUST_OUTLIER" for item in result.excluded)


def test_mad_zero_uses_absolute_tolerance_without_division_by_zero() -> None:
    result = recommend_price(
        context(),
        market(("1000", "1000", "1000", "1000", "5000")),
        BUDGET_COEFFICIENTS,
    )

    assert result.outlier_method == "mad"
    assert result.fair_price == Decimal("1000")
    assert result.outlier_count == 1
    assert result.action == RecommendationAction.MANUAL_REVIEW


def test_four_observations_are_descriptive_only() -> None:
    result = recommend_price(context(), market()[:4], BUDGET_COEFFICIENTS)

    assert result.fair_price == Decimal("1075")
    assert result.action == RecommendationAction.MANUAL_REVIEW
    assert result.recommended_price is None


@pytest.mark.parametrize(
    ("age_hours", "expected"),
    [("0", "1"), ("24", "0.5"), ("48", "0.25")],
)
def test_freshness_uses_true_half_life(age_hours: str, expected: str) -> None:
    policy = PricingPolicy(
        confidence_aggregation=ConfidenceAggregation.MINIMUM,
        factor_floor=Decimal("0"),
        factor_floors={
            name: Decimal("0")
            for name in (
                "coverage",
                "dispersion",
                "freshness",
                "match",
                "tier",
                "source",
            )
        },
        confidence_min=Decimal("0"),
    )

    result = recommend_price(
        context(), market(age_hours=age_hours), BUDGET_COEFFICIENTS, policy=policy
    )

    assert result.factor_scores["freshness"] == pytest.approx(Decimal(expected))


def test_low_tier_confidence_blocks_all_automatic_actions() -> None:
    offers = market(tier_confidence=Decimal("0.59"))

    result = recommend_price(context(), offers, BUDGET_COEFFICIENTS)

    assert result.action == RecommendationAction.INSUFFICIENT_DATA
    assert all(item.reason == "LOW_TIER_CONFIDENCE" for item in result.excluded)


def test_high_dispersion_blocks_action() -> None:
    result = recommend_price(
        context(),
        market(("600", "800", "1000", "1400", "1800")),
        BUDGET_COEFFICIENTS,
    )

    assert result.action == RecommendationAction.MANUAL_REVIEW
    assert "HIGH_DISPERSION" in result.reasons


def test_insufficient_effective_sample_blocks_action() -> None:
    offers = [
        offer(
            0,
            "1000",
            match_confidence=Decimal("1"),
            tier_confidence=Decimal("1"),
        )
    ]
    offers.extend(
        offer(
            index,
            str(1000 + index * 20),
            age_hours="72",
            match_confidence=Decimal("0.70"),
            tier_confidence=Decimal("0.60"),
            source_confidence=Decimal("0.50"),
        )
        for index in range(1, 5)
    )

    result = recommend_price(context(), offers, BUDGET_COEFFICIENTS)

    assert result.effective_competitor_count < Decimal("3")
    assert result.action == RecommendationAction.MANUAL_REVIEW
    assert "LOW_EFFECTIVE_SAMPLE_SIZE" in result.reasons


def test_severe_data_health_issue_forces_zero_confidence_review() -> None:
    result = recommend_price(
        context(severe_data_health_issue=True), market(), BUDGET_COEFFICIENTS
    )

    assert result.action == RecommendationAction.MANUAL_REVIEW
    assert result.confidence == Decimal("0")
    assert "SEVERE_DATA_HEALTH_ISSUE" in result.data_health_issues


@pytest.mark.parametrize("age", ["0", "12", "24", "48", "72"])
def test_confidence_is_always_bounded(age: str) -> None:
    result = recommend_price(context(), market(age_hours=age), BUDGET_COEFFICIENTS)

    assert Decimal("0") <= result.confidence <= Decimal("1")


def test_direct_kemp_reference_cannot_change_raise_target() -> None:
    without_kemp = recommend_price(context(), market(), BUDGET_COEFFICIENTS)
    with_kemp = recommend_price(
        context(),
        market() + [offer(10, "1200", tier=ProductTier.KEMP)],
        BUDGET_COEFFICIENTS,
    )

    assert without_kemp.action == RecommendationAction.RAISE
    assert with_kemp.action == RecommendationAction.RAISE
    assert with_kemp.recommended_price == without_kemp.recommended_price
    assert with_kemp.fair_price == without_kemp.fair_price


def test_kemp_price_alone_does_not_infer_target_market_dumping() -> None:
    offers = market() + [
        offer(10, "1000", tier=ProductTier.KEMP),
        offer(11, "1020", tier=ProductTier.KEMP),
        offer(12, "500", tier=ProductTier.KEMP),
    ]

    result = recommend_price(context(), offers, BUDGET_COEFFICIENTS)

    assert result.kemp_reference_count == 3
    assert not any(item.observation_id == "obs-12" for item in result.excluded)


def test_low_confidence_never_returns_raise_or_lower() -> None:
    policy = PricingPolicy(factor_floor=Decimal("0.75"))
    offers = market(match_confidence=Decimal("0.71"))

    result = recommend_price(context(), offers, BUDGET_COEFFICIENTS, policy=policy)

    assert result.action not in {
        RecommendationAction.RAISE,
        RecommendationAction.LOWER,
    }
    assert result.recommended_price is None


def test_dead_stock_engine_is_independent_of_cost_authorization_metadata() -> None:
    incomplete = below_cost_authorization(below_cost_authorized_by=None)
    complete = below_cost_authorization()

    first = recommend_price(
        context("1500", **incomplete),
        market(("500", "550", "600", "650", "700")),
        BUDGET_COEFFICIENTS,
    )
    second = recommend_price(
        context("1500", **complete),
        market(("500", "550", "600", "650", "700")),
        BUDGET_COEFFICIENTS,
    )

    assert first.action == second.action == RecommendationAction.LOWER
    assert first.recommended_price == second.recommended_price
    assert first.cost_floor is None


def test_missing_approved_floor_does_not_block_manual_market_candidate() -> None:
    incomplete = below_cost_authorization(below_cost_floor=None)

    result = recommend_price(
        context("1500", **incomplete),
        market(("500", "550", "600", "650", "700")),
        BUDGET_COEFFICIENTS,
    )

    assert result.action == RecommendationAction.LOWER
    assert result.recommended_price is not None
    assert result.cost_floor is None


def test_configured_cost_floor_does_not_replace_market_evidence() -> None:
    result = recommend_price(
        context("1500", **below_cost_authorization()),
        market(("500", "550", "600", "650", "700")),
        BUDGET_COEFFICIENTS,
    )

    assert result.action == RecommendationAction.LOWER
    assert result.recommended_price is not None
    assert result.cost_floor is None
    assert result.recommended_price < Decimal("1200")


def test_cost_never_changes_fair_market_price() -> None:
    cheap = recommend_price(
        context("1500", stock_status=StockStatus.STALE, cost=Decimal("500")),
        market(),
        BUDGET_COEFFICIENTS,
    )
    expensive = recommend_price(
        context("1500", stock_status=StockStatus.STALE, cost=Decimal("1400")),
        market(),
        BUDGET_COEFFICIENTS,
    )

    assert cheap.fair_price == expensive.fair_price == Decimal("1100")


@pytest.mark.parametrize("current_price", ["500", "800", "1100", "1500", "2500"])
def test_fresh_items_move_up_or_stay_put_but_never_down(current_price: str) -> None:
    """Direction is asymmetric on purpose: raise or say nothing.

    Above the target the engine holds instead of proposing a cut, so an item
    that is already expensive keeps its margin rather than being talked down.
    """

    result = recommend_price(
        context(current_price, stock_status=StockStatus.FRESH),
        market(),
        BUDGET_COEFFICIENTS,
    )

    assert result.action != RecommendationAction.LOWER
    if Decimal(current_price) < Decimal("1000"):
        assert result.action == RecommendationAction.RAISE
        assert result.recommended_price > Decimal(current_price)
    else:
        assert result.action == RecommendationAction.HOLD
        assert result.recommended_price is None


def test_raise_priority_increases_with_expected_units() -> None:
    low = recommend_price(
        context(expected_units_sold=Decimal("5")), market(), BUDGET_COEFFICIENTS
    )
    high = recommend_price(
        context(expected_units_sold=Decimal("10")), market(), BUDGET_COEFFICIENTS
    )

    assert high.priority_score > low.priority_score
    assert high.priority_score_type == PriorityScoreType.GROSS_UPLIFT_OPPORTUNITY


def test_raise_priority_decreases_with_confidence() -> None:
    fresh = recommend_price(
        context(expected_units_sold=Decimal("10")),
        market(age_hours="0"),
        BUDGET_COEFFICIENTS,
    )
    older = recommend_price(
        context(expected_units_sold=Decimal("10")),
        market(age_hours="12"),
        BUDGET_COEFFICIENTS,
    )

    assert fresh.recommended_price == older.recommended_price
    assert fresh.confidence > older.confidence
    assert fresh.priority_score > older.priority_score


def test_clearance_priority_increases_with_quantity_and_age() -> None:
    common = {"stock_status": StockStatus.STALE, "cost": Decimal("800")}
    small = recommend_price(
        context(
            "1500", stock_qty=Decimal("1"), stock_age_days=Decimal("100"), **common
        ),
        market(),
        BUDGET_COEFFICIENTS,
    )
    large_old = recommend_price(
        context(
            "1500", stock_qty=Decimal("10"), stock_age_days=Decimal("730"), **common
        ),
        market(),
        BUDGET_COEFFICIENTS,
    )

    assert large_old.priority_score > small.priority_score


def test_dead_stock_ranks_above_equivalent_stale_stock() -> None:
    common = {
        "cost": Decimal("800"),
        "stock_qty": Decimal("10"),
        "stock_age_days": Decimal("500"),
    }
    stale = recommend_price(
        context("1500", stock_status=StockStatus.STALE, **common),
        market(),
        BUDGET_COEFFICIENTS,
    )
    dead = recommend_price(
        context("1500", stock_status=StockStatus.DEAD_STOCK, **common),
        market(),
        BUDGET_COEFFICIENTS,
    )

    assert dead.priority_score > stale.priority_score


def test_missing_sales_uses_explicitly_labeled_proxy() -> None:
    result = recommend_price(context(), market(), BUDGET_COEFFICIENTS)

    assert result.priority_score_type == PriorityScoreType.GAP_CONFIDENCE_PROXY
    assert result.priority_inputs["unit"] == "DIMENSIONLESS_GAP_CONFIDENCE_PROXY"


def test_high_capital_low_confidence_dead_stock_gets_review_priority() -> None:
    policy = PricingPolicy(factor_floor=Decimal("0.75"))
    offers = market(match_confidence=Decimal("0.71"))
    low = recommend_price(
        context(
            "1500",
            stock_status=StockStatus.DEAD_STOCK,
            cost=Decimal("1000"),
            stock_qty=Decimal("1"),
            stock_age_days=Decimal("800"),
        ),
        offers,
        BUDGET_COEFFICIENTS,
        policy=policy,
    )
    high = recommend_price(
        context(
            "1500",
            stock_status=StockStatus.DEAD_STOCK,
            cost=Decimal("1000"),
            stock_qty=Decimal("100"),
            stock_age_days=Decimal("800"),
        ),
        offers,
        BUDGET_COEFFICIENTS,
        policy=policy,
    )

    assert high.review_priority > low.review_priority


def test_priority_scores_with_different_units_are_never_mislabeled() -> None:
    raise_result = recommend_price(
        context(expected_units_sold=Decimal("10")),
        market(),
        BUDGET_COEFFICIENTS,
    )
    clearance_result = recommend_price(
        context(
            "1500",
            stock_status=StockStatus.STALE,
            cost=Decimal("800"),
            stock_qty=Decimal("10"),
            stock_age_days=Decimal("500"),
        ),
        market(),
        BUDGET_COEFFICIENTS,
    )

    assert raise_result.priority_score_type != clearance_result.priority_score_type
    assert raise_result.priority_inputs["unit"] == "UAH_PER_MONTH_CONFIDENCE_ADJUSTED"
    assert (
        clearance_result.priority_inputs["unit"]
        == "UAH_LOCKED_INVENTORY_CONFIDENCE_ADJUSTED"
    )


def test_realistic_scenario_a_mixed_tiers_normalizes_to_kemp_level() -> None:
    offers = [
        offer(0, "3200", tier=ProductTier.OEM),
        offer(1, "2000", tier=ProductTier.OES),
        offer(2, "1400", tier=ProductTier.AFTERMARKET_A),
        offer(3, "850", tier=ProductTier.KEMP),
        offer(4, "400", tier=ProductTier.USED, is_used=True),
    ]
    coefficients = {
        (CATEGORY, ProductTier.OEM): coefficient(ProductTier.OEM, "3.2"),
        (CATEGORY, ProductTier.OES): coefficient(ProductTier.OES, "2"),
        (CATEGORY, ProductTier.AFTERMARKET_A): coefficient(
            ProductTier.AFTERMARKET_A, "1.4"
        ),
    }

    result = recommend_price(context(), offers, coefficients)

    assert result.fair_price == Decimal("1000")
    assert max(item.normalized_price for item in result.evidence) == Decimal("1000")
    assert any(item.reason == "USED_OR_REFURBISHED" for item in result.excluded)
    assert result.action == RecommendationAction.MANUAL_REVIEW


def test_realistic_scenario_f_weak_evidence_abstains() -> None:
    offers = [
        offer(0, "600", age_hours="60"),
        offer(1, "1100", age_hours="60"),
        offer(2, "1800", age_hours="60"),
    ]

    result = recommend_price(context(), offers, BUDGET_COEFFICIENTS)

    assert result.action == RecommendationAction.MANUAL_REVIEW
    assert result.recommended_price is None
