"""Deterministic source plans; a route is not an access authorization."""

from __future__ import annotations

from typing import Any
import unicodedata


_OFFICIAL_BRAND_SOURCES = {
    "sachs": ("zf_aftermarket", "official_manufacturer_catalog"),
    "trw": ("zf_aftermarket", "official_manufacturer_catalog"),
    "lemforder": ("zf_aftermarket", "official_manufacturer_catalog"),
    "boge": ("zf_aftermarket", "official_manufacturer_catalog"),
    "zf": ("zf_aftermarket", "official_manufacturer_catalog"),
    "kyb": ("kyb_catalogue", "official_manufacturer_catalog"),
    "bosch": ("bosch_aftermarket", "official_manufacturer_catalog"),
}


def _brand_key(value: str | None) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKC", value or "").casefold()
        if character.isalnum()
    )


def route_fitment_sources(brand: str | None) -> dict[str, Any]:
    """Return a query-level retrieval plan without claiming legal permission."""

    key = _brand_key(brand)
    preferred: list[dict[str, Any]] = []
    official = _OFFICIAL_BRAND_SOURCES.get(key)
    if official is not None:
        preferred.append(
            {
                "source_key": official[0],
                "source_type": official[1],
                "source_tier": "A",
                "priority": 1,
                "purpose": "article_and_aftermarket_cross_verification",
                "requires_registered_access_policy": True,
            }
        )
    preferred.extend(
        [
            {
                "source_key": "partsouq",
                "source_type": "structured_industry_catalog",
                "source_tier": "B",
                "priority": 2 if official else 1,
                "purpose": "oem_existence_supersession_and_vehicle_node",
                "requires_registered_access_policy": True,
            },
            {
                "source_key": "seven_zap",
                "source_type": "structured_industry_catalog",
                "source_tier": "B",
                "priority": 3 if official else 2,
                "purpose": "independent_oem_scheme_and_position_check",
                "requires_registered_access_policy": True,
            },
        ]
    )
    fallback = [
        {
            "source_key": "authorized_distributor_search",
            "source_type": "authorized_distributor_catalog",
            "source_tier": "B",
            "priority": 4 if official else 3,
            "purpose": "brand_article_and_oe_pair",
            "requires_registered_access_policy": True,
        },
        {
            "source_key": "structured_web_search",
            "source_type": "structured_web_search",
            "source_tier": "C",
            "priority": 5 if official else 4,
            "purpose": "discovery_only_until_independent_confirmation",
            "requires_registered_access_policy": True,
        },
    ]
    return {
        "brand": brand.strip() if brand else None,
        "preferred_sources": preferred,
        "fallback_sources": fallback,
        "retrieval_mode": "query_level",
        "automatic_access_authorized": False,
    }


__all__ = ["route_fitment_sources"]
