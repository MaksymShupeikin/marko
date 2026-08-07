"""Ordered public market search keys for a catalog identity snapshot.

The marketplace collection path historically sent **one** retrieval number per
position (``customer_identity_query``).  Coverage improves when every *safe*
public identifier known for the row can be tried — confirmed OE first, then
confirmed one-hop crosses, then public MPN / characteristic part numbers —
without ever emitting a private KEMP shelf code.

This module is pure: it does not touch the database or the network.  Pricing
admission remains separate — only keys with ``pricing_primary=True`` may become
the pricing run's primary market identity; the rest are discovery/expansion.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal

from marko.services.catalog_identity_safety import (
    catalog_identity_pair_has_safe_shape,
    is_internal_catalog_code,
)
from metis.pricing.crosses import normalize_cross_oem
from metis.pricing.identity_graph import is_safe_public_number_shape

PublicSearchRole = Literal["OE", "CROSS", "PUBLIC_MPN", "PART_NUMBER"]
PublicSearchConfidence = Literal["confirmed", "retrieval_only"]

# Role priority for dedupe: keep the strongest role when the same number appears
# under multiple sources.
_ROLE_RANK: dict[str, int] = {
    "OE": 0,
    "CROSS": 1,
    "PUBLIC_MPN": 2,
    "PART_NUMBER": 3,
}

# Match the single-query floor used by ``customer_identity_query_from_fields``.
MIN_PUBLIC_QUERY_NUMBER_LENGTH = 4

# Confirmed graph edges must not smuggle REVIEW / anomalous evidence into the
# multi-key list.  These keys mirror the frozen-run reader.
_CONFIRMED_STATUS = "CONFIRMED"


@dataclass(frozen=True, slots=True)
class PublicSearchKey:
    """One safe public identifier that may be sent to Prom as a query."""

    number: str
    role: PublicSearchRole
    source: str
    confidence: PublicSearchConfidence
    """``confirmed`` = graph/asserted OE; ``retrieval_only`` = MPN/part list."""

    pricing_primary: bool
    """Whether this key is eligible as the *primary* pricing market identity."""

    raw: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _public_normalized(value: Any) -> str:
    normalized = normalize_cross_oem("" if value is None else str(value))
    if not normalized:
        return ""
    if is_internal_catalog_code(normalized):
        return ""
    if not is_safe_public_number_shape(normalized):
        return ""
    return normalized


def _usable_retrieval_number(value: Any) -> str:
    """Public number safe as a non-OE Prom query (same floor as single-query)."""

    normalized = _public_normalized(value)
    if not normalized:
        return ""
    if normalized.isdigit() and len(normalized) < MIN_PUBLIC_QUERY_NUMBER_LENGTH:
        return ""
    return normalized


def _link_is_confirmed_for_search(link: Mapping[str, Any]) -> bool:
    status = str(link.get("validation_status") or "").strip().upper()
    if status != _CONFIRMED_STATUS:
        return False
    if link.get("anomaly"):
        return False
    details = link.get("validation_details")
    if isinstance(details, Mapping) and details.get("automatic_eligible") is False:
        # Explicit denial only.  Missing flag still allows *discovery* use of
        # the public endpoint when the pair shape is safe; pricing_primary stays
        # false for cross keys unless automatic_eligible is True.
        return False
    return True


def _link_automatic_eligible(link: Mapping[str, Any]) -> bool:
    details = link.get("validation_details")
    if not isinstance(details, Mapping):
        return False
    return details.get("automatic_eligible") is True


def _add_key(
    by_number: dict[str, PublicSearchKey],
    *,
    number: str,
    role: PublicSearchRole,
    source: str,
    confidence: PublicSearchConfidence,
    pricing_primary: bool,
    raw: str | None = None,
) -> None:
    if not number:
        return
    candidate = PublicSearchKey(
        number=number,
        role=role,
        source=source,
        confidence=confidence,
        pricing_primary=pricing_primary,
        raw=raw,
    )
    existing = by_number.get(number)
    if existing is None:
        by_number[number] = candidate
        return
    # Prefer stronger role; within the same role prefer pricing_primary and
    # confirmed confidence.
    if _ROLE_RANK[role] < _ROLE_RANK[existing.role]:
        by_number[number] = candidate
        return
    if role == existing.role:
        if pricing_primary and not existing.pricing_primary:
            by_number[number] = candidate
            return
        if (
            confidence == "confirmed"
            and existing.confidence != "confirmed"
            and pricing_primary == existing.pricing_primary
        ):
            by_number[number] = candidate


def build_public_search_keys(
    *,
    identity_status: str | None,
    oe_norm: str | None = None,
    mpn_norm: str | None = None,
    part_numbers_norm: Iterable[str] = (),
    confirmed_identity_links: Sequence[Mapping[str, Any]] = (),
    primary_query: str | None = None,
) -> tuple[PublicSearchKey, ...]:
    """Build a deduplicated, priority-ordered list of public search keys.

    Parameters
    ----------
    identity_status:
        Catalog namespace: ``OE_CONFIRMED`` | ``MPN_ONLY`` | ``UNRESOLVED``.
    oe_norm / mpn_norm / part_numbers_norm:
        Snapshot fields from the catalog row (already import-normalized when
        available; re-normalized here fail-closed).
    confirmed_identity_links:
        Optional edge snapshots (same shape as pricing-run frozen links).
        Only ``CONFIRMED`` non-anomalous pairs with safe public endpoints
        contribute a ``CROSS`` key (the endpoint opposite the primary OE).
    primary_query:
        Optional already-resolved single query (e.g. from
        ``customer_identity_query``).  When present and public, it is forced to
        the front so multi-key expansion never reorders the legacy primary.
    """

    status = str(identity_status or "").strip().upper()
    by_number: dict[str, PublicSearchKey] = {}

    oe = _public_normalized(oe_norm)
    if status == "OE_CONFIRMED" and oe:
        _add_key(
            by_number,
            number=oe,
            role="OE",
            source="catalog_oe",
            confidence="confirmed",
            pricing_primary=True,
            raw=str(oe_norm or "").strip() or None,
        )

    # Confirmed identity graph: one-hop public endpoints.
    anchor = oe if status == "OE_CONFIRMED" and oe else ""
    for link in confirmed_identity_links:
        if not isinstance(link, Mapping):
            continue
        if not _link_is_confirmed_for_search(link):
            continue
        left = str(link.get("our_oem_norm") or "").strip()
        right = str(link.get("extracted_oem_norm") or "").strip()
        if not catalog_identity_pair_has_safe_shape(left, right):
            continue
        left_n = _public_normalized(left)
        right_n = _public_normalized(right)
        if not left_n or not right_n:
            continue
        # Prefer the endpoint that is not the catalog OE anchor; if neither
        # matches the anchor, emit both (dedupe handles self-collisions).
        endpoints: list[tuple[str, str]] = []
        if anchor and left_n == anchor and right_n != anchor:
            endpoints.append((right_n, right))
        elif anchor and right_n == anchor and left_n != anchor:
            endpoints.append((left_n, left))
        else:
            if left_n != anchor:
                endpoints.append((left_n, left))
            if right_n != anchor:
                endpoints.append((right_n, right))
        auto = _link_automatic_eligible(link)
        method = str(link.get("extraction_method") or "identity_link").strip()
        for number, raw in endpoints:
            _add_key(
                by_number,
                number=number,
                role="CROSS" if number != oe or status != "OE_CONFIRMED" else "OE",
                source=method or "identity_link",
                confidence="confirmed" if auto else "retrieval_only",
                # Crosses are never pricing_primary here — pricing path still
                # requires the asserted OE (and separate cross admission).
                pricing_primary=False,
                raw=raw or None,
            )

    mpn = _usable_retrieval_number(mpn_norm)
    if mpn:
        # MPN is never pricing_primary for market OE identity; it expands
        # discovery for MPN_ONLY and supplements OE rows that also carry a
        # public supplier article.
        _add_key(
            by_number,
            number=mpn,
            role="PUBLIC_MPN",
            source="catalog_mpn",
            confidence="retrieval_only",
            pricing_primary=False,
            raw=str(mpn_norm or "").strip() or None,
        )
        # Short non-numeric MPN (e.g. ``A1``) is still allowed by
        # ``_usable_retrieval_number`` when not digit-only short — mirror the
        # single-query path for alphanumeric codes shorter than the digit floor.
    elif status == "MPN_ONLY":
        # Keep short alphanumeric MPN as retrieval_only (matches single-query).
        short_mpn = _public_normalized(mpn_norm)
        if short_mpn and not (
            short_mpn.isdigit() and len(short_mpn) < MIN_PUBLIC_QUERY_NUMBER_LENGTH
        ):
            _add_key(
                by_number,
                number=short_mpn,
                role="PUBLIC_MPN",
                source="catalog_mpn",
                confidence="retrieval_only",
                pricing_primary=False,
                raw=str(mpn_norm or "").strip() or None,
            )

    for value in part_numbers_norm:
        number = _usable_retrieval_number(value)
        if not number:
            continue
        _add_key(
            by_number,
            number=number,
            role="PART_NUMBER",
            source="catalog_characteristics",
            confidence="retrieval_only",
            pricing_primary=False,
            raw=str(value or "").strip() or None,
        )

    # Force legacy primary query to the front when provided and public.
    primary = _public_normalized(primary_query) if primary_query else ""
    if primary and primary not in by_number:
        # Primary without a role context is treated as OE when OE_CONFIRMED,
        # otherwise as PART_NUMBER retrieval.
        if status == "OE_CONFIRMED":
            _add_key(
                by_number,
                number=primary,
                role="OE",
                source="primary_query",
                confidence="confirmed",
                pricing_primary=True,
                raw=str(primary_query or "").strip() or None,
            )
        else:
            usable = _usable_retrieval_number(primary_query)
            if usable:
                _add_key(
                    by_number,
                    number=usable,
                    role="PART_NUMBER",
                    source="primary_query",
                    confidence="retrieval_only",
                    pricing_primary=False,
                    raw=str(primary_query or "").strip() or None,
                )
            else:
                short = _public_normalized(primary_query)
                if short and not (
                    short.isdigit() and len(short) < MIN_PUBLIC_QUERY_NUMBER_LENGTH
                ):
                    _add_key(
                        by_number,
                        number=short,
                        role="PUBLIC_MPN",
                        source="primary_query",
                        confidence="retrieval_only",
                        pricing_primary=False,
                        raw=str(primary_query or "").strip() or None,
                    )

    ordered = sorted(
        by_number.values(),
        key=lambda key: (
            0 if primary and key.number == primary else 1,
            0 if key.pricing_primary else 1,
            _ROLE_RANK[key.role],
            0 if key.confidence == "confirmed" else 1,
            key.number,
        ),
    )
    return tuple(ordered)


def public_search_key_numbers(
    keys: Sequence[PublicSearchKey],
    *,
    max_keys: int | None = None,
    roles: frozenset[str] | None = None,
    pricing_primary_only: bool = False,
) -> tuple[str, ...]:
    """Project keys to ordered unique numbers with optional filters."""

    out: list[str] = []
    for key in keys:
        if pricing_primary_only and not key.pricing_primary:
            continue
        if roles is not None and key.role not in roles:
            continue
        out.append(key.number)
        if max_keys is not None and len(out) >= max_keys:
            break
    return tuple(out)


__all__ = [
    "MIN_PUBLIC_QUERY_NUMBER_LENGTH",
    "PublicSearchKey",
    "PublicSearchConfidence",
    "PublicSearchRole",
    "build_public_search_keys",
    "public_search_key_numbers",
]
