"""Workspace catalog assembled from listings of connected owned stores."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import unicodedata
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    Listing,
    MarketplaceStore,
    StoreKind,
    WorkspaceStore,
)


@dataclass(frozen=True)
class OwnedCatalogListing:
    listing_id: UUID
    store_id: UUID
    store_external_id: str
    store_name: str | None
    store_url: str
    name: str
    listing_url: str
    sku: str | None
    model_id: str | None
    brand: str | None
    currency: str
    current_price: Decimal | None
    is_available: bool | None
    image_url: str | None
    oe_raw: str | None


@dataclass(frozen=True)
class OwnedCatalogStorePresence:
    store_id: UUID
    external_id: str
    name: str
    url: str
    listing_url: str
    listing_count: int
    price: Decimal | None
    currency: str
    is_available: bool | None


@dataclass(frozen=True)
class OwnedCatalogProduct:
    id: str
    identity_kind: str
    name: str
    sku: str | None
    oe: str | None
    model_id: str | None
    brand: str | None
    image_url: str | None
    price_min: Decimal | None
    price_max: Decimal | None
    currency: str | None
    listing_count: int
    stores: tuple[OwnedCatalogStorePresence, ...]


@dataclass(frozen=True)
class OwnedCatalogPage:
    items: tuple[OwnedCatalogProduct, ...]
    total: int
    catalog_total: int
    listing_total: int
    duplicates_removed: int
    store_total: int
    limit: int
    offset: int


async def list_owned_catalog(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    query: str | None,
    limit: int,
    offset: int,
) -> OwnedCatalogPage:
    result = await session.execute(_owned_catalog_statement(workspace_id))
    rows = tuple(OwnedCatalogListing(**dict(row)) for row in result.mappings().all())
    return build_owned_catalog_page(
        rows,
        query=query,
        limit=limit,
        offset=offset,
    )


def _owned_catalog_statement(workspace_id: UUID):
    return (
        select(
            Listing.id.label("listing_id"),
            Listing.store_id.label("store_id"),
            MarketplaceStore.external_id.label("store_external_id"),
            MarketplaceStore.name.label("store_name"),
            MarketplaceStore.canonical_url.label("store_url"),
            Listing.name.label("name"),
            Listing.url.label("listing_url"),
            Listing.sku.label("sku"),
            Listing.model_id.label("model_id"),
            Listing.brand.label("brand"),
            Listing.currency.label("currency"),
            Listing.current_price.label("current_price"),
            Listing.is_available.label("is_available"),
            Listing.raw_data["image"].as_string().label("image_url"),
            Listing.raw_data["oe_raw"].as_string().label("oe_raw"),
        )
        .join(MarketplaceStore, MarketplaceStore.id == Listing.store_id)
        .join(WorkspaceStore, WorkspaceStore.store_id == MarketplaceStore.id)
        .where(
            WorkspaceStore.workspace_id == workspace_id,
            WorkspaceStore.kind == StoreKind.owned,
        )
        .order_by(
            MarketplaceStore.external_id,
            Listing.name,
            Listing.id,
        )
    )


def build_owned_catalog_page(
    rows: tuple[OwnedCatalogListing, ...] | list[OwnedCatalogListing],
    *,
    query: str | None,
    limit: int,
    offset: int,
) -> OwnedCatalogPage:
    grouped: dict[tuple[str, str], list[OwnedCatalogListing]] = {}
    for row in rows:
        grouped.setdefault(catalog_identity(row), []).append(row)

    products_with_rows = [
        (_catalog_product(identity, group), group)
        for identity, group in grouped.items()
    ]
    products_with_rows.sort(key=lambda item: (item[0].name.casefold(), item[0].id))

    normalized_query = normalize_catalog_code(query)
    text_query = (query or "").strip().casefold()
    if normalized_query or text_query:
        products_with_rows = [
            item
            for item in products_with_rows
            if _matches_query(
                item[0],
                item[1],
                normalized_query=normalized_query,
                text_query=text_query,
            )
        ]

    catalog_total = len(grouped)
    listing_total = len(rows)
    total = len(products_with_rows)
    return OwnedCatalogPage(
        items=tuple(
            product for product, _ in products_with_rows[offset : offset + limit]
        ),
        total=total,
        catalog_total=catalog_total,
        listing_total=listing_total,
        duplicates_removed=max(0, listing_total - catalog_total),
        store_total=len({row.store_id for row in rows}),
        limit=limit,
        offset=offset,
    )


def catalog_identity(row: OwnedCatalogListing) -> tuple[str, str]:
    brand = normalize_catalog_code(row.brand)
    sku = canonical_catalog_sku(row.sku, row.brand)
    if brand and sku:
        return "brand_sku", f"{brand}:{sku}"

    model_id = (row.model_id or "").strip()
    if model_id:
        return "prom_model", model_id

    oe = normalize_catalog_code(row.oe_raw)
    if brand and oe:
        return "brand_oe", f"{brand}:{oe}"
    if sku and len(sku) >= 3:
        return "sku", sku
    return "listing", f"{row.store_id}:{row.listing_id}"


def canonical_catalog_sku(value: str | None, brand: str | None) -> str:
    sku = normalize_catalog_code(value)
    brand_code = normalize_catalog_code(brand)
    if not sku or not brand_code:
        return sku
    if sku.startswith(brand_code) and len(sku) - len(brand_code) >= 3:
        sku = sku[len(brand_code) :]
    if sku.endswith(brand_code) and len(sku) - len(brand_code) >= 3:
        sku = sku[: -len(brand_code)]
    return sku


def normalize_catalog_code(value: str | None) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value).upper()
    return "".join(character for character in normalized if character.isalnum())


def _catalog_product(
    identity: tuple[str, str],
    rows: list[OwnedCatalogListing],
) -> OwnedCatalogProduct:
    representative = _representative(rows)
    store_groups: dict[UUID, list[OwnedCatalogListing]] = {}
    for row in rows:
        store_groups.setdefault(row.store_id, []).append(row)
    stores = tuple(
        sorted(
            (_store_presence(group) for group in store_groups.values()),
            key=lambda store: (store.name.casefold(), store.external_id),
        )
    )

    currencies = {row.currency for row in rows if row.current_price is not None}
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    prices = (
        [row.current_price for row in rows if row.current_price is not None]
        if currency is not None
        else []
    )
    display_sku = min(
        (value for value in (row.sku for row in rows) if value),
        key=lambda value: (len(normalize_catalog_code(value)), len(value), value),
        default=None,
    )
    oe = next((row.oe_raw for row in rows if row.oe_raw), None)
    stable_id = hashlib.sha256(f"{identity[0]}:{identity[1]}".encode()).hexdigest()
    return OwnedCatalogProduct(
        id=stable_id[:32],
        identity_kind=identity[0],
        name=representative.name,
        sku=display_sku,
        oe=oe,
        model_id=representative.model_id,
        brand=representative.brand,
        image_url=_safe_image_url(representative.image_url),
        price_min=min(prices) if prices else None,
        price_max=max(prices) if prices else None,
        currency=currency,
        listing_count=len(rows),
        stores=stores,
    )


def _store_presence(rows: list[OwnedCatalogListing]) -> OwnedCatalogStorePresence:
    representative = _representative(rows)
    return OwnedCatalogStorePresence(
        store_id=representative.store_id,
        external_id=representative.store_external_id,
        name=representative.store_name or f"Prom {representative.store_external_id}",
        url=representative.store_url,
        listing_url=representative.listing_url,
        listing_count=len(rows),
        price=representative.current_price,
        currency=representative.currency,
        is_available=representative.is_available,
    )


def _representative(rows: list[OwnedCatalogListing]) -> OwnedCatalogListing:
    return min(
        rows,
        key=lambda row: (
            -sum(
                (
                    bool(_safe_image_url(row.image_url)),
                    bool(row.brand),
                    bool(row.sku),
                    row.current_price is not None,
                    row.is_available is not None,
                    bool(row.model_id),
                )
            ),
            -len(row.name),
            row.name.casefold(),
            row.store_external_id,
            str(row.listing_id),
        ),
    )


def _safe_image_url(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized if normalized.startswith(("https://", "http://")) else None


def _matches_query(
    product: OwnedCatalogProduct,
    rows: list[OwnedCatalogListing],
    *,
    normalized_query: str,
    text_query: str,
) -> bool:
    if text_query and any(text_query in row.name.casefold() for row in rows):
        return True
    if not normalized_query:
        return False
    values = (
        product.sku,
        product.oe,
        product.model_id,
        product.brand,
        product.name,
        *(row.sku for row in rows),
        *(row.oe_raw for row in rows),
        *(row.name for row in rows),
    )
    return any(normalized_query in normalize_catalog_code(value) for value in values)


__all__ = [
    "OwnedCatalogListing",
    "OwnedCatalogPage",
    "OwnedCatalogProduct",
    "OwnedCatalogStorePresence",
    "build_owned_catalog_page",
    "canonical_catalog_sku",
    "catalog_identity",
    "list_owned_catalog",
    "normalize_catalog_code",
]
