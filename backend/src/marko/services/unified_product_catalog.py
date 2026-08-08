"""Read the current product catalog across Prom stores and XLSX sources."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    CatalogProduct,
    MarketplaceStore,
    StoreKind,
    WorkspaceStore,
)
from marko.services.owned_catalog import (
    OwnedCatalogPage,
    OwnedCatalogProduct,
    OwnedCatalogStoreOption,
    OwnedCatalogStorePresence,
)
from marko.services.unified_catalog import SOURCE_PROM_STORE


async def list_unified_products(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    query: str | None,
    store_ids: frozenset[UUID] | None,
    limit: int,
    offset: int,
) -> OwnedCatalogPage:
    conditions = [CatalogProduct.workspace_id == workspace_id]
    if store_ids:
        conditions.extend(
            [
                CatalogProduct.source_kind == SOURCE_PROM_STORE,
                CatalogProduct.source_id.in_(store_ids),
            ]
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
    total = int(
        await session.scalar(
            select(func.count(CatalogProduct.id)).where(*conditions)
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
    store_by_id = {store.id: store for store in stores}
    return OwnedCatalogPage(
        items=tuple(_product_view(product, store_by_id) for product in products),
        total=total,
        catalog_total=total,
        listing_total=total,
        duplicates_removed=0,
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
    stores = await _owned_stores(session, workspace_id=workspace_id)
    return _product_view(product, {store.id: store for store in stores})


async def _owned_stores(
    session: AsyncSession,
    *,
    workspace_id: UUID,
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
        ).unique().all()
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
) -> OwnedCatalogProduct:
    presences: tuple[OwnedCatalogStorePresence, ...] = ()
    if product.source_kind == SOURCE_PROM_STORE:
        store = store_by_id.get(product.source_id)
        if store is not None:
            presences = (
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
                ),
            )
    return OwnedCatalogProduct(
        id=str(product.id),
        identity_kind=(
            "oe" if product.oe_norm else "mpn" if product.mpn_norm else "sku"
        ),
        name=product.name,
        sku=product.sku,
        oe=product.oe_norm,
        mpn=product.mpn_norm,
        model_id=product.mpn_norm,
        brand=product.brand,
        image_url=_image_url(product.raw_data),
        price_min=product.current_price,
        price_max=product.current_price,
        currency=product.currency,
        listing_count=1,
        stores=presences,
    )


def _image_url(raw_data: dict | None) -> str | None:
    value = (raw_data or {}).get("image")
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized.startswith(("https://", "http://")) else None


__all__ = ["get_unified_product", "list_unified_products"]
