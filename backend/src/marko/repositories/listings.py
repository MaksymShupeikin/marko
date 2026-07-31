from __future__ import annotations

from collections.abc import Collection, Sequence
import uuid
from sqlalchemy import ColumnElement, and_, or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    Listing,
    MarketplaceStore,
    PriceObservation,
    WorkspaceStore,
)
from marko.services.owned_catalog import normalize_catalog_code


async def count_listings_for_store(
    session: AsyncSession, store_id: uuid.UUID, query: str | None = None
) -> int:
    statement = select(func.count(Listing.id)).where(Listing.store_id == store_id)
    condition = listing_search_condition(query)
    if condition is not None:
        statement = statement.where(condition)
    return (await session.execute(statement)).scalar_one()


async def list_listings_for_store(
    session: AsyncSession,
    store_id: uuid.UUID,
    limit: int,
    offset: int,
    query: str | None = None,
) -> list[Listing]:
    statement = select(Listing).where(Listing.store_id == store_id)
    condition = listing_search_condition(query)
    if condition is not None:
        statement = statement.where(condition)
    return list(
        (
            await session.execute(
                statement.order_by(Listing.name, Listing.id).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )


async def search_listings_in_other_stores(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    excluded_store_id: uuid.UUID,
    identities: Collection[str],
    limit: int,
) -> list[tuple[Listing, MarketplaceStore]]:
    """Listings of every other store of this workspace carrying one identity."""

    condition = listing_identity_condition(identities)
    if condition is None:
        return []
    return await _search_other_stores(
        session,
        workspace_id=workspace_id,
        excluded_store_id=excluded_store_id,
        condition=condition,
        limit=limit,
    )


async def search_listing_text_in_other_stores(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    excluded_store_id: uuid.UUID,
    query: str,
    limit: int,
) -> list[tuple[Listing, MarketplaceStore]]:
    """Free-text fallback for queries that carry no usable OE/SKU identity."""

    condition = listing_search_condition(query)
    if condition is None:
        return []
    return await _search_other_stores(
        session,
        workspace_id=workspace_id,
        excluded_store_id=excluded_store_id,
        condition=condition,
        limit=limit,
    )


async def _search_other_stores(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    excluded_store_id: uuid.UUID,
    condition: ColumnElement[bool],
    limit: int,
) -> list[tuple[Listing, MarketplaceStore]]:
    statement = (
        select(Listing, MarketplaceStore)
        .join(MarketplaceStore, MarketplaceStore.id == Listing.store_id)
        .join(WorkspaceStore, WorkspaceStore.store_id == MarketplaceStore.id)
        .where(
            WorkspaceStore.workspace_id == workspace_id,
            Listing.store_id != excluded_store_id,
            condition,
        )
        .order_by(MarketplaceStore.external_id, Listing.name, Listing.id)
        .limit(limit)
    )
    return [
        (listing, store) for listing, store in (await session.execute(statement)).all()
    ]


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


def listing_search_condition(query: str | None) -> ColumnElement[bool] | None:
    """Catalog search over one listing row.

    Mirrors the workspace catalog matcher in ``owned_catalog``: a raw substring
    of the title, the whole normalized query inside one normalized field, or
    every normalized token present across the row.
    """

    text = (query or "").strip()
    if not text:
        return None

    haystack = _catalog_haystack()
    clauses: list[ColumnElement[bool]] = [
        Listing.name.ilike(_contains_pattern(text), escape="\\")
    ]
    normalized = normalize_catalog_code(text)
    if normalized:
        clauses.append(haystack.like(_contains_pattern(normalized), escape="\\"))
    tokens = _normalized_tokens(text)
    if len(tokens) > 1:
        clauses.append(
            and_(
                *(
                    haystack.like(_contains_pattern(token), escape="\\")
                    for token in tokens
                )
            )
        )
    return or_(*clauses)


def listing_identity_condition(
    identities: Collection[str],
) -> ColumnElement[bool] | None:
    """Match a listing on an OE/SKU identity rather than on free text."""

    values = [identity for identity in dict.fromkeys(identities) if identity]
    if not values:
        return None

    clauses: list[ColumnElement[bool]] = [
        expression.in_(values) for expression in _identity_expressions()
    ]
    title = identity_expression(Listing.name)
    clauses.extend(
        title.like(_contains_pattern(identity), escape="\\") for identity in values
    )
    return or_(*clauses)


def identity_expression(column) -> ColumnElement[str]:
    """Uppercase ASCII-alphanumeric identity, matching ``normalize_candidate_oem``."""

    return func.regexp_replace(
        func.upper(func.coalesce(column, "")), "[^A-Z0-9]", "", "g"
    )


def catalog_code_expression(column) -> ColumnElement[str]:
    """Uppercase alphanumeric form that keeps Cyrillic titles searchable."""

    return func.regexp_replace(
        func.upper(func.coalesce(column, "")), "[^[:alnum:]]", "", "g"
    )


def _identity_expressions() -> tuple[ColumnElement[str], ...]:
    return (
        identity_expression(Listing.sku),
        identity_expression(Listing.model_id),
        identity_expression(Listing.external_id),
        identity_expression(Listing.raw_data["oe_raw"].as_string()),
    )


def _catalog_haystack() -> ColumnElement[str]:
    # The ``|`` separators keep a token from matching across two adjacent
    # fields once normalization has removed their own separators.
    return func.concat_ws(
        "|",
        catalog_code_expression(Listing.name),
        catalog_code_expression(Listing.sku),
        catalog_code_expression(Listing.model_id),
        catalog_code_expression(Listing.brand),
        catalog_code_expression(Listing.external_id),
        catalog_code_expression(Listing.raw_data["oe_raw"].as_string()),
    )


def _normalized_tokens(text: str) -> tuple[str, ...]:
    return tuple(
        token for raw in text.split() if (token := normalize_catalog_code(raw))
    )


def _contains_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


__all__: Sequence[str] = (
    "add_listing",
    "add_price_observation",
    "catalog_code_expression",
    "count_listings_for_store",
    "get_listings_by_external_ids",
    "identity_expression",
    "list_listings_for_store",
    "listing_identity_condition",
    "listing_search_condition",
    "search_listing_text_in_other_stores",
    "search_listings_in_other_stores",
)
