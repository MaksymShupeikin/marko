"""Catalog-wide actions: one operation applied to every product a filter matches.

The catalog holds tens of thousands of products, so "all" is expressed as the
filter itself, never as a list of ids sent by the client. Deleting is a single
statement; re-reading every product page is a crawl, so it runs as a background
job with progress instead of blocking a request.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from celery import Celery
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import marko.repositories.listings as listings_repo
import marko.repositories.stores as stores_repo
from marko.infrastructure.db.models import (
    Listing,
    SyncRun,
    SyncStatus,
    WorkspaceListingOverride,
)
from marko.infrastructure.db.session import async_session_factory
from marko.parsers.prom.client import AsyncHttpClient
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.exceptions import ParseError, RequestFailed
from marko.parsers.prom.parser import parse_product_page
from marko.parsers.prom_export import canonical_product_url, parse_price
from marko.services.parser_models import Product
from marko.services.price_validation import positive_price_or_none

log = logging.getLogger(__name__)

REFRESH_TASK = "marko.worker.refresh_catalog"
REFRESH_KIND = "catalog_refresh"

_FETCH_CONCURRENCY = 4  # ввічливо до майданчика: це десятки тисяч сторінок
_PROGRESS_EVERY = 25


class BulkDispatchError(RuntimeError):
    """The refresh job could not be queued."""


@dataclass(frozen=True)
class CatalogFilter:
    """The same filter the catalog grid is showing, carried to the worker."""

    query: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    source: str | None = None
    # Рядки, а не UUID: фільтр їде в celery-таску через JSON.
    store_ids: tuple[str, ...] = ()

    def as_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["store_ids"] = list(self.store_ids)
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> CatalogFilter:
        data = data or {}
        return cls(
            query=data.get("query"),
            price_min=data.get("price_min"),
            price_max=data.get("price_max"),
            source=data.get("source"),
            store_ids=tuple(data.get("store_ids") or ()),
        )

    @property
    def store_uuids(self) -> list[UUID]:
        return [UUID(value) for value in self.store_ids]


async def _matching_ids(
    session: AsyncSession, workspace_id: UUID, catalog_filter: CatalogFilter
) -> list[UUID]:
    return await listings_repo.manageable_workspace_listing_ids(
        session,
        workspace_id,
        query=catalog_filter.query,
        price_min=catalog_filter.price_min,
        price_max=catalog_filter.price_max,
        source=catalog_filter.source,
        store_ids=catalog_filter.store_uuids,
    )


async def delete_matching(
    session: AsyncSession, workspace_id: UUID, catalog_filter: CatalogFilter
) -> int:
    """Hide every matching product. One statement, whatever the count."""
    ids = await _matching_ids(session, workspace_id, catalog_filter)
    if not ids:
        return 0
    # asyncpg обмежує запит 32767 параметрами — 50к+ рядків шлемо частинами.
    for chunk in _chunks(ids, 5000):
        statement = pg_insert(WorkspaceListingOverride).values(
            [
                {"workspace_id": workspace_id, "listing_id": listing_id, "is_deleted": True}
                for listing_id in chunk
            ]
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["workspace_id", "listing_id"],
                set_={"is_deleted": True},
            )
        )
    await session.commit()
    return len(ids)


async def queue_refresh(
    session: AsyncSession,
    workspace_id: UUID,
    catalog_filter: CatalogFilter,
    *,
    celery_app: Celery,
) -> SyncRun:
    """Queue a re-read of every matching product from its own page."""
    total = len(await _matching_ids(session, workspace_id, catalog_filter))
    sync_run = await stores_repo.create_sync_run(
        session,
        workspace_id=workspace_id,
        store_id=None,
        kind=REFRESH_KIND,
        status=SyncStatus.queued,
    )
    sync_run.progress_total = total
    await session.commit()

    try:
        result = await asyncio.to_thread(
            celery_app.send_task,
            REFRESH_TASK,
            args=[str(sync_run.id), catalog_filter.as_json()],
        )
    except Exception as exc:
        sync_run.status = SyncStatus.failed
        sync_run.error = f"Не вдалося поставити оновлення в чергу: {exc}"[:4000]
        sync_run.finished_at = datetime.now(UTC)
        await session.commit()
        raise BulkDispatchError(sync_run.error) from exc

    sync_run.task_id = result.id
    await session.commit()
    return sync_run


async def refresh_matching(sync_run_id: UUID, catalog_filter: CatalogFilter) -> int:
    """Worker side: walk the matching products, re-reading each by its URL."""
    async with async_session_factory() as session:
        sync_run = await session.get(SyncRun, sync_run_id)
        if sync_run is None or sync_run.workspace_id is None:
            raise LookupError(f"Sync run {sync_run_id} does not exist")
        workspace_id = sync_run.workspace_id

        rows = await listings_repo.manageable_workspace_listings(
            session,
            workspace_id,
            query=catalog_filter.query,
            price_min=catalog_filter.price_min,
            price_max=catalog_filter.price_max,
            source=catalog_filter.source,
            store_ids=catalog_filter.store_uuids,
        )
        sync_run.status = SyncStatus.running
        sync_run.started_at = datetime.now(UTC)
        sync_run.progress_total = len(rows)
        sync_run.progress_current = 0
        sync_run.error = None
        await session.commit()

        done = 0
        failed = 0
        slots = asyncio.Semaphore(_FETCH_CONCURRENCY)
        async with AsyncHttpClient(
            ScrapeConfig(page_concurrency=_FETCH_CONCURRENCY)
        ) as client:

            async def fetch(listing: Listing) -> tuple[Listing, Product | None]:
                async with slots:
                    try:
                        html = await client.get_html(
                            canonical_product_url(listing.url)
                        )
                        return listing, parse_product_page(html).product
                    except (RequestFailed, ParseError) as exc:
                        log.info("Товар %s не оновлено: %s", listing.id, exc)
                        return listing, None

            for chunk in _chunks(rows, _PROGRESS_EVERY):
                fetched = await asyncio.gather(
                    *(fetch(listing) for listing, _ in chunk)
                )
                for (listing, override), (_, product) in zip(chunk, fetched):
                    done += 1
                    if product is None:
                        failed += 1
                        continue
                    apply_scraped_product(
                        ensure_override(session, workspace_id, listing, override),
                        product,
                    )
                sync_run.progress_current = done
                await session.commit()

        sync_run.status = SyncStatus.completed
        sync_run.finished_at = datetime.now(UTC)
        sync_run.error = (
            f"Не вдалося оновити {failed} з {len(rows)} товарів" if failed else None
        )
        await session.commit()
        return done - failed


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def ensure_override(
    session: AsyncSession,
    workspace_id: UUID,
    listing: Listing,
    override: WorkspaceListingOverride | None,
) -> WorkspaceListingOverride:
    """The workspace's editable layer for a listing, seeded from it when new."""
    if override is not None:
        return override
    raw_data = listing.raw_data if isinstance(listing.raw_data, dict) else {}
    override = WorkspaceListingOverride(
        workspace_id=workspace_id,
        listing_id=listing.id,
        name=listing.name,
        sku=listing.sku,
        brand=listing.brand,
        current_price=listing.current_price,
        is_available=listing.is_available,
        image_url=listing.image_url,
        oem_numbers=[
            str(value) for value in (raw_data.get("oem_numbers") or []) if value
        ],
    )
    session.add(override)
    return override


def apply_scraped_product(
    override: WorkspaceListingOverride, product: Product
) -> None:
    """Mirror the product page: every field the page carries wins, blanks included.

    Зникла ціна чи бренд — це теж дані: товар має виглядати так, як зараз
    виглядає сторінка, інакше каталог тихо носить торішні значення.
    """
    # Порожня назва — це зламаний парс, а не товар без назви.
    if product.name:
        override.name = product.name
    parsed_price = parse_price(product.effective_price)
    if parsed_price is None:
        # A genuinely absent page price remains an explicit absence.
        override.current_price = None
    else:
        # Zero/negative placeholders never destroy a previously valid price.
        valid_price = positive_price_or_none(parsed_price)
        if valid_price is not None:
            override.current_price = valid_price
    override.sku = product.sku
    override.brand = product.brand
    override.image_url = product.image
    override.is_available = product.is_available
    # Сторінка товару не віддає OEM-номери — вони приходять лише з файлу
    # вивантаження. Чистити їх тут означало б зламати пошук конкурентів.
    if product.oem_numbers:
        override.oem_numbers = list(dict.fromkeys(product.oem_numbers))
    override.is_deleted = False
    override.synced_at = datetime.now(UTC)
