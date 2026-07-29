"""What our price is raised against, and the guards before it is proposed.

The basis is the set of competitor prices already converted to our own level,
so every value here is comparable by construction.  From it the module picks a
target point, and then spends most of its logic refusing to act:

* below the significance threshold the customer is not disturbed at all;
* a jump larger than one step is capped, because a tripled price is almost
  always a matching error rather than a market;
* a thin or scattered basis downgrades the answer to "here is the arithmetic,
  decide yourself" instead of a recommendation;
* rounding only ever goes down, so the proposal cannot overshoot the target.

For anything still selling the module never proposes a cut.  Staying silent is
the worst outcome it is allowed to produce.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
import hashlib
from pathlib import Path
from typing import Any

import yaml

from .statistics import percentile, round_down_to_tick
from .types import StockStatus

RAISE_POLICY_SCHEMA_VERSION = "metis-raise-policy-v1"

ZERO = Decimal("0")
ONE = Decimal("1")


class RaisePolicyConfigError(ValueError):
    """The raise policy cannot be trusted as written."""


class RaiseStrategy(StrEnum):
    AGGRESSIVE = "aggressive"
    BALANCED = "balanced"
    PREMIUM = "premium"


class RaiseOutcome(StrEnum):
    RAISE = "RAISE"
    NO_DATA = "NO_DATA"
    ALREADY_COMPETITIVE = "NO_RECOMMENDATION_ALREADY_COMPETITIVE"
    INSIGNIFICANT = "NO_RECOMMENDATION_INSIGNIFICANT"
    STALE_NOT_CHEAPEST = "NO_RECOMMENDATION_STALE_NOT_CHEAPEST"
    SHOW_BUT_FLAG = "SHOW_BUT_FLAG"


class RaiseConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


FLAG_STEP_CAPPED = "STEP_CAPPED"
FLAG_STALE_CAPPED_AT_CHEAPEST = "STALE_CAPPED_AT_CHEAPEST"
FLAG_ROUNDED_BELOW_SIGNIFICANCE = "ROUNDED_BELOW_SIGNIFICANCE"
FLAG_BELOW_COST_FLOOR = "BELOW_COST_FLOOR"


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
    method_version: str = "raise-policy-v1"
    source_sha256: str | None = None


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

    @property
    def is_actionable(self) -> bool:
        return self.outcome is RaiseOutcome.RAISE and self.recommended_price is not None

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
        }


def default_raise_policy() -> RaisePolicy:
    """The balanced preset in code form, for callers without a config file.

    It mirrors ``config/raise_policy.yaml``; the file stays the source of truth
    for a deployment, and a mismatch is caught by a test.
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
    )


def build_basis(prices: list[Decimal] | tuple[Decimal, ...]) -> RaiseBasis | None:
    """Summarize the converted competitor prices, or nothing if there are none."""

    ordered = tuple(sorted(prices))
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
) -> RaiseDecision:
    """Decide whether to propose a higher price, and which one.

    ``prices`` must already be converted to our own level; this function never
    normalizes and never inspects a tier.
    """

    flags: list[str] = []
    reasons: list[str] = []

    basis = build_basis(prices)
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
            guards.get("psychological_step"), "psychological_step"
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
    )
    if policy.psychological_step <= ZERO:
        raise RaisePolicyConfigError("psychological_step must be positive")
    if policy.min_change_pct < ZERO or policy.max_step_pct <= ZERO:
        raise RaisePolicyConfigError("guard thresholds must be non-negative")
    if policy.high_max_robust_cv > policy.medium_max_robust_cv:
        raise RaisePolicyConfigError(
            "high_max_robust_cv must not exceed medium_max_robust_cv"
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


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RaisePolicyConfigError(f"{field} must be a non-empty string")
    return value.strip()


__all__ = [
    "FLAG_BELOW_COST_FLOOR",
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
    "RaiseStrategy",
    "build_basis",
    "decide_raise",
    "default_raise_policy",
    "grade_confidence",
    "load_raise_policy",
]
