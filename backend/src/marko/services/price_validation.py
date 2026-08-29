"""One validity rule for every catalog price write path."""

from __future__ import annotations

from decimal import Decimal


def positive_price_or_none(value: Decimal | None) -> Decimal | None:
    """A catalog price is usable only when it is strictly greater than zero."""
    return value if value is not None and value > 0 else None


__all__ = ["positive_price_or_none"]
