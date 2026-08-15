"""A price that cannot be real must not set the target, and must stay visible.

Two different things were producing the same absurd recommendation, and only one
of them is a matching problem:

* a numeric collision puts an unrelated product in the basis — blue wire at 1.00
  against a radiator, because ``646822`` occurs in its title;
* a genuinely correct match is listed at 1.00 as "price on request" — the Nissens
  radiator and the TRW pads are the right parts at a placeholder price.

No improvement to matching can ever fix the second kind, because the part really
is the same one.  Both are excluded here on the only property they share: the
price cannot be a real price for this part.

The exclusion is deliberately narrow.  It removes an offer from *target
selection* and from nothing else: the position keeps its recommendation, the
offer stays in the basis the customer reads, and the count of what was set aside
is reported.  The customer reviews every recommendation by hand, so hiding a
position costs him a real opportunity while showing a suspect one costs him a
few seconds — the asymmetry runs the opposite way to a system that priced on its
own.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from metis.pricing.raise_policy import (
    FLAG_IMPLAUSIBLE_EXCLUDED_FROM_TARGET,
    RaiseConfidence,
    RaiseOutcome,
    RaisePolicyConfigError,
    RaiseStrategy,
    decide_raise,
    load_raise_policy,
)
from metis.pricing.types import StockStatus


BACKEND_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = BACKEND_ROOT / "config" / "raise_policy.yaml"
SHIPPED_BUDGET = load_raise_policy(POLICY_PATH, strategy="budget_floor")
# 0.35 is a measured candidate, not an owner-approved production value.
# Exercise the mechanism explicitly without silently activating it.
BUDGET = replace(
    SHIPPED_BUDGET,
    target_floor_ratio=Decimal("0.35"),
)


def _decide(prices, current, policy=None):
    return decide_raise(
        current_price=Decimal(str(current)),
        prices=[Decimal(str(price)) for price in prices],
        stock_status=StockStatus.FRESH,
        policy=policy or BUDGET,
    )


# ------------------------------------------------------- the exclusion itself


def test_a_placeholder_price_does_not_set_the_target() -> None:
    """1.00 for a 2747 radiator is not a market; the next real offer is."""

    decision = _decide([1, 1200, 1300, 1400], current=2747)

    # The accepted floor is 1200, so the fixed target is 1200 * 0.95 = 1140.
    assert decision.outcome is RaiseOutcome.LOWER
    assert decision.recommended_price == Decimal("1140")
    assert decision.fair_price == Decimal("1200")
    assert FLAG_IMPLAUSIBLE_EXCLUDED_FROM_TARGET in decision.flags
    assert decision.excluded_implausible_count == 1


def test_the_excluded_offer_stays_in_the_basis_the_customer_reads() -> None:
    """Excluded from the target, not from the evidence: he still sees the 1.00."""

    decision = _decide([1, 1200, 1300, 1400], current=2747)

    assert decision.basis is not None
    assert decision.basis.count == 4
    assert decision.basis.cheapest == Decimal("1")
    assert decision.basis.prices == (
        Decimal("1"),
        Decimal("1200"),
        Decimal("1300"),
        Decimal("1400"),
    )


def test_removing_junk_can_turn_a_cut_into_a_raise() -> None:
    """The measured +19: garbage at the minimum was masking a raise.

    200 against our 1000 is the dangerous shape — low enough to be a collision or
    a placeholder, high enough that rounding still lands inside the band, so the
    pre-existing tick guard does not catch it and it becomes a real cut.
    """

    guarded = _decide([200, 1200, 1300, 1400], current=1000)

    assert guarded.outcome is RaiseOutcome.RAISE
    assert guarded.recommended_price == Decimal("1140")
    assert guarded.fair_price == Decimal("1200")
    assert guarded.excluded_implausible_count == 1

    # With the plausibility floor off, the 200 does become the floor — that part
    # of the shape is unchanged.  What no longer happens is an automatic cut: 200
    # sits below this cohort's lower fence, so the cut is escalated rather than
    # emitted.  The two guards catch this case for different reasons and neither
    # makes the other redundant: the floor turns it into a correct *raise*, while
    # the isolation test only refuses to act on it.
    unguarded = _decide(
        [200, 1200, 1300, 1400],
        current=1000,
        policy=replace(BUDGET, target_floor_ratio=Decimal("0")),
    )
    assert unguarded.outcome is RaiseOutcome.SHOW_BUT_FLAG
    assert unguarded.recommended_price is None
    assert unguarded.fair_price == Decimal("200")
    assert "FLOOR_MATERIALLY_BELOW_NEXT_SELLER" in unguarded.reasons


def test_a_sub_tick_placeholder_was_already_withheld() -> None:
    """The 1.00 listings never produced a price, for an unrelated reason.

    Their band is narrower than one rounding tick, so the target could not land
    inside it.  The floor is what makes the *survivable* cases safe, and this
    records that the two guards are independent rather than duplicated.
    """

    decision = _decide(
        [1, 1200, 1300, 1400],
        current=1000,
        policy=replace(BUDGET, target_floor_ratio=Decimal("0")),
    )

    assert decision.outcome is RaiseOutcome.SHOW_BUT_FLAG
    assert "NO_PRICE_TICK_WITHIN_CUSTOMER_BAND" in decision.reasons


def test_nothing_plausible_is_surfaced_not_hidden() -> None:
    """He must still be told the position was looked at and why it is unusable."""

    decision = _decide([1, 2, 3], current=2747)

    assert decision.outcome is RaiseOutcome.SHOW_BUT_FLAG
    assert decision.recommended_price is None
    assert "ALL_EVIDENCE_BELOW_PLAUSIBILITY_FLOOR" in decision.reasons
    assert decision.basis is not None and decision.basis.count == 3
    assert decision.excluded_implausible_count == 3


def test_a_clean_basis_is_untouched_and_unflagged() -> None:
    decision = _decide([1200, 1300, 1400, 1500], current=1000)

    assert decision.outcome is RaiseOutcome.RAISE
    assert decision.fair_price == Decimal("1200")
    assert FLAG_IMPLAUSIBLE_EXCLUDED_FROM_TARGET not in decision.flags
    assert decision.excluded_implausible_count == 0


@pytest.mark.parametrize(
    ("price", "kept"),
    [("350", True), ("349.99", False)],
)
def test_the_floor_is_inclusive(price, kept) -> None:
    """0.35 x 1000 = 350 exactly, and an offer sitting on it is still evidence."""

    decision = _decide([price, 1200, 1300], current=1000)

    assert (decision.excluded_implausible_count == 0) is kept
    assert (decision.fair_price == Decimal(price)) is kept


# --------------------------------------------------------------- confidence


def test_confidence_counts_the_offers_that_set_the_target() -> None:
    """Grading on discarded evidence would overstate a thin basis."""

    thin = _decide([1, 2, 1200, 1300], current=1000)
    full = _decide([1200, 1300, 1400, 1500], current=1000)

    assert thin.excluded_implausible_count == 2
    assert thin.confidence is RaiseConfidence.LOW
    assert full.confidence is RaiseConfidence.HIGH


# -------------------------------------------------------------------- config


def test_the_shipped_strategy_does_not_activate_an_unapproved_floor() -> None:
    assert SHIPPED_BUDGET.strategy is RaiseStrategy.BUDGET_FLOOR
    assert SHIPPED_BUDGET.target_floor_ratio == Decimal("0")


def test_legacy_strategies_keep_the_whole_basis() -> None:
    """Only the minimum-based target is exposed to a single bad offer."""

    balanced = load_raise_policy(POLICY_PATH, strategy="balanced")

    assert balanced.target_floor_ratio == Decimal("0")

    decision = _decide([1, 1900, 2000, 2100], current=1800, policy=balanced)
    assert decision.excluded_implausible_count == 0


@pytest.mark.parametrize("ratio", ["-0.1", "1", "1.5"])
def test_an_impossible_floor_is_rejected(ratio, tmp_path) -> None:
    source = POLICY_PATH.read_text(encoding="utf-8").replace(
        'target_floor_ratio: "0"', f'target_floor_ratio: "{ratio}"'
    )
    broken = tmp_path / "raise_policy.yaml"
    broken.write_text(source, encoding="utf-8")

    with pytest.raises(RaisePolicyConfigError):
        load_raise_policy(broken, strategy="budget_floor")
