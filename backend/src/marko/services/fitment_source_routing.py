"""Deterministic source plans; a route is not an access authorization."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping
import unicodedata
from urllib.parse import urlsplit

from metis.pricing.crosses import normalize_cross_oem


_OFFICIAL_BRAND_SOURCES = {
    "sachs": ("zf_aftermarket", "official_manufacturer_catalog"),
    "trw": ("zf_aftermarket", "official_manufacturer_catalog"),
    "lemforder": ("zf_aftermarket", "official_manufacturer_catalog"),
    "boge": ("zf_aftermarket", "official_manufacturer_catalog"),
    "zf": ("zf_aftermarket", "official_manufacturer_catalog"),
    "kyb": ("kyb_catalogue", "official_manufacturer_catalog"),
    "bosch": ("bosch_aftermarket", "official_manufacturer_catalog"),
}

FITMENT_CROSS_MIN_CONFIDENCE = Decimal("0.75")
FITMENT_CROSS_MIN_SOURCE_RELIABILITY = Decimal("0.75")
FITMENT_CROSS_MIN_EXTRACTION_CONFIDENCE = Decimal("0.85")
FITMENT_CROSS_MIN_DIRECTNESS = Decimal("0.90")
FITMENT_CROSS_MIN_INDEPENDENCE = Decimal("0.75")


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
            "source_key": "avto_pro",
            "source_type": "aftermarket_cross_index",
            "source_tier": "C",
            "priority": 4 if official else 3,
            "purpose": "cross_candidate_discovery_by_verified_part_number",
            "requires_registered_access_policy": True,
            "independence_policy": "prove_distinct_upstream_or_require_human_confirmation",
        },
        {
            "source_key": "exist_ua",
            "source_type": "distributor_cross_catalog",
            "source_tier": "C",
            "priority": 5 if official else 4,
            "purpose": "cross_candidate_discovery_and_reciprocal_lookup",
            "requires_registered_access_policy": True,
            "independence_policy": "prove_distinct_upstream_or_require_human_confirmation",
        },
        {
            "source_key": "authorized_distributor_search",
            "source_type": "authorized_distributor_catalog",
            "source_tier": "B",
            "priority": 6 if official else 5,
            "purpose": "brand_article_and_oe_pair",
            "requires_registered_access_policy": True,
        },
        {
            "source_key": "structured_web_search",
            "source_type": "structured_web_search",
            "source_tier": "C",
            "priority": 7 if official else 6,
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


def source_confirmation_policy_allows(
    evidence_groups: Iterable[tuple[str, str]],
) -> bool:
    """Return whether source evidence alone may confirm a cross relation.

    One Tier A group or two *different* Tier B correlation groups are required.
    Tier C discovery indexes, including Avto.pro and Exist.ua, deliberately do
    not contribute to automatic confirmation even when both name the pair:
    they may share an upstream catalogue and remain useful only as discovery
    evidence until a human or stronger primary source confirms the relation.
    """

    tier_a_groups: set[str] = set()
    tier_b_groups: set[str] = set()
    for raw_tier, raw_group in evidence_groups:
        tier = str(raw_tier or "").strip().upper()
        group = str(raw_group or "").strip()
        if not group:
            continue
        if tier == "A":
            tier_a_groups.add(group)
        elif tier == "B":
            tier_b_groups.add(group)
    return bool(tier_a_groups or len(tier_b_groups) >= 2)


def source_claim_quality_allows(
    *,
    statement_status: object,
    evidence_value: object,
    polarity: object,
    source_reliability: object,
    extraction_confidence: object,
    directness: object,
    independence_factor: object,
) -> bool:
    """Apply the same source-confirmation quality floor at write and read time."""

    try:
        evidence = Decimal(str(evidence_value))
        reliability = Decimal(str(source_reliability))
        extraction = Decimal(str(extraction_confidence))
        direct = Decimal(str(directness))
        independence = Decimal(str(independence_factor))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return bool(
        str(statement_status or "").strip().upper() == "FACT"
        and evidence == 1
        and str(polarity or "").strip().casefold() == "supports"
        and reliability >= FITMENT_CROSS_MIN_SOURCE_RELIABILITY
        and extraction >= FITMENT_CROSS_MIN_EXTRACTION_CONFIDENCE
        and direct >= FITMENT_CROSS_MIN_DIRECTNESS
        and independence >= FITMENT_CROSS_MIN_INDEPENDENCE
    )


def source_access_policy_allows(
    *,
    access_status: object,
    access_reference: object,
    robots_checked: object,
    terms_checked: object,
) -> bool:
    """Return whether the current source-policy row authorizes evidence use."""

    reference = str(access_reference or "").strip()
    return bool(
        str(access_status or "").strip().upper()
        in {"PERMITTED", "OWNER_RISK_ACCEPTED"}
        and reference
        and reference != "legacy-unreviewed"
        and robots_checked is True
        and terms_checked is True
    )


def source_url_matches_domain(url: str, domain: str) -> bool:
    try:
        host = (urlsplit(url).hostname or "").strip().casefold().rstrip(".")
    except ValueError:
        return False
    expected = str(domain or "").strip().casefold().rstrip(".")
    return bool(
        host and expected and (host == expected or host.endswith(f".{expected}"))
    )


def _flatten_evidence_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        result: list[str] = []
        for key in sorted(value, key=str):
            result.extend(_flatten_evidence_text(key))
            result.extend(_flatten_evidence_text(value[key]))
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        result = []
        for item in value:
            result.extend(_flatten_evidence_text(item))
        return result
    return [str(value)]


def claim_names_both_numbers(
    *,
    claim_value: object,
    raw_fragment: object,
    article: str,
    oe: str,
) -> bool:
    """Require the persisted source fragment to name both sides of a cross."""

    evidence_text = _flatten_evidence_text(claim_value)
    evidence_text.extend(_flatten_evidence_text(raw_fragment))
    haystack = " ".join(evidence_text)

    def exact_number_appears(value: str) -> bool:
        normalized = normalize_cross_oem(value)
        if not normalized:
            return False
        # Permit presentation separators inside the number while preserving
        # alphanumeric boundaries.  Plain substring matching would wrongly
        # treat article 123 as explicitly named by an unrelated 1234.
        flexible = r"[\s./_-]*".join(re.escape(character) for character in normalized)
        return bool(
            re.search(
                rf"(?<![^\W_]){flexible}(?![^\W_])",
                haystack,
                flags=re.IGNORECASE,
            )
        )

    return exact_number_appears(article) and exact_number_appears(oe)


__all__ = [
    "FITMENT_CROSS_MIN_CONFIDENCE",
    "FITMENT_CROSS_MIN_DIRECTNESS",
    "FITMENT_CROSS_MIN_EXTRACTION_CONFIDENCE",
    "FITMENT_CROSS_MIN_INDEPENDENCE",
    "FITMENT_CROSS_MIN_SOURCE_RELIABILITY",
    "claim_names_both_numbers",
    "route_fitment_sources",
    "source_access_policy_allows",
    "source_claim_quality_allows",
    "source_confirmation_policy_allows",
    "source_url_matches_domain",
]
