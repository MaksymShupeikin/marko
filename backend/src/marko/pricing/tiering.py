"""Deterministic brand/tier classification with explicit conflict states."""

from __future__ import annotations

from decimal import Decimal
import re
import unicodedata
from collections.abc import Mapping

from .types import ProductTier, TierClassification


TIER_METHOD_VERSION = "brand-tier-v1"

DEFAULT_BRAND_TIERS: dict[str, ProductTier] = {
    "AUDI": ProductTier.OEM,
    "BMW": ProductTier.OEM,
    "MERCEDESBENZ": ProductTier.OEM,
    "PORSCHE": ProductTier.OEM,
    "SEAT": ProductTier.OEM,
    "SKODA": ProductTier.OEM,
    "VAG": ProductTier.OEM,
    "VOLKSWAGEN": ProductTier.OEM,
    "BOSCH": ProductTier.OES,
    "CONTINENTAL": ProductTier.OES,
    "HELLA": ProductTier.OES,
    "LEMFORDER": ProductTier.OES,
    "NISSENS": ProductTier.OES,
    "SACHS": ProductTier.OES,
    "FEBI": ProductTier.AFTERMARKET_A,
    "MEYLE": ProductTier.AFTERMARKET_A,
    "SKF": ProductTier.AFTERMARKET_A,
    "TRW": ProductTier.AFTERMARKET_A,
    "DELPHI": ProductTier.AFTERMARKET_B,
    "FEBEST": ProductTier.AFTERMARKET_B,
    "MAXGEAR": ProductTier.AFTERMARKET_B,
    "RIDEX": ProductTier.BUDGET,
    "STARK": ProductTier.BUDGET,
    "KEMP": ProductTier.KEMP,
}

_NON_ALNUM = re.compile(r"[^A-Z0-9]")
_USED_MARKERS = (
    "б/у",
    " бу ",
    "вживан",
    "разборк",
    "used",
    "refurb",
    "відновлен",
    "восстановлен",
)
_OEM_MARKERS = ("оригинал", "original", "genuine", "оем", " oem ")


def normalize_brand(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value).upper()
    return _NON_ALNUM.sub("", normalized)


def classify_tier(
    *,
    brand: str | None,
    title: str,
    description: str | None = None,
    manual_override: ProductTier | None = None,
    brand_tiers: Mapping[str, ProductTier] | None = None,
    method_version: str = TIER_METHOD_VERSION,
) -> TierClassification:
    text = f" {title} {description or ''} ".casefold()
    normalized_brand = normalize_brand(brand)
    rules = brand_tiers or DEFAULT_BRAND_TIERS

    if manual_override is not None:
        return TierClassification(
            tier=manual_override,
            confidence=Decimal("1"),
            is_used=manual_override == ProductTier.USED,
            is_kemp=manual_override == ProductTier.KEMP,
            exclusion_reason="USED" if manual_override == ProductTier.USED else None,
            reasons=("MANUAL_OVERRIDE",),
            method_version=method_version,
        )

    if any(marker in text for marker in _USED_MARKERS):
        return TierClassification(
            tier=ProductTier.USED,
            confidence=Decimal("0.99"),
            is_used=True,
            is_kemp=False,
            exclusion_reason="USED_OR_REFURBISHED",
            reasons=("USED_MARKER",),
            method_version=method_version,
        )

    brand_tier = rules.get(normalized_brand)
    if normalized_brand == "KEMP" or re.search(r"\bkemp\b", text):
        return TierClassification(
            tier=ProductTier.KEMP,
            confidence=Decimal("0.99"),
            is_used=False,
            is_kemp=True,
            exclusion_reason=None,
            reasons=("KEMP_MARKER",),
            method_version=method_version,
        )

    has_oem_marker = any(marker in text for marker in _OEM_MARKERS)
    if has_oem_marker and brand_tier not in (None, ProductTier.OEM):
        return TierClassification(
            tier=ProductTier.UNKNOWN,
            confidence=Decimal("0.20"),
            is_used=False,
            is_kemp=False,
            exclusion_reason="TIER_CONFLICT",
            reasons=("OEM_TEXT_BRAND_CONFLICT",),
            method_version=method_version,
        )

    if brand_tier is not None:
        return TierClassification(
            tier=brand_tier,
            confidence=Decimal("0.95"),
            is_used=False,
            is_kemp=False,
            exclusion_reason=None,
            reasons=("EXACT_BRAND_RULE",),
            method_version=method_version,
        )

    if has_oem_marker:
        return TierClassification(
            tier=ProductTier.OEM,
            confidence=Decimal("0.65"),
            is_used=False,
            is_kemp=False,
            exclusion_reason=None,
            reasons=("OEM_TEXT_MARKER",),
            method_version=method_version,
        )

    return TierClassification(
        tier=ProductTier.UNKNOWN,
        confidence=Decimal("0"),
        is_used=False,
        is_kemp=False,
        exclusion_reason="UNKNOWN_TIER",
        reasons=("NO_TIER_EVIDENCE",),
        method_version=method_version,
    )
