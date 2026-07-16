"""Deterministic robust-statistics helpers used by the pricing engine."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP
import math


ZERO = Decimal("0")
ONE = Decimal("1")


def clamp01(value: Decimal) -> Decimal:
    return min(ONE, max(ZERO, value))


def median(values: Iterable[Decimal]) -> Decimal:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("median requires at least one value")
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2)


def percentile(values: Iterable[Decimal], quantile: Decimal) -> Decimal:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    if quantile < ZERO or quantile > ONE:
        raise ValueError("quantile must be between zero and one")
    if len(ordered) == 1:
        return ordered[0]
    position = quantile * Decimal(len(ordered) - 1)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - Decimal(lower_index)
    return (
        ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction
    )


def mad(values: Iterable[Decimal]) -> Decimal:
    collected = tuple(values)
    center = median(collected)
    return median(abs(value - center) for value in collected)


def iqr_fences(
    values: Iterable[Decimal], *, multiplier: Decimal = Decimal("1.5")
) -> tuple[Decimal, Decimal]:
    collected = tuple(values)
    q1 = percentile(collected, Decimal("0.25"))
    q3 = percentile(collected, Decimal("0.75"))
    spread = q3 - q1
    return q1 - multiplier * spread, q3 + multiplier * spread


def winsorize(
    values: Iterable[Decimal], *, lower: Decimal, upper: Decimal
) -> tuple[Decimal, ...]:
    collected = tuple(values)
    if not collected:
        return ()
    if lower < ZERO or upper > ONE or lower >= upper:
        raise ValueError("winsor quantiles must satisfy 0 <= lower < upper <= 1")
    lower_value = percentile(collected, lower)
    upper_value = percentile(collected, upper)
    return tuple(min(upper_value, max(lower_value, value)) for value in collected)


def effective_sample_size(weights: Iterable[Decimal]) -> Decimal:
    collected = tuple(weight for weight in weights if weight > ZERO)
    if not collected:
        return ZERO
    total = sum(collected, ZERO)
    squared = sum((weight * weight for weight in collected), ZERO)
    if squared == ZERO:
        return ZERO
    return (total * total) / squared


def geometric_mean(
    scores: Mapping[str, Decimal],
    *,
    weights: Mapping[str, Decimal] | None = None,
    epsilon: Decimal = Decimal("0.000001"),
) -> Decimal:
    if not scores:
        return ZERO
    if epsilon <= ZERO:
        raise ValueError("epsilon must be positive")
    selected_weights = weights or {name: ONE for name in scores}
    numerator = 0.0
    denominator = ZERO
    for name, score in scores.items():
        weight = Decimal(str(selected_weights.get(name, ONE)))
        if weight <= ZERO:
            raise ValueError("geometric-mean weights must be positive")
        bounded = max(epsilon, clamp01(score))
        numerator += float(weight) * math.log(float(bounded))
        denominator += weight
    if denominator <= ZERO:
        return ZERO
    return clamp01(Decimal(str(math.exp(numerator / float(denominator)))))


def log_coverage(count: Decimal, reference_count: int) -> Decimal:
    if count <= ZERO or reference_count <= 0:
        return ZERO
    value = math.log1p(float(count)) / math.log1p(reference_count)
    return clamp01(Decimal(str(value)))


def round_down_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    if tick <= ZERO:
        raise ValueError("price_tick must be positive")
    return (value / tick).to_integral_value(rounding=ROUND_DOWN) * tick


def round_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    if tick <= ZERO:
        raise ValueError("price_tick must be positive")
    return (value / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick


def round_up_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    if tick <= ZERO:
        raise ValueError("price_tick must be positive")
    return (value / tick).to_integral_value(rounding=ROUND_CEILING) * tick


__all__ = [
    "clamp01",
    "effective_sample_size",
    "geometric_mean",
    "iqr_fences",
    "log_coverage",
    "mad",
    "median",
    "percentile",
    "round_down_to_tick",
    "round_to_tick",
    "round_up_to_tick",
    "winsorize",
]
