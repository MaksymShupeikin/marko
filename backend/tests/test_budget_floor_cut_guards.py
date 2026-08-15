"""A cut off a lone floor is escalated; the owner's target is never moved.

The budget-floor strategy takes the cheapest comparable offer as the target, and
that is the owner's instruction, not an approximation of it. The minimum has a
breakdown point of zero, though, so the question these guards answer is not
"which price should we use" — it is "may this one act by itself".

Two things are deliberately kept apart:

* the *target* stays the literal cheapest offer in every case here.  A guard
  that quietly moved it to the second-cheapest would make us the second-cheapest
  shop by construction, which is the opposite of what was asked for;
* the *action* may be withheld.  A cut is realised on the first sale and cannot
  be taken back, and its known cause is one cheap offer that is not this part.

Depth is not the discriminator, and that is the point worth guarding: our own
price at 2747 against a tight cohort at 1200–1400 needs a 57% cut and that cut
is correct.  Isolation within the cohort is what separates it from the same 57%
driven by a lone 200 among the same 1200–1400.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from metis.pricing.raise_policy import (
    FLAG_FLOOR_CORROBORATION_UNAVAILABLE,
    RaiseConfidence,
    FLAG_FLOOR_RESTS_ON_ONE_SELLER,
    RaiseOutcome,
    RaisePolicyConfigError,
    RaisePolicyInputError,
    build_basis,
    corroborated_floor,
    decide_raise,
    load_raise_policy,
)
from metis.pricing.types import StockStatus

BACKEND_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = BACKEND_ROOT / "config" / "raise_policy.yaml"
SHIPPED = load_raise_policy(POLICY_PATH, strategy="budget_floor")


def _decide(prices, current, *, sellers=None, policy=None):
    return decide_raise(
        current_price=Decimal(str(current)),
        prices=[Decimal(str(price)) for price in prices],
        stock_status=StockStatus.FRESH,
        policy=policy or SHIPPED,
        sellers=sellers,
    )


# --------------------------------------------------------- the cut escalation


def test_a_cut_driven_by_an_isolated_floor_is_not_emitted() -> None:
    decision = _decide([200, 1200, 1300, 1400], current=1000)

    assert decision.outcome is RaiseOutcome.SHOW_BUT_FLAG
    assert decision.recommended_price is None
    assert "FLOOR_MATERIALLY_BELOW_NEXT_SELLER" in decision.reasons


def test_the_escalated_position_still_carries_the_floor_and_the_band() -> None:
    """Withholding the number must not withhold the reasoning behind it."""

    decision = _decide([200, 1200, 1300, 1400], current=1000)

    assert decision.fair_price == Decimal("200")
    assert decision.target_band_low == Decimal("190.00")
    assert decision.target_band_high == Decimal("190.00")
    assert decision.basis is not None and decision.basis.count == 4


def test_a_deep_cut_from_a_tight_cohort_is_still_emitted() -> None:
    """57% down is correct when the whole market agrees, and depth is not a fault."""

    decision = _decide([1200, 1300, 1400], current=2747)

    assert decision.outcome is RaiseOutcome.LOWER
    assert decision.recommended_price == Decimal("1140")


def test_a_raise_is_never_withheld_by_isolation() -> None:
    """Reaching the floor is the whole strategy; an over-raise self-corrects."""

    decision = _decide([200, 1200, 1300, 1400], current=100)

    assert decision.outcome is RaiseOutcome.RAISE
    assert decision.recommended_price == Decimal("190")


def test_isolation_is_not_judged_without_a_cohort_to_be_isolated_from() -> None:
    """Two offers have no interquartile shape; the shipped min_evidence is three."""

    decision = _decide([200, 1400], current=1000)

    assert decision.outcome is RaiseOutcome.NO_DATA
    assert "TOO_FEW_PRICING_EVIDENCE" in decision.reasons


def test_our_own_price_does_not_enter_the_isolation_test() -> None:
    """The same cohort behaves the same way whatever we happen to charge.

    A guard keyed on our own price would be circular in the direction this
    project has refused all along: our price deciding which competitor prices
    count, in order to then compare against them.
    """

    for current in (1200, 5000, 20000):
        decision = _decide([1200, 1300, 1400], current=current)
        assert decision.outcome is RaiseOutcome.LOWER
        assert decision.recommended_price == Decimal("1140")


# ------------------------------------------------- the corroboration reporting


def test_a_floor_standing_on_one_seller_is_reported_but_still_used() -> None:
    decision = _decide(
        [200, 1200, 1300, 1400],
        current=100,
        sellers=["a", "b", "c", "d"],
    )

    assert FLAG_FLOOR_RESTS_ON_ONE_SELLER in decision.flags
    # The owner's rule is untouched: the target is still measured from the 200.
    assert decision.fair_price == Decimal("200")
    assert decision.recommended_price == Decimal("190")


def test_a_second_seller_at_the_floor_clears_the_flag() -> None:
    decision = _decide(
        [1200, 1200, 1300, 1400],
        current=1000,
        sellers=["a", "b", "c", "d"],
    )

    assert FLAG_FLOOR_RESTS_ON_ONE_SELLER not in decision.flags
    assert decision.outcome is RaiseOutcome.RAISE


def test_one_seller_listing_the_same_part_twice_is_not_two_sellers() -> None:
    decision = _decide(
        [1200, 1200, 1300, 1400],
        current=1000,
        sellers=["a", "a", "b", "c"],
    )

    assert FLAG_FLOOR_RESTS_ON_ONE_SELLER in decision.flags


def test_a_caller_without_seller_identity_says_so_instead_of_passing() -> None:
    decision = _decide([1200, 1300, 1400], current=1000)

    assert FLAG_FLOOR_CORROBORATION_UNAVAILABLE in decision.flags
    assert FLAG_FLOOR_RESTS_ON_ONE_SELLER not in decision.flags


def test_mismatched_seller_and_price_lengths_are_refused() -> None:
    decision = _decide([1200, 1300, 1400], current=1000, sellers=["a", "b"])

    assert decision.outcome is RaiseOutcome.NO_DATA
    assert "SELLER_COUNT_MISMATCH" in decision.reasons


# ------------------------------------------------------------ the helper itself


def test_corroborated_floor_returns_the_price_the_second_seller_meets() -> None:
    pairs = (
        (Decimal("100"), "a"),
        (Decimal("110"), "a"),
        (Decimal("200"), "b"),
    )

    assert corroborated_floor(pairs, required_sellers=1) == Decimal("100")
    assert corroborated_floor(pairs, required_sellers=2) == Decimal("200")
    assert corroborated_floor(pairs, required_sellers=3) is None


def test_an_unknown_seller_cannot_corroborate_but_keeps_its_place() -> None:
    pairs = ((Decimal("100"), None), (Decimal("200"), "b"))

    assert corroborated_floor(pairs, required_sellers=1) == Decimal("200")


def test_corroboration_requirement_must_be_positive() -> None:
    with pytest.raises(ValueError):
        corroborated_floor(((Decimal("100"), "a"),), required_sellers=0)


def test_the_basis_keeps_sellers_attached_to_their_own_price() -> None:
    basis = build_basis(
        [Decimal("300"), Decimal("100"), Decimal("200")],
        sellers=["c", "a", "b"],
    )

    assert basis is not None
    assert basis.prices == (Decimal("100"), Decimal("200"), Decimal("300"))
    assert basis.sellers == ("a", "b", "c")
    assert basis.distinct_seller_count == 3


def test_a_basis_without_sellers_reports_no_count_rather_than_zero() -> None:
    basis = build_basis([Decimal("100")])

    assert basis is not None
    assert basis.sellers is None
    assert basis.distinct_seller_count is None
    assert basis.as_dict()["distinct_seller_count"] is None


def test_a_seller_length_mismatch_is_a_typed_input_error() -> None:
    with pytest.raises(RaisePolicyInputError):
        build_basis([Decimal("100"), Decimal("200")], sellers=["a"])


# ------------------------------------------------------------------ the config


def test_budget_floor_must_state_its_corroboration_requirement() -> None:
    """A value that arrives by omission is nobody's decision."""

    source = POLICY_PATH.read_text(encoding="utf-8")
    stripped = source.replace("    floor_corroboration_sellers: 1\n", "")
    assert stripped != source
    path = BACKEND_ROOT / "tests" / "_tmp_policy_without_corroboration.yaml"
    path.write_text(stripped, encoding="utf-8")
    try:
        with pytest.raises(RaisePolicyConfigError, match="floor_corroboration_sellers"):
            load_raise_policy(path, strategy="budget_floor")
    finally:
        path.unlink()


def test_the_shipped_policy_takes_the_literal_minimum() -> None:
    """Recorded so a change of the owner's rule cannot pass unnoticed."""

    assert SHIPPED.floor_corroboration_sellers == 1


def test_raising_the_requirement_moves_the_target_off_the_minimum() -> None:
    """The mechanism the owner would be opting into, exercised without shipping it."""

    decision = _decide(
        [1000, 1200, 1400],
        current=700,
        sellers=["a", "b", "c"],
        policy=replace(SHIPPED, floor_corroboration_sellers=2),
    )

    assert decision.fair_price == Decimal("1200")
    assert decision.outcome is RaiseOutcome.RAISE


def test_a_market_too_small_for_the_required_corroboration_is_escalated() -> None:
    decision = _decide(
        [1000, 1200, 1400],
        current=700,
        sellers=["a", "a", "a"],
        policy=replace(SHIPPED, floor_corroboration_sellers=2),
    )

    assert decision.outcome is RaiseOutcome.SHOW_BUT_FLAG
    assert "FLOOR_NOT_CORROBORATED_AS_REQUIRED" in decision.reasons


# ------------------------------------------- agreement, not just count (31.07)


def test_spread_does_not_replace_the_literal_valid_floor() -> None:
    """The fixed-floor rule does not use a dispersion statistic.

    The explicit commercial-integrity and lone-floor gates decide whether the
    cheapest card is valid; later expensive cards do not move that valid floor.
    """

    spread = [1087, 1132, 1183, 1400, 2000, 2250, 2500, 2594, 2625, 2747, 12968]

    decision = _decide(spread, current=5163, sellers=[f"s{i}" for i in range(11)])

    assert decision.outcome is RaiseOutcome.LOWER
    assert "LOW_CONFIDENCE_BASIS" not in decision.reasons
    assert decision.recommended_price == Decimal("1032")


def test_the_exact_five_percent_target_is_still_shown() -> None:
    spread = [1087, 1132, 1183, 1400, 2000, 2250, 2500, 2594, 2625, 2747, 12968]

    decision = _decide(spread, current=5163, sellers=[f"s{i}" for i in range(11)])

    assert decision.fair_price == Decimal("1087")
    assert decision.target_band_low == Decimal("1032.65")
    assert decision.target_band_high == Decimal("1032.65")
    assert decision.basis is not None and decision.basis.count == 11


def test_a_deep_cut_from_a_cohort_that_agrees_is_still_emitted() -> None:
    """Depth is not the fault, and this is the case that proves it.

    Five offers between 1577 and 1969 while we ask 4942: the market agrees with
    itself and we are the outlier. -69% is the right answer and it goes out.
    """

    decision = _decide(
        [1577, 1610, 1829, 1900, 1969],
        current=4942,
        sellers=["a", "b", "c", "d", "e"],
    )

    assert decision.outcome is RaiseOutcome.LOWER
    assert decision.recommended_price == Decimal("1498")


def test_a_raise_uses_the_valid_floor_without_dispersion_statistics() -> None:
    decision = _decide(
        [3028, 3500, 4189, 5000, 6000, 12312],
        current=2714,
        sellers=[f"s{i}" for i in range(6)],
    )

    assert decision.outcome is RaiseOutcome.RAISE
    assert "LOW_CONFIDENCE_BASIS" not in decision.reasons
    assert decision.recommended_price == Decimal("2876")


def test_the_grade_uses_the_shipped_thresholds_and_invents_none() -> None:
    """No new number was introduced; these two are the owner's, already in use
    for confidence grading before this rule existed."""

    assert SHIPPED.high_max_robust_cv == Decimal("0.15")
    assert SHIPPED.medium_max_robust_cv == Decimal("0.35")


def test_count_grades_evidence_after_deterministic_offer_gates() -> None:
    many = [1000, 1100, 1200, 1300, 1400, 9000, 10000, 11000]

    decision = _decide(many, current=5000, sellers=[f"s{i}" for i in range(8)])

    assert decision.confidence is RaiseConfidence.HIGH
    assert decision.outcome is RaiseOutcome.LOWER
    assert decision.recommended_price == Decimal("950")
