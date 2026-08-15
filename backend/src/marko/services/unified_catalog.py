"""Materialise source-specific evidence as stable workspace products."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    AttentionItem,
    CatalogImportBatch,
    CatalogItem,
    CatalogProduct,
    Listing,
    StoreSyncProductSnapshot,
)
from metis.identifiers import normalize_oem_identifier


SOURCE_PROM_STORE = "PROM_STORE"
SOURCE_XLSX = "XLSX"


def xlsx_source_id(*, workspace_id: UUID, filename: str) -> UUID:
    """Stable source identity for replacement imports of the same workbook."""

    normalized = filename.strip().casefold() or "catalog.xlsx"
    digest = hashlib.md5(
        f"marko:xlsx:{workspace_id}:{normalized}".encode(),
        usedforsecurity=False,
    ).hexdigest()
    return UUID(digest)


async def upsert_prom_products(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    store_id: UUID,
    rows: Sequence[tuple[Listing, dict[str, Any]]],
) -> list[CatalogProduct]:
    """Upsert the current product view for one persisted store-sync chunk."""

    if not rows:
        return []
    source_ids = [listing.external_id for listing, _ in rows]
    existing = {
        product.source_product_id: product
        for product in (
            await session.scalars(
                select(CatalogProduct).where(
                    CatalogProduct.workspace_id == workspace_id,
                    CatalogProduct.source_kind == SOURCE_PROM_STORE,
                    CatalogProduct.source_id == store_id,
                    CatalogProduct.source_product_id.in_(source_ids),
                )
            )
        ).all()
    }
    now = datetime.now(UTC)
    products: list[CatalogProduct] = []
    for listing, payload in rows:
        raw_oe = _text(payload.get("oe_raw"))
        oe_norm = normalize_oem_identifier(raw_oe or "") or None
        product = existing.get(listing.external_id)
        if product is None:
            product = CatalogProduct(
                workspace_id=workspace_id,
                source_kind=SOURCE_PROM_STORE,
                source_id=store_id,
                source_product_id=listing.external_id,
            )
            session.add(product)
        product.listing_id = listing.id
        product.name = listing.name
        product.sku = listing.sku
        # A seller SKU is an internal code until independent evidence says it is
        # an OE. Keeping the two fields apart fixes the old "Код товару == OE"
        # assumption at the unified boundary.
        product.internal_code = listing.sku
        product.oe_raw = raw_oe
        product.oe_norm = oe_norm
        product.mpn_raw = _text(payload.get("mpn_raw") or payload.get("mpn"))
        product.mpn_norm = normalize_oem_identifier(product.mpn_raw or "") or None
        product.brand = listing.brand
        product.category = _category(payload)
        product.description = _text(payload.get("description"))
        product.product_url = listing.url
        product.current_price = listing.current_price
        product.currency = listing.currency
        product.is_available = listing.is_available
        product.identity_status = "UNRESOLVED"
        product.identity_reason = (
            "PROM_EXPLICIT_OE_REQUIRES_VERIFICATION" if oe_norm else "PROM_OE_NOT_FOUND"
        )
        product.raw_data = payload
        product.source_updated_at = now
        products.append(product)

    await session.flush()
    await _ensure_attention_items(session, products)
    return products


async def retire_missing_prom_products(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    store_id: UUID,
    sync_run_id: UUID,
) -> int:
    """Resolve products absent from a completed full store snapshot."""

    seen_product_ids = select(StoreSyncProductSnapshot.external_id).where(
        StoreSyncProductSnapshot.sync_run_id == sync_run_id
    )
    products = list(
        (
            await session.scalars(
                select(CatalogProduct).where(
                    CatalogProduct.workspace_id == workspace_id,
                    CatalogProduct.source_kind == SOURCE_PROM_STORE,
                    CatalogProduct.source_id == store_id,
                    CatalogProduct.source_product_id.not_in(seen_product_ids),
                )
            )
        ).all()
    )
    await _retire_products(session, products)
    return len(products)


async def upsert_xlsx_products(
    session: AsyncSession,
    *,
    batch: CatalogImportBatch,
    items: Sequence[CatalogItem],
) -> list[CatalogProduct]:
    """Upsert imported rows into the same product model used by store sync."""

    if not items:
        return []
    source_id = xlsx_source_id(
        workspace_id=batch.workspace_id,
        filename=batch.filename,
    )
    source_product_ids = [item.sku for item in items]
    existing = {
        product.source_product_id: product
        for product in (
            await session.scalars(
                select(CatalogProduct).where(
                    CatalogProduct.workspace_id == batch.workspace_id,
                    CatalogProduct.source_kind == SOURCE_XLSX,
                    CatalogProduct.source_id == source_id,
                    CatalogProduct.source_product_id.in_(source_product_ids),
                )
            )
        ).all()
    }
    now = datetime.now(UTC)
    products: list[CatalogProduct] = []
    for item in items:
        product = existing.get(item.sku)
        if product is None:
            product = CatalogProduct(
                workspace_id=batch.workspace_id,
                source_kind=SOURCE_XLSX,
                source_id=source_id,
                source_product_id=item.sku,
            )
            session.add(product)
        product.catalog_item_id = item.id
        product.name = item.name
        product.sku = item.sku
        # ``sku`` is the Prom/export row identifier.  The private KEMP join
        # key has its own audited column and must never be reconstructed from
        # SKU (or exposed later as an OE/query token).
        product.internal_code = item.internal_code_norm or None
        product.oe_raw = item.oe_raw or None
        product.oe_norm = item.oe_norm or None
        product.mpn_raw = item.mpn_raw or None
        product.mpn_norm = item.mpn_norm or None
        product.brand = item.brand
        product.category = item.category
        product.description = item.description
        product.product_url = item.product_url
        product.current_price = item.current_price
        product.currency = item.currency
        product.is_available = item.is_available
        product.identity_status = (
            "VERIFIED_EXACT" if item.identity_status == "OE_CONFIRMED" else "UNRESOLVED"
        )
        product.identity_reason = item.identity_reason or "XLSX_IDENTITY_UNRESOLVED"
        product.raw_data = item.raw_row or {}
        product.source_updated_at = now
        products.append(product)

    await session.flush()
    await _ensure_attention_items(session, products)
    missing = list(
        (
            await session.scalars(
                select(CatalogProduct).where(
                    CatalogProduct.workspace_id == batch.workspace_id,
                    CatalogProduct.source_kind == SOURCE_XLSX,
                    CatalogProduct.source_id == source_id,
                    CatalogProduct.source_product_id.not_in(source_product_ids),
                )
            )
        ).all()
    )
    await _retire_products(session, missing)
    return products


async def _ensure_attention_items(
    session: AsyncSession,
    products: Sequence[CatalogProduct],
) -> None:
    if not products:
        return
    product_ids = [product.id for product in products]
    existing = {
        item.product_id: item
        for item in (
            await session.scalars(
                select(AttentionItem).where(AttentionItem.product_id.in_(product_ids))
            )
        ).all()
    }
    for product in products:
        item = existing.get(product.id)
        unavailable = product.is_available is False
        status = (
            "PROCESSING"
            if not unavailable and product.current_price is not None and product.oe_norm
            else "REVIEW_REQUIRED"
        )
        if item is None:
            item = AttentionItem(
                workspace_id=product.workspace_id,
                product_id=product.id,
                status=status,
                severity=(
                    0 if unavailable else 50 if status == "REVIEW_REQUIRED" else 0
                ),
                review_state="RESOLVED" if unavailable else "OPEN",
            )
            session.add(item)
        else:
            item.status = status
            item.severity = (
                0 if unavailable else 50 if status == "REVIEW_REQUIRED" else 0
            )
            item.review_state = "RESOLVED" if unavailable else "OPEN"


async def _retire_products(
    session: AsyncSession,
    products: Sequence[CatalogProduct],
) -> None:
    if not products:
        return
    product_ids = [product.id for product in products]
    attention_items = list(
        (
            await session.scalars(
                select(AttentionItem).where(AttentionItem.product_id.in_(product_ids))
            )
        ).all()
    )
    for product in products:
        product.is_available = False
    for item in attention_items:
        item.review_state = "RESOLVED"
        item.severity = 0


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _category(payload: dict[str, Any]) -> str | None:
    for key in ("category_name", "category", "categoryTitle"):
        if value := _text(payload.get(key)):
            return value[:255]
    return None


__all__ = [
    "SOURCE_PROM_STORE",
    "SOURCE_XLSX",
    "retire_missing_prom_products",
    "upsert_prom_products",
    "upsert_xlsx_products",
    "xlsx_source_id",
]
