"""Owner-approved fixed-five-percent budget-floor pricing contract."""

from __future__ import annotations

from dataclasses import fields, replace
from decimal import Decimal
from pathlib import Path

import pytest

from metis.pricing import (
    CohortRole,
    CompetitorOffer,
    ExcludedOffer,
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
from marko.core.config import Settings
from marko.services.market_collection import (
    apply_comparability_activation_gate,
    customer_budget_floor_trace,
    resolve_comparability_activation,
)
from marko.services.cost_privacy import privacy_safe_mapping
from marko.services.pricing_runs import (
    _raise_policy_from_snapshot,
    execution_policy_hash,
    policy_to_dict,
)


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
    *,
    seller_groups: dict[str, str] | None = None,
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
        seller_groups=seller_groups,
    )


def test_active_strategy_is_owner_approved_budget_floor() -> None:
    assert BUDGET_POLICY.strategy is RaiseStrategy.BUDGET_FLOOR
    assert BUDGET_POLICY.minimum_discount == Decimal("0.05")
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
    assert (
        persisted["owner_decision_reference"]
        == "customer-reply-2026-08-12-fixed-five-percent"
    )
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
    assert decision.target_band_high == Decimal("950.00")
    assert decision.recommended_price == Decimal("950")
    assert decision.is_actionable


def test_budget_floor_lowers_to_high_end_of_customer_band() -> None:
    decision = _budget_decision("1200")

    assert decision.outcome is RaiseOutcome.LOWER
    assert decision.recommended_price == Decimal("950")
    assert decision.is_actionable


def test_engine_keeps_large_lowering_as_a_non_applying_operator_recommendation() -> (
    None
):
    offers = [
        _offer(index, price, tier=ProductTier.BUDGET)
        for index, price in enumerate(("1000", "1200", "1400", "1600", "1800"))
    ]

    result = _engine_result("3000", offers)

    assert result.action is RecommendationAction.LOWER
    assert result.recommended_price == Decimal("950")
    assert result.lower_bound == Decimal("950.00")
    assert result.upper_bound == Decimal("950.00")
    assert "FLOOR_RESTS_ON_ONE_SELLER" in result.reasons


def test_related_sellers_do_not_corroborate_the_floor() -> None:
    # Два магазина одной сферы по 300 выглядят как подтверждённый минимум,
    # но независимого подтверждения здесь нет: вторая цена — тот же продавец.
    decision = decide_raise(
        current_price=Decimal("700"),
        prices=[Decimal("300"), Decimal("300"), Decimal("1200")],
        stock_status=StockStatus.FRESH,
        policy=BUDGET_POLICY,
        sellers=["seller-a", "seller-b", "seller-c"],
        seller_groups={"seller-b": "seller-a"},
    )

    assert "FLOOR_RESTS_ON_ONE_SELLER" in decision.flags
    assert "FLOOR_CORROBORATION_BY_RELATED_SELLERS" in decision.flags
    # Цель не сдвинулась: тот же минимум, та же формула.
    assert decision.fair_price == Decimal("300")
    # Понижение на одинокий оторванный минимум уходит на проверку.
    assert decision.outcome is RaiseOutcome.SHOW_BUT_FLAG
    assert "FLOOR_MATERIALLY_BELOW_NEXT_SELLER" in decision.reasons


def test_independent_sellers_still_corroborate_the_floor() -> None:
    decision = decide_raise(
        current_price=Decimal("700"),
        prices=[Decimal("300"), Decimal("300"), Decimal("1200")],
        stock_status=StockStatus.FRESH,
        policy=BUDGET_POLICY,
        sellers=["seller-a", "seller-b", "seller-c"],
        seller_groups={"seller-x": "seller-y"},
    )

    assert "FLOOR_RESTS_ON_ONE_SELLER" not in decision.flags
    assert "FLOOR_CORROBORATION_BY_RELATED_SELLERS" not in decision.flags
    assert decision.outcome is RaiseOutcome.LOWER
    assert decision.recommended_price == Decimal("285")


def test_engine_collapses_related_sellers_for_floor_corroboration() -> None:
    offers = [
        _offer(0, "300", tier=ProductTier.BUDGET),
        _offer(1, "300", tier=ProductTier.BUDGET),
        _offer(2, "1200", tier=ProductTier.BUDGET),
    ]

    result = _engine_result(
        "700",
        offers,
        seller_groups={"seller-1": "seller-0"},
    )

    assert "FLOOR_CORROBORATION_BY_RELATED_SELLERS" in result.reasons
    assert "FLOOR_RESTS_ON_ONE_SELLER" in result.reasons


def test_the_per_strategy_seller_counts_survive_a_run_snapshot() -> None:
    # ``min_evidence`` and ``medium_min_evidence`` are now per-strategy entries
    # in the yaml.  A run freezes its policy and reads it back through the
    # snapshot, so a key the loader accepts but the snapshot drops would leave
    # the run silently pricing under the shipped defaults instead.
    stored = policy_to_dict(replace(PricingPolicy(), raise_policy=BUDGET_POLICY))
    restored = _raise_policy_from_snapshot(stored["raise_policy"])

    assert restored == BUDGET_POLICY
    assert restored.strategy is RaiseStrategy.BUDGET_FLOOR
    assert restored.min_evidence == 2
    assert restored.medium_min_evidence == 2
    assert restored.tier_agnostic is True


def test_two_independent_sellers_are_enough_to_reach_a_number() -> None:
    # The owner's floor is two independent sellers.  Every count threshold in
    # the chain -- cohort admission, post-cleaning, action gating and the
    # effective-sample guard -- has to agree, or the run produces a cohort and
    # still refuses to name a price.
    offers = [
        _offer(0, "1000", tier=ProductTier.BUDGET),
        _offer(1, "1000", tier=ProductTier.BUDGET),
    ]

    result = _engine_result("2000", offers)

    assert result.unique_seller_count == 2
    assert result.action_gates_passed
    assert result.recommended_price == Decimal("950")
    assert "TOO_FEW_COMPETITORS" not in result.reasons
    assert "LOW_EFFECTIVE_SAMPLE_SIZE" not in result.reasons


def test_a_lone_floor_is_recorded_even_when_the_cut_still_applies() -> None:
    # The target is the cheapest of the two, and only one seller stands at it.
    # That fact is always reported; on its own it does not withhold the price,
    # because the prices are close enough that the floor is not suspicious.
    offers = [
        _offer(0, "1000", tier=ProductTier.BUDGET),
        _offer(1, "1200", tier=ProductTier.BUDGET),
    ]

    result = _engine_result("2000", offers)

    assert result.recommended_price == Decimal("950")
    assert "FLOOR_RESTS_ON_ONE_SELLER" in result.reasons


def test_a_lone_floor_far_below_the_next_seller_is_held_back() -> None:
    # Same two-seller cohort, but 200 against 1400 is not a market price until
    # somebody confirms it.
    offers = [
        _offer(0, "200", tier=ProductTier.BUDGET),
        _offer(1, "1400", tier=ProductTier.BUDGET),
    ]

    result = _engine_result("1000", offers)

    assert result.recommended_price is None
    assert "FLOOR_RESTS_ON_ONE_SELLER" in result.reasons


def test_a_single_seller_is_still_not_a_market() -> None:
    result = _engine_result("2000", [_offer(0, "1000", tier=ProductTier.BUDGET)])

    assert result.recommended_price is None
    assert "TOO_FEW_COMPETITORS" in result.reasons


def test_a_tier_priced_policy_keeps_its_own_cohort_floor() -> None:
    # Only the owner's budget-floor strategy names its cohort size; the
    # statistical strategies keep the three they were calibrated against.
    offers = [
        _offer(0, "1000", tier=ProductTier.BUDGET),
        _offer(1, "1200", tier=ProductTier.BUDGET),
    ]

    result = recommend_price(
        ProductPricingContext(
            sku="OWNER-BUDGET-1",
            category="brakes",
            current_price=Decimal("2000"),
        ),
        offers,
        {},
        policy=PricingPolicy(
            version="pricing-v2",
            raise_policy=replace(BUDGET_POLICY, strategy=RaiseStrategy.BALANCED),
        ),
    )

    assert result.recommended_price is None
    assert "TOO_FEW_COMPETITORS" in result.reasons


def test_budget_floor_holds_price_already_inside_customer_band() -> None:
    decision = _budget_decision("950")

    assert decision.outcome is RaiseOutcome.TARGET_BAND
    assert decision.recommended_price is None
    assert decision.reasons[-1] == "PRICE_WITHIN_CUSTOMER_TARGET_BAND"


def test_budget_floor_does_not_suppress_a_small_move_into_the_customer_band() -> None:
    decision = _budget_decision("990")

    assert decision.outcome is RaiseOutcome.LOWER
    assert decision.recommended_price == Decimal("950")
    assert decision.target_band_low == Decimal("950.00")
    assert decision.target_band_high == Decimal("950.00")


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
    assert decision.recommended_price == Decimal("950")
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
    assert decision.target_band_high == Decimal("95.00")
    assert decision.reasons[-1] == "NO_PRICE_TICK_WITHIN_CUSTOMER_BAND"


def test_engine_ignores_brand_tier_and_coefficients_but_keeps_verified_matching() -> (
    None
):
    offers = [
        _offer(0, "1000", tier=ProductTier.UNKNOWN),
        _offer(1, "1200", tier=ProductTier.OEM),
        _offer(2, "1400", tier=ProductTier.OES),
        _offer(3, "1600", tier=ProductTier.AFTERMARKET_A),
        _offer(4, "1800", tier=ProductTier.BUDGET),
    ]

    result = _engine_result("800", offers)

    assert result.action is RecommendationAction.RAISE
    assert result.recommended_price == Decimal("950")
    assert result.fair_price == Decimal("1000")
    assert result.lower_bound == Decimal("950.00")
    assert result.upper_bound == Decimal("950.00")
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
    assert result.recommended_price == Decimal("950")
    assert result.fair_price == Decimal("1000")


def test_engine_preserves_verified_cheapest_offer_instead_of_outlier_filtering() -> (
    None
):
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
    assert "FLOOR_MATERIALLY_BELOW_NEXT_SELLER" in result.reasons
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
    assert result.recommended_price == Decimal("1140")
    assert result.fair_price == Decimal("1200")
    assert result.lower_bound == Decimal("1140.00")
    assert result.upper_bound == Decimal("1140.00")
    assert "IMPLAUSIBLE_EXCLUDED_FROM_TARGET" in result.reasons
    assert policy_trace is not None
    assert policy_trace["excluded_implausible_count"] == 1
    assert policy_trace["plausibility_floor"] == "350.00"
    assert advisory is not None
    assert advisory["minimum_comparable_price"] == "1200"
    assert advisory["target_band_low"] == "1140.00"
    assert advisory["target_band_high"] == "1140.00"


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
    assert result.recommended_price == Decimal("950")
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
        "recommended_price": "950",
        "absolute_change": "150",
        "percentage_change": "0.1875",
        "minimum_comparable_price": "1000",
        "target_band_low": "950.00",
        "target_band_high": "950.00",
        "automatic_price_application": False,
        "operator_cost_warning": (
            "Before accepting the recommendation, account for procurement, "
            "Prom commission, payment fees, taxes, packaging, delivery, returns, "
            "warranty, and the minimum acceptable margin. These expenses do not "
            "change the competitor-minus-5-percent formula automatically."
        ),
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


def test_no_cohort_visible_offers_yield_incomplete_evidence_advisory() -> None:
    """Canary path: 7 raw offers, zero admitted, operator still sees min − 5%."""

    result = _engine_result("679", [])
    result = replace(
        result,
        action=RecommendationAction.INSUFFICIENT_DATA,
        recommended_price=None,
        fair_price=None,
        lower_bound=None,
        upper_bound=None,
        automatic_eligible=False,
        reasons=("TOO_FEW_COMPETITORS",),
        evidence=(),
        excluded=(
            ExcludedOffer(
                observation_id="obs-used",
                reason="USED_OR_REFURBISHED",
                seller_id="seller-used",
                raw_price=Decimal("300"),
                cohort_role=CohortRole.USED_REJECTED,
            ),
            ExcludedOffer(
                observation_id="obs-hard",
                reason="PRICE_ON_REQUEST",
                seller_id="seller-hard",
                raw_price=Decimal("200"),
                cohort_role=CohortRole.HARD_REJECTED,
            ),
            ExcludedOffer(
                observation_id="obs-1",
                reason="MANUAL_MISSING_CONDITION",
                seller_id="seller-1",
                raw_price=Decimal("739"),
                cohort_role=CohortRole.MANUAL_REVIEW,
            ),
            ExcludedOffer(
                observation_id="obs-2",
                reason="SEMANTIC_PRICING_EVIDENCE_INCOMPLETE",
                seller_id="seller-2",
                raw_price=Decimal("850"),
                cohort_role=CohortRole.MANUAL_REVIEW,
            ),
            ExcludedOffer(
                observation_id="obs-3",
                reason="MANUAL_MISSING_PACKAGE_QUANTITY",
                seller_id="seller-3",
                raw_price=Decimal("910"),
                cohort_role=CohortRole.MANUAL_REVIEW,
            ),
        ),
        unknown_hard_fields=("condition", "package_quantity", "unit_basis"),
    )

    _policy_trace, advisory = customer_budget_floor_trace(
        policy=BUDGET_POLICY,
        result=result,
        comparability_activation_verified=False,
    )

    assert result.recommended_price is None
    assert advisory is not None
    assert advisory["status"] == "INCOMPLETE_EVIDENCE_REVIEW_REQUIRED"
    assert advisory["reason"] == "ADVISORY_FROM_UNVERIFIED_VISIBLE_OFFERS"
    assert advisory["automatic_price_application"] is False
    assert advisory["minimum_comparable_price"] == "739"
    assert advisory["recommended_price"] == "702"
    assert advisory["action"] == "RAISE"
    assert advisory["basis_offer_count"] == 3
    assert advisory["basis_independent_sellers"] == 3
    assert "condition" in advisory["missing_pricing_dimensions"]
    assert advisory["check_package_unit"] is True
    assert "operator_cost_warning" in advisory


def test_radiator_motor_visible_minimum_rounds_down_to_owner_formula() -> None:
    result = _engine_result("962", [])
    result = replace(
        result,
        action=RecommendationAction.INSUFFICIENT_DATA,
        recommended_price=None,
        automatic_eligible=False,
        reasons=("TOO_FEW_COMPETITORS",),
        evidence=(),
        excluded=(
            ExcludedOffer(
                observation_id="obs-rad",
                reason="MANUAL_MISSING_CONDITION",
                seller_id="seller-rad",
                raw_price=Decimal("1150"),
                cohort_role=CohortRole.MANUAL_REVIEW,
            ),
        ),
    )

    _policy_trace, advisory = customer_budget_floor_trace(
        policy=BUDGET_POLICY,
        result=result,
        comparability_activation_verified=False,
    )

    assert advisory is not None
    assert advisory["minimum_comparable_price"] == "1150"
    assert advisory["recommended_price"] == "1092"


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
    assert automatic.recommended_price == Decimal("950")
    assert gated.action is RecommendationAction.MANUAL_REVIEW
    assert gated.recommended_price is None
    assert not gated.automatic_eligible
    assert "COMPARABILITY_AUTOMATIC_ACTIVATION_BLOCKED" in gated.reasons


def _activation_settings(**overrides: object) -> Settings:
    return Settings(**{"environment": "test", **overrides})  # type: ignore[arg-type]


def test_owner_flag_opens_activation_outside_production() -> None:
    verified, basis = resolve_comparability_activation(
        _activation_settings(pricing_comparability_v1_automatic_enabled=True)
    )

    assert verified is True
    assert basis == "owner_flag"


def test_activation_stays_closed_without_the_owner_flag() -> None:
    verified, basis = resolve_comparability_activation(_activation_settings())

    assert verified is False
    assert basis == "closed"


@pytest.mark.parametrize("environment", ["production", "staging", "prodcution"])
def test_unrecognized_or_production_environment_still_demands_the_artifact(
    environment: str,
) -> None:
    # Anything outside the explicit dev set fails closed -- a typo'd
    # ENVIRONMENT must not open a release gate the config validator no
    # longer guards.
    verified, basis = resolve_comparability_activation(
        _activation_settings(
            environment=environment,
            firebase_project_id="marko-prod",
            allowed_hosts="marko.example.com",
            pricing_comparability_v1_automatic_enabled=True,
            pricing_comparability_activation_artifact="/nonexistent/artifact.json",
            pricing_comparability_activation_sha256="0" * 64,
        )
    )

    assert verified is False
    assert basis == "closed"


def test_a_configured_artifact_is_validated_even_in_dev(tmp_path: Path) -> None:
    # Setting the artifact fields in a dev environment opts back into the
    # production contract: a broken artifact closes the gate instead of
    # being ignored in favour of the flag.
    broken = tmp_path / "activation.json"
    broken.write_text("{}", encoding="utf-8")
    verified, basis = resolve_comparability_activation(
        _activation_settings(
            pricing_comparability_v1_automatic_enabled=True,
            pricing_comparability_activation_artifact=str(broken),
            pricing_comparability_activation_sha256="0" * 64,
        )
    )

    assert verified is False
    assert basis == "closed"
