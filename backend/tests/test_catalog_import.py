from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from factories import product
from marko.api.schemas.stores import StoreCreateRequest
import marko.services.catalog_import as catalog_import_module
from marko.services.catalog_import import _merge_raw_data, parse_product_price
from marko.services.parser_models import Seller


def test_parse_product_price_accepts_decimal_string():
    assert parse_product_price(product(price="1234.5")) == Decimal("1234.50")


def test_parse_product_price_accepts_spaces_and_comma():
    assert parse_product_price(product(price="1 234,56 грн")) == Decimal("1234.56")


def test_parse_product_price_returns_none_for_missing_value():
    assert parse_product_price(
        product(price=None, discountedPrice=None, priceOriginal=None)
    ) is None


def test_parse_product_price_rejects_zero_and_negative():
    """Нуль у картці — це відсутня ціна: краще лишити стару, ніж показати 0 грн."""
    assert parse_product_price(product(price="0", priceOriginal="0")) is None
    assert parse_product_price(product(price="-15", priceOriginal=None)) is None


def test_merge_raw_data_keeps_fields_the_new_source_does_not_carry():
    # A file import has OEM numbers but no seller; a scrape is the other way
    # round. Importing one must not erase what the other stored.
    stored = {"seller_id": 10, "model_id": "M-1", "oem_numbers": ["W914/2"]}

    merged = _merge_raw_data(stored, product(sku="ABC", company=None, newModelId=None))

    assert merged["seller_id"] == 10
    assert merged["model_id"] == "M-1"
    assert merged["oem_numbers"] == ["W914/2"]
    assert merged["sku"] == "ABC"


def test_merge_raw_data_lets_the_new_source_win_where_it_has_a_value():
    merged = _merge_raw_data({"sku": "OLD", "price": "100"}, product(sku="NEW"))

    assert merged["sku"] == "NEW"
    assert merged["price"] == "1000"


def test_store_create_request_normalizes_prom_url():
    request = StoreCreateRequest(url="  https://prom.ua/ua/c2847093-kemp.html  ")
    assert request.url == "https://prom.ua/ua/c2847093-kemp.html"


def test_store_create_request_accepts_url_without_language():
    request = StoreCreateRequest(url="https://prom.ua/c4015921-avtobust.html")
    assert request.url == "https://prom.ua/c4015921-avtobust.html"


def test_store_create_request_rejects_non_prom_url():
    with pytest.raises(ValidationError):
        StoreCreateRequest(url="https://example.com/store")


async def test_xlsx_import_persists_permanent_seller_exclusion(monkeypatch):
    workspace_id = uuid4()
    store_id = uuid4()
    seller = Seller(company_id="9876543", slug="my-shop", lang="ua")
    parsed_products = [product(id=1, name="Фільтр", urlText="filtr")]
    store = SimpleNamespace(last_synced_at=None)
    session = AsyncMock()
    session.get.return_value = store

    monkeypatch.setattr(
        catalog_import_module,
        "parse_export",
        lambda _file: iter(parsed_products),
    )
    monkeypatch.setattr(catalog_import_module, "seller_of", lambda _products: seller)
    monkeypatch.setattr(
        catalog_import_module.stores_repo,
        "upsert_marketplace_store",
        AsyncMock(return_value=store_id),
    )
    monkeypatch.setattr(
        catalog_import_module.stores_repo,
        "upsert_workspace_store",
        AsyncMock(),
    )
    exclusion = AsyncMock()
    monkeypatch.setattr(
        catalog_import_module.stores_repo,
        "upsert_competitor_seller_exclusion",
        exclusion,
    )
    monkeypatch.setattr(
        catalog_import_module,
        "persist_products",
        AsyncMock(return_value=1),
    )
    monkeypatch.setattr(
        catalog_import_module.listings_repo,
        "undelete_listings_for_store",
        AsyncMock(),
    )

    result = await catalog_import_module.import_export_file(
        session,
        workspace_id=workspace_id,
        content=b"xlsx",
    )

    assert result.store_id == store_id
    exclusion.assert_awaited_once_with(
        session,
        workspace_id=workspace_id,
        marketplace="prom",
        external_id="9876543",
        slug="my-shop",
        canonical_url="https://prom.ua/ua/c9876543-my-shop.html",
    )
