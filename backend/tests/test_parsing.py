import pytest

from marko.parsers.prom.exceptions import ParseError
from marko.parsers.prom.parser import (
    _extract_apollo_state,
    _slice_balanced_json,
    parse_listing,
    parse_product_group_ids,
    parse_product_page,
)

from factories import html_with_state, raw_product


# _slice_balanced_json

def test_slice_balanced_json_simple_object():
    text = 'prefix {"k": 1} suffix'
    start = text.index("{")
    assert _slice_balanced_json(text, start) == '{"k": 1}'


def test_slice_balanced_json_ignores_braces_inside_strings():
    text = '{"k": "a}b{c"}'
    assert _slice_balanced_json(text, 0) == text


def test_slice_balanced_json_handles_escaped_quote():
    text = '{"k": "a\\"}"}'
    assert _slice_balanced_json(text, 0) == text


def test_slice_balanced_json_unbalanced_raises():
    with pytest.raises(ParseError):
        _slice_balanced_json('{"k": 1', 0)


# _extract_apollo_state

def test_extract_apollo_state_parses_object():
    assert _extract_apollo_state(html_with_state({"x": 1})) == {"x": 1}


def test_extract_apollo_state_missing_raises():
    with pytest.raises(ParseError):
        _extract_apollo_state("<html>no state here</html>")


def test_extract_apollo_state_invalid_json_raises():
    with pytest.raises(ParseError):
        _extract_apollo_state("window.ApolloCacheState = {not: valid};")


# parse_listing

def test_parse_listing_extracts_products():
    state = {"_FAST_CACHE": {"CompanyListingQuery({})": {
        "result": {"listing": {"page": {"total": 2, "products": [
            {"product": raw_product(id=1)},
            {"product": raw_product(id=2)},
        ]}}}
    }}}
    page = parse_listing(html_with_state(state))
    assert (len(page.products), page.total) == (2, 2)


def test_parse_listing_missing_record_returns_empty():
    page = parse_listing(html_with_state({"_FAST_CACHE": {}}))
    assert page.is_empty


def test_parse_product_group_ids_returns_distinct_ids_in_page_order():
    html = (
        '<a href="/ua/c1-store.html?product_group=20">A</a>'
        '<a href="/ua/c1-store.html?sort=price&amp;product_group=10">B</a>'
        '<a href="/ua/c1-store.html?product_group=20">A again</a>'
    )
    assert parse_product_group_ids(html) == ("20", "10")


# parse_product_page

def test_parse_product_page_extracts_seed_and_buybox():
    state = {"_FAST_CACHE": {"ProductCardPageQuery({})": {
        "result": {"product": raw_product(id=9), "buyBox": {"companyCount": 3, "minPrice": 100, "maxPrice": 200}}
    }}}
    seed = parse_product_page(html_with_state(state))
    assert (seed.product.id, seed.seller_count, seed.min_price) == (9, 3, 100)


def test_parse_product_page_without_product_raises():
    state = {"_FAST_CACHE": {"ProductCardPageQuery({})": {"result": {"product": None}}}}
    with pytest.raises(ParseError):
        parse_product_page(html_with_state(state))
