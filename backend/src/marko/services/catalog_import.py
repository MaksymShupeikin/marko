"""Service for importing a Prom seller catalog."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    Listing,
    MarketplaceStore,
    PriceObservation,
    StoreKind,
    SyncRun,
    SyncStatus,
)
from marko.infrastructure.db.session import async_session_factory
from marko.parsers.prom.gateway import PromGateway
from marko.parsers.prom_export import (
    ExportFormatError,
    parse_export,
    parse_price,
    seller_of,
)
from marko.services.parser_models import Product

import marko.repositories.stores as stores_repo
import marko.repositories.listings as listings_repo

_BATCH_SIZE = 500


class CatalogImportError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExportImportResult:
    """Outcome of importing one uploaded catalog file."""
    store_id: UUID
    store_name: str
    imported: int
    skipped: int


def parse_product_price(product: Product) -> Decimal | None:
    return parse_price(product.effective_price)


async def import_store_catalog(sync_run_id: UUID, *, task_id: str | None = None) -> int:
    try:
        return await _run_import(sync_run_id, task_id=task_id)
    except Exception as exc:
        await _mark_failed(sync_run_id, exc)
        raise


async def _run_import(
    sync_run_id: UUID,
    *,
    task_id: str | None,
) -> int:
    async with async_session_factory() as session:
        sync_run = await session.get(SyncRun, sync_run_id)
        if sync_run is None:
            raise CatalogImportError(f"Sync run {sync_run_id} does not exist")
        if sync_run.store_id is None:
            raise CatalogImportError(f"Sync run {sync_run_id} has no store")

        store = await session.get(MarketplaceStore, sync_run.store_id)
        if store is None:
            raise CatalogImportError(f"Store {sync_run.store_id} does not exist")

        sync_run.status = SyncStatus.running
        sync_run.started_at = datetime.now(UTC)
        sync_run.error = None
        if task_id and not sync_run.task_id:
            sync_run.task_id = task_id
        await session.commit()

        imported = 0
        batch: list[Product] = []
        gateway = PromGateway()
        async for product in gateway.scrape_strict_async(store.canonical_url):
            batch.append(product)
            if len(batch) >= _BATCH_SIZE:
                imported += await persist_products(session, store.id, batch)
                batch.clear()
                sync_run.progress_current = imported
                # Тумбстоуни знімаємо кожним батчем, а не лише в кінці — інакше
                # при повторному імпорті картки не з'являються до завершення.
                await listings_repo.undelete_listings_for_store(
                    session, sync_run.workspace_id, store.id
                )
                await session.commit()

        if batch:
            imported += await persist_products(session, store.id, batch)

        if imported == 0:
            raise CatalogImportError("Prom returned no valid products for this store")

        await listings_repo.undelete_listings_for_store(
            session, sync_run.workspace_id, store.id
        )

        now = datetime.now(UTC)
        store.last_synced_at = now
        store.logo_url = gateway.company_logo or store.logo_url
        sync_run.status = SyncStatus.completed
        sync_run.progress_current = imported
        sync_run.progress_total = imported
        sync_run.finished_at = now
        await session.commit()
        return imported


async def import_export_file(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    content: bytes,
) -> ExportImportResult:
    """Import a Prom XLSX export into the seller's store, creating it if needed."""
    # openpyxl is CPU-bound: keep it off the event loop.
    products = await asyncio.to_thread(lambda: list(parse_export(BytesIO(content))))
    seller = seller_of(products)
    if seller is None:
        raise ExportFormatError(
            "Не вдалось визначити магазин: у файлі немає посилань на товари Prom."
        )

    store_id = await stores_repo.upsert_marketplace_store(
        session,
        workspace_id=workspace_id,
        marketplace="prom",
        external_id=seller.company_id,
        name=seller.slug,
        canonical_url=seller.listing_url,
    )
    await stores_repo.upsert_workspace_store(
        session,
        workspace_id=workspace_id,
        store_id=store_id,
        kind=StoreKind.owned,
    )

    # ponytail: imported inside the request; move to Celery if files outgrow
    # the client timeout (a 5k-row export takes a few seconds).
    imported = 0
    for start in range(0, len(products), _BATCH_SIZE):
        imported += await persist_products(
            session, store_id, products[start : start + _BATCH_SIZE]
        )

    # Re-activate any previously deleted listing overrides for this store in this workspace
    await listings_repo.undelete_listings_for_store(session, workspace_id, store_id)

    store = await session.get(MarketplaceStore, store_id)
    if store is not None:
        store.last_synced_at = datetime.now(UTC)
    await session.commit()
    return ExportImportResult(
        store_id=store_id,
        store_name=seller.slug,
        imported=imported,
        skipped=len(products) - imported,
    )


async def persist_products(
    session: AsyncSession, store_id: UUID, products: list[Product]
) -> int:
    valid_products = [
        product
        for product in products
        if product.id is not None and product.name and product.url
    ]
    if not valid_products:
        return 0

    external_ids = [str(product.id) for product in valid_products]
    existing_listings = await listings_repo.get_listings_by_external_ids(
        session,
        store_id,
        external_ids,
    )
    existing = {listing.external_id: listing for listing in existing_listings}

    now = datetime.now(UTC)

    for product in valid_products:
        external_id = str(product.id)
        price = parse_product_price(product)
        currency = _currency_code(product.currency)
        listing = existing.get(external_id)
        previous_price = listing.current_price if listing else None
        previous_currency = listing.currency if listing else None
        previous_availability = listing.is_available if listing else None

        if listing is None:
            listing = Listing(
                id=uuid4(),
                store_id=store_id,
                external_id=external_id,
                name=product.name or external_id,
                url=product.url or "",
            )
            await listings_repo.add_listing(session, listing)

        # Scrape and file import fill different fields for the same listing, so
        # a source only overwrites what it actually carries. A field the source
        # left empty keeps whatever the other source stored.
        listing.name = product.name or listing.name
        listing.url = product.url or listing.url
        listing.sku = product.sku or listing.sku
        listing.model_id = product.model_id or listing.model_id
        listing.brand = product.brand or listing.brand
        listing.currency = currency
        if price is not None:
            listing.current_price = price
        if product.is_available is not None:
            listing.is_available = product.is_available
        listing.raw_data = _merge_raw_data(listing.raw_data, product)
        listing.last_seen_at = now

        price_changed = (
            previous_price != price
            or previous_currency != currency
            or previous_availability != product.is_available
        )
        if price is not None and (external_id not in existing or price_changed):
            observation = PriceObservation(
                listing_id=listing.id,
                price=price,
                currency=currency,
                is_available=product.is_available,
                observed_at=now,
            )
            await listings_repo.add_price_observation(session, observation)

    await session.flush()
    return len(valid_products)


def _merge_raw_data(stored: dict | None, product: Product) -> dict:
    """Product fields over the stored snapshot; empty incoming values kept out."""
    incoming = {
        key: value
        for key, value in product.as_dict().items()
        if value not in (None, (), [], "")
    }
    return {**(stored or {}), **incoming}


async def _mark_failed(
    sync_run_id: UUID,
    error: Exception,
) -> None:
    async with async_session_factory() as session:
        sync_run = await session.get(SyncRun, sync_run_id)
        if sync_run is None:
            return
        # Скасований запуск падає, коли celery вбиває задачу — це не помилка.
        if sync_run.status == SyncStatus.cancelled:
            return
        sync_run.status = SyncStatus.failed
        sync_run.error = f"{type(error).__name__}: {error}"[:4000]
        sync_run.finished_at = datetime.now(UTC)
        await session.commit()


def _currency_code(value: str | None) -> str:
    normalized = (value or "UAH").strip().upper()
    return normalized[:3] or "UAH"
