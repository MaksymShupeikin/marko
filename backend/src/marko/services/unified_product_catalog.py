"""Excel-centric catalog projection with exact owned Prom listing groups."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    CatalogImportBatch,
    CatalogItem,
    CatalogKempLinkResolution,
    CatalogKempOwnedListingLink,
    CatalogProduct,
    Listing,
    MarketplaceStore,
    StoreKind,
    WorkspaceStore,
)
from marko.services.catalog_data_evidence import catalog_data_evidence
from marko.services.owned_catalog import (
    OwnedCatalogPage,
    OwnedCatalogProduct,
    OwnedCatalogStoreOption,
    OwnedCatalogStorePresence,
)
from marko.services.unified_catalog import SOURCE_PROM_STORE, SOURCE_XLSX


async def list_unified_products(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    query: str | None,
    store_ids: frozenset[UUID] | None,
    limit: int,
    offset: int,
    kemp_status: str | None = None,
    no_oem: bool = False,
) -> OwnedCatalogPage:
    latest_import_batch_id = (
        select(CatalogImportBatch.id)
        .where(
            CatalogImportBatch.workspace_id == workspace_id,
            CatalogImportBatch.status.in_(("completed", "partial")),
        )
        .order_by(CatalogImportBatch.created_at.desc(), CatalogImportBatch.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    current_xlsx_product = exists(
        select(CatalogItem.id).where(
            CatalogItem.id == CatalogProduct.catalog_item_id,
            CatalogItem.import_batch_id == latest_import_batch_id,
        )
    )
    latest_resolution_for_link = (
        select(CatalogKempLinkResolution.id)
        .where(
            CatalogKempLinkResolution.workspace_id == workspace_id,
            CatalogKempLinkResolution.catalog_item_id
            == CatalogKempOwnedListingLink.catalog_item_id,
        )
        .order_by(
            CatalogKempLinkResolution.created_at.desc(),
            CatalogKempLinkResolution.id.desc(),
        )
        .limit(1)
        .correlate(CatalogKempOwnedListingLink)
        .scalar_subquery()
    )
    linked_listing = exists(
        select(CatalogKempOwnedListingLink.id).where(
            CatalogKempOwnedListingLink.workspace_id == workspace_id,
            CatalogKempOwnedListingLink.listing_id == CatalogProduct.listing_id,
            CatalogKempOwnedListingLink.resolution_id == latest_resolution_for_link,
        )
    )
    conditions = [
        CatalogProduct.workspace_id == workspace_id,
        or_(
            ((CatalogProduct.source_kind == SOURCE_XLSX) & current_xlsx_product),
            ((CatalogProduct.source_kind == SOURCE_PROM_STORE) & ~linked_listing),
        ),
    ]
    if store_ids:
        canonical_in_store = exists(
            select(CatalogKempOwnedListingLink.id).where(
                CatalogKempOwnedListingLink.workspace_id == workspace_id,
                CatalogKempOwnedListingLink.catalog_item_id
                == CatalogProduct.catalog_item_id,
                CatalogKempOwnedListingLink.store_id.in_(store_ids),
            )
        )
        conditions.append(
            or_(CatalogProduct.source_id.in_(store_ids), canonical_in_store)
        )
    if normalized := (query or "").strip():
        pattern = f"%{normalized}%"
        conditions.append(
            or_(
                CatalogProduct.name.ilike(pattern),
                CatalogProduct.sku.ilike(pattern),
                CatalogProduct.internal_code.ilike(pattern),
                CatalogProduct.oe_norm.ilike(pattern),
                CatalogProduct.mpn_norm.ilike(pattern),
                CatalogProduct.brand.ilike(pattern),
            )
        )
    if no_oem:
        conditions.append(
            or_(CatalogProduct.oe_norm.is_(None), CatalogProduct.oe_norm == "")
        )
    if kemp_status:
        latest_status = (
            select(CatalogKempLinkResolution.status)
            .where(
                CatalogKempLinkResolution.catalog_item_id
                == CatalogProduct.catalog_item_id
            )
            .order_by(
                CatalogKempLinkResolution.created_at.desc(),
                CatalogKempLinkResolution.id.desc(),
            )
            .limit(1)
            .scalar_subquery()
        )
        conditions.append(latest_status == kemp_status)

    filtered_products = (
        select(
            CatalogProduct.id.label("product_id"),
            CatalogProduct.catalog_item_id.label("catalog_item_id"),
        )
        .where(*conditions)
        .subquery()
    )
    total = int(
        await session.scalar(select(func.count()).select_from(filtered_products)) or 0
    )
    latest_resolutions = (
        select(
            CatalogKempLinkResolution.id.label("resolution_id"),
            CatalogKempLinkResolution.catalog_item_id.label("catalog_item_id"),
            func.row_number()
            .over(
                partition_by=CatalogKempLinkResolution.catalog_item_id,
                order_by=(
                    CatalogKempLinkResolution.created_at.desc(),
                    CatalogKempLinkResolution.id.desc(),
                ),
            )
            .label("rank"),
        )
        .where(CatalogKempLinkResolution.workspace_id == workspace_id)
        .subquery()
    )
    hidden_listing_count = int(
        await session.scalar(
            select(func.count(CatalogKempOwnedListingLink.id))
            .join(
                latest_resolutions,
                latest_resolutions.c.resolution_id
                == CatalogKempOwnedListingLink.resolution_id,
            )
            .join(
                filtered_products,
                filtered_products.c.catalog_item_id
                == CatalogKempOwnedListingLink.catalog_item_id,
            )
            .where(latest_resolutions.c.rank == 1)
        )
        or 0
    )
    products = list(
        (
            await session.scalars(
                select(CatalogProduct)
                .where(*conditions)
                .order_by(CatalogProduct.name, CatalogProduct.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    stores = await _owned_stores(session, workspace_id=workspace_id)
    item_ids = {
        product.catalog_item_id for product in products if product.catalog_item_id
    }
    items = (
        {
            item.id: item
            for item in (
                await session.scalars(
                    select(CatalogItem).where(CatalogItem.id.in_(item_ids))
                )
            ).all()
        }
        if item_ids
        else {}
    )
    resolutions = (
        list(
            (
                await session.scalars(
                    select(CatalogKempLinkResolution)
                    .where(CatalogKempLinkResolution.catalog_item_id.in_(item_ids))
                    .order_by(
                        CatalogKempLinkResolution.catalog_item_id,
                        CatalogKempLinkResolution.created_at.desc(),
                        CatalogKempLinkResolution.id.desc(),
                    )
                )
            ).all()
        )
        if item_ids
        else []
    )
    latest_by_item: dict[UUID, CatalogKempLinkResolution] = {}
    for resolution in resolutions:
        latest_by_item.setdefault(resolution.catalog_item_id, resolution)
    resolution_ids = {resolution.id for resolution in latest_by_item.values()}
    links = (
        list(
            (
                await session.scalars(
                    select(CatalogKempOwnedListingLink).where(
                        CatalogKempOwnedListingLink.resolution_id.in_(resolution_ids)
                    )
                )
            ).all()
        )
        if resolution_ids
        else []
    )
    listing_ids = {link.listing_id for link in links}
    listings = (
        {
            listing.id: listing
            for listing in (
                await session.scalars(
                    select(Listing).where(Listing.id.in_(listing_ids))
                )
            ).all()
        }
        if listing_ids
        else {}
    )
    links_by_resolution: dict[UUID, list[CatalogKempOwnedListingLink]] = defaultdict(
        list
    )
    for link in links:
        links_by_resolution[link.resolution_id].append(link)
    store_by_id = {store.id: store for store in stores}
    return OwnedCatalogPage(
        items=tuple(
            _product_view(
                product,
                store_by_id,
                item=items.get(product.catalog_item_id),
                resolution=latest_by_item.get(product.catalog_item_id),
                links=links_by_resolution.get(
                    latest_by_item[product.catalog_item_id].id, ()
                )
                if product.catalog_item_id in latest_by_item
                else (),
                listings=listings,
            )
            for product in products
        ),
        total=total,
        # These are filtered-set totals, never page-local counts.  Each exact
        # owned card hidden under its Excel product is still conserved in the
        # listing total and reported as one merged duplicate.
        catalog_total=total,
        listing_total=total + hidden_listing_count,
        duplicates_removed=hidden_listing_count,
        store_total=len(stores),
        stores=tuple(_store_option(store) for store in stores),
        limit=limit,
        offset=offset,
    )


async def get_unified_product(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    product_id: UUID,
) -> OwnedCatalogProduct | None:
    product = await session.scalar(
        select(CatalogProduct).where(
            CatalogProduct.id == product_id,
            CatalogProduct.workspace_id == workspace_id,
        )
    )
    if product is None:
        return None
    # Legacy Prom deep links resolve to their canonical Excel product.
    if product.source_kind == SOURCE_PROM_STORE and product.listing_id:
        latest_resolution_for_link = (
            select(CatalogKempLinkResolution.id)
            .where(
                CatalogKempLinkResolution.workspace_id == workspace_id,
                CatalogKempLinkResolution.catalog_item_id
                == CatalogKempOwnedListingLink.catalog_item_id,
            )
            .order_by(
                CatalogKempLinkResolution.created_at.desc(),
                CatalogKempLinkResolution.id.desc(),
            )
            .limit(1)
            .correlate(CatalogKempOwnedListingLink)
            .scalar_subquery()
        )
        link = await session.scalar(
            select(CatalogKempOwnedListingLink)
            .where(
                CatalogKempOwnedListingLink.workspace_id == workspace_id,
                CatalogKempOwnedListingLink.listing_id == product.listing_id,
                CatalogKempOwnedListingLink.resolution_id == latest_resolution_for_link,
            )
            .order_by(CatalogKempOwnedListingLink.created_at.desc())
            .limit(1)
        )
        if link is not None:
            canonical = await session.scalar(
                select(CatalogProduct).where(
                    CatalogProduct.workspace_id == workspace_id,
                    CatalogProduct.source_kind == SOURCE_XLSX,
                    CatalogProduct.catalog_item_id == link.catalog_item_id,
                )
            )
            if canonical is not None:
                product = canonical
    stores = await _owned_stores(session, workspace_id=workspace_id)
    item = (
        await session.get(CatalogItem, product.catalog_item_id)
        if product.catalog_item_id
        else None
    )
    resolution = None
    links: list[CatalogKempOwnedListingLink] = []
    listings: dict[UUID, Listing] = {}
    if product.catalog_item_id:
        resolution = await session.scalar(
            select(CatalogKempLinkResolution)
            .where(
                CatalogKempLinkResolution.workspace_id == workspace_id,
                CatalogKempLinkResolution.catalog_item_id == product.catalog_item_id,
            )
            .order_by(
                CatalogKempLinkResolution.created_at.desc(),
                CatalogKempLinkResolution.id.desc(),
            )
            .limit(1)
        )
    if resolution is not None:
        links = list(
            (
                await session.scalars(
                    select(CatalogKempOwnedListingLink).where(
                        CatalogKempOwnedListingLink.workspace_id == workspace_id,
                        CatalogKempOwnedListingLink.resolution_id == resolution.id,
                    )
                )
            ).all()
        )
        listing_ids = {link.listing_id for link in links}
        if listing_ids:
            listings = {
                listing.id: listing
                for listing in (
                    await session.scalars(
                        select(Listing).where(Listing.id.in_(listing_ids))
                    )
                ).all()
            }
    return _product_view(
        product,
        {store.id: store for store in stores},
        item=item,
        resolution=resolution,
        links=links,
        listings=listings,
    )


async def _owned_stores(
    session: AsyncSession, *, workspace_id: UUID
) -> list[MarketplaceStore]:
    return list(
        (
            await session.scalars(
                select(MarketplaceStore)
                .join(WorkspaceStore, WorkspaceStore.store_id == MarketplaceStore.id)
                .where(
                    WorkspaceStore.workspace_id == workspace_id,
                    WorkspaceStore.kind == StoreKind.owned,
                )
                .order_by(MarketplaceStore.name, MarketplaceStore.external_id)
            )
        )
        .unique()
        .all()
    )


def _store_option(store: MarketplaceStore) -> OwnedCatalogStoreOption:
    return OwnedCatalogStoreOption(
        store_id=store.id,
        external_id=store.external_id,
        name=(store.name or "").strip() or f"Prom {store.external_id}",
    )


def _product_view(
    product: CatalogProduct,
    store_by_id: dict[UUID, MarketplaceStore],
    *,
    item: CatalogItem | None = None,
    resolution: CatalogKempLinkResolution | None = None,
    links: tuple[CatalogKempOwnedListingLink, ...]
    | list[CatalogKempOwnedListingLink] = (),
    listings: dict[UUID, Listing] | None = None,
) -> OwnedCatalogProduct:
    listing_map = listings or {}
    presences: list[OwnedCatalogStorePresence] = []
    for link in links:
        listing = listing_map.get(link.listing_id)
        store = store_by_id.get(link.store_id)
        if listing is None or store is None:
            continue
        presences.append(
            OwnedCatalogStorePresence(
                store_id=store.id,
                external_id=store.external_id,
                name=(store.name or "").strip() or f"Prom {store.external_id}",
                url=store.canonical_url,
                listing_url=listing.url,
                listing_count=1,
                price=listing.current_price,
                currency=listing.currency,
                is_available=listing.is_available,
                is_owned=True,
                listing_id=listing.id,
                source_listing_id=listing.external_id,
                snapshot_at=listing.last_seen_at,
            )
        )
    if product.source_kind == SOURCE_PROM_STORE and not presences:
        store = store_by_id.get(product.source_id)
        if store is not None:
            presences.append(
                OwnedCatalogStorePresence(
                    store_id=store.id,
                    external_id=store.external_id,
                    name=(store.name or "").strip() or f"Prom {store.external_id}",
                    url=store.canonical_url,
                    listing_url=product.product_url or store.canonical_url,
                    listing_count=1,
                    price=product.current_price,
                    currency=product.currency,
                    is_available=product.is_available,
                    is_owned=True,
                    listing_id=product.listing_id,
                    source_listing_id=product.source_product_id,
                    snapshot_at=product.source_updated_at,
                )
            )
    prices = [presence.price for presence in presences if presence.price is not None]
    evidence = catalog_data_evidence(item).as_dict() if item is not None else None
    return OwnedCatalogProduct(
        id=str(product.id),
        identity_kind="oe" if product.oe_norm else "mpn" if product.mpn_norm else "sku",
        name=product.name,
        sku=product.sku,
        oe=product.oe_norm,
        mpn=product.mpn_norm,
        model_id=product.mpn_norm,
        brand=product.brand,
        image_url=_image_url(product.raw_data),
        price_min=min(prices) if prices else product.current_price,
        price_max=max(prices) if prices else product.current_price,
        currency=(presences[0].currency if presences else product.currency),
        listing_count=(
            len(presences)
            if product.source_kind == SOURCE_XLSX
            else max(1, len(presences))
        ),
        stores=tuple(presences),
        internal_code=product.internal_code,
        kemp_link_status=(
            resolution.status
            if resolution is not None
            else "UNLINKED_PROM_DIAGNOSTIC"
            if product.source_kind == SOURCE_PROM_STORE
            else None
        ),
        identity_status=item.identity_status
        if item is not None
        else product.identity_status,
        catalog_data_evidence=evidence,
        owned_listings=tuple(presences),
    )


def _image_url(raw_data: dict | None) -> str | None:
    value = (raw_data or {}).get("image")
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized.startswith(("https://", "http://")) else None


__all__ = ["get_unified_product", "list_unified_products"]
