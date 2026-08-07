"""One canonical active-price boundary for persisted market observations."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def effective_observation_price(observation: Any) -> Decimal:
    """Return the current sell price, never the crossed-out reference price.

    New observations persist sale_price and retain the old/list price in
    reference_price. Older rows may have only the backwards-compatible
    price column, so the fallback is intentionally retained. A malformed
    or non-positive sale value cannot replace a valid active price.
    """

    sale_raw = getattr(observation, "sale_price", None)
    try:
        sale = Decimal(str(sale_raw))
    except (InvalidOperation, TypeError, ValueError):
        sale = None
    if sale is not None and sale.is_finite() and sale > 0:
        return sale

    price_raw = getattr(observation, "price", None)
    try:
        price = Decimal(str(price_raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Market observation has no valid active price") from exc
    if not price.is_finite() or price <= 0:
        raise ValueError("Market observation has no valid active price")
    return price


__all__ = ["effective_observation_price"]
