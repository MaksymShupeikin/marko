"""Permanent seller identities excluded from competitor pricing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

import marko.repositories.stores as stores_repo
from marko.infrastructure.db.models import CompetitorSellerExclusion
from marko.services.parser_models import Seller


@dataclass(frozen=True)
class SellerExclusion:
    marketplace: str
    external_id: str
    slug: str
    canonical_url: str


# Installation-wide own stores. They apply even when a workspace has never
# imported them and therefore intentionally live in code, not tenant rows.
GLOBAL_PROM_SELLER_EXCLUSIONS: tuple[SellerExclusion, ...] = (
    SellerExclusion(
        marketplace="prom",
        external_id="2847093",
        slug="kemp",
        canonical_url="https://prom.ua/ua/c2847093-kemp.html",
    ),
    SellerExclusion(
        marketplace="prom",
        external_id="4015921",
        slug="avtobust",
        canonical_url="https://prom.ua/ua/c4015921-avtobust.html",
    ),
    SellerExclusion(
        marketplace="prom",
        external_id="3325174",
        slug="profparts",
        canonical_url="https://prom.ua/ua/c3325174-profparts.html",
    ),
    SellerExclusion(
        marketplace="prom",
        external_id="3912822",
        slug="parts-avto",
        canonical_url="https://prom.ua/ua/c3912822-parts-avto.html",
    ),
)


async def remember_prom_seller(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    seller: Seller,
) -> UUID:
    """Idempotently persist a parsed Prom seller in the workspace registry."""
    return await stores_repo.upsert_competitor_seller_exclusion(
        session,
        workspace_id=workspace_id,
        marketplace="prom",
        external_id=seller.company_id,
        slug=seller.slug,
        canonical_url=seller.listing_url,
    )


async def load_prom_seller_exclusions(
    session: AsyncSession,
    workspace_id: UUID,
) -> tuple[SellerExclusion, ...]:
    """Preset exclusions plus permanent rows belonging to this workspace."""
    stored = await stores_repo.list_competitor_seller_exclusions(
        session,
        workspace_id,
        marketplace="prom",
    )
    return merge_prom_seller_exclusions(stored)


def merge_prom_seller_exclusions(
    stored: Iterable[CompetitorSellerExclusion | SellerExclusion],
) -> tuple[SellerExclusion, ...]:
    """Normalize, deduplicate, and sort the full Prom exclusion context."""
    merged = {
        (
            item.marketplace.casefold(),
            item.external_id.strip(),
            item.slug.strip().casefold(),
        ): SellerExclusion(
            marketplace=item.marketplace.casefold(),
            external_id=item.external_id.strip(),
            slug=item.slug.strip().casefold(),
            canonical_url=item.canonical_url.strip(),
        )
        for item in GLOBAL_PROM_SELLER_EXCLUSIONS
    }
    for item in stored:
        marketplace = item.marketplace.strip().casefold()
        external_id = item.external_id.strip()
        slug = item.slug.strip().casefold()
        merged[(marketplace, external_id, slug)] = SellerExclusion(
            marketplace=marketplace,
            external_id=external_id,
            slug=slug,
            canonical_url=item.canonical_url.strip(),
        )
    return tuple(merged[key] for key in sorted(merged) if key[0] == "prom")
