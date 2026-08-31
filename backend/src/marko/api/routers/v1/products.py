"""Workspace-wide product catalog: search, filter, sort, and management."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

import marko.repositories.listings as listings_repo
from marko.api.dependencies import CurrentUser, WorkspaceManager, get_session
from marko.api.schemas.competitor_prices import CompetitorPriceReportResponse
from marko.api.schemas.stores import (
    BulkDeleteResponse,
    CatalogFilterRequest,
    CatalogPageResponse,
    CatalogProductResponse,
    CatalogSiblingResponse,
    ProductUpdateRequest,
    StoreSyncResponse,
)
from marko.api.sse import competitor_price_stream
from marko.infrastructure.db.models import (
    StoreKind,
    WorkspaceListingOverride,
)
from marko.parsers.prom.client import AsyncHttpClient
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.exceptions import ParseError, RequestFailed
from marko.parsers.prom.parser import parse_product_page
from marko.parsers.prom_export import canonical_product_url, is_export_url
from marko.services.billing import consume_check
from marko.services.bulk_products import (
    BulkDispatchError,
    apply_scraped_product,
    delete_matching,
    ensure_override,
    queue_refresh,
)
from marko.services.competitor_prices import (
    competitor_prices_for_listing,
    listing_search_query,
)
from marko.services.rate_limit import enforce_workspace_limit
from marko.worker.celery_app import celery_app

router = APIRouter()

SortOption = Literal["name", "price_asc", "price_desc", "updated"]
SourceOption = Literal["export", "scrape"]


def _parse_store_ids(raw: str | None) -> list[UUID]:
    try:
        return [
            UUID(value.strip()) for value in (raw or "").split(",") if value.strip()
        ]
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="store_ids має бути списком UUID через кому",
        ) from exc


@router.get("", response_model=CatalogPageResponse)
async def search_products(
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
    q: Annotated[str | None, Query(max_length=200)] = None,
    sort: SortOption = "name",
    price_min: Annotated[float | None, Query(ge=0)] = None,
    price_max: Annotated[float | None, Query(ge=0)] = None,
    source: SourceOption | None = None,
    # UUID магазинів через кому: "id1,id2" — фільтр за кількома одразу.
    store_ids: Annotated[str | None, Query(max_length=2000)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 60,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CatalogPageResponse:
    stores_filter = _parse_store_ids(store_ids)
    group_duplicates = not stores_filter
    rows = await listings_repo.search_workspace_listings(
        session,
        current.workspace_id,
        query=q,
        price_min=price_min,
        price_max=price_max,
        source=source,
        store_ids=stores_filter,
        group_duplicates=group_duplicates,
        order=sort,
        limit=limit,
        offset=offset,
    )
    total = await listings_repo.count_workspace_listings(
        session,
        current.workspace_id,
        query=q,
        price_min=price_min,
        price_max=price_max,
        source=source,
        store_ids=stores_filter,
        group_duplicates=group_duplicates,
    )
    items = [
        _catalog_item(listing, store, kind, override)
        for listing, store, kind, override, _ in rows
    ]
    if group_duplicates:
        group_keys = {
            group_key
            for _, _, kind, _, group_key in rows
            if kind == StoreKind.owned and group_key.startswith("sku:")
        }
        copies_by_group: dict[str, list[listings_repo.OwnedSiblingListing]] = {}
        for copy in await listings_repo.list_owned_siblings(
            session, current.workspace_id, group_keys
        ):
            copies_by_group.setdefault(copy.group_key, []).append(copy)

        enriched: list[CatalogProductResponse] = []
        for item, (_, _, kind, _, group_key) in zip(items, rows, strict=True):
            copies = (
                copies_by_group.get(group_key, [])
                if kind == StoreKind.owned and group_key.startswith("sku:")
                else []
            )
            siblings = [
                CatalogSiblingResponse(
                    listing_id=copy.listing_id,
                    store_id=copy.store_id,
                    store_name=copy.store_name,
                    current_price=copy.current_price,
                    currency=copy.currency,
                    is_available=copy.is_available,
                    url=copy.url,
                )
                for copy in copies
                if copy.listing_id != item.id
            ]
            enriched.append(
                item.model_copy(
                    update={
                        "group_size": 1 + len(siblings),
                        "siblings": siblings,
                    }
                )
            )
        items = enriched

    return CatalogPageResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/bulk/delete", response_model=BulkDeleteResponse)
async def bulk_delete_products(
    payload: CatalogFilterRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: WorkspaceManager,
) -> BulkDeleteResponse:
    """Hide every product the filter matches — the whole catalog, if unfiltered."""
    await enforce_workspace_limit(
        current.workspace_id,
        policy="bulk-mutation",
        limit=10,
        window_seconds=300,
    )
    deleted = await delete_matching(session, current.workspace_id, payload.to_filter())
    return BulkDeleteResponse(deleted=deleted)


@router.post("/bulk/refresh", response_model=StoreSyncResponse)
async def bulk_refresh_products(
    payload: CatalogFilterRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: WorkspaceManager,
) -> StoreSyncResponse:
    """Queue a re-read of every matching product; progress lands in /jobs."""
    await enforce_workspace_limit(
        current.workspace_id,
        policy="bulk-mutation",
        limit=10,
        window_seconds=300,
    )
    try:
        sync_run = await queue_refresh(
            session,
            current.workspace_id,
            payload.to_filter(),
            celery_app=celery_app,
        )
    except BulkDispatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return StoreSyncResponse(
        store_id=sync_run.store_id,
        sync_run_id=sync_run.id,
        status=sync_run.status.value,
    )


@router.patch("/{listing_id}", response_model=CatalogProductResponse)
async def update_product(
    listing_id: UUID,
    payload: ProductUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: WorkspaceManager,
) -> CatalogProductResponse:
    await enforce_workspace_limit(
        current.workspace_id,
        policy="product-mutation",
        limit=30,
        window_seconds=300,
    )
    row = await listings_repo.get_manageable_workspace_listing(
        session,
        current.workspace_id,
        listing_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Товар не знайдено або його не можна редагувати.",
        )

    listing, store, override = row
    override = ensure_override(session, current.workspace_id, listing, override)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(override, field, value)
    override.is_deleted = False

    await session.commit()
    return _catalog_item(listing, store, StoreKind.owned, override)


@router.post("/{listing_id}/refresh", response_model=CatalogProductResponse)
async def refresh_product(
    listing_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: WorkspaceManager,
) -> CatalogProductResponse:
    await enforce_workspace_limit(
        current.workspace_id,
        policy="product-refresh",
        limit=20,
        window_seconds=300,
    )
    row = await listings_repo.get_manageable_workspace_listing(
        session,
        current.workspace_id,
        listing_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Товар не знайдено або його не можна оновити.",
        )
    listing, store, override = row
    target_url = listing.url
    if not target_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="У товару немає посилання (URL) для оновлення даних.",
        )

    client = AsyncHttpClient(ScrapeConfig(page_concurrency=1))
    try:
        try:
            safe_url = canonical_product_url(target_url)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        html = await client.get_html(safe_url)
        prod = parse_product_page(html).product
    except (RequestFailed, ParseError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Не вдалося отримати актуальні дані за посиланням: {exc}",
        ) from exc
    finally:
        await client.close()

    override = ensure_override(session, current.workspace_id, listing, override)
    apply_scraped_product(override, prod)

    await session.commit()
    return _catalog_item(listing, store, StoreKind.owned, override)


@router.delete("/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    listing_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: WorkspaceManager,
) -> Response:
    await enforce_workspace_limit(
        current.workspace_id,
        policy="product-mutation",
        limit=30,
        window_seconds=300,
    )
    row = await listings_repo.get_manageable_workspace_listing(
        session,
        current.workspace_id,
        listing_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Товар не знайдено або його не можна видалити.",
        )
    listing, _, override = row
    override = ensure_override(session, current.workspace_id, listing, override)
    override.is_deleted = True
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{listing_id}/competitor-prices",
    response_model=CompetitorPriceReportResponse,
)
async def competitor_prices(
    listing_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
    refresh: bool = False,
) -> CompetitorPriceReportResponse:
    await enforce_workspace_limit(
        current.workspace_id,
        policy="competitor-search",
        limit=12,
        window_seconds=60,
    )
    await consume_check(session, current.workspace_id)
    try:
        payload = await competitor_prices_for_listing(
            session,
            current.workspace_id,
            listing_id,
            refresh=refresh,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return CompetitorPriceReportResponse.model_validate(payload)


@router.get("/{listing_id}/competitor-prices/stream")
async def competitor_prices_stream(
    listing_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
    refresh: bool = False,
) -> StreamingResponse:
    """Той самий звіт, але з підписами стадій, поки джерела ще збираються."""
    await enforce_workspace_limit(
        current.workspace_id,
        policy="competitor-search",
        limit=12,
        window_seconds=60,
    )
    try:
        query = await listing_search_query(session, current.workspace_id, listing_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    # Пейвол — до старту потоку: у генераторі сесії вже немає (див. sse.py).
    await consume_check(session, current.workspace_id)
    return competitor_price_stream(query, refresh=refresh)


def _catalog_item(
    listing,
    store,
    kind: StoreKind,
    override: WorkspaceListingOverride | None,
) -> CatalogProductResponse:
    raw_data = listing.raw_data if isinstance(listing.raw_data, dict) else {}
    item = CatalogProductResponse.model_validate(listing).model_dump()
    if override is not None:
        for field in ("name", "sku", "brand", "current_price", "is_available"):
            item[field] = getattr(override, field)
    # Оновлення пишеться в overrides, тож свіжість товару — це його synced_at;
    # last_seen_at спільного лістингу лишається часом імпорту.
    synced_at = override.synced_at if override is not None else None
    item.update(
        store_name=store.name,
        marketplace=store.marketplace,
        last_seen_at=synced_at or item["last_seen_at"],
        image_url=override.image_url if override is not None else item["image_url"],
        oem_numbers=[
            str(value)
            for value in (
                override.oem_numbers
                if override is not None
                else raw_data.get("oem_numbers") or []
            )
            if value
        ],
        can_manage=kind == StoreKind.owned,
        source="export" if is_export_url(listing.url) else "scrape",
    )
    return CatalogProductResponse.model_validate(item)
