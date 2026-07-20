from __future__ import annotations

import uuid
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import Listing, PriceObservation


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


async def add_price_observation(
    session: AsyncSession, observation: PriceObservation
) -> None:
    session.add(observation)
