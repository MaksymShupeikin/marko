from __future__ import annotations

from dataclasses import dataclass
import uuid
from sqlalchemy import (
    Text,
    and_,
    case,
    cast,
    delete,
    func,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    Listing,
    MarketplaceStore,
    PriceObservation,
    StoreKind,
    WorkspaceListingOverride,
    WorkspaceStore,
)


@dataclass(frozen=True)
class WorkspaceListingView:
    id: uuid.UUID
    name: str
    url: str
    sku: str | None
    brand: str | None
    raw_data: dict | None


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


# Products imported from an XLSX export keep the seller's own subdomain link
# ("kemp-cs2847093.prom.ua/p..."); scraped ones carry a marketplace link.
_EXPORT_URL_PATTERN = "%.prom.ua/%"


# Один фізичний товар лежить у чотирьох власних магазинах під тим самим
# артикулом, але записаним по-різному: у Prom «312783 KEMP», в експорті —
# «312783». Тому ключ групи — артикул без розділових знаків, у верхньому
# регістрі й без хвоста власної марки.
_OWN_BRAND_SUFFIX = "(KEMP)$"


def _group_key():
    sku = _effective(WorkspaceListingOverride.sku, Listing.sku)
    cleaned = func.upper(
        func.regexp_replace(func.coalesce(sku, ""), r"[^0-9A-Za-z]", "", "g")
    )
    stripped = func.regexp_replace(cleaned, _OWN_BRAND_SUFFIX, "")
    # Без артикула групувати нема за чим: товар лишається сам по собі,
    # інакше всі безартикульні картки злиплися б в одну.
    return case((stripped == "", cast(Listing.id, Text)), else_=stripped)


def _group_rank_subquery(workspace_id: uuid.UUID):
    """Представник групи — найдешевша власна картка з додатною ціною.

    Ранжування рахується до фільтрів каталогу: інакше пошук чи ціновий
    діапазон міняли б представника, і той самий товар показувався б то
    однією карткою, то іншою.
    """
    key = _group_key()
    price = _effective(WorkspaceListingOverride.current_price, Listing.current_price)
    # Нульова й порожня ціна представником не стає — з неї не порахувати
    # ні рекомендації, ні порівняння з ринком.
    unpriced = case((or_(price.is_(None), price <= 0), 1), else_=0)
    return (
        select(
            Listing.id.label("listing_id"),
            func.row_number()
            .over(partition_by=key, order_by=(unpriced.asc(), price.asc(), Listing.id.asc()))
            .label("rn"),
            func.count().over(partition_by=key).label("group_size"),
        )
        .join(WorkspaceStore, WorkspaceStore.store_id == Listing.store_id)
        .outerjoin(
            WorkspaceListingOverride,
            and_(
                WorkspaceListingOverride.listing_id == Listing.id,
                WorkspaceListingOverride.workspace_id == workspace_id,
            ),
        )
        .where(
            WorkspaceStore.workspace_id == workspace_id,
            or_(
                WorkspaceListingOverride.is_deleted.is_(None),
                WorkspaceListingOverride.is_deleted.is_(False),
            ),
        )
        .subquery()
    )


def _workspace_listings_query(
    workspace_id: uuid.UUID,
    *,
    query: str | None,
    price_min: float | None,
    price_max: float | None,
    source: str | None = None,
    store_ids: list[uuid.UUID] | None = None,
):
    # Фільтр за магазином — це запит «покажи каталог саме цього магазину»,
    # тож там групування вимикаємо: інакше товар зник би з видачі лише через
    # те, що найдешевша його копія лежить в іншому магазині.
    grouped = not store_ids
    ranks = _group_rank_subquery(workspace_id) if grouped else None
    group_size = ranks.c.group_size if grouped else literal(1)
    statement = (
        select(
            Listing,
            MarketplaceStore,
            WorkspaceStore.kind,
            WorkspaceListingOverride,
            group_size.label("group_size"),
        )
        .join(MarketplaceStore, MarketplaceStore.id == Listing.store_id)
        .join(WorkspaceStore, WorkspaceStore.store_id == Listing.store_id)
        .outerjoin(
            WorkspaceListingOverride,
            and_(
                WorkspaceListingOverride.listing_id == Listing.id,
                WorkspaceListingOverride.workspace_id == workspace_id,
            ),
        )
        .where(
            WorkspaceStore.workspace_id == workspace_id,
            or_(
                WorkspaceListingOverride.is_deleted.is_(None),
                WorkspaceListingOverride.is_deleted.is_(False),
            ),
        )
    )
    if ranks is not None:
        statement = statement.join(
            ranks, ranks.c.listing_id == Listing.id
        ).where(ranks.c.rn == 1)
    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                _effective(WorkspaceListingOverride.name, Listing.name).ilike(pattern),
                _effective(WorkspaceListingOverride.sku, Listing.sku).ilike(pattern),
                _effective(WorkspaceListingOverride.brand, Listing.brand).ilike(pattern),
            )
        )
    if source == "export":
        statement = statement.where(Listing.url.ilike(_EXPORT_URL_PATTERN))
    elif source == "scrape":
        statement = statement.where(~Listing.url.ilike(_EXPORT_URL_PATTERN))
    if store_ids:
        statement = statement.where(Listing.store_id.in_(store_ids))
    if price_min is not None:
        statement = statement.where(
            _effective(
                WorkspaceListingOverride.current_price, Listing.current_price
            )
            >= price_min
        )
    if price_max is not None:
        statement = statement.where(
            _effective(
                WorkspaceListingOverride.current_price, Listing.current_price
            )
            <= price_max
        )
    return statement


# Ordering is picked by name so the API never interpolates SQL from the client.
def _listing_order(order: str):
    price = _effective(
        WorkspaceListingOverride.current_price, Listing.current_price
    )
    orders = {
        "name": _effective(WorkspaceListingOverride.name, Listing.name).asc(),
        "price_asc": price.asc().nulls_last(),
        "price_desc": price.desc().nulls_last(),
        "updated": _effective(
            WorkspaceListingOverride.updated_at, Listing.last_seen_at
        ).desc(),
    }
    return orders.get(order, orders["name"])


async def count_workspace_listings(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    query: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    source: str | None = None,
    store_ids: list[uuid.UUID] | None = None,
) -> int:
    statement = _workspace_listings_query(
        workspace_id,
        query=query,
        price_min=price_min,
        price_max=price_max,
        source=source,
        store_ids=store_ids,
    ).with_only_columns(func.count(Listing.id))
    return (await session.execute(statement)).scalar_one()


async def search_workspace_listings(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    query: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    source: str | None = None,
    store_ids: list[uuid.UUID] | None = None,
    order: str = "name",
    limit: int = 60,
    offset: int = 0,
) -> list[
    tuple[
        Listing,
        MarketplaceStore,
        StoreKind,
        WorkspaceListingOverride | None,
        int,
    ]
]:
    statement = (
        _workspace_listings_query(
            workspace_id,
            query=query,
            price_min=price_min,
            price_max=price_max,
            source=source,
            store_ids=store_ids,
        )
        .order_by(_listing_order(order), Listing.id)
        .limit(limit)
        .offset(offset)
    )
    return [tuple(row) for row in (await session.execute(statement)).all()]


async def list_group_siblings(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    listing_id: uuid.UUID,
) -> list[tuple[Listing, MarketplaceStore, WorkspaceListingOverride | None]]:
    """Ті самі товари у власних магазинах — усі, включно з представником.

    Панель показує, яку ціну поставити в кожному магазині, тож потрібні всі
    копії, а не лише чужі.
    """
    key = _group_key()
    base = (
        select(key.label("group_key"))
        .outerjoin(
            WorkspaceListingOverride,
            and_(
                WorkspaceListingOverride.listing_id == Listing.id,
                WorkspaceListingOverride.workspace_id == workspace_id,
            ),
        )
        .where(Listing.id == listing_id)
        .scalar_subquery()
    )
    statement = (
        select(Listing, MarketplaceStore, WorkspaceListingOverride)
        .join(MarketplaceStore, MarketplaceStore.id == Listing.store_id)
        .join(WorkspaceStore, WorkspaceStore.store_id == Listing.store_id)
        .outerjoin(
            WorkspaceListingOverride,
            and_(
                WorkspaceListingOverride.listing_id == Listing.id,
                WorkspaceListingOverride.workspace_id == workspace_id,
            ),
        )
        .where(
            WorkspaceStore.workspace_id == workspace_id,
            or_(
                WorkspaceListingOverride.is_deleted.is_(None),
                WorkspaceListingOverride.is_deleted.is_(False),
            ),
            key == base,
        )
        .order_by(
            _effective(
                WorkspaceListingOverride.current_price, Listing.current_price
            ).asc()
        )
    )
    return [tuple(row) for row in (await session.execute(statement)).all()]


async def get_workspace_listing(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    listing_id: uuid.UUID,
) -> WorkspaceListingView | None:
    row = (
        await session.execute(
            select(Listing, WorkspaceListingOverride)
            .join(WorkspaceStore, WorkspaceStore.store_id == Listing.store_id)
            .outerjoin(
                WorkspaceListingOverride,
                and_(
                    WorkspaceListingOverride.listing_id == Listing.id,
                    WorkspaceListingOverride.workspace_id == workspace_id,
                ),
            )
            .where(
                WorkspaceStore.workspace_id == workspace_id,
                Listing.id == listing_id,
                or_(
                    WorkspaceListingOverride.is_deleted.is_(None),
                    WorkspaceListingOverride.is_deleted.is_(False),
                ),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    listing, override = row
    raw_data = dict(listing.raw_data or {})
    if override is not None:
        raw_data["image"] = override.image_url
        raw_data["oem_numbers"] = override.oem_numbers or []
    return WorkspaceListingView(
        id=listing.id,
        name=override.name if override is not None else listing.name,
        url=listing.url,
        sku=override.sku if override is not None else listing.sku,
        brand=override.brand if override is not None else listing.brand,
        raw_data=raw_data,
    )


async def get_manageable_workspace_listing(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    listing_id: uuid.UUID,
) -> tuple[
    Listing,
    MarketplaceStore,
    WorkspaceListingOverride | None,
] | None:
    row = (
        await session.execute(
            select(Listing, MarketplaceStore, WorkspaceListingOverride)
            .join(MarketplaceStore, MarketplaceStore.id == Listing.store_id)
            .join(WorkspaceStore, WorkspaceStore.store_id == Listing.store_id)
            .outerjoin(
                WorkspaceListingOverride,
                and_(
                    WorkspaceListingOverride.listing_id == Listing.id,
                    WorkspaceListingOverride.workspace_id == workspace_id,
                ),
            )
            .where(
                WorkspaceStore.workspace_id == workspace_id,
                WorkspaceStore.kind == StoreKind.owned,
                Listing.id == listing_id,
                or_(
                    WorkspaceListingOverride.is_deleted.is_(None),
                    WorkspaceListingOverride.is_deleted.is_(False),
                ),
            )
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1], row[2])


async def manageable_workspace_listings(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    query: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    source: str | None = None,
    store_ids: list[uuid.UUID] | None = None,
) -> list[tuple[Listing, WorkspaceListingOverride | None]]:
    """Every product in the workspace's own stores that the filter matches.

    No paging: catalog-wide actions work on the whole match, not on a page.
    """
    statement = _workspace_listings_query(
        workspace_id,
        query=query,
        price_min=price_min,
        price_max=price_max,
        source=source,
        store_ids=store_ids,
    ).where(WorkspaceStore.kind == StoreKind.owned)
    rows = (
        await session.execute(
            statement.with_only_columns(Listing, WorkspaceListingOverride)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def manageable_workspace_listing_ids(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    query: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    source: str | None = None,
    store_ids: list[uuid.UUID] | None = None,
) -> list[uuid.UUID]:
    statement = (
        _workspace_listings_query(
            workspace_id,
            query=query,
            price_min=price_min,
            price_max=price_max,
            source=source,
            store_ids=store_ids,
        )
        .where(WorkspaceStore.kind == StoreKind.owned)
        .with_only_columns(Listing.id)
    )
    return list((await session.execute(statement)).scalars().all())


def _effective(override_column, listing_column):
    return case(
        (WorkspaceListingOverride.listing_id.is_not(None), override_column),
        else_=listing_column,
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


async def set_listing_oem_numbers(
    session: AsyncSession, listing_id: uuid.UUID, numbers: list[str]
) -> None:
    """Кладе знайдені каталожні номери в raw_data картки, не чіпаючи решти.

    Комітить викликач: репозиторій лише змінює, як і решта функцій тут.
    """
    listing = await session.get(Listing, listing_id)
    if listing is None:
        return
    raw = dict(listing.raw_data or {})
    raw["oem_numbers"] = numbers
    listing.raw_data = raw


async def count_export_listings_for_store(
    session: AsyncSession, store_id: uuid.UUID
) -> int:
    """Скільки товарів магазину приїхало з XLSX-файлу (лінк-піддомен продавця)."""
    statement = (
        select(func.count())
        .select_from(Listing)
        .where(Listing.store_id == store_id, Listing.url.ilike(_EXPORT_URL_PATTERN))
    )
    return (await session.execute(statement)).scalar_one()


async def delete_export_listings_for_store(
    session: AsyncSession, store_id: uuid.UUID
) -> int:
    """Прибирає з магазину все, що прийшло з файлу; Prom-товари не чіпає.

    Спостереження цін і override-и йдуть каскадом (FK ON DELETE CASCADE).
    Повертає кількість видаленого — щоб сервіс мав що записати в лог.
    """
    subquery = select(Listing.id).where(
        Listing.store_id == store_id, Listing.url.ilike(_EXPORT_URL_PATTERN)
    )
    result = await session.execute(
        delete(Listing).where(Listing.id.in_(subquery))
    )
    return result.rowcount or 0


async def add_listing(session: AsyncSession, listing: Listing) -> None:
    session.add(listing)


async def add_price_observation(session: AsyncSession, observation: PriceObservation) -> None:
    session.add(observation)


async def undelete_listings_for_store(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    store_id: uuid.UUID,
) -> None:
    """Restore visibility of store listings for a workspace upon re-import or sync."""
    subquery = select(Listing.id).where(Listing.store_id == store_id)
    # Remove tombstone overrides that had no field edits
    delete_statement = (
        delete(WorkspaceListingOverride)
        .where(
            WorkspaceListingOverride.workspace_id == workspace_id,
            WorkspaceListingOverride.listing_id.in_(subquery),
            WorkspaceListingOverride.is_deleted.is_(True),
            WorkspaceListingOverride.name.is_(None),
            WorkspaceListingOverride.current_price.is_(None),
            WorkspaceListingOverride.sku.is_(None),
            WorkspaceListingOverride.brand.is_(None),
        )
    )
    await session.execute(delete_statement)

    # For any remaining overrides with field edits, unset is_deleted flag
    update_statement = (
        update(WorkspaceListingOverride)
        .where(
            WorkspaceListingOverride.workspace_id == workspace_id,
            WorkspaceListingOverride.listing_id.in_(subquery),
            WorkspaceListingOverride.is_deleted.is_(True),
        )
        .values(is_deleted=False)
    )
    await session.execute(update_statement)

