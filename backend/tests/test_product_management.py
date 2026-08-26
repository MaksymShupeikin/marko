from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from marko.api.routers.v1 import products
from marko.api.schemas.stores import ProductUpdateRequest
from marko.infrastructure.db.models import Listing, MarketplaceStore, SyncStatus


class FakeSession:
    def __init__(self) -> None:
        self.added = []
        self.executed = []
        self.commit = AsyncMock()
        self.refresh = AsyncMock()

    def add(self, value) -> None:
        self.added.append(value)

    async def execute(self, statement):
        self.executed.append(statement)
        return None


def _listing() -> Listing:
    return Listing(
        id=uuid4(),
        store_id=uuid4(),
        external_id="prom-1",
        name="Стара назва",
        url="https://prom.ua/p1.html",
        sku="OLD",
        brand="Old",
        currency="UAH",
        current_price=Decimal("100.00"),
        is_available=True,
        raw_data={"image": "https://example.com/old.jpg"},
        last_seen_at=datetime.now(UTC),
    )


def _scraped(**changes):
    """A parsed product page; pass only the fields a test cares about."""
    from marko.services.parser_models import Product

    fields = dict(
        id=123,
        name="Оновлений через URL",
        sku="SKU-NEW",
        price="250.0",
        price_original=None,
        discounted_price=None,
        has_discount=False,
        currency="UAH",
        price_usd=None,
        presence="В наявності",
        is_available=True,
        measure_unit="шт.",
        category_id=1,
        brand="NewBrand",
        model_id=None,
        seller_id=1,
        seller_name="Seller",
        seller_slug="seller",
        opinions_count=0,
        opinions_rating=0.0,
        image="https://example.com/new.jpg",
        url_text="product",
        url="https://prom.ua/p1.html",
        oem_numbers=("OEM-NEW",),
    )
    fields.update(changes)
    return Product(**fields)


def _store(listing: Listing) -> MarketplaceStore:
    return MarketplaceStore(
        id=listing.store_id,
        marketplace="prom",
        external_id="store-1",
        name="Мій магазин",
        canonical_url="https://prom.ua/c1.html",
    )


def test_product_update_normalizes_optional_fields_and_oem_numbers():
    payload = ProductUpdateRequest(
        name="  Нова назва  ",
        sku="  ",
        oem_numbers=[" OEM-1 ", "OEM-1", "", "oem-2"],
    )

    assert payload.name == "Нова назва"
    assert payload.sku is None
    assert payload.oem_numbers == ["OEM-1", "oem-2"]


def test_product_update_rejects_empty_payload_and_invalid_image_url():
    with pytest.raises(ValidationError):
        ProductUpdateRequest()
    with pytest.raises(ValidationError):
        ProductUpdateRequest(image_url="example.com/image.jpg")


async def test_update_product_persists_overrides(monkeypatch):
    listing = _listing()
    store = _store(listing)
    session = FakeSession()
    monkeypatch.setattr(
        products.listings_repo,
        "get_manageable_workspace_listing",
        AsyncMock(return_value=(listing, store, None)),
    )

    response = await products.update_product(
        listing.id,
        ProductUpdateRequest(
            name="Нова назва",
            sku=None,
            current_price=Decimal("125.50"),
            is_available=False,
            image_url=None,
            oem_numbers=["OEM-1"],
        ),
        session,
        SimpleNamespace(workspace_id=uuid4()),
    )

    assert response.name == "Нова назва"
    assert response.current_price == Decimal("125.50")
    assert response.can_manage is True
    assert listing.name == "Стара назва"
    assert listing.sku == "OLD"
    assert listing.is_available is True
    assert len(session.added) == 1
    override = session.added[0]
    assert override.workspace_id is not None
    assert override.name == "Нова назва"
    assert override.sku is None
    assert override.current_price == Decimal("125.50")
    assert override.image_url is None
    assert override.oem_numbers == ["OEM-1"]
    session.commit.assert_awaited_once()


async def test_delete_product_soft_deletes_listing(monkeypatch):
    listing = _listing()
    session = FakeSession()
    monkeypatch.setattr(
        products.listings_repo,
        "get_manageable_workspace_listing",
        AsyncMock(return_value=(listing, _store(listing), None)),
    )

    response = await products.delete_product(
        listing.id,
        session,
        SimpleNamespace(workspace_id=uuid4()),
    )

    assert response.status_code == 204
    assert listing.name == "Стара назва"
    assert len(session.added) == 1
    assert session.added[0].is_deleted is True
    session.commit.assert_awaited_once()


async def test_refresh_product_fetches_and_persists_overrides(monkeypatch):
    listing = _listing()
    store = _store(listing)
    session = FakeSession()
    monkeypatch.setattr(
        products.listings_repo,
        "get_manageable_workspace_listing",
        AsyncMock(return_value=(listing, store, None)),
    )

    mock_client = AsyncMock()
    mock_client.get_html.return_value = "<html>product</html>"
    mock_client.close = AsyncMock()
    # Клієнт вимагає конфіг: підміна без аргументу ховала TypeError у проді.
    monkeypatch.setattr(products, "AsyncHttpClient", lambda config: mock_client)

    from marko.services.parser_models import SeedInfo
    seed = SeedInfo(
        product=_scraped(),
        seller_count=1,
        min_price="250.0",
        max_price="250.0",
    )
    monkeypatch.setattr(products, "parse_product_page", lambda html: seed)

    response = await products.refresh_product(
        listing.id,
        session,
        SimpleNamespace(workspace_id=uuid4()),
    )

    assert response.name == "Оновлений через URL"
    assert response.current_price == Decimal("250.0")
    assert response.sku == "SKU-NEW"
    assert response.brand == "NewBrand"
    assert response.image_url == "https://example.com/new.jpg"
    assert response.oem_numbers == ["OEM-NEW"]
    # Час синхронізації йде від оновлення, а не від імпорту лістингу.
    assert response.last_seen_at > listing.last_seen_at
    assert len(session.added) == 1
    session.commit.assert_awaited_once()


async def test_bulk_delete_hides_every_match_in_one_statement(monkeypatch):
    """«Усі» — це фільтр, а не список id: клієнт не надсилає 14 тисяч рядків."""
    from marko.services import bulk_products

    listing_ids = [uuid4() for _ in range(3)]
    session = FakeSession()
    monkeypatch.setattr(
        bulk_products.listings_repo,
        "manageable_workspace_listing_ids",
        AsyncMock(return_value=listing_ids),
    )

    deleted = await bulk_products.delete_matching(
        session,
        uuid4(),
        bulk_products.CatalogFilter(source="export"),
    )

    assert deleted == 3
    # Один statement на всю вибірку, скільки б її не було.
    assert len(session.executed) == 1
    session.commit.assert_awaited_once()


async def test_bulk_refresh_is_queued_with_the_filter(monkeypatch):
    from marko.services import bulk_products

    session = FakeSession()
    sync_run = SimpleNamespace(
        id=uuid4(),
        store_id=None,
        status=SyncStatus.queued,
        progress_total=None,
        task_id=None,
        error=None,
        finished_at=None,
    )
    monkeypatch.setattr(
        bulk_products.listings_repo,
        "manageable_workspace_listing_ids",
        AsyncMock(return_value=[uuid4(), uuid4()]),
    )
    monkeypatch.setattr(
        bulk_products.stores_repo,
        "create_sync_run",
        AsyncMock(return_value=sync_run),
    )
    sent: list[tuple] = []

    class FakeCelery:
        def send_task(self, name, args):
            sent.append((name, args))
            return SimpleNamespace(id="task-1")

    queued = await bulk_products.queue_refresh(
        session,
        uuid4(),
        bulk_products.CatalogFilter(query="радіатор", source="scrape"),
        celery_app=FakeCelery(),
    )

    assert queued.progress_total == 2
    assert queued.task_id == "task-1"
    name, args = sent[0]
    assert name == bulk_products.REFRESH_TASK
    assert args[1] == {
        "query": "радіатор",
        "price_min": None,
        "price_max": None,
        "source": "scrape",
        "store_ids": [],
    }


def test_refresh_mirrors_the_page_and_stamps_the_sync_time():
    """Зникле на сторінці зникає і в каталозі — крім OEM, яких сторінка не має."""
    from marko.infrastructure.db.models import WorkspaceListingOverride
    from marko.services.bulk_products import apply_scraped_product

    override = WorkspaceListingOverride(
        workspace_id=uuid4(),
        listing_id=uuid4(),
        name="Стара назва",
        sku="OLD",
        brand="Old",
        current_price=Decimal("100.00"),
        is_available=True,
        image_url="https://example.com/old.jpg",
        oem_numbers=["OEM-1", "OEM-2"],
    )

    apply_scraped_product(
        override,
        _scraped(
            name="Нова назва",
            brand=None,
            price=None,
            sku=None,
            image=None,
            is_available=None,
            oem_numbers=(),
        ),
    )

    assert override.name == "Нова назва"
    assert override.brand is None
    assert override.current_price is None
    assert override.sku is None
    assert override.image_url is None
    assert override.is_available is None
    # OEM живуть тільки у файлі вивантаження, сторінка їх не віддає.
    assert override.oem_numbers == ["OEM-1", "OEM-2"]
    assert override.synced_at is not None


def test_refresh_keeps_the_name_when_the_page_parses_empty():
    from marko.infrastructure.db.models import WorkspaceListingOverride
    from marko.services.bulk_products import apply_scraped_product

    override = WorkspaceListingOverride(name="Стара назва")
    apply_scraped_product(override, _scraped(name=None))

    assert override.name == "Стара назва"
