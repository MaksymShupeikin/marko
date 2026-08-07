"""Fail-closed assessment for description-cross discovery candidates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from marko.services.parser_models import Product
from marko.services.catalog_identity_safety import is_internal_catalog_code
from metis.pricing import (
    ConditionState,
    ProductTier,
    classify_condition,
    classify_tier,
    normalize_brand,
)
from metis.pricing.crosses import normalize_cross_oem


def evaluate_cross_discovery_product(
    product: Product,
    *,
    cross_oe: str,
    owned_seller_ids: set[str],
    brand_tiers: Mapping[str, ProductTier] | None = None,
) -> dict[str, Any]:
    """Classify a search result as discovery evidence, never pricing evidence."""

    target_cross = normalize_cross_oem(cross_oe)
    # A private KEMP shelf code is a catalog join key, not a public cross
    # identity. Refuse it as the target as well as filtering it from native
    # candidate identifiers below; otherwise a caller could publish a
    # warehouse-code search as a cross discovery result.
    if target_cross and is_internal_catalog_code(target_cross):
        target_cross = ""
    native_identifiers = (
        product.sku,
        product.mpn,
        product.oe_raw,
        *product.part_numbers,
    )
    exact = bool(
        target_cross
        and any(
            (normalized := normalize_cross_oem(value))
            and not is_internal_catalog_code(normalized)
            and normalized == target_cross
            for value in native_identifiers
        )
    )
    seller_id = str(product.seller_id or "")
    is_owned = bool(seller_id and seller_id in owned_seller_ids)
    condition = classify_condition(
        title=product.name,
        description=product.description,
        explicit_condition=product.condition,
    )
    available = product.is_available is True
    tier = classify_tier(
        brand=product.brand,
        title=product.name or "",
        description=product.description,
        condition=product.condition,
        brand_tiers=brand_tiers,
    )
    reason_codes: list[str] = []
    if not exact:
        reason_codes.append("NOT_EXACT_CROSS_SKU_OR_OE")
    if is_owned:
        reason_codes.append("OWNED_SELLER")
    if not available:
        reason_codes.append("NOT_PROVEN_AVAILABLE")
    if condition.state is ConditionState.USED_OR_REFURBISHED:
        reason_codes.append("USED_OR_REFURBISHED")
    elif condition.state is ConditionState.CONFLICT:
        reason_codes.append("CONDITION_CONFLICT")
    discovery_candidate = not reason_codes
    return {
        "exact": exact,
        "owned": is_owned,
        "available": available,
        "condition_state": condition.state.value,
        "discovery_candidate": discovery_candidate,
        "pricing_eligible": False,
        "reason_codes": reason_codes,
        "pricing_block_reasons": [
            "MISSING_CATEGORY_VALIDATION",
            "MISSING_HUMAN_MATCH_LABEL",
            "MISSING_HUMAN_TIER_LABEL",
        ],
        "independent_kemp": normalize_brand(product.brand) == "KEMP" and not is_owned,
        "predicted_tier": tier.tier.value,
        "tier_confidence": str(tier.confidence),
        "tier_reasons": list(tier.reasons),
    }


__all__ = ["evaluate_cross_discovery_product"]
