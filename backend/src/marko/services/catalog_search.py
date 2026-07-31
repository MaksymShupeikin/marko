"""Cross-store fallback for a catalog search that returned nothing locally.

The store catalog page searches one store first. When that store has no row for
the typed text, the same query is replayed against every other store connected
to the workspace and against verified competitor observations, matching on the
normalized OE/SKU identity rather than on wording. Confirmed cross-links widen
the identity so an equivalent OE number still resolves to the right product.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from metis.pricing import normalize_candidate_oem

from marko.infrastructure.db.models import (
    CatalogIdentityLink,
    CrossLink,
    Listing,
    MarketObservation,
    MarketplaceStore,
    PricingRun,
    PricingRunItem,
)

import marko.repositories.listings as listings_repo

#: Shorter fragments match far too many unrelated articles to be useful.
MIN_IDENTITY_LENGTH = 3
MAX_CROSS_STORE_MATCHES = 24

VERIFIED_OE_STATUSES = ("VERIFIED_EXACT", "VERIFIED_CROSS")

MATCHED_ON_OEM = "oem"
MATCHED_ON_SKU = "sku"
MATCHED_ON_NAME = "name"

SOURCE_STORE = "store"
SOURCE_MARKET = "market"


@dataclass(frozen=True)
class CrossStoreMatch:
    """One product found outside the store the operator is looking at."""

    source: str
    store_id: UUID | None
    store_name: str
    marketplace: str
    product_id: UUID | None
    name: str
    url: str
    sku: str | None
    brand: str | None
    price: Decimal | None
    currency: str
    image_url: str | None
    matched_on: str
    matched_value: str
    via_cross: bool


@dataclass(frozen=True)
class CrossStoreSearch:
    query: str
    normalized_query: str
    identities: tuple[str, ...]
    matches: tuple[CrossStoreMatch, ...]


async def search_other_stores(
    session: AsyncSession,
    *,
    store_id: UUID,
    workspace_id: UUID,
    query: str,
    limit: int = MAX_CROSS_STORE_MATCHES,
) -> CrossStoreSearch:
    text = (query or "").strip()
    reference = normalize_candidate_oem(text)
    if len(reference) < MIN_IDENTITY_LENGTH:
        reference = ""

    identities: tuple[str, ...] = ()
    matches: list[CrossStoreMatch] = []

    if reference:
        identities = (
            reference,
            *sorted(
                await _confirmed_cross_oems(
                    session, workspace_id=workspace_id, reference=reference
                )
            ),
        )
        matches.extend(
            _listing_match(listing, store, identities=identities, reference=reference)
            for listing, store in await listings_repo.search_listings_in_other_stores(
                session,
                workspace_id=workspace_id,
                excluded_store_id=store_id,
                identities=identities,
                limit=limit,
            )
        )
        remaining = limit - len(matches)
        if remaining > 0:
            matches.extend(
                await _verified_market_matches(
                    session,
                    workspace_id=workspace_id,
                    identities=identities,
                    reference=reference,
                    limit=remaining,
                )
            )

    if not matches and text:
        # A Cyrillic or descriptive query carries no OE identity at all, so the
        # only honest fallback left is the wording of the other catalogs.
        matches.extend(
            _text_match(listing, store, query=text)
            for listing, store in await listings_repo.search_listing_text_in_other_stores(
                session,
                workspace_id=workspace_id,
                excluded_store_id=store_id,
                query=text,
                limit=limit,
            )
        )

    return CrossStoreSearch(
        query=text,
        normalized_query=reference,
        identities=identities,
        matches=tuple(matches[:limit]),
    )


async def _confirmed_cross_oems(
    session: AsyncSession, *, workspace_id: UUID, reference: str
) -> frozenset[str]:
    """Union of the two link tables — see the note in ``catalog_discovery``.

    Kept as a second implementation rather than shared because the two callers
    normalize their input differently; what must stay identical is the set of
    tables read and the ``CONFIRMED`` filter, which is what the test asserts.
    """

    rows = list(
        (
            await session.execute(
                select(CrossLink.our_oem_norm, CrossLink.extracted_oem_norm).where(
                    CrossLink.workspace_id == workspace_id,
                    CrossLink.validation_status == "CONFIRMED",
                    or_(
                        CrossLink.our_oem_norm == reference,
                        CrossLink.extracted_oem_norm == reference,
                    ),
                )
            )
        ).all()
    )
    rows.extend(
        (
            await session.execute(
                select(
                    CatalogIdentityLink.our_oem_norm,
                    CatalogIdentityLink.extracted_oem_norm,
                ).where(
                    CatalogIdentityLink.workspace_id == workspace_id,
                    CatalogIdentityLink.validation_status == "CONFIRMED",
                    or_(
                        CatalogIdentityLink.our_oem_norm == reference,
                        CatalogIdentityLink.extracted_oem_norm == reference,
                    ),
                )
            )
        ).all()
    )
    equivalents = {
        normalized
        for our_oem, extracted_oem in rows
        for value in (our_oem, extracted_oem)
        if (normalized := normalize_candidate_oem(value)) and normalized != reference
    }
    return frozenset(equivalents)


async def _verified_market_matches(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    identities: tuple[str, ...],
    reference: str,
    limit: int,
) -> list[CrossStoreMatch]:
    """Competitor offers whose OE identity was verified by the pricing pipeline.

    Unverified observations are deliberately left out: presenting them as an
    OE match would claim evidence the collection pipeline never established.
    """

    rows = (
        (
            await session.execute(
                select(MarketObservation)
                .join(
                    PricingRunItem,
                    PricingRunItem.id == MarketObservation.pricing_run_item_id,
                )
                .join(PricingRun, PricingRun.id == PricingRunItem.pricing_run_id)
                .where(
                    PricingRun.workspace_id == workspace_id,
                    MarketObservation.url != "",
                    MarketObservation.oe_verification_status.in_(VERIFIED_OE_STATUSES),
                    MarketObservation.verified_matched_oe_norm.in_(identities),
                )
                .order_by(MarketObservation.observed_at.desc())
                .limit(limit * 4)
            )
        )
        .scalars()
        .all()
    )

    matches: list[CrossStoreMatch] = []
    seen: set[tuple[str, str]] = set()
    for observation in rows:
        key = (observation.seller_id, observation.url)
        if key in seen:
            continue
        seen.add(key)
        matched_value = observation.verified_matched_oe_norm or reference
        matches.append(
            CrossStoreMatch(
                source=SOURCE_MARKET,
                store_id=None,
                store_name=observation.seller_name,
                marketplace=observation.source,
                product_id=None,
                name=observation.title,
                url=observation.url,
                sku=None,
                brand=observation.brand_raw,
                price=observation.sale_price or observation.price,
                currency=observation.currency,
                image_url=None,
                matched_on=MATCHED_ON_OEM,
                matched_value=matched_value,
                via_cross=matched_value != reference,
            )
        )
        if len(matches) == limit:
            break
    return matches


def _listing_match(
    listing: Listing,
    store: MarketplaceStore,
    *,
    identities: tuple[str, ...],
    reference: str,
) -> CrossStoreMatch:
    matched_on, matched_value = _classify_listing(listing, identities)
    return _match(
        listing,
        store,
        matched_on=matched_on,
        matched_value=matched_value,
        via_cross=normalize_candidate_oem(matched_value) != reference,
    )


def _text_match(
    listing: Listing, store: MarketplaceStore, *, query: str
) -> CrossStoreMatch:
    return _match(
        listing,
        store,
        matched_on=MATCHED_ON_NAME,
        matched_value=query,
        via_cross=False,
    )


def _match(
    listing: Listing,
    store: MarketplaceStore,
    *,
    matched_on: str,
    matched_value: str,
    via_cross: bool,
) -> CrossStoreMatch:
    return CrossStoreMatch(
        source=SOURCE_STORE,
        store_id=store.id,
        store_name=_store_name(listing, store),
        marketplace=store.marketplace,
        product_id=listing.id,
        name=listing.name,
        url=listing.url,
        sku=listing.sku,
        brand=listing.brand,
        price=listing.current_price,
        currency=listing.currency,
        image_url=listing.image_url,
        matched_on=matched_on,
        matched_value=matched_value,
        via_cross=via_cross,
    )


def _classify_listing(
    listing: Listing, identities: tuple[str, ...]
) -> tuple[str, str]:
    """Report which field carried the identity, so the UI can justify the hint."""

    candidates: tuple[tuple[str, str, str | None], ...] = (
        (MATCHED_ON_SKU, "sku", listing.sku),
        (MATCHED_ON_SKU, "external_id", listing.external_id),
        (MATCHED_ON_OEM, "model_id", listing.model_id),
        (MATCHED_ON_OEM, "oe_raw", _raw_oe(listing)),
    )
    for matched_on, _field, value in candidates:
        if value and normalize_candidate_oem(value) in identities:
            return matched_on, value

    title = normalize_candidate_oem(listing.name)
    for identity in identities:
        if identity in title:
            return MATCHED_ON_OEM, identity
    return MATCHED_ON_NAME, listing.name


def _raw_oe(listing: Listing) -> str | None:
    raw_data = listing.raw_data
    if not isinstance(raw_data, dict):
        return None
    value = raw_data.get("oe_raw")
    return value if isinstance(value, str) else None


def _store_name(listing: Listing, store: MarketplaceStore) -> str:
    raw_data = listing.raw_data if isinstance(listing.raw_data, dict) else {}
    seller_name = raw_data.get("seller_name")
    if isinstance(seller_name, str) and seller_name.strip():
        return seller_name.strip()
    return (store.name or "").strip() or f"Prom {store.external_id}"


__all__ = [
    "MAX_CROSS_STORE_MATCHES",
    "MIN_IDENTITY_LENGTH",
    "CrossStoreMatch",
    "CrossStoreSearch",
    "search_other_stores",
]
