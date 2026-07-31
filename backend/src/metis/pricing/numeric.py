"""Versioned precision boundary for non-algebraic pricing calculations.

Money and algebraic ratios remain ``Decimal`` end-to-end.  Python's standard
library exposes logarithms, exponentials, powers, and square roots through
binary libm operations, so those approximations are admitted only here and are
immediately reduced to a documented 12-significant-digit replay profile.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
import math
from typing import Callable


TRANSCENDENTAL_PROFILE_VERSION = "decimal-libm-12sig-v1"
TRANSCENDENTAL_SIGNIFICANT_DIGITS = 12
TRANSCENDENTAL_RELATIVE_TOLERANCE = Decimal("1e-11")


def _finite(value: Decimal, *, operation: str) -> Decimal:
    if not value.is_finite():
        raise ValueError(f"{operation} requires finite Decimal inputs")
    return value


def _evaluate(
    operation: str,
    function: Callable[..., float],
    *values: Decimal,
) -> Decimal:
    for value in values:
        _finite(value, operation=operation)
    try:
        result = function(*(float(value) for value in values))
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{operation} input is outside the numeric profile") from exc
    if not math.isfinite(result):
        raise ValueError(f"{operation} produced a non-finite result")
    return Decimal(format(result, f".{TRANSCENDENTAL_SIGNIFICANT_DIGITS}g"))


def decimal_ln(value: Decimal) -> Decimal:
    """Natural logarithm under the versioned approximation contract."""

    if value <= 0:
        raise ValueError("ln requires a positive value")
    return _evaluate("ln", math.log, value)


def decimal_log1p(value: Decimal) -> Decimal:
    """Natural logarithm of ``1 + value`` under the replay contract."""

    if value <= -1:
        raise ValueError("log1p requires a value greater than -1")
    return _evaluate("log1p", math.log1p, value)


def decimal_exp(value: Decimal) -> Decimal:
    """Exponential under the versioned approximation contract."""

    return _evaluate("exp", math.exp, value)


def decimal_sqrt(value: Decimal) -> Decimal:
    """Square root under the versioned approximation contract."""

    if value < 0:
        raise ValueError("sqrt requires a non-negative value")
    return _evaluate("sqrt", math.sqrt, value)


def decimal_pow(base: Decimal, exponent: Decimal) -> Decimal:
    """Power under the versioned approximation contract."""

    return _evaluate("pow", math.pow, base, exponent)


def profile_decimal(value: Decimal) -> Decimal:
    """Round derived Decimal arithmetic to the profile's significant digits."""

    _finite(value, operation="profile")
    with localcontext() as context:
        context.prec = TRANSCENDENTAL_SIGNIFICANT_DIGITS
        return +value


__all__ = [
    "TRANSCENDENTAL_PROFILE_VERSION",
    "TRANSCENDENTAL_RELATIVE_TOLERANCE",
    "TRANSCENDENTAL_SIGNIFICANT_DIGITS",
    "decimal_exp",
    "decimal_ln",
    "decimal_log1p",
    "decimal_pow",
    "decimal_sqrt",
    "profile_decimal",
]
