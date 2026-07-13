import pytest

from marko.services.parser_models import Product, Seller, get_nested

from factories import product, raw_product


# get_nested

def test_get_nested_returns_leaf_value():
    assert get_nested({"a": {"b": {"c": 7}}}, "a.b.c") == 7


def test_get_nested_missing_key_returns_none():
    assert get_nested({"a": {"b": 1}}, "a.x") is None


def test_get_nested_non_dict_midway_returns_none():
    assert get_nested({"a": 5}, "a.b") is None


# Product.from_raw

def test_from_raw_builds_url():
    assert product(id=5, urlText="slug").url == "https://prom.ua/ua/p5-slug.html"


def test_from_raw_url_none_without_id():
    assert Product.from_raw({"urlText": "slug"}, "ua").url is None


def test_from_raw_uses_fallback_keys():
    p = Product.from_raw({"id": 5, "newModelId": "NM", "company_id": 99}, "ua")
    assert (p.model_id, p.seller_id) == ("NM", 99)


def test_field_names_end_with_url():
    assert Product.field_names()[-1] == "url"


# Seller.from_url

def test_seller_from_url_parses_and_lowercases_lang():
    seller = Seller.from_url("https://prom.ua/UA/c2847093-kemp.html")
    assert (seller.company_id, seller.slug, seller.lang) == ("2847093", "kemp", "ua")


def test_seller_from_url_invalid_raises():
    with pytest.raises(ValueError):
        Seller.from_url("https://example.com/not-a-seller")
