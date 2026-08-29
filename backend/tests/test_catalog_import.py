from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from factories import product
from marko.api.schemas.stores import StoreCreateRequest
import marko.services.catalog_import as catalog_import
from marko.services.catalog_import import _merge_raw_data, parse_product_price


def test_parse_product_price_accepts_decimal_string():
    assert parse_product_price(product(price="1234.5")) == Decimal("1234.50")


def test_parse_product_price_accepts_spaces_and_comma():
    assert parse_product_price(product(price="1 234,56 грн")) == Decimal("1234.56")


def test_parse_product_price_returns_none_for_missing_value():
    assert parse_product_price(
        product(price=None, discountedPrice=None, priceOriginal=None)
    ) is None


def test_parse_product_price_rejects_zero_and_negative_values():
    assert parse_product_price(product(price="0")) is None
    assert parse_product_price(product(price="-10")) is None


async def test_zero_import_does_not_overwrite_valid_price_or_create_observation(
    monkeypatch,
):
    listing = SimpleNamespace(
        id=uuid4(),
        external_id="123",
        current_price=Decimal("500"),
        currency="UAH",
        is_available=True,
        name="Old",
        url="https://prom.ua/ua/p123-old.html",
        sku="OLD",
        model_id=None,
        brand=None,
        raw_data={},
        last_seen_at=None,
    )
    session = SimpleNamespace(flush=AsyncMock())
    observations: list[object] = []
    monkeypatch.setattr(
        catalog_import.listings_repo,
        "get_listings_by_external_ids",
        AsyncMock(return_value=[listing]),
    )
    monkeypatch.setattr(
        catalog_import.listings_repo,
        "add_price_observation",
        lambda _session, observation: observations.append(observation),
    )

    await catalog_import.persist_products(
        session,
        uuid4(),
        [product(id="123", price="0", name="Updated", urlText="updated")],
    )

    assert listing.current_price == Decimal("500")
    assert observations == []


async def test_new_zero_price_listing_is_stored_as_missing_without_observation(
    monkeypatch,
):
    session = SimpleNamespace(flush=AsyncMock())
    added: list[object] = []
    observations: list[object] = []
    monkeypatch.setattr(
        catalog_import.listings_repo,
        "get_listings_by_external_ids",
        AsyncMock(return_value=[]),
    )

    async def add_listing(_session, listing):
        added.append(listing)

    async def add_observation(_session, observation):
        observations.append(observation)

    monkeypatch.setattr(catalog_import.listings_repo, "add_listing", add_listing)
    monkeypatch.setattr(
        catalog_import.listings_repo, "add_price_observation", add_observation
    )

    await catalog_import.persist_products(
        session,
        uuid4(),
        [product(id="124", price="0", name="New", urlText="new")],
    )

    assert len(added) == 1
    assert added[0].current_price is None
    assert observations == []


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
