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
import re
from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from metis.pricing import CohortRole, normalize_candidate_oem

from marko.infrastructure.db.models import (
    CatalogIdentityLink,
    Listing,
    MarketObservation,
    MarketplaceStore,
    ObservationTierClassification,
    PricingRun,
    PricingRunItem,
    StoreKind,
    WorkspaceStore,
)

import marko.repositories.listings as listings_repo
from marko.services.catalog_identity_safety import (
    catalog_identity_pair_has_safe_shape,
    confirmed_catalog_identity_conditions,
)
from marko.services.offer_identity import persisted_identity_fields_consistent
from marko.services.market_price import effective_observation_price
from marko.services.semantic_candidate_gate import semantic_gate_snapshot_is_current

#: Shorter fragments match far too many unrelated articles to be useful.
MIN_IDENTITY_LENGTH = 3
MAX_CROSS_STORE_MATCHES = 24
SHORT_NUMERIC_IDENTITY_MAX_DIGITS = 6

VERIFIED_OE_STATUSES = ("VERIFIED_EXACT", "VERIFIED_CROSS")
# Only these retained Prom lanes can be rendered as market evidence here.
# Other sources must not accidentally share the numeric seller-id namespace.
PROM_MARKET_OBSERVATION_SOURCES = frozenset(
    {"prom", "prom_public", "prom_legacy_untraced"}
)

MATCHED_ON_OEM = "oem"
MATCHED_ON_SKU = "sku"
MATCHED_ON_NAME = "name"

SOURCE_STORE = "store"
SOURCE_MARKET = "market"

_IDENTIFIER_LABEL_RE = re.compile(
    r"(?:\b(?:oe|oem|art|article|артикул|арт)\b|"
    r"\bpart\s+(?:no|number)\b|"
    r"\bкод\s+(?:запчасти|запчастини|виробника|производителя)\b|[#№])",
    re.IGNORECASE,
)
_IDENTIFIER_BOUNDARY_CHARS = r"A-Za-zА-Яа-яЇїІіЄєҐґ0-9"


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
        # The SQL identity lane intentionally remains broad for compatibility
        # with existing catalog indexes.  Re-check the original title here and
        # discard rows that only matched a normalized substring.  Fetch a small
        # bounded surplus so false title hits do not starve genuine rows.
        listing_rows = await listings_repo.search_listings_in_other_stores(
            session,
            workspace_id=workspace_id,
            excluded_store_id=store_id,
            identities=identities,
            limit=max(limit * 4, limit),
        )
        matches.extend(
            match
            for listing, store in listing_rows
            if (
                match := _listing_match(
                    listing, store, identities=identities, reference=reference
                )
            ).matched_on
            != MATCHED_ON_NAME
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

    if not matches and text and not reference:
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
    """Current global catalog identities, never historical run-local claims."""

    rows = list(
        (
            await session.execute(
                select(
                    CatalogIdentityLink.our_oem_norm,
                    CatalogIdentityLink.extracted_oem_norm,
                ).where(
                    *confirmed_catalog_identity_conditions(workspace_id),
                    or_(
                        CatalogIdentityLink.our_oem_norm == reference,
                        CatalogIdentityLink.extracted_oem_norm == reference,
                    ),
                )
            )
        ).all()
    )
    rows = [
        (our_oem, extracted_oem)
        for our_oem, extracted_oem in rows
        if catalog_identity_pair_has_safe_shape(our_oem, extracted_oem)
    ]
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

    latest_classification = aliased(ObservationTierClassification)
    latest_classification_id = (
        select(latest_classification.id)
        .where(
            latest_classification.market_observation_id == MarketObservation.id
        )
        .order_by(
            latest_classification.classified_at.desc(),
            latest_classification.id.desc(),
        )
        .limit(1)
        .correlate(MarketObservation)
        .scalar_subquery()
    )
    target_classification = aliased(ObservationTierClassification)
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
                    MarketObservation.source.in_(PROM_MARKET_OBSERVATION_SOURCES),
                    MarketObservation.url != "",
                    MarketObservation.oe_verification_status.in_(VERIFIED_OE_STATUSES),
                    MarketObservation.verified_matched_oe_norm.in_(identities),
                    # The UI contract says these are competitors that entered
                    # the calculation, not merely parser hits.  A verified OE
                    # token alone is still manual/review evidence and must not
                    # be presented as a price-bearing competitor.
                    MarketObservation.automatic_eligible.is_(True),
                    MarketObservation.comparability_hard_gate_result == "PASS",
                    MarketObservation.seller_identity_verified.is_(True),
                    MarketObservation.source_provenance_verified.is_(True),
                    # The materialized scalar is not enough for a read path:
                    # a legacy row may still say ``automatic_eligible=true``
                    # after its latest tier classification became owned, KEMP,
                    # used or manual.  Require the current classification and
                    # fail closed when it is missing.
                    exists(
                        select(1).where(
                            target_classification.id == latest_classification_id,
                            target_classification.cohort_role
                            == CohortRole.TARGET_MARKET.value,
                            target_classification.is_owned.is_(False),
                            target_classification.is_kemp.is_(False),
                            target_classification.is_used.is_(False),
                            target_classification.is_dumping.is_(False),
                            target_classification.exclusion_reason.is_(None),
                        )
                    ),
                    ~_owned_prom_seller_exists(
                        workspace_id=workspace_id,
                        seller_id=MarketObservation.seller_id,
                    ),
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
        # ``automatic_eligible`` is a materialized decision, not a timeless
        # truth.  A gate/version or source-locator change must demote an old
        # row even if legacy columns still say PASS/eligible; otherwise this
        # read-only catalog panel would resurrect stale price evidence.
        if not semantic_gate_snapshot_is_current(
            observation.candidate_snapshot,
            expected_source_listing_id=observation.source_listing_id,
            expected_raw_capture_id=observation.raw_capture_id,
            expected_identity_key=observation.comparison_identity_key,
            require_identity_namespace=observation.catalog_item_id is not None,
        ):
            continue
        # The SQL admission above protects the common path. Re-check the
        # denormalized Q/E/V/identity-key projection in Python as well: this
        # catches stale fixtures and alternate-dialect adapters where the
        # scalar flag and snapshot survived but identity fields no longer do.
        if not persisted_identity_fields_consistent(observation):
            continue
        key = (observation.seller_id, observation.url)
        if key in seen:
            continue
        seen.add(key)
        # The SQL predicate already excludes NULL in PostgreSQL, but keep the
        # serialization boundary fail-closed as defense against stale fixtures,
        # alternate dialects and future query refactors.  The search reference
        # is acquisition intent, never proof of the candidate identity.
        matched_value = observation.verified_matched_oe_norm
        if not matched_value:
            continue
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
                price=effective_observation_price(observation),
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


def _owned_prom_seller_exists(*, workspace_id: UUID, seller_id):
    """Build the tenant-scoped owned-seller exclusion for market rows.

    ``seller_id`` is a column expression from the outer observation query, so
    the inner tables are explicitly aliased.  Reusing the outer table names
    would let SQLAlchemy correlate the wrong relation and silently reintroduce
    one of the customer's own Prom storefronts.
    """

    owned_workspace_store = aliased(WorkspaceStore)
    owned_marketplace_store = aliased(MarketplaceStore)
    return exists(
        select(1)
        .select_from(owned_workspace_store)
        .join(
            owned_marketplace_store,
            owned_marketplace_store.id == owned_workspace_store.store_id,
        )
        .where(
            owned_workspace_store.workspace_id == workspace_id,
            owned_workspace_store.kind == StoreKind.owned,
            owned_marketplace_store.marketplace == "prom",
            owned_marketplace_store.external_id == seller_id,
        )
    )


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
        (MATCHED_ON_OEM, "model_id", listing.model_id),
        (MATCHED_ON_OEM, "oe_raw", _raw_oe(listing)),
    )
    for matched_on, _field, value in candidates:
        if value and normalize_candidate_oem(value) in identities:
            return matched_on, value

    for identity in identities:
        if _title_carries_identity(listing.name, identity):
            return MATCHED_ON_OEM, identity
    return MATCHED_ON_NAME, listing.name


def _title_carries_identity(title: str | None, identity: str) -> bool:
    """Accept only an identifier-shaped title hit, never an arbitrary substring.

    ``normalize_candidate_oem`` intentionally removes punctuation.  A plain
    ``identity in normalized_title`` therefore turns ``123456`` into a match
    inside an unrelated longer article.  Keep the original title for boundary
    and label checks while still accepting grouped OE forms such as
    ``1K0 121 251``.
    """

    if not title or not identity:
        return False
    if identity.isdigit() and len(identity) <= SHORT_NUMERIC_IDENTITY_MAX_DIGITS:
        return _short_numeric_title_is_labelled(title, identity)

    pieces = r"[\s./_-]*".join(re.escape(character) for character in identity)
    pattern = re.compile(
        rf"(?<![{_IDENTIFIER_BOUNDARY_CHARS}]){pieces}"
        rf"(?![{_IDENTIFIER_BOUNDARY_CHARS}])",
        re.IGNORECASE,
    )
    return pattern.search(title) is not None


def _short_numeric_title_is_labelled(title: str, identity: str) -> bool:
    pieces = r"[\s./_-]*".join(re.escape(character) for character in identity)
    pattern = re.compile(
        rf"(?<![{_IDENTIFIER_BOUNDARY_CHARS}]){pieces}"
        rf"(?![{_IDENTIFIER_BOUNDARY_CHARS}])",
        re.IGNORECASE,
    )
    for match in pattern.finditer(title):
        prefix = title[max(0, match.start() - 48) : match.start()]
        if _IDENTIFIER_LABEL_RE.search(prefix):
            return True
    return False


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
    "SHORT_NUMERIC_IDENTITY_MAX_DIGITS",
    "CrossStoreMatch",
    "CrossStoreSearch",
    "search_other_stores",
]
