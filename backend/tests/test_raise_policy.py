"""Variation suite for the raise decision: typical, boundary and degenerate."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from metis.pricing.raise_policy import (
    FLAG_BELOW_COST_FLOOR,
    FLAG_ROUNDED_BELOW_SIGNIFICANCE,
    FLAG_STALE_CAPPED_AT_CHEAPEST,
    FLAG_STEP_CAPPED,
    RaiseConfidence,
    RaiseOutcome,
    RaisePolicyConfigError,
    RaiseStrategy,
    build_basis,
    decide_raise,
    grade_confidence,
    load_raise_policy,
)
from metis.pricing.types import StockStatus


BACKEND_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = BACKEND_ROOT / "config" / "raise_policy.yaml"
# The legacy arithmetic suite exercises the still-supported balanced strategy.
# The deployment default is tested separately because the owner's active
# decision intentionally changed it to the tier-agnostic budget-floor strategy.
POLICY = load_raise_policy(POLICY_PATH, strategy="balanced")
DEPLOYMENT_POLICY = load_raise_policy(POLICY_PATH)


def _decide(prices, current="1800", stock=StockStatus.FRESH, policy=None, cost=None):
    return decide_raise(
        current_price=Decimal(current),
        prices=[Decimal(str(price)) for price in prices],
        stock_status=stock,
        policy=policy or POLICY,
        cost_floor=None if cost is None else Decimal(cost),
    )


# ------------------------------------------------------------ verified example


def test_verified_example_reproduces_the_documented_arithmetic() -> None:
    """The worked example from the specification, digit for digit.

    It is deliberately on the boundary: n = 4 would allow HIGH, but the spread
    is 0.1516, just above 0.15, so the grade must fall to MEDIUM.
    """

    basis = build_basis([Decimal(x) for x in ("1650", "1720", "1940", "2100")])

    assert basis is not None
    assert basis.count == 4
    assert basis.p25 == Decimal("1702.5")
    assert basis.p50 == Decimal("1830.0")
    assert basis.p75 == Decimal("1980.0")
    assert basis.iqr == Decimal("277.5")
    assert basis.robust_cv.quantize(Decimal("0.0001")) == Decimal("0.1516")
    assert grade_confidence(basis, POLICY) is RaiseConfidence.MEDIUM


def test_verified_example_is_not_actionable_at_1800() -> None:
    """Fair 1830 against 1800 is +1.7%, under the 3% significance threshold."""

    decision = _decide(["1650", "1720", "1940", "2100"])

    assert decision.outcome is RaiseOutcome.INSIGNIFICANT
    assert decision.recommended_price is None
    assert decision.fair_price == Decimal("1830.0")
    assert decision.confidence is RaiseConfidence.MEDIUM


# ------------------------------------------------------------------- typical


def test_typical_cohort_produces_a_recommendation() -> None:
    decision = _decide(["1900", "2000", "2100", "2150", "2200"], current="1800")

    assert decision.outcome is RaiseOutcome.RAISE
    assert decision.recommended_price == Decimal("2100")
    assert decision.confidence is RaiseConfidence.HIGH
    assert decision.flags == ()


def test_recommendation_is_rounded_down_never_up() -> None:
    decision = _decide(["2007", "2008", "2009", "2010"], current="1800")

    assert decision.recommended_price == Decimal("2000")
    assert decision.recommended_price < decision.fair_price


def test_strategy_moves_the_target_point() -> None:
    prices = ["1900", "2000", "2100", "2150", "2200"]
    aggressive = load_raise_policy(POLICY_PATH, strategy="aggressive")
    premium = load_raise_policy(POLICY_PATH, strategy="premium")

    low = _decide(prices, current="1800", policy=aggressive)
    high = _decide(prices, current="1800", policy=premium)

    assert aggressive.strategy is RaiseStrategy.AGGRESSIVE
    assert low.fair_price < high.fair_price
    assert low.recommended_price is not None
    assert high.recommended_price is not None
    assert low.recommended_price < high.recommended_price


# ------------------------------------------------------------------ guardrails


def test_oversized_jump_is_capped_and_flagged() -> None:
    decision = _decide(["5000", "5200", "5400", "5600"], current="1000")

    assert decision.outcome is RaiseOutcome.RAISE
    assert decision.recommended_price == Decimal("1250")
    assert FLAG_STEP_CAPPED in decision.flags


def test_low_confidence_shows_the_arithmetic_without_a_recommendation() -> None:
    decision = _decide(["1000", "2000", "9000"], current="900")

    assert decision.outcome is RaiseOutcome.SHOW_BUT_FLAG
    assert decision.recommended_price is None
    assert decision.confidence is RaiseConfidence.LOW
    assert decision.basis is not None


def test_cost_floor_informs_but_never_moves_the_recommendation() -> None:
    decision = _decide(
        ["1900", "2000", "2100", "2150", "2200"], current="1800", cost="2500"
    )

    assert decision.outcome is RaiseOutcome.RAISE
    assert decision.recommended_price == Decimal("2100")
    assert FLAG_BELOW_COST_FLOOR in decision.flags


def test_rounding_that_erases_the_change_withholds_the_recommendation() -> None:
    """Only reachable on cheap goods, where one tick outweighs the threshold."""

    decision = _decide(["104", "104", "104", "104"], current="100")

    assert decision.outcome is RaiseOutcome.INSIGNIFICANT
    assert decision.reasons == ("ROUNDING_REMOVED_THE_CHANGE",)


def test_rounding_below_the_threshold_is_flagged_not_hidden() -> None:
    """Guards run in the specified order, so rounding may undercut step one."""

    decision = _decide(["1858", "1858", "1858", "1858"], current="1800")

    assert decision.outcome is RaiseOutcome.RAISE
    assert decision.recommended_price == Decimal("1850")
    assert FLAG_ROUNDED_BELOW_SIGNIFICANCE in decision.flags


def test_already_at_market_stays_silent() -> None:
    decision = _decide(["1500", "1600", "1700", "1750"], current="1800")

    assert decision.outcome is RaiseOutcome.ALREADY_COMPETITIVE
    assert decision.recommended_price is None


def test_never_recommends_a_cut_for_a_selling_item() -> None:
    decision = _decide(["500", "600", "700", "800"], current="1800")

    assert decision.recommended_price is None
    assert decision.outcome is not RaiseOutcome.RAISE


# ---------------------------------------------------------------------- stale


def test_stale_is_raised_only_when_it_is_the_cheapest_offer() -> None:
    decision = _decide(
        ["1900", "2000", "2100", "2150"], current="1800", stock=StockStatus.STALE
    )

    assert decision.outcome is RaiseOutcome.RAISE
    assert decision.recommended_price == Decimal("1900")
    assert FLAG_STALE_CAPPED_AT_CHEAPEST in decision.flags


def test_stale_that_is_not_the_cheapest_stays_silent() -> None:
    decision = _decide(
        ["1700", "2000", "2100", "2150"], current="1800", stock=StockStatus.STALE
    )

    assert decision.outcome is RaiseOutcome.STALE_NOT_CHEAPEST
    assert decision.recommended_price is None


def test_stale_boundary_equal_to_cheapest_is_not_cheaper() -> None:
    decision = _decide(
        ["1800", "2000", "2100", "2150"], current="1800", stock=StockStatus.STALE
    )

    assert decision.outcome is RaiseOutcome.STALE_NOT_CHEAPEST


def test_fresh_is_not_capped_at_the_cheapest_competitor() -> None:
    fresh = _decide(["1900", "2000", "2100", "2150"], current="1800")

    assert fresh.recommended_price == Decimal("2050")
    assert FLAG_STALE_CAPPED_AT_CHEAPEST not in fresh.flags


# ------------------------------------------------------------------- boundary


def test_three_prices_are_enough_and_two_are_not() -> None:
    assert _decide(["2000", "2100", "2200"], current="1800").outcome is (
        RaiseOutcome.RAISE
    )
    thin = _decide(["2000", "2100"], current="1800")
    assert thin.outcome is RaiseOutcome.NO_DATA
    assert thin.recommended_price is None


def test_empty_basis_is_no_data() -> None:
    decision = _decide([], current="1800")

    assert decision.outcome is RaiseOutcome.NO_DATA
    assert decision.basis is None


def test_single_competitor_is_no_data() -> None:
    assert _decide(["2000"], current="1800").outcome is RaiseOutcome.NO_DATA


@pytest.mark.parametrize(
    ("bad_price", "expected_code"),
    [
        ("-100", "NON_POSITIVE_PRICE"),
        ("0", "NON_POSITIVE_PRICE"),
        ("NaN", "NON_FINITE_PRICE"),
        ("Infinity", "NON_FINITE_PRICE"),
    ],
)
def test_public_raise_basis_rejects_invalid_market_evidence(
    bad_price: str,
    expected_code: str,
) -> None:
    with pytest.raises(ValueError) as captured:
        build_basis([Decimal(bad_price), Decimal("100"), Decimal("200")])

    assert getattr(captured.value, "code", None) == expected_code


def test_raise_decision_abstains_on_invalid_market_evidence() -> None:
    decision = _decide(["-100", "100", "200"], current="80")

    assert decision.outcome is RaiseOutcome.NO_DATA
    assert decision.recommended_price is None
    assert decision.reasons == ("NON_POSITIVE_PRICE",)


@pytest.mark.parametrize("current", ["0", "-1", "NaN", "Infinity"])
def test_raise_decision_abstains_on_invalid_current_price(current: str) -> None:
    decision = _decide(["100", "110", "120"], current=current)

    assert decision.outcome is RaiseOutcome.NO_DATA
    assert decision.recommended_price is None
    assert decision.reasons == ("INVALID_CURRENT_PRICE",)


@pytest.mark.parametrize(
    ("prices", "expected"),
    [
        # robust_CV exactly 0.15 must not be HIGH, exactly 0.35 must not be MEDIUM.
        (("700", "1000", "1000", "1300"), RaiseConfidence.MEDIUM),
        (("300", "1000", "1000", "1700"), RaiseConfidence.LOW),
    ],
)
def test_confidence_thresholds_are_strict(prices, expected) -> None:
    basis = build_basis([Decimal(price) for price in prices])

    assert basis is not None
    assert basis.robust_cv in {Decimal("0.15"), Decimal("0.35")}
    assert grade_confidence(basis, POLICY) is expected


def test_change_exactly_at_the_significance_threshold_is_actionable() -> None:
    decision = _decide(["1854", "1854", "1854", "1854"], current="1800")

    # The guard rejects a change strictly below the threshold, so exactly 3%
    # still acts.
    assert (Decimal("1854") - Decimal("1800")) / Decimal("1800") == Decimal("0.03")
    assert decision.outcome is RaiseOutcome.RAISE


# ----------------------------------------------------------------- degenerate


def test_identical_prices_are_perfect_agreement_not_a_division_by_zero() -> None:
    decision = _decide(["2000", "2000", "2000", "2000"], current="1800")

    assert decision.basis is not None
    assert decision.basis.iqr == Decimal("0")
    assert decision.basis.robust_cv == Decimal("0")
    assert decision.confidence is RaiseConfidence.HIGH
    assert decision.recommended_price == Decimal("2000")


def test_dead_stock_is_not_handled_here() -> None:
    """Liquidation stays in the clearance path; this module must not see it."""

    decision = _decide(
        ["1900", "2000", "2100", "2150"], current="1800", stock=StockStatus.DEAD_STOCK
    )

    # No stale-specific guard applies, so it behaves like any non-stale item.
    assert decision.outcome is RaiseOutcome.RAISE
    assert FLAG_STALE_CAPPED_AT_CHEAPEST not in decision.flags


# -------------------------------------------------------------------- config


def test_policy_file_defaults_to_customer_budget_floor() -> None:
    assert DEPLOYMENT_POLICY.strategy is RaiseStrategy.BUDGET_FLOOR
    assert DEPLOYMENT_POLICY.target_quantile == Decimal("0")
    assert DEPLOYMENT_POLICY.minimum_discount == Decimal("0.05")
    assert DEPLOYMENT_POLICY.maximum_discount == Decimal("0.05")
    assert DEPLOYMENT_POLICY.psychological_step == Decimal("1")
    assert DEPLOYMENT_POLICY.tier_agnostic
    assert DEPLOYMENT_POLICY.allow_lower
    assert DEPLOYMENT_POLICY.ignore_stock_status
    assert DEPLOYMENT_POLICY.ignore_cost_floor
    assert (
        DEPLOYMENT_POLICY.owner_decision_reference
        == "customer-reply-2026-08-12-fixed-five-percent"
    )
    assert DEPLOYMENT_POLICY.source_sha256 is not None


def test_unknown_strategy_is_rejected() -> None:
    with pytest.raises(RaisePolicyConfigError):
        load_raise_policy(POLICY_PATH, strategy="reckless")


def test_missing_policy_file_is_rejected(tmp_path) -> None:
    with pytest.raises(RaisePolicyConfigError):
        load_raise_policy(tmp_path / "absent.yaml")


def test_code_default_matches_explicit_balanced_fallback() -> None:
    """Callers without deployment config retain the conservative legacy preset."""

    from dataclasses import replace

    from metis.pricing.raise_policy import default_raise_policy

    shipped = replace(
        load_raise_policy(POLICY_PATH, strategy="balanced"),
        source_sha256=None,
    )

    assert shipped == default_raise_policy()
