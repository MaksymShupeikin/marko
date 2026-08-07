from decimal import Decimal

import pytest
from pydantic import ValidationError

from factories import product
from marko.api.schemas.stores import StoreCreateRequest
from marko.services.catalog_import import (
    _currency_evidence,
    _merge_structured_completeness,
    parse_product_price,
)


def test_parse_product_price_accepts_decimal_string():
    assert parse_product_price(product(price="1234.5")) == Decimal("1234.50")


def test_parse_product_price_accepts_spaces_and_comma():
    assert parse_product_price(product(price="1 234,56 грн")) == Decimal("1234.56")


def test_parse_product_price_rejects_inverted_discount_against_current_price():
    assert (
        parse_product_price(
            product(price="330", discountedPrice="412", priceOriginal="412")
        )
        == Decimal("330.00")
    )


def test_parse_product_price_uses_original_when_current_is_missing():
    assert (
        parse_product_price(
            product(price=None, discountedPrice="412", priceOriginal="330")
        )
        == Decimal("330.00")
    )


def test_parse_product_price_returns_none_for_missing_value():
    assert (
        parse_product_price(
            product(price=None, discountedPrice=None, priceOriginal=None)
        )
        is None
    )


@pytest.mark.parametrize("raw", ["0", "-1", "-15.40 грн"])
def test_parse_product_price_rejects_non_positive_values(raw):
    assert parse_product_price(product(price=raw)) is None


def test_store_create_request_normalizes_prom_url():
    request = StoreCreateRequest(url="  https://prom.ua/ua/c2847093-kemp.html  ")
    assert request.url == "https://prom.ua/ua/c2847093-kemp.html"


def test_store_create_request_rejects_non_prom_url():
    with pytest.raises(ValidationError):
        StoreCreateRequest(url="https://example.com/store")


def test_currency_evidence_preserves_raw_source_value():
    assert _currency_evidence(" грн ") == ("UAH", "грн", False)


def test_currency_evidence_marks_missing_source_value_as_inferred():
    assert _currency_evidence(None) == ("UAH", None, True)


def test_duplicate_replay_does_not_change_structured_completeness():
    assert _merge_structured_completeness(
        current=Decimal("0.750000"),
        current_count=4,
        added_sum=Decimal("0"),
        added_count=0,
    ) == Decimal("0.750000")


def test_structured_completeness_weights_only_new_snapshots():
    assert _merge_structured_completeness(
        current=Decimal("0.750000"),
        current_count=4,
        added_sum=Decimal("2"),
        added_count=2,
    ) == Decimal("0.833333")
