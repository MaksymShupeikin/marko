"""Workspace-wide product catalog: search, filter, sort."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from marko.api.dependencies import CurrentUser, get_session
from marko.api.schemas.stores import CatalogPageResponse, CatalogProductResponse

import marko.repositories.listings as listings_repo

router = APIRouter()

SortOption = Literal["name", "price_asc", "price_desc", "updated"]


@router.get("", response_model=CatalogPageResponse)
async def search_products(
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
    q: Annotated[str | None, Query(max_length=200)] = None,
    sort: SortOption = "name",
    price_min: Annotated[float | None, Query(ge=0)] = None,
    price_max: Annotated[float | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 60,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CatalogPageResponse:
    rows = await listings_repo.search_workspace_listings(
        session,
        current.workspace_id,
        query=q,
        price_min=price_min,
        price_max=price_max,
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
    )
    return CatalogPageResponse(
        items=[_catalog_item(listing, store) for listing, store in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _catalog_item(listing, store) -> CatalogProductResponse:
    raw_data = listing.raw_data if isinstance(listing.raw_data, dict) else {}
    return CatalogProductResponse.model_validate(listing).model_copy(
        update={
            "store_name": store.name,
            "marketplace": store.marketplace,
            "oem_numbers": [
                str(value) for value in (raw_data.get("oem_numbers") or []) if value
            ],
        }
    )
