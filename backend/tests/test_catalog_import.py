from decimal import Decimal

import pytest
from pydantic import ValidationError

from factories import product
from marko.api.schemas.stores import StoreCreateRequest
from marko.services.catalog_import import parse_product_price


def test_parse_product_price_accepts_decimal_string():
    assert parse_product_price(product(price="1234.5")) == Decimal("1234.50")


def test_parse_product_price_accepts_spaces_and_comma():
    assert parse_product_price(product(price="1 234,56 грн")) == Decimal("1234.56")


def test_parse_product_price_returns_none_for_missing_value():
    assert parse_product_price(
        product(price=None, discountedPrice=None, priceOriginal=None)
    ) is None


def test_store_create_request_normalizes_prom_url():
    request = StoreCreateRequest(url="  https://prom.ua/ua/c2847093-kemp.html  ")
    assert request.url == "https://prom.ua/ua/c2847093-kemp.html"


def test_store_create_request_rejects_non_prom_url():
    with pytest.raises(ValidationError):
        StoreCreateRequest(url="https://example.com/store")
