from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from marko.api.routers.v1 import products
from marko.infrastructure.db.base import Base
from marko.infrastructure.db.models import (
    Listing,
    MarketplaceStore,
    StoreKind,
    Workspace,
    WorkspaceListingOverride,
    WorkspaceStore,
)


class AsyncSessionAdapter:
    """Run async repository functions against deterministic in-memory SQLite."""

    def __init__(self, session: Session) -> None:
        self.sync_session = session

    async def execute(self, statement):
        return self.sync_session.execute(statement)


@pytest.fixture
def catalog_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Workspace.__table__,
            MarketplaceStore.__table__,
            WorkspaceStore.__table__,
            Listing.__table__,
            WorkspaceListingOverride.__table__,
        ],
    )
    with Session(engine) as session:
        workspace = Workspace(name="Grouping", slug=f"grouping-{uuid4()}")
        session.add(workspace)
        session.flush()
        yield session, AsyncSessionAdapter(session), workspace.id
    engine.dispose()


def _store(
    session: Session,
    workspace_id: UUID,
    name: str,
    *,
    kind: StoreKind = StoreKind.owned,
) -> MarketplaceStore:
    store = MarketplaceStore(
        workspace_id=workspace_id,
        marketplace="prom",
        external_id=str(uuid4()),
        name=name,
        canonical_url=f"https://{name.lower()}.prom.ua/ua/",
    )
    session.add(store)
    session.flush()
    session.add(
        WorkspaceStore(
            workspace_id=workspace_id,
            store_id=store.id,
            kind=kind,
        )
    )
    session.flush()
    return store


def _listing(
    session: Session,
    store: MarketplaceStore,
    *,
    sku: str | None,
    price: str | None,
    name: str | None = None,
    is_available: bool | None = True,
) -> Listing:
    listing_id = uuid4()
    listing = Listing(
        id=listing_id,
        store_id=store.id,
        external_id=str(listing_id),
        name=name or f"Product {listing_id}",
        url=f"https://prom.ua/p{listing_id}.html",
        sku=sku,
        model_id=None,
        brand="Brand",
        currency="UAH",
        current_price=Decimal(price) if price is not None else None,
        is_available=is_available,
        raw_data={},
    )
    session.add(listing)
    session.flush()
    return listing


def _override(
    session: Session,
    workspace_id: UUID,
    listing: Listing,
    **values,
) -> WorkspaceListingOverride:
    fields = {
        "name": listing.name,
        "sku": listing.sku,
        "brand": listing.brand,
        "current_price": listing.current_price,
        "is_available": listing.is_available,
        "image_url": listing.image_url,
        "oem_numbers": [],
    }
    fields.update(values)
    override = WorkspaceListingOverride(
        workspace_id=workspace_id,
        listing_id=listing.id,
        **fields,
    )
    session.add(override)
    session.flush()
    return override


async def _search(async_session: AsyncSessionAdapter, workspace_id: UUID, **values):
    defaults = {
        "q": None,
        "sort": "name",
        "price_min": None,
        "price_max": None,
        "source": None,
        "store_ids": None,
        "limit": 60,
        "offset": 0,
    }
    defaults.update(values)
    return await products.search_products(
        async_session,
        SimpleNamespace(workspace_id=workspace_id),
        **defaults,
    )


async def test_groups_owned_copies_by_sku_and_returns_cheapest_with_sibling(
    catalog_db,
):
    session, async_session, workspace_id = catalog_db
    cheap_store = _store(session, workspace_id, "KEMP")
    expensive_store = _store(session, workspace_id, "Avtobust")
    cheap = _listing(session, cheap_store, sku="ABC-1", price="1000")
    expensive = _listing(session, expensive_store, sku="ABC-1", price="1200")

    page = await _search(async_session, workspace_id)

    assert page.total == 1
    assert [item.id for item in page.items] == [cheap.id]
    assert page.items[0].current_price == Decimal(1000)
    assert page.items[0].group_size == 2
    assert len(page.items[0].siblings) == 1
    sibling = page.items[0].siblings[0]
    assert sibling.listing_id == expensive.id
    assert sibling.store_id == expensive_store.id
    assert sibling.store_name == "Avtobust"
    assert sibling.current_price == Decimal(1200)


async def test_normalizes_sku_case_and_whitespace(catalog_db):
    session, async_session, workspace_id = catalog_db
    first_store = _store(session, workspace_id, "First")
    second_store = _store(session, workspace_id, "Second")
    cheap = _listing(session, first_store, sku="  AbC-1 ", price="100")
    _listing(session, second_store, sku="abc-1", price="120")

    page = await _search(async_session, workspace_id)

    assert page.total == 1
    assert page.items[0].id == cheap.id
    assert page.items[0].group_size == 2


async def test_blank_and_null_skus_remain_individual_cards(catalog_db):
    session, async_session, workspace_id = catalog_db
    first_store = _store(session, workspace_id, "First")
    second_store = _store(session, workspace_id, "Second")
    blank = _listing(session, first_store, sku="   ", price="100")
    missing = _listing(session, second_store, sku=None, price="120")

    page = await _search(async_session, workspace_id)

    assert page.total == 2
    assert {item.id for item in page.items} == {blank.id, missing.id}
    assert all(item.group_size == 1 and item.siblings == [] for item in page.items)


async def test_store_filter_disables_grouping(catalog_db):
    session, async_session, workspace_id = catalog_db
    first_store = _store(session, workspace_id, "First")
    second_store = _store(session, workspace_id, "Second")
    first = _listing(session, first_store, sku="SAME", price="100")
    second = _listing(session, second_store, sku="SAME", price="120")

    page = await _search(
        async_session,
        workspace_id,
        store_ids=f"{first_store.id},{second_store.id}",
    )

    assert page.total == 2
    assert {item.id for item in page.items} == {first.id, second.id}
    assert all(item.group_size == 1 and item.siblings == [] for item in page.items)


async def test_lower_override_price_changes_group_representative(catalog_db):
    session, async_session, workspace_id = catalog_db
    first_store = _store(session, workspace_id, "First")
    second_store = _store(session, workspace_id, "Second")
    original_cheap = _listing(session, first_store, sku="SAME", price="1000")
    overridden = _listing(session, second_store, sku="SAME", price="1200")
    _override(session, workspace_id, overridden, current_price=Decimal(900))

    page = await _search(async_session, workspace_id)

    assert page.total == 1
    assert page.items[0].id == overridden.id
    assert page.items[0].current_price == Decimal(900)
    assert page.items[0].siblings[0].listing_id == original_cheap.id


async def test_representative_prefers_available_positive_price_then_cheapest(
    catalog_db,
):
    session, async_session, workspace_id = catalog_db
    first_store = _store(session, workspace_id, "First")
    second_store = _store(session, workspace_id, "Second")
    third_store = _store(session, workspace_id, "Third")
    _listing(session, first_store, sku="SAME", price="0")
    _listing(session, second_store, sku="SAME", price="800", is_available=False)
    available = _listing(
        session, third_store, sku="SAME", price="1000", is_available=True
    )

    page = await _search(async_session, workspace_id)

    assert page.total == 1
    assert page.items[0].id == available.id
    assert page.items[0].current_price == Decimal(1000)


async def test_deleted_copy_is_absent_from_group_and_siblings(catalog_db):
    session, async_session, workspace_id = catalog_db
    first_store = _store(session, workspace_id, "First")
    second_store = _store(session, workspace_id, "Second")
    visible = _listing(session, first_store, sku="SAME", price="100")
    deleted = _listing(session, second_store, sku="SAME", price="120")
    _override(session, workspace_id, deleted, is_deleted=True)

    page = await _search(async_session, workspace_id)

    assert page.total == 1
    assert page.items[0].id == visible.id
    assert page.items[0].group_size == 1
    assert page.items[0].siblings == []


async def test_competitor_store_with_same_sku_remains_separate(catalog_db):
    session, async_session, workspace_id = catalog_db
    first_store = _store(session, workspace_id, "First")
    second_store = _store(session, workspace_id, "Second")
    competitor_store = _store(
        session,
        workspace_id,
        "Competitor",
        kind=StoreKind.competitor,
    )
    cheap = _listing(session, first_store, sku="SAME", price="100")
    _listing(session, second_store, sku="SAME", price="120")
    competitor = _listing(session, competitor_store, sku="SAME", price="90")

    page = await _search(async_session, workspace_id)

    assert page.total == 2
    assert {item.id for item in page.items} == {cheap.id, competitor.id}
    own_item = next(item for item in page.items if item.id == cheap.id)
    competitor_item = next(item for item in page.items if item.id == competitor.id)
    assert own_item.group_size == 2
    assert competitor_item.group_size == 1


async def test_price_sort_pagination_and_group_total_remain_consistent(catalog_db):
    session, async_session, workspace_id = catalog_db
    first_store = _store(session, workspace_id, "First")
    second_store = _store(session, workspace_id, "Second")
    a = _listing(session, first_store, sku="A", price="100")
    _listing(session, second_store, sku="A", price="200")
    b = _listing(session, first_store, sku="B", price="150")
    c = _listing(session, second_store, sku="C", price="300")

    first_page = await _search(
        async_session,
        workspace_id,
        sort="price_asc",
        limit=2,
    )
    second_page = await _search(
        async_session,
        workspace_id,
        sort="price_asc",
        limit=2,
        offset=2,
    )

    assert first_page.total == second_page.total == 3
    assert [item.id for item in first_page.items] == [a.id, b.id]
    assert [item.id for item in second_page.items] == [c.id]
    assert len(first_page.items) < first_page.total
    assert 2 + len(second_page.items) == second_page.total


async def test_representative_is_ranked_before_price_filter(catalog_db):
    session, async_session, workspace_id = catalog_db
    first_store = _store(session, workspace_id, "First")
    second_store = _store(session, workspace_id, "Second")
    _listing(session, first_store, sku="A", price="100", name="Cheap")
    _listing(session, second_store, sku="A", price="200", name="Expensive")
    visible = _listing(session, first_store, sku="B", price="150", name="Visible")

    page = await _search(async_session, workspace_id, price_min=110)

    assert page.total == 1
    assert [item.id for item in page.items] == [visible.id]


async def test_search_matching_only_hidden_copy_does_not_replace_representative(
    catalog_db,
):
    session, async_session, workspace_id = catalog_db
    first_store = _store(session, workspace_id, "First")
    second_store = _store(session, workspace_id, "Second")
    _listing(session, first_store, sku="A", price="100", name="Canonical")
    _listing(session, second_store, sku="A", price="200", name="Needle")

    page = await _search(async_session, workspace_id, q="Needle")

    assert page.total == 0
    assert page.items == []


async def test_catalog_and_foreign_store_filter_are_isolated_by_workspace(catalog_db):
    session, async_session, first_workspace_id = catalog_db
    second_workspace = Workspace(name="Other", slug=f"other-{uuid4()}")
    session.add(second_workspace)
    session.flush()

    first_store = _store(session, first_workspace_id, "First tenant")
    second_store = _store(session, second_workspace.id, "Second tenant")
    first_listing = _listing(session, first_store, sku="PRIVATE-A", price="100")
    second_listing = _listing(session, second_store, sku="PRIVATE-B", price="200")

    first_page = await _search(async_session, first_workspace_id)
    second_page = await _search(async_session, second_workspace.id)
    injected_filter = await _search(
        async_session,
        first_workspace_id,
        store_ids=str(second_store.id),
    )

    assert [item.id for item in first_page.items] == [first_listing.id]
    assert [item.id for item in second_page.items] == [second_listing.id]
    assert injected_filter.items == []
    assert injected_filter.total == 0
