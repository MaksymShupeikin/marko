"""Service for importing a Prom seller catalog."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import re
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    Listing,
    MarketplaceStore,
    PriceObservation,
    SyncRun,
    SyncStatus,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.parser_models import Product
from marko.parsers.prom.gateway import PromGateway

import marko.repositories.stores as stores_repo
import marko.repositories.listings as listings_repo

_BATCH_SIZE = 25
_PRICE_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


class CatalogImportError(RuntimeError):
    pass


def parse_product_price(product: Product) -> Decimal | None:
    raw = product.price or product.discounted_price or product.price_original
    if raw is None:
        return None
    normalized = str(raw).replace("\u00a0", "").replace(" ", "").replace(",", ".")
    match = _PRICE_NUMBER_RE.search(normalized)
    if match is None:
        return None
    try:
        return Decimal(match.group()).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


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
        for product in gateway.scrape(store.canonical_url, strict=True):
            batch.append(product)
            if len(batch) >= _BATCH_SIZE:
                imported += await _persist_batch(session, store.id, batch)
                batch.clear()
                sync_run.progress_current = imported
                await session.commit()

        if batch:
            imported += await _persist_batch(session, store.id, batch)

        if imported == 0:
            raise CatalogImportError("Prom returned no valid products for this store")

        now = datetime.now(UTC)
        store.last_synced_at = now
        sync_run.status = SyncStatus.completed
        sync_run.progress_current = imported
        sync_run.progress_total = imported
        sync_run.finished_at = now
        await session.commit()
        return imported


async def _persist_batch(
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
    existing_listings = await listings_repo.get_listings_by_external_ids(session, store_id, external_ids)
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

        listing.name = product.name or listing.name
        listing.url = product.url or listing.url
        listing.sku = product.sku
        listing.model_id = product.model_id
        listing.brand = product.brand
        listing.currency = currency
        listing.current_price = price
        listing.is_available = product.is_available
        listing.raw_data = product.as_dict()
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


async def _mark_failed(
    sync_run_id: UUID,
    error: Exception,
) -> None:
    async with async_session_factory() as session:
        sync_run = await session.get(SyncRun, sync_run_id)
        if sync_run is None:
            return
        sync_run.status = SyncStatus.failed
        sync_run.error = f"{type(error).__name__}: {error}"[:4000]
        sync_run.finished_at = datetime.now(UTC)
        await session.commit()


def _currency_code(value: str | None) -> str:
    normalized = (value or "UAH").strip().upper()
    return normalized[:3] or "UAH"
