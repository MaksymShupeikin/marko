from decimal import Decimal
from uuid import uuid4

from marko.infrastructure.db.models import CatalogProduct, MarketplaceStore
from marko.api.schemas.catalog import OwnedCatalogPageResponse
from marko.services.unified_catalog import SOURCE_PROM_STORE, SOURCE_XLSX
from marko.services.unified_product_catalog import OwnedCatalogPage
from marko.services.unified_product_catalog import _product_view


def _product(*, source_kind: str, source_id):
    return CatalogProduct(
        id=uuid4(),
        workspace_id=uuid4(),
        source_kind=source_kind,
        source_id=source_id,
        source_product_id="SKU-1",
        name="Амортизатор",
        sku="SKU-1",
        oe_norm="8E0413031",
        current_price=Decimal("1200"),
        currency="UAH",
        is_available=True,
        raw_data={"image": "https://images.example.test/part.jpg"},
    )


def test_prom_product_keeps_its_store_and_listing_provenance() -> None:
    store_id = uuid4()
    store = MarketplaceStore(
        id=store_id,
        external_id="2847093",
        name="Kemp",
        canonical_url="https://kemp.prom.ua",
    )
    product = _product(source_kind=SOURCE_PROM_STORE, source_id=store_id)
    product.product_url = "https://prom.ua/ua/p1-part.html"

    view = _product_view(product, {store_id: store})

    assert view.id == str(product.id)
    assert view.identity_kind == "oe"
    assert view.price_min == Decimal("1200")
    assert view.image_url == "https://images.example.test/part.jpg"
    assert len(view.stores) == 1
    assert view.stores[0].store_id == store_id
    assert view.stores[0].listing_url == product.product_url


def test_xlsx_product_is_visible_without_inventing_a_prom_store() -> None:
    product = _product(source_kind=SOURCE_XLSX, source_id=uuid4())

    view = _product_view(product, {})

    assert view.id == str(product.id)
    assert view.name == "Амортизатор"
    assert view.stores == ()


def test_unified_catalog_page_serializes_from_service_dataclass() -> None:
    page = OwnedCatalogPage(
        items=(),
        total=0,
        catalog_total=0,
        listing_total=0,
        duplicates_removed=0,
        store_total=0,
        stores=(),
        limit=48,
        offset=0,
    )

    response = OwnedCatalogPageResponse.model_validate(page)

    assert response.model_dump() == {
        "items": [],
        "total": 0,
        "catalog_total": 0,
        "listing_total": 0,
        "duplicates_removed": 0,
        "store_total": 0,
        "stores": [],
        "limit": 48,
        "offset": 0,
    }
