"""Deployment-owned market-position policy and its deterministic guards.

The basis is the set of competitor prices already converted to our own level,
so every value here is comparable by construction. Two policy families remain
available:

* the legacy quantile strategies retain their raise-only safety behaviour;
* ``budget_floor`` implements the owner's 2026-08-12 decision: use the cheapest
  verified comparable offer irrespective of brand tier, and position our price
  exactly 5% below it in either direction.

Rounding always goes down.  For the fixed-five-percent rule the normal sub-unit
rounding remainder is allowed; a coarse tick that would move the price by more
than one currency unit is withheld rather than silently changing the policy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
import hashlib
from pathlib import Path
from typing import Any

import yaml

from .statistics import percentile, round_down_to_tick
from .types import StockStatus

RAISE_POLICY_SCHEMA_VERSION = "metis-raise-policy-v2"

ZERO = Decimal("0")
ONE = Decimal("1")


class RaisePolicyConfigError(ValueError):
    """The raise policy cannot be trusted as written."""


class RaisePolicyInputError(ValueError):
    """A stable typed rejection at the public raise-policy boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RaiseStrategy(StrEnum):
    AGGRESSIVE = "aggressive"
    BALANCED = "balanced"
    PREMIUM = "premium"
    BUDGET_FLOOR = "budget_floor"


class RaiseOutcome(StrEnum):
    RAISE = "RAISE"
    LOWER = "LOWER"
    NO_DATA = "NO_DATA"
    ALREADY_COMPETITIVE = "NO_RECOMMENDATION_ALREADY_COMPETITIVE"
    INSIGNIFICANT = "NO_RECOMMENDATION_INSIGNIFICANT"
    STALE_NOT_CHEAPEST = "NO_RECOMMENDATION_STALE_NOT_CHEAPEST"
    TARGET_BAND = "NO_RECOMMENDATION_WITHIN_TARGET_BAND"
    SHOW_BUT_FLAG = "SHOW_BUT_FLAG"


class RaiseConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


FLAG_STEP_CAPPED = "STEP_CAPPED"
FLAG_STALE_CAPPED_AT_CHEAPEST = "STALE_CAPPED_AT_CHEAPEST"
FLAG_ROUNDED_BELOW_SIGNIFICANCE = "ROUNDED_BELOW_SIGNIFICANCE"
FLAG_BELOW_COST_FLOOR = "BELOW_COST_FLOOR"
FLAG_IMPLAUSIBLE_EXCLUDED_FROM_TARGET = "IMPLAUSIBLE_EXCLUDED_FROM_TARGET"
#: No second independent seller meets or beats the cheapest offer, so the target
#: rests on one listing.  The target still uses it — that is the owner's rule —
#: but a raise carries this flag and a cut is sent to review instead.
FLAG_FLOOR_RESTS_ON_ONE_SELLER = "FLOOR_RESTS_ON_ONE_SELLER"
#: Seller identity did not reach this call, so corroboration could not run.
#: Reported rather than assumed: the resulting target may rest on one listing.
FLAG_FLOOR_CORROBORATION_UNAVAILABLE = "FLOOR_CORROBORATION_UNAVAILABLE"
#: Raw seller ids suggested a corroborated floor, but the corroborating sellers
#: collapse into one affiliated sphere once seller-relation records are
#: applied.  Two shops of the same owner are one market signal, not two.
FLAG_FLOOR_CORROBORATION_BY_RELATED_SELLERS = (
    "FLOOR_CORROBORATION_BY_RELATED_SELLERS"
)


@dataclass(frozen=True, slots=True)
class RaisePolicy:
    strategy: RaiseStrategy
    target_quantile: Decimal
    min_evidence: int
    min_change_pct: Decimal
    max_step_pct: Decimal
    psychological_step: Decimal
    high_min_evidence: int
    high_max_robust_cv: Decimal
    medium_min_evidence: int
    medium_max_robust_cv: Decimal
    method_version: str = "raise-policy-v2"
    source_sha256: str | None = None
    minimum_discount: Decimal = ZERO
    maximum_discount: Decimal = ZERO
    tier_agnostic: bool = False
    allow_lower: bool = False
    ignore_stock_status: bool = False
    ignore_cost_floor: bool = False
    owner_decision_reference: str | None = None
    # Share of our own price below which an offer cannot be a real price for this
    # part, and is therefore not allowed to set the target.  Zero disables it,
    # which is the right default for the quantile strategies: a median absorbs a
    # single bad offer, a minimum *is* it.
    target_floor_ratio: Decimal = ZERO
    # How many independent sellers must meet or beat a price before it may be
    # treated as the market floor.  One reproduces the raw minimum, where a
    # single listing decides the recommendation; the quantile strategies never
    # consult this because a quantile is already corroborated by construction.
    floor_corroboration_sellers: int = 1
    # A literal, non-statistical guard for a lone suspicious floor.  If the
    # cheapest price is below this share of the next independent seller, the
    # calculation is shown but requires review.  Zero disables the guard.
    floor_gap_review_ratio: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class RaiseBasis:
    """The competitor prices, already converted to our level, and their shape."""

    count: int
    p25: Decimal
    p50: Decimal
    p75: Decimal
    iqr: Decimal
    robust_cv: Decimal
    cheapest: Decimal
    dearest: Decimal
    prices: tuple[Decimal, ...]
    #: Seller of each price, in the same ascending order as ``prices``.  ``None``
    #: for the whole basis means the caller carried no seller identity, which is
    #: a different statement from a basis whose sellers are individually unknown.
    sellers: tuple[str | None, ...] | None = None

    def pairs(self) -> tuple[tuple[Decimal, str | None], ...]:
        """Price with its seller, cheapest first."""

        if self.sellers is None:
            return tuple((price, None) for price in self.prices)
        return tuple(zip(self.prices, self.sellers, strict=True))

    @property
    def distinct_seller_count(self) -> int | None:
        if self.sellers is None:
            return None
        return len({seller for seller in self.sellers if seller is not None})

    def as_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "p25": str(self.p25),
            "p50": str(self.p50),
            "p75": str(self.p75),
            "iqr": str(self.iqr),
            "robust_cv": str(self.robust_cv),
            "cheapest": str(self.cheapest),
            "dearest": str(self.dearest),
            "prices": [str(price) for price in self.prices],
            # Seller identities are deliberately not persisted here; the count is
            # what a reviewer needs to judge whether the floor means anything.
            "distinct_seller_count": self.distinct_seller_count,
        }


@dataclass(frozen=True, slots=True)
class RaiseDecision:
    outcome: RaiseOutcome
    recommended_price: Decimal | None
    fair_price: Decimal | None
    basis: RaiseBasis | None
    confidence: RaiseConfidence | None
    flags: tuple[str, ...]
    reasons: tuple[str, ...]
    target_band_low: Decimal | None = None
    target_band_high: Decimal | None = None
    # How many offers were set aside for target selection, and the threshold that
    # set them aside.  Reported rather than silently applied: a recommendation
    # computed from 9 of 12 offers is a different claim from one computed from 12.
    excluded_implausible_count: int = 0
    plausibility_floor: Decimal | None = None

    @property
    def is_actionable(self) -> bool:
        return (
            self.outcome in {RaiseOutcome.RAISE, RaiseOutcome.LOWER}
            and self.recommended_price is not None
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "recommended_price": (
                None if self.recommended_price is None else str(self.recommended_price)
            ),
            "fair_price": None if self.fair_price is None else str(self.fair_price),
            "basis": None if self.basis is None else self.basis.as_dict(),
            "confidence": None if self.confidence is None else self.confidence.value,
            "flags": list(self.flags),
            "reasons": list(self.reasons),
            "target_band_low": (
                None if self.target_band_low is None else str(self.target_band_low)
            ),
            "target_band_high": (
                None if self.target_band_high is None else str(self.target_band_high)
            ),
            "excluded_implausible_count": self.excluded_implausible_count,
            "plausibility_floor": (
                None
                if self.plausibility_floor is None
                else str(self.plausibility_floor)
            ),
        }


def default_raise_policy() -> RaisePolicy:
    """The balanced preset in code form, for callers without a config file.

    The deployment file is authoritative and currently selects budget-floor.
    This fallback intentionally stays balanced so a missing deployment setting
    cannot silently opt an external caller into a more permissive strategy.
    """

    return RaisePolicy(
        strategy=RaiseStrategy.BALANCED,
        target_quantile=Decimal("0.50"),
        min_evidence=3,
        min_change_pct=Decimal("0.03"),
        max_step_pct=Decimal("0.25"),
        psychological_step=Decimal("10"),
        high_min_evidence=4,
        high_max_robust_cv=Decimal("0.15"),
        medium_min_evidence=3,
        medium_max_robust_cv=Decimal("0.35"),
        method_version="raise-policy-v2",
    )


def build_basis(
    prices: list[Decimal] | tuple[Decimal, ...],
    *,
    sellers: Sequence[str | None] | None = None,
) -> RaiseBasis | None:
    """Summarize the converted competitor prices, or nothing if there are none.

    ``sellers`` is optional and positional against ``prices``. It exists so a
    floor can be required to have more than one seller behind it; the summary
    statistics ignore it entirely.
    """

    for price in prices:
        if not price.is_finite():
            raise RaisePolicyInputError("NON_FINITE_PRICE")
        if price <= ZERO:
            raise RaisePolicyInputError("NON_POSITIVE_PRICE")
    if sellers is not None and len(sellers) != len(prices):
        raise RaisePolicyInputError("SELLER_COUNT_MISMATCH")
    if sellers is None:
        ordered = tuple(sorted(prices))
        ordered_sellers: tuple[str | None, ...] | None = None
    else:
        # Sorted on price alone: sellers must stay attached to their own price,
        # and seller identity must never influence the order.
        ranked = sorted(zip(prices, sellers, strict=True), key=lambda pair: pair[0])
        ordered = tuple(price for price, _ in ranked)
        ordered_sellers = tuple(seller for _, seller in ranked)
    if not ordered:
        return None
    p25 = percentile(ordered, Decimal("0.25"))
    p50 = percentile(ordered, Decimal("0.50"))
    p75 = percentile(ordered, Decimal("0.75"))
    iqr = p75 - p25
    # An identical cohort has zero spread, which is perfect agreement rather
    # than a division by zero.  A non-positive centre cannot happen for real
    # prices, so it is treated as maximally unreliable instead of raising.
    robust_cv = iqr / p50 if p50 > ZERO else Decimal("Infinity")
    return RaiseBasis(
        count=len(ordered),
        p25=p25,
        p50=p50,
        p75=p75,
        iqr=iqr,
        robust_cv=robust_cv,
        cheapest=ordered[0],
        dearest=ordered[-1],
        prices=ordered,
        sellers=ordered_sellers,
    )


def corroborated_floor(
    pairs: Sequence[tuple[Decimal, str | None]],
    *,
    required_sellers: int,
) -> Decimal | None:
    """The cheapest price that ``required_sellers`` distinct sellers meet or beat.

    ``pairs`` must be ascending by price. An offer whose seller is unknown is
    passed over as a corroborator — two unknowns may well be one shop — but it
    keeps its place in the evidence, because refusing to count it and deleting
    it are different acts.

    Returns nothing when the market never assembles that many sellers, which is
    a shortage of independent evidence rather than an error.
    """

    if required_sellers <= 0:
        # Not a typed reason code: this is a caller mistake, never a statement
        # about the market, and it must not reach a customer-facing reason list.
        raise ValueError("required_sellers must be positive")
    distinct: set[str] = set()
    for price, seller in pairs:
        if seller is None:
            continue
        distinct.add(seller)
        if len(distinct) >= required_sellers:
            return price
    return None


def _apply_seller_groups(
    pairs: Sequence[tuple[Decimal, str | None]],
    seller_groups: Mapping[str, str] | None,
) -> tuple[tuple[Decimal, str | None], ...]:
    """Collapse affiliated sellers into their shared corroboration sphere.

    The mapping rewrites only the seller key; the price and its place in the
    evidence stay untouched.  A seller absent from the mapping keeps its own
    id, so a deployment without seller-relation records behaves exactly as
    before.  Only the budget-floor strategy consults the result: a quantile
    never needed seller identity at all.
    """

    if not seller_groups:
        return tuple(pairs)
    return tuple(
        (price, None if seller is None else seller_groups.get(seller, seller))
        for price, seller in pairs
    )


def grade_confidence(basis: RaiseBasis, policy: RaisePolicy) -> RaiseConfidence:
    """Grade the basis on size and spread, with strictly-less-than thresholds.

    The comparison is deliberately strict: a cohort sitting exactly on the
    boundary is not granted the better grade.
    """

    if (
        basis.count >= policy.high_min_evidence
        and basis.robust_cv < policy.high_max_robust_cv
    ):
        return RaiseConfidence.HIGH
    if (
        basis.count >= policy.medium_min_evidence
        and basis.robust_cv < policy.medium_max_robust_cv
    ):
        return RaiseConfidence.MEDIUM
    return RaiseConfidence.LOW


def decide_raise(
    *,
    current_price: Decimal,
    prices: list[Decimal] | tuple[Decimal, ...],
    stock_status: StockStatus,
    policy: RaisePolicy,
    cost_floor: Decimal | None = None,
    sellers: Sequence[str | None] | None = None,
    seller_groups: Mapping[str, str] | None = None,
) -> RaiseDecision:
    """Decide whether to propose a higher price, and which one.

    ``prices`` must already be converted to our own level; this function never
    normalizes and never inspects a tier.

    ``sellers`` is positional against ``prices`` and is only consulted by the
    budget-floor strategy, which refuses to let one listing be the market.

    ``seller_groups`` maps a raw seller id onto the shared sphere it belongs
    to (own/related/possibly-related storefronts).  Only budget-floor
    corroboration consults it: two sellers inside one sphere are one
    independent signal, not two.  The target itself never moves.
    """

    flags: list[str] = []
    reasons: list[str] = []

    if not current_price.is_finite() or current_price <= ZERO:
        return RaiseDecision(
            outcome=RaiseOutcome.NO_DATA,
            recommended_price=None,
            fair_price=None,
            basis=None,
            confidence=None,
            flags=(),
            reasons=("INVALID_CURRENT_PRICE",),
        )

    try:
        basis = build_basis(prices, sellers=sellers)
    except RaisePolicyInputError as exc:
        return RaiseDecision(
            outcome=RaiseOutcome.NO_DATA,
            recommended_price=None,
            fair_price=None,
            basis=None,
            confidence=None,
            flags=(),
            reasons=(exc.code,),
        )
    if basis is None or basis.count < policy.min_evidence:
        return RaiseDecision(
            outcome=RaiseOutcome.NO_DATA,
            recommended_price=None,
            fair_price=None,
            basis=basis,
            confidence=None,
            flags=(),
            reasons=("TOO_FEW_PRICING_EVIDENCE",),
        )

    if policy.strategy is RaiseStrategy.BUDGET_FLOOR:
        return _decide_budget_floor(
            current_price=current_price,
            basis=basis,
            policy=policy,
            seller_groups=seller_groups,
        )

    fair = percentile(basis.prices, policy.target_quantile)
    target = fair

    # A slow-moving item is only pushed up when it is literally the cheapest
    # offer on the market, and then no further than the cheapest competitor:
    # raising it past them would trade the last of its demand for margin.
    if stock_status is StockStatus.STALE:
        if current_price >= basis.cheapest:
            return RaiseDecision(
                outcome=RaiseOutcome.STALE_NOT_CHEAPEST,
                recommended_price=None,
                fair_price=fair,
                basis=basis,
                confidence=grade_confidence(basis, policy),
                flags=(),
                reasons=("STALE_NOT_BELOW_CHEAPEST_COMPETITOR",),
            )
        if target > basis.cheapest:
            target = basis.cheapest
            flags.append(FLAG_STALE_CAPPED_AT_CHEAPEST)

    if target <= current_price:
        return RaiseDecision(
            outcome=RaiseOutcome.ALREADY_COMPETITIVE,
            recommended_price=None,
            fair_price=fair,
            basis=basis,
            confidence=grade_confidence(basis, policy),
            flags=tuple(flags),
            reasons=("PRICE_ALREADY_AT_OR_ABOVE_TARGET",),
        )

    # 1. Significance.  Do not disturb the customer for a couple of percent.
    if (target - current_price) / current_price < policy.min_change_pct:
        return RaiseDecision(
            outcome=RaiseOutcome.INSIGNIFICANT,
            recommended_price=None,
            fair_price=fair,
            basis=basis,
            confidence=grade_confidence(basis, policy),
            flags=tuple(flags),
            reasons=("CHANGE_BELOW_SIGNIFICANCE_THRESHOLD",),
        )

    # 2. Step limit.
    ceiling = current_price * (ONE + policy.max_step_pct)
    if target > ceiling:
        target = ceiling
        flags.append(FLAG_STEP_CAPPED)

    # 3. Confidence.
    confidence = grade_confidence(basis, policy)
    if confidence is RaiseConfidence.LOW:
        return RaiseDecision(
            outcome=RaiseOutcome.SHOW_BUT_FLAG,
            recommended_price=None,
            fair_price=fair,
            basis=basis,
            confidence=confidence,
            flags=tuple(flags),
            reasons=("LOW_CONFIDENCE_BASIS",),
        )

    # 4. Rounding, downwards only, so the proposal never overshoots the target.
    recommended = round_down_to_tick(target, policy.psychological_step)
    if recommended <= current_price:
        return RaiseDecision(
            outcome=RaiseOutcome.INSIGNIFICANT,
            recommended_price=None,
            fair_price=fair,
            basis=basis,
            confidence=confidence,
            flags=tuple(flags),
            reasons=("ROUNDING_REMOVED_THE_CHANGE",),
        )
    if (recommended - current_price) / current_price < policy.min_change_pct:
        # Applied in the order the specification gives, so the proposal stands;
        # the flag records that rounding pushed it under the threshold that the
        # unrounded target had cleared.
        flags.append(FLAG_ROUNDED_BELOW_SIGNIFICANCE)

    # 5. Cost floor informs, never overrides.
    if cost_floor is not None and recommended < cost_floor:
        flags.append(FLAG_BELOW_COST_FLOOR)
        reasons.append("RECOMMENDATION_BELOW_COST_FLOOR")

    reasons.append("MARKET_SUPPORTS_RAISE")
    return RaiseDecision(
        outcome=RaiseOutcome.RAISE,
        recommended_price=recommended,
        fair_price=fair,
        basis=basis,
        confidence=confidence,
        flags=tuple(flags),
        reasons=tuple(reasons),
    )


def _floor_has_material_gap(
    eligible: Sequence[tuple[Decimal, str | None]],
    *,
    ratio: Decimal,
) -> bool:
    """Whether one cheapest seller is materially below the next seller.

    This is deliberately ordinary arithmetic rather than IQR/MAD/outlier
    statistics: cheapest / next independent seller < the explicit policy
    ratio.  Equal low prices from two sellers corroborate the floor.
    """

    if ratio <= ZERO or len(eligible) < 2:
        return False
    cheapest, cheapest_seller = eligible[0]
    next_price = next(
        (
            price
            for price, seller in eligible[1:]
            if seller is None or cheapest_seller is None or seller != cheapest_seller
        ),
        None,
    )
    return next_price is not None and cheapest / next_price < ratio


def _decide_budget_floor(
    *,
    current_price: Decimal,
    basis: RaiseBasis,
    policy: RaisePolicy,
    seller_groups: Mapping[str, str] | None = None,
) -> RaiseDecision:
    """Apply the owner's tier-agnostic fixed 5% below-minimum positioning.

    The minimum has a breakdown point of zero: one offer that cannot be a real
    price becomes the recommendation outright.  Two unrelated causes produce such
    offers — a numeric collision dragging in a different product, and a correct
    match listed at a placeholder price — and the second is beyond the reach of
    any matching improvement, because the part genuinely is the same one.

    Both are handled where they actually bite, at target selection.  The offer
    stays in ``basis`` because the customer reads that, and he reviews every
    recommendation by hand: suppressing the position would cost him a real
    opportunity, while showing him a suspect number costs a few seconds.

    An optional corroboration guard can be configured for the same reason
    without removing an offer from the evidence:

    * the floor must be met or beaten by ``floor_corroboration_sellers``
      independent sellers.  A plausibility ratio only catches prices that are
      absurd against our own; a mismatched part listed at a merely low price
      passes it and, alone, still becomes the answer.  Two shops agreeing is
      the cheapest evidence that a price is a market and not a mistake.

    The shipped owner policy keeps that at one seller, so the target is the
    literal minimum he asked for.  Whether a second seller stands behind that
    minimum is nonetheless always measured, because it is a fact about the
    evidence rather than a threshold anyone chose, and it is reported as
    ``FLOOR_RESTS_ON_ONE_SELLER``.

    Raises are never capped or suppressed: reaching the market floor is the
    point of the strategy, and either legacy guard would push the proposal
    outside the approved target or swallow a necessary small correction into
    it.  A cut whose floor has a material gap to the next independent seller
    goes to review with its evidence instead.
    """

    floor = (
        current_price * policy.target_floor_ratio
        if policy.target_floor_ratio > ZERO
        else None
    )
    eligible_raw = tuple(
        pair for pair in basis.pairs() if floor is None or pair[0] >= floor
    )
    # Corroboration and the gap guard run on effective sellers: two affiliated
    # storefronts are one independent signal.  The raw pairs are kept alongside
    # so the flag can say precisely when grouping changed the answer.
    eligible = _apply_seller_groups(eligible_raw, seller_groups)
    excluded = basis.count - len(eligible)

    reasons: tuple[str, ...] = (
        "CUSTOMER_BUDGET_FLOOR_POLICY",
        "TIER_AGNOSTIC_OWNER_POLICY",
        "STOCK_AND_COST_IGNORED_BY_OWNER_POLICY",
        "TARGET_5_PERCENT_BELOW_MINIMUM",
    )
    flags: tuple[str, ...] = (
        (FLAG_IMPLAUSIBLE_EXCLUDED_FROM_TARGET,) if excluded else ()
    )

    if not eligible:
        # Every offer is implausible, so there is no defensible target.  Say so
        # instead of returning NO_DATA: the search did find a market, and what it
        # found is exactly what he needs to see to judge it himself.
        return RaiseDecision(
            outcome=RaiseOutcome.SHOW_BUT_FLAG,
            recommended_price=None,
            fair_price=None,
            basis=basis,
            confidence=RaiseConfidence.LOW,
            flags=flags,
            reasons=reasons + ("ALL_EVIDENCE_BELOW_PLAUSIBILITY_FLOOR",),
            excluded_implausible_count=excluded,
            plausibility_floor=floor,
        )

    market_floor = eligible[0][0]
    if policy.floor_corroboration_sellers > 1:
        # The owner may require the floor itself to be corroborated, which moves
        # the target off the literal minimum.  Shipped at one, so this is off.
        selected = corroborated_floor(
            eligible, required_sellers=policy.floor_corroboration_sellers
        )
        if selected is None:
            return RaiseDecision(
                outcome=RaiseOutcome.SHOW_BUT_FLAG,
                recommended_price=None,
                fair_price=None,
                basis=basis,
                confidence=RaiseConfidence.LOW,
                flags=flags,
                reasons=reasons + ("FLOOR_NOT_CORROBORATED_AS_REQUIRED",),
                excluded_implausible_count=excluded,
                plausibility_floor=floor,
            )
        market_floor = selected
    # Measured unconditionally and never used to move the target: "is there a
    # second shop at or below this price" is a property of the evidence, not a
    # threshold someone picked, and it is the one thing that separates a market
    # from a single listing.
    if basis.sellers is None:
        # A caller that carries no seller identity cannot corroborate anything.
        # The engine always carries it; a direct library caller may not, and a
        # guard that never ran must not be reported as one that passed.
        floor_is_alone = False
        flags += (FLAG_FLOOR_CORROBORATION_UNAVAILABLE,)
    else:
        second = corroborated_floor(eligible, required_sellers=2)
        floor_is_alone = second is None or second > market_floor
        if floor_is_alone:
            flags += (FLAG_FLOOR_RESTS_ON_ONE_SELLER,)
        if seller_groups and floor_is_alone:
            # Raw ids said the floor had a second shop; effective sellers say
            # it does not.  The corroboration was inside one affiliated
            # sphere, and that is exactly what a reviewer needs to know.
            second_raw = corroborated_floor(eligible_raw, required_sellers=2)
            if second_raw is not None and second_raw <= market_floor:
                flags += (FLAG_FLOOR_CORROBORATION_BY_RELATED_SELLERS,)
    target_band_low = market_floor * (ONE - policy.maximum_discount)
    target_band_high = market_floor * (ONE - policy.minimum_discount)
    # This strategy intentionally has no dispersion/IQR confidence rule.  Its
    # authority comes from deterministic offer gates plus a minimum count of
    # independent sellers; spread does not move or suppress the literal floor.
    # The separate material-gap guard below still highlights a lone suspicious
    # floor before it can trigger an irreversible cut.
    evidence_count = len(eligible)
    if evidence_count >= policy.high_min_evidence:
        confidence = RaiseConfidence.HIGH
    elif evidence_count >= policy.medium_min_evidence:
        confidence = RaiseConfidence.MEDIUM
    else:
        confidence = RaiseConfidence.LOW
    recommended = round_down_to_tick(
        target_band_high,
        policy.psychological_step,
    )
    fixed_discount = policy.minimum_discount == policy.maximum_discount
    ordinary_rounding_slippage = (
        fixed_discount
        and recommended > ZERO
        and recommended <= target_band_high
        and target_band_high - recommended < ONE
    )
    if (
        recommended < target_band_low or recommended > target_band_high
    ) and not ordinary_rounding_slippage:
        return RaiseDecision(
            outcome=RaiseOutcome.SHOW_BUT_FLAG,
            recommended_price=None,
            fair_price=market_floor,
            basis=basis,
            confidence=confidence,
            flags=flags,
            reasons=reasons + ("NO_PRICE_TICK_WITHIN_CUSTOMER_BAND",),
            target_band_low=target_band_low,
            target_band_high=target_band_high,
            excluded_implausible_count=excluded,
            plausibility_floor=floor,
        )
    if target_band_low <= current_price <= target_band_high:
        return RaiseDecision(
            outcome=RaiseOutcome.TARGET_BAND,
            recommended_price=None,
            fair_price=market_floor,
            basis=basis,
            confidence=confidence,
            flags=flags,
            reasons=reasons + ("PRICE_WITHIN_CUSTOMER_TARGET_BAND",),
            target_band_low=target_band_low,
            target_band_high=target_band_high,
            excluded_implausible_count=excluded,
            plausibility_floor=floor,
        )
    outcome = (
        RaiseOutcome.RAISE if current_price < target_band_low else RaiseOutcome.LOWER
    )
    if confidence is RaiseConfidence.LOW:
        # The rule the quantile strategies apply and this one had dropped: a
        # basis nobody agrees on does not move a live price on its own.  It
        # applies in both directions, because a raise off a cohort spanning
        # twelve-fold is the same guess as a cut off it.
        #
        # The number is not hidden — ``fair_price`` and the band travel with the
        # decision, so the review queue shows what would have been proposed and
        # why it was not proposed automatically.  That is what "highlight it"
        # asks for.
        return RaiseDecision(
            outcome=RaiseOutcome.SHOW_BUT_FLAG,
            recommended_price=None,
            fair_price=market_floor,
            basis=basis,
            confidence=confidence,
            flags=flags,
            reasons=reasons + ("LOW_CONFIDENCE_BASIS",),
            target_band_low=target_band_low,
            target_band_high=target_band_high,
            excluded_implausible_count=excluded,
            plausibility_floor=floor,
        )
    if outcome is RaiseOutcome.LOWER and _floor_has_material_gap(
        eligible,
        ratio=policy.floor_gap_review_ratio,
    ):
        # Cuts and raises are not symmetric, and the difference is not taste.
        # An over-raise is self-limiting and reversible: the part does not sell,
        # and the next run corrects it.  A cut is realised on the first sale and
        # cannot be taken back.
        #
        # What is *not* the discriminator is the depth of the cut.  Our own price
        # at 2747 against a tight cohort at 1200–1400 needs a 57% cut and that
        # cut is correct; the same 57% driven by a lone 200 among 1200–1400 is a
        # matching error.  The difference is whether the floor belongs to the
        # cohort or sits apart from it, so that — and not the size of the move,
        # and not our own price — is what is tested.
        #
        # Nothing is clamped either.  A clamped cut is 5% below nothing at all:
        # it satisfies neither the owner's rule nor the evidence, and it would
        # look like an answer.  It goes to him with the offers attached, which is
        # what he asked the system to do — highlight it, and let him judge.
        return RaiseDecision(
            outcome=RaiseOutcome.SHOW_BUT_FLAG,
            recommended_price=None,
            fair_price=market_floor,
            basis=basis,
            confidence=confidence,
            flags=flags,
            reasons=reasons + ("FLOOR_MATERIALLY_BELOW_NEXT_SELLER",),
            target_band_low=target_band_low,
            target_band_high=target_band_high,
            excluded_implausible_count=excluded,
            plausibility_floor=floor,
        )
    direction_reason = (
        "MARKET_SUPPORTS_RAISE"
        if outcome is RaiseOutcome.RAISE
        else "MARKET_SUPPORTS_LOWER"
    )
    return RaiseDecision(
        outcome=outcome,
        recommended_price=recommended,
        fair_price=market_floor,
        basis=basis,
        confidence=confidence,
        flags=flags,
        reasons=reasons + (direction_reason,),
        target_band_low=target_band_low,
        target_band_high=target_band_high,
        excluded_implausible_count=excluded,
        plausibility_floor=floor,
    )


def load_raise_policy(path: str | Path, *, strategy: str | None = None) -> RaisePolicy:
    """Load one named strategy from the policy file, hashing its bytes."""

    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise RaisePolicyConfigError(f"Raise policy does not exist: {source_path}")
    raw = source_path.read_bytes()
    try:
        payload: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise RaisePolicyConfigError("Raise policy is not valid YAML") from exc
    if not isinstance(payload, dict):
        raise RaisePolicyConfigError("Raise policy root must be a mapping")
    if payload.get("schema_version") != RAISE_POLICY_SCHEMA_VERSION:
        raise RaisePolicyConfigError(
            f"Unsupported raise policy schema: {payload.get('schema_version')!r}"
        )
    method_version = _text(payload.get("method_version"), "method_version")
    selected = strategy or payload.get("active_strategy")
    if not isinstance(selected, str) or not selected.strip():
        raise RaisePolicyConfigError("active_strategy must be a non-empty string")
    try:
        resolved = RaiseStrategy(selected.strip().casefold())
    except ValueError as exc:
        raise RaisePolicyConfigError(f"Unknown strategy: {selected!r}") from exc

    guards = payload.get("guards")
    if not isinstance(guards, dict):
        raise RaisePolicyConfigError("guards must be a mapping")
    confidence = payload.get("confidence")
    if not isinstance(confidence, dict):
        raise RaisePolicyConfigError("confidence must be a mapping")
    strategies = payload.get("strategies")
    if not isinstance(strategies, dict) or resolved.value not in strategies:
        raise RaisePolicyConfigError(f"strategies must define {resolved.value!r}")
    entry = strategies[resolved.value]
    if not isinstance(entry, dict):
        raise RaisePolicyConfigError(f"strategies.{resolved.value} must be a mapping")

    target_quantile = _decimal(entry.get("target_quantile"), "target_quantile")
    if target_quantile < ZERO or target_quantile > ONE:
        raise RaisePolicyConfigError("target_quantile must be between zero and one")

    policy = RaisePolicy(
        strategy=resolved,
        target_quantile=target_quantile,
        min_evidence=_positive_int(guards.get("min_evidence"), "min_evidence"),
        min_change_pct=_decimal(guards.get("min_change_pct"), "min_change_pct"),
        max_step_pct=_decimal(guards.get("max_step_pct"), "max_step_pct"),
        psychological_step=_decimal(
            entry.get("psychological_step", guards.get("psychological_step")),
            "psychological_step",
        ),
        high_min_evidence=_positive_int(
            confidence.get("high_min_evidence"), "high_min_evidence"
        ),
        high_max_robust_cv=_decimal(
            confidence.get("high_max_robust_cv"), "high_max_robust_cv"
        ),
        medium_min_evidence=_positive_int(
            confidence.get("medium_min_evidence"), "medium_min_evidence"
        ),
        medium_max_robust_cv=_decimal(
            confidence.get("medium_max_robust_cv"), "medium_max_robust_cv"
        ),
        method_version=method_version,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        minimum_discount=_decimal(
            entry.get("minimum_discount", "0"),
            "minimum_discount",
        ),
        maximum_discount=_decimal(
            entry.get("maximum_discount", "0"),
            "maximum_discount",
        ),
        tier_agnostic=_boolean(
            entry.get("tier_agnostic", False),
            "tier_agnostic",
        ),
        allow_lower=_boolean(entry.get("allow_lower", False), "allow_lower"),
        ignore_stock_status=_boolean(
            entry.get("ignore_stock_status", False),
            "ignore_stock_status",
        ),
        ignore_cost_floor=_boolean(
            entry.get("ignore_cost_floor", False),
            "ignore_cost_floor",
        ),
        owner_decision_reference=_optional_text(
            entry.get("owner_decision_reference"),
            "owner_decision_reference",
        ),
        target_floor_ratio=_decimal(
            entry.get("target_floor_ratio", "0"),
            "target_floor_ratio",
        ),
        floor_corroboration_sellers=_positive_int(
            entry.get("floor_corroboration_sellers", 1),
            "floor_corroboration_sellers",
        ),
        floor_gap_review_ratio=_decimal(
            entry.get("floor_gap_review_ratio", "0"),
            "floor_gap_review_ratio",
        ),
    )
    if policy.psychological_step <= ZERO:
        raise RaisePolicyConfigError("psychological_step must be positive")
    if policy.min_change_pct < ZERO or policy.max_step_pct <= ZERO:
        raise RaisePolicyConfigError("guard thresholds must be non-negative")
    if policy.high_max_robust_cv > policy.medium_max_robust_cv:
        raise RaisePolicyConfigError(
            "high_max_robust_cv must not exceed medium_max_robust_cv"
        )
    if not (ZERO <= policy.target_floor_ratio < ONE):
        # At 1 the floor would discard every offer cheaper than our own price,
        # which is the entire population a cut is derived from.
        raise RaisePolicyConfigError("target_floor_ratio must satisfy 0 <= ratio < 1")
    if not (ZERO <= policy.floor_gap_review_ratio < ONE):
        raise RaisePolicyConfigError(
            "floor_gap_review_ratio must satisfy 0 <= ratio < 1"
        )
    if policy.strategy is RaiseStrategy.BUDGET_FLOOR:
        if not (ZERO < policy.minimum_discount <= policy.maximum_discount < ONE):
            raise RaisePolicyConfigError(
                "budget_floor discounts must satisfy "
                "0 < minimum_discount <= maximum_discount < 1"
            )
        if not (
            policy.tier_agnostic
            and policy.allow_lower
            and policy.ignore_stock_status
            and policy.ignore_cost_floor
        ):
            raise RaisePolicyConfigError(
                "budget_floor requires tier_agnostic, allow_lower, "
                "ignore_stock_status and ignore_cost_floor"
            )
        if policy.owner_decision_reference is None:
            raise RaisePolicyConfigError(
                "budget_floor requires owner_decision_reference"
            )
        if "floor_corroboration_sellers" not in entry:
            # Deliberately not defaulted for this strategy.  One seller is the raw
            # minimum, whose breakdown point is zero, and a value that arrives by
            # omission is nobody's decision.  Choosing it is the owner's; making
            # the choice explicit is ours.
            raise RaisePolicyConfigError(
                "budget_floor requires an explicit floor_corroboration_sellers"
            )
    return policy


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise RaisePolicyConfigError(f"{field} must be a number")
    try:
        parsed = Decimal(str(value))
    except (ArithmeticError, ValueError) as exc:
        raise RaisePolicyConfigError(f"{field} must be a number") from exc
    if not parsed.is_finite():
        raise RaisePolicyConfigError(f"{field} must be finite")
    return parsed


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RaisePolicyConfigError(f"{field} must be a positive integer")
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise RaisePolicyConfigError(f"{field} must be boolean")
    return value


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RaisePolicyConfigError(f"{field} must be a non-empty string")
    return value.strip()


__all__ = [
    "FLAG_BELOW_COST_FLOOR",
    "FLAG_FLOOR_CORROBORATION_BY_RELATED_SELLERS",
    "FLAG_FLOOR_CORROBORATION_UNAVAILABLE",
    "FLAG_FLOOR_RESTS_ON_ONE_SELLER",
    "FLAG_IMPLAUSIBLE_EXCLUDED_FROM_TARGET",
    "FLAG_ROUNDED_BELOW_SIGNIFICANCE",
    "FLAG_STALE_CAPPED_AT_CHEAPEST",
    "FLAG_STEP_CAPPED",
    "RAISE_POLICY_SCHEMA_VERSION",
    "RaiseBasis",
    "RaiseConfidence",
    "RaiseDecision",
    "RaiseOutcome",
    "RaisePolicy",
    "RaisePolicyConfigError",
    "RaisePolicyInputError",
    "RaiseStrategy",
    "build_basis",
    "corroborated_floor",
    "decide_raise",
    "default_raise_policy",
    "grade_confidence",
    "load_raise_policy",
]
