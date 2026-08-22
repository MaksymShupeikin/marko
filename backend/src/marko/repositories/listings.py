from __future__ import annotations

import uuid
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    Listing,
    MarketplaceStore,
    PriceObservation,
    WorkspaceStore,
)


async def count_listings_for_store(session: AsyncSession, store_id: uuid.UUID) -> int:
    return (
        await session.execute(
            select(func.count(Listing.id)).where(Listing.store_id == store_id)
        )
    ).scalar_one()


async def list_listings_for_store(
    session: AsyncSession, store_id: uuid.UUID, limit: int, offset: int
) -> list[Listing]:
    return list(
        (
            await session.execute(
                select(Listing)
                .where(Listing.store_id == store_id)
                .order_by(Listing.name)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )


def _workspace_listings_query(
    workspace_id: uuid.UUID,
    *,
    query: str | None,
    price_min: float | None,
    price_max: float | None,
):
    statement = (
        select(Listing, MarketplaceStore)
        .join(MarketplaceStore, MarketplaceStore.id == Listing.store_id)
        .join(WorkspaceStore, WorkspaceStore.store_id == Listing.store_id)
        .where(WorkspaceStore.workspace_id == workspace_id)
    )
    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                Listing.name.ilike(pattern),
                Listing.sku.ilike(pattern),
                Listing.brand.ilike(pattern),
            )
        )
    if price_min is not None:
        statement = statement.where(Listing.current_price >= price_min)
    if price_max is not None:
        statement = statement.where(Listing.current_price <= price_max)
    return statement


# Ordering is picked by name so the API never interpolates SQL from the client.
LISTING_ORDERS = {
    "name": Listing.name.asc(),
    "price_asc": Listing.current_price.asc().nulls_last(),
    "price_desc": Listing.current_price.desc().nulls_last(),
    "updated": Listing.last_seen_at.desc(),
}


async def count_workspace_listings(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    query: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
) -> int:
    statement = _workspace_listings_query(
        workspace_id, query=query, price_min=price_min, price_max=price_max
    ).with_only_columns(func.count(Listing.id))
    return (await session.execute(statement)).scalar_one()


async def search_workspace_listings(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    query: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    order: str = "name",
    limit: int = 60,
    offset: int = 0,
) -> list[tuple[Listing, MarketplaceStore]]:
    statement = (
        _workspace_listings_query(
            workspace_id, query=query, price_min=price_min, price_max=price_max
        )
        .order_by(LISTING_ORDERS.get(order, LISTING_ORDERS["name"]), Listing.id)
        .limit(limit)
        .offset(offset)
    )
    return [tuple(row) for row in (await session.execute(statement)).all()]


async def get_listings_by_external_ids(
    session: AsyncSession, store_id: uuid.UUID, external_ids: list[str]
) -> list[Listing]:
    return list(
        (
            await session.execute(
                select(Listing).where(
                    Listing.store_id == store_id,
                    Listing.external_id.in_(external_ids),
                )
            )
        )
        .scalars()
        .all()
    )


async def add_listing(session: AsyncSession, listing: Listing) -> None:
    session.add(listing)


async def add_price_observation(session: AsyncSession, observation: PriceObservation) -> None:
    session.add(observation)
