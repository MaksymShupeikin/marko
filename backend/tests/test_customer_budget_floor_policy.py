"""Owner-approved 2026-07-30 budget-segment pricing contract."""

from __future__ import annotations

from dataclasses import fields, replace
from decimal import Decimal
from pathlib import Path

import pytest

from metis.pricing import (
    CompetitorOffer,
    PricingPolicy,
    ProductPricingContext,
    ProductTier,
    RecommendationAction,
    StockStatus,
    recommend_price,
    verified_comparison_evidence,
)
from metis.pricing.raise_policy import (
    RaiseOutcome,
    RaisePolicy,
    RaiseStrategy,
    decide_raise,
    load_raise_policy,
)
from marko.services.market_collection import (
    apply_comparability_activation_gate,
    customer_budget_floor_trace,
)
from marko.services.cost_privacy import privacy_safe_mapping
from marko.services.pricing_runs import execution_policy_hash, policy_to_dict


BACKEND_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = BACKEND_ROOT / "config" / "raise_policy.yaml"
BUDGET_POLICY = load_raise_policy(POLICY_PATH)


def _budget_decision(
    current: str,
    *,
    prices: tuple[str, ...] = ("1000", "1200", "1400"),
    stock_status: StockStatus = StockStatus.FRESH,
    cost_floor: str | None = None,
    policy=None,
):
    return decide_raise(
        current_price=Decimal(current),
        prices=[Decimal(value) for value in prices],
        stock_status=stock_status,
        policy=policy or BUDGET_POLICY,
        cost_floor=None if cost_floor is None else Decimal(cost_floor),
    )


def _offer(
    index: int,
    price: str,
    *,
    tier: ProductTier,
    tier_confidence: str = "0",
    is_used: bool = False,
) -> CompetitorOffer:
    seller_id = f"seller-{index}"
    return CompetitorOffer(
        observation_id=f"observation-{index}",
        seller_id=seller_id,
        seller_name=f"Seller {index}",
        price=Decimal(price),
        currency="UAH",
        currency_raw="UAH",
        is_available=True,
        age_hours=Decimal("0"),
        match_confidence=Decimal("0.99"),
        tier=tier,
        tier_confidence=Decimal(tier_confidence),
        source_confidence=Decimal("1"),
        semantic_gate_current=True,
        automatic_eligible=True,
        is_used=is_used,
        comparison_evidence=verified_comparison_evidence(
            stable_seller_id=seller_id,
            source_record_id=f"observation-{index}",
            retrieval_kind="search_query",
        ),
    )


def _engine_result(
    current: str,
    offers: list[CompetitorOffer],
):
    return recommend_price(
        ProductPricingContext(
            sku="OWNER-BUDGET-1",
            category="brakes",
            current_price=Decimal(current),
            stock_status=StockStatus.DEAD_STOCK,
            cost=Decimal("5000"),
            stock_age_days=Decimal("999"),
        ),
        offers,
        {},
        policy=PricingPolicy(
            version="pricing-v2",
            raise_policy=BUDGET_POLICY,
        ),
    )


def test_active_strategy_is_owner_approved_budget_floor() -> None:
    assert BUDGET_POLICY.strategy is RaiseStrategy.BUDGET_FLOOR
    assert BUDGET_POLICY.minimum_discount == Decimal("0.02")
    assert BUDGET_POLICY.maximum_discount == Decimal("0.05")
    assert BUDGET_POLICY.psychological_step == Decimal("1")
    assert BUDGET_POLICY.tier_agnostic
    assert BUDGET_POLICY.allow_lower
    assert BUDGET_POLICY.ignore_stock_status
    assert BUDGET_POLICY.ignore_cost_floor
    # The owner approved "the cheapest comparable offer", not a relative
    # plausibility threshold.  The measured 0.35 candidate remains testable
    # separately, but shipping it active would assign a domain value in
    # violation of C-10/G-6.
    assert BUDGET_POLICY.target_floor_ratio == Decimal("0")


def test_run_policy_snapshot_records_every_raise_policy_field() -> None:
    """Снимок несёт ВСЕ поля политики повышения, а не выбранное подмножество.

    Раньше здесь сохранялся «отпечаток личности» из тринадцати полей, а
    ``target_quantile``, ``min_evidence``, ``max_step_pct`` и пороги уверенности
    в него не входили.  Их правка в файле развёртывания меняла результат
    прогона, не меняя ни одного сохранённого байта: расхождение было
    невидимым.  Тест перечисляет поля не именами, а составом датакласса —
    новое поле ``RaisePolicy`` обязано попасть в снимок само.
    """

    snapshot = policy_to_dict(PricingPolicy(raise_policy=BUDGET_POLICY))
    persisted = snapshot["raise_policy"]

    assert set(persisted) == {item.name for item in fields(RaisePolicy)}
    assert persisted["strategy"] == "budget_floor"
    assert persisted["method_version"] == "raise-policy-v2"
    assert persisted["source_sha256"] == BUDGET_POLICY.source_sha256
    assert persisted["owner_decision_reference"] == "customer-reply-2026-07-30"
    # Именно те поля, которых прежде не было — и которые решают, куда встанет
    # рекомендация.
    assert persisted["target_quantile"] == str(BUDGET_POLICY.target_quantile)
    assert persisted["min_evidence"] == BUDGET_POLICY.min_evidence
    assert persisted["max_step_pct"] == str(BUDGET_POLICY.max_step_pct)
    assert persisted["min_change_pct"] == str(BUDGET_POLICY.min_change_pct)
    assert persisted["high_min_evidence"] == BUDGET_POLICY.high_min_evidence
    assert persisted["medium_min_evidence"] == BUDGET_POLICY.medium_min_evidence


def test_changing_any_raise_policy_field_changes_the_stored_bytes() -> None:
    """Изменение любого поля обязано менять и байты снимка, и его отпечаток."""

    baseline = PricingPolicy(raise_policy=BUDGET_POLICY)
    baseline_hash = execution_policy_hash(policy_to_dict(baseline))
    for name in (item.name for item in fields(RaisePolicy)):
        current = getattr(BUDGET_POLICY, name)
        if isinstance(current, bool):
            mutated_value: object = not current
        elif isinstance(current, Decimal):
            mutated_value = current + Decimal("0.01")
        elif isinstance(current, int):
            mutated_value = current + 1
        elif isinstance(current, str) or current is None:
            mutated_value = f"p15017-{name}"
        else:
            mutated_value = current
        mutated = PricingPolicy(
            raise_policy=replace(BUDGET_POLICY, **{name: mutated_value})
        )
        assert execution_policy_hash(policy_to_dict(mutated)) != baseline_hash, name


def test_budget_floor_raises_to_high_end_of_customer_band() -> None:
    decision = _budget_decision("800")

    assert decision.outcome is RaiseOutcome.RAISE
    assert decision.fair_price == Decimal("1000")
    assert decision.target_band_low == Decimal("950.00")
    assert decision.target_band_high == Decimal("980.00")
    assert decision.recommended_price == Decimal("980")
    assert decision.is_actionable


def test_budget_floor_lowers_to_high_end_of_customer_band() -> None:
    decision = _budget_decision("1200")

    assert decision.outcome is RaiseOutcome.LOWER
    assert decision.recommended_price == Decimal("980")
    assert decision.is_actionable


def test_engine_keeps_large_lowering_as_a_non_applying_operator_recommendation() -> None:
    offers = [
        _offer(index, price, tier=ProductTier.BUDGET)
        for index, price in enumerate(("1000", "1200", "1400", "1600", "1800"))
    ]

    result = _engine_result("3000", offers)

    assert result.action is RecommendationAction.LOWER
    assert result.recommended_price == Decimal("980")
    assert result.lower_bound == Decimal("950.00")
    assert result.upper_bound == Decimal("980.00")
    assert "FLOOR_RESTS_ON_ONE_SELLER" in result.reasons


def test_budget_floor_holds_price_already_inside_customer_band() -> None:
    decision = _budget_decision("970")

    assert decision.outcome is RaiseOutcome.TARGET_BAND
    assert decision.recommended_price is None
    assert decision.reasons[-1] == "PRICE_WITHIN_CUSTOMER_TARGET_BAND"


def test_budget_floor_does_not_suppress_a_small_move_into_the_customer_band() -> None:
    decision = _budget_decision("990")

    assert decision.outcome is RaiseOutcome.LOWER
    assert decision.recommended_price == Decimal("980")
    assert decision.target_band_low == Decimal("950.00")
    assert decision.target_band_high == Decimal("980.00")


@pytest.mark.parametrize(
    "stock_status",
    (
        StockStatus.FRESH,
        StockStatus.STALE,
        StockStatus.DEAD_STOCK,
        StockStatus.UNKNOWN,
    ),
)
def test_budget_floor_ignores_stock_and_cost_for_price_direction(
    stock_status: StockStatus,
) -> None:
    decision = _budget_decision(
        "1200",
        stock_status=stock_status,
        cost_floor="5000",
    )

    assert decision.outcome is RaiseOutcome.LOWER
    assert decision.recommended_price == Decimal("980")
    assert "RECOMMENDATION_BELOW_COST_FLOOR" not in decision.reasons
    assert "STOCK_AND_COST_IGNORED_BY_OWNER_POLICY" in decision.reasons


def test_budget_floor_abstains_when_rounding_cannot_stay_inside_band() -> None:
    decision = _budget_decision(
        "80",
        prices=("100", "110", "120"),
        policy=replace(BUDGET_POLICY, psychological_step=Decimal("10")),
    )

    assert decision.outcome is RaiseOutcome.SHOW_BUT_FLAG
    assert decision.recommended_price is None
    assert decision.target_band_low == Decimal("95.00")
    assert decision.target_band_high == Decimal("98.00")
    assert decision.reasons[-1] == "NO_PRICE_TICK_WITHIN_CUSTOMER_BAND"


def test_engine_ignores_brand_tier_and_coefficients_but_keeps_verified_matching() -> None:
    offers = [
        _offer(0, "1000", tier=ProductTier.UNKNOWN),
        _offer(1, "1200", tier=ProductTier.OEM),
        _offer(2, "1400", tier=ProductTier.OES),
        _offer(3, "1600", tier=ProductTier.AFTERMARKET_A),
        _offer(4, "1800", tier=ProductTier.BUDGET),
    ]

    result = _engine_result("800", offers)

    assert result.action is RecommendationAction.RAISE
    assert result.recommended_price == Decimal("980")
    assert result.fair_price == Decimal("1000")
    assert result.lower_bound == Decimal("950.00")
    assert result.upper_bound == Decimal("980.00")
    assert result.outlier_method == "owner_minimum_raw"
    assert len(result.outlier_method) <= 24
    assert not {
        "UNKNOWN_TIER",
        "LOW_TIER_CONFIDENCE",
        "UNVALIDATED_TIER_COEFFICIENT",
    } & set(result.reasons)
    assert all(
        offer.coefficient_version == "owner-tier-agnostic-v1"
        for offer in result.evidence
    )


def test_engine_uses_cheapest_original_when_only_original_offers_exist() -> None:
    offers = [
        _offer(index, price, tier=ProductTier.OEM)
        for index, price in enumerate(("1000", "1100", "1200", "1300", "1400"))
    ]

    result = _engine_result("800", offers)

    assert result.action is RecommendationAction.RAISE
    assert result.recommended_price == Decimal("980")
    assert result.fair_price == Decimal("1000")


def test_engine_preserves_verified_cheapest_offer_instead_of_outlier_filtering() -> None:
    """No offer is filtered out — but a cut off a lone floor is not automatic.

    500 against a cohort at 1000–1030 is both shapes at once: a shop clearing
    stock, and a number belonging to another part.  Price alone cannot tell them
    apart, so the offer keeps its place as the floor and the position is put in
    front of the customer instead of cutting a live price by a fifth on it.
    """

    offers = [
        _offer(index, price, tier=ProductTier.BUDGET)
        for index, price in enumerate(("500", "1000", "1010", "1020", "1030"))
    ]

    result = _engine_result("600", offers)

    assert result.action is RecommendationAction.MANUAL_REVIEW
    assert "CUT_FROM_ISOLATED_FLOOR" in result.reasons
    # The point of the original test still holds: nothing was cleaned away, and
    # the cheapest verified offer is still what the target was measured from.
    assert result.outlier_count == 0
    assert result.fair_price == Decimal("500")
    assert len(result.evidence) == 5


def test_engine_and_advisory_use_the_same_plausible_minimum() -> None:
    offers = [
        _offer(index, price, tier=ProductTier.BUDGET)
        for index, price in enumerate(("1", "1200", "1300", "1400", "1500"))
    ]

    measured_floor_policy = replace(
        BUDGET_POLICY,
        target_floor_ratio=Decimal("0.35"),
    )
    result = recommend_price(
        ProductPricingContext(
            sku="OWNER-BUDGET-1",
            category="brakes",
            current_price=Decimal("1000"),
            stock_status=StockStatus.DEAD_STOCK,
            cost=Decimal("5000"),
            stock_age_days=Decimal("999"),
        ),
        offers,
        {},
        policy=PricingPolicy(
            version="pricing-v2",
            raise_policy=measured_floor_policy,
        ),
    )
    policy_trace, advisory = customer_budget_floor_trace(
        policy=measured_floor_policy,
        result=result,
        comparability_activation_verified=False,
    )

    assert result.action is RecommendationAction.RAISE
    assert result.recommended_price == Decimal("1176")
    assert result.fair_price == Decimal("1200")
    assert result.lower_bound == Decimal("1140.00")
    assert result.upper_bound == Decimal("1176.00")
    assert "IMPLAUSIBLE_EXCLUDED_FROM_TARGET" in result.reasons
    assert policy_trace is not None
    assert policy_trace["excluded_implausible_count"] == 1
    assert policy_trace["plausibility_floor"] == "350.00"
    assert advisory is not None
    assert advisory["minimum_comparable_price"] == "1200"
    assert advisory["target_band_low"] == "1140.00"
    assert advisory["target_band_high"] == "1176.00"


def test_engine_surfaces_an_all_placeholder_market_without_a_price_target() -> None:
    offers = [
        _offer(index, price, tier=ProductTier.BUDGET)
        for index, price in enumerate(("1", "2", "3", "4", "5"))
    ]

    measured_floor_policy = replace(
        BUDGET_POLICY,
        target_floor_ratio=Decimal("0.35"),
    )
    result = recommend_price(
        ProductPricingContext(
            sku="OWNER-BUDGET-1",
            category="brakes",
            current_price=Decimal("1000"),
            stock_status=StockStatus.DEAD_STOCK,
            cost=Decimal("5000"),
            stock_age_days=Decimal("999"),
        ),
        offers,
        {},
        policy=PricingPolicy(
            version="pricing-v2",
            raise_policy=measured_floor_policy,
        ),
    )
    policy_trace, advisory = customer_budget_floor_trace(
        policy=measured_floor_policy,
        result=result,
        comparability_activation_verified=False,
    )

    assert result.action is RecommendationAction.MANUAL_REVIEW
    assert result.recommended_price is None
    assert result.fair_price is None
    assert "ALL_EVIDENCE_BELOW_PLAUSIBILITY_FLOOR" in result.reasons
    assert policy_trace is not None
    assert policy_trace["excluded_implausible_count"] == 5
    assert advisory is None


def test_engine_still_rejects_used_offer_before_selecting_minimum() -> None:
    offers = [
        _offer(0, "100", tier=ProductTier.USED, is_used=True),
        *[
            _offer(index, price, tier=ProductTier.OEM)
            for index, price in enumerate(
                ("1000", "1010", "1020", "1030"),
                start=1,
            )
        ],
    ]

    result = _engine_result("800", offers)

    assert result.action is RecommendationAction.RAISE
    assert result.recommended_price == Decimal("980")
    assert any(item.reason == "USED_OR_REFURBISHED" for item in result.excluded)


def test_gated_automatic_result_becomes_explicit_non_applying_advisory() -> None:
    offers = [
        _offer(index, price, tier=ProductTier.UNKNOWN)
        for index, price in enumerate(("1000", "1100", "1200", "1300", "1400"))
    ]
    result = _engine_result("800", offers)

    policy_trace, advisory = customer_budget_floor_trace(
        policy=BUDGET_POLICY,
        result=result,
        comparability_activation_verified=False,
    )

    assert policy_trace is not None
    assert policy_trace["market_basis"] == "minimum_verified_comparable_price"
    assert policy_trace["brand_tier_handling"] == "ignored_for_price"
    assert policy_trace["stock_status_handling"] == "ignored_for_price"
    assert policy_trace["procurement_basis_handling"] == "ignored_for_price"
    assert policy_trace["automatic_price_application"] is False
    assert (
        privacy_safe_mapping({"customer_pricing_policy": policy_trace})[
            "customer_pricing_policy"
        ]["procurement_basis_handling"]
        == "ignored_for_price"
    )
    assert advisory == {
        "status": "COMPARABILITY_REVIEW_REQUIRED",
        "action": "RAISE",
        "current_price": "800",
        "recommended_price": "980",
        "absolute_change": "180",
        "percentage_change": "0.225",
        "minimum_comparable_price": "1000",
        "target_band_low": "950.00",
        "target_band_high": "980.00",
        "automatic_price_application": False,
        "reason": "COMPARABILITY_AUTOMATIC_ACTIVATION_BLOCKED",
    }


def test_verified_release_has_normal_result_without_duplicate_advisory() -> None:
    offers = [
        _offer(index, price, tier=ProductTier.OEM)
        for index, price in enumerate(("1000", "1100", "1200", "1300", "1400"))
    ]
    result = _engine_result("1200", offers)

    policy_trace, advisory = customer_budget_floor_trace(
        policy=BUDGET_POLICY,
        result=result,
        comparability_activation_verified=True,
    )

    assert policy_trace is not None
    assert advisory is None


def test_comparability_gate_keeps_advisory_math_but_blocks_auto_action() -> None:
    offers = [
        _offer(index, price, tier=ProductTier.UNKNOWN)
        for index, price in enumerate(("1000", "1100", "1200", "1300", "1400"))
    ]
    automatic = _engine_result("800", offers)
    gated = apply_comparability_activation_gate(
        automatic,
        activation_verified=False,
    )

    assert automatic.action is RecommendationAction.RAISE
    assert automatic.recommended_price == Decimal("980")
    assert gated.action is RecommendationAction.MANUAL_REVIEW
    assert gated.recommended_price is None
    assert not gated.automatic_eligible
    assert "COMPARABILITY_AUTOMATIC_ACTIVATION_BLOCKED" in gated.reasons
