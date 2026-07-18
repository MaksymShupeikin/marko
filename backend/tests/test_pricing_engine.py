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
        "is_kemp": is_kemp,
        "is_dumping": is_dumping,
    }
    values.update(overrides)
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
    result = recommend_price(context(), market_prices(), {})

    assert result.action == RecommendationAction.RAISE
    assert result.recommended_price == Decimal("920")
    assert result.recommended_price <= Decimal("800") * Decimal("1.15")


def test_fresh_product_is_never_automatically_lowered() -> None:
    result = recommend_price(context("1500"), market_prices(), {})

    assert result.action == RecommendationAction.HOLD
    assert result.recommended_price is None
    assert "MARKET_NOT_ABOVE_RAISE_THRESHOLD" in result.reasons


def test_two_competitors_are_insufficient() -> None:
    result = recommend_price(context(), market_prices()[:2], {})

    assert result.action == RecommendationAction.INSUFFICIENT_DATA
    assert result.confidence == Decimal("0")


def test_three_competitors_require_manual_review() -> None:
    result = recommend_price(context(), market_prices()[:3], {})

    assert result.action == RecommendationAction.MANUAL_REVIEW
    assert "TOO_FEW_COMPETITORS_FOR_ACTION" in result.reasons


def test_iqr_removes_extreme_outlier_without_using_mean() -> None:
    offers = [offer(index, str(1000 + index * 10)) for index in range(7)]
    offers.append(offer(99, "10000"))

    result = recommend_price(context(), offers, {})

    assert result.fair_price == Decimal("1030")
    assert any(item.reason == "ROBUST_OUTLIER" for item in result.excluded)


def test_same_seller_does_not_receive_two_votes() -> None:
    offers = market_prices()
    offers.append(offer(99, "5000", seller_id="seller-0"))

    result = recommend_price(context(), offers, {})

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

    result = recommend_price(context(), offers, {}, policy=policy)

    assert result.factor_scores["freshness"] == pytest.approx(Decimal("0.5"))


def test_low_factor_cannot_be_hidden_by_other_high_scores() -> None:
    offers = [
        offer(index, str(1000 + index * 50), match_confidence=Decimal("0.71"))
        for index in range(5)
    ]
    policy = PricingPolicy(factor_floor=Decimal("0.75"))

    result = recommend_price(context(), offers, {}, policy=policy)

    assert result.action == RecommendationAction.MANUAL_REVIEW
    assert "LOW_MATCH" in result.reasons


def test_non_dumping_direct_kemp_offer_is_a_raise_guardrail() -> None:
    offers = market_prices()
    offers.append(offer(10, "850", tier=ProductTier.KEMP, is_kemp=True))

    result = recommend_price(context(), offers, {})

    assert result.action == RecommendationAction.RAISE
    assert result.recommended_price == Decimal("850")


def test_dumping_kemp_offer_is_excluded_from_center_and_guardrail() -> None:
    offers = market_prices()
    offers.append(
        offer(10, "500", tier=ProductTier.KEMP, is_kemp=True, is_dumping=True)
    )

    result = recommend_price(context(), offers, {})

    assert result.recommended_price == Decimal("920")
    assert any(item.reason == "KEMP_DUMPING" for item in result.excluded)


def test_stale_stock_can_be_marked_down_but_not_below_cost() -> None:
    result = recommend_price(
        context(
            "1500",
            stock_status=StockStatus.STALE,
            cost=Decimal("1200"),
            stock_qty=Decimal("10"),
            stock_age_days=Decimal("500"),
        ),
        market_prices(),
        {},
    )

    assert result.action == RecommendationAction.LOWER
    assert result.recommended_price == Decimal("1275")
    assert result.recommended_price >= Decimal("1200")
    assert result.priority_score_type == PriorityScoreType.CLEARANCE_PRIORITY


def test_dead_stock_below_cost_requires_explicit_floor_override() -> None:
    result = recommend_price(
        context(
            "1500",
            stock_status=StockStatus.DEAD_STOCK,
            cost=Decimal("1200"),
            stock_qty=Decimal("10"),
            stock_age_days=Decimal("800"),
            allow_below_cost=True,
            below_cost_floor=Decimal("700"),
            below_cost_authorization_id="override-1",
            below_cost_authorized_by="user-1",
            below_cost_authorized_at=datetime.now(UTC),
            below_cost_reason="Approved dead-stock liquidation",
            below_cost_warning_confirmed=True,
        ),
        [offer(index, str(800 + index * 50)) for index in range(5)],
        {},
    )

    assert result.action == RecommendationAction.LOWER
    assert result.recommended_price == Decimal("850")
    assert result.recommended_price < Decimal("1200")
    assert "EXPLICIT_BELOW_COST_OVERRIDE" in result.reasons


def test_stale_stock_cannot_enable_below_cost_override() -> None:
    result = recommend_price(
        context(
            "1500",
            stock_status=StockStatus.STALE,
            cost=Decimal("1200"),
            allow_below_cost=True,
            below_cost_floor=Decimal("700"),
        ),
        market_prices(),
        {},
    )

    assert result.action == RecommendationAction.MANUAL_REVIEW
    assert "BELOW_COST_ONLY_FOR_DEAD_STOCK" in result.reasons


def test_clearance_without_cost_or_approved_floor_requires_manual_review() -> None:
    result = recommend_price(
        context("1500", stock_status=StockStatus.DEAD_STOCK),
        market_prices(),
        {},
    )

    assert result.action == RecommendationAction.MANUAL_REVIEW
    assert "MISSING_COST" in result.reasons


def test_raise_priority_uses_expected_monthly_units_and_confidence() -> None:
    result = recommend_price(
        context(expected_units_sold=Decimal("10")),
        market_prices(),
        {},
    )

    assert result.priority_score_type == PriorityScoreType.GROSS_UPLIFT_OPPORTUNITY
    assert result.priority_score > Decimal("0")
    assert result.priority_score <= Decimal("1200")


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
        {},
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
        context("1500", cost=Decimal("400"), **common), market_prices(), {}
    )
    high_cost = recommend_price(
        context("1500", cost=Decimal("1400"), **common), market_prices(), {}
    )

    assert low_cost.priority_score == high_cost.priority_score
