import pytest

from marko.parsers.prom.exceptions import ParseError, ParserSchemaChanged
from marko.parsers.prom.parser import (
    _extract_apollo_state,
    _slice_balanced_json,
    parse_listing,
    parse_product_page,
    parse_search,
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
    state = {
        "_FAST_CACHE": {
            "CompanyListingQuery({})": {
                "result": {
                    "listing": {
                        "page": {
                            "total": 2,
                            "products": [
                                {"product": raw_product(id=1)},
                                {"product": raw_product(id=2)},
                            ],
                        }
                    }
                }
            }
        }
    }
    page = parse_listing(html_with_state(state))
    assert (len(page.products), page.total) == (2, 2)


def test_parse_listing_missing_record_is_schema_change():
    with pytest.raises(ParserSchemaChanged):
        parse_listing(html_with_state({"_FAST_CACHE": {}}))


def test_parse_search_explicit_empty_market_is_typed() -> None:
    state = {
        "_FAST_CACHE": {
            "SearchListingQuery({})": {
                "result": {"listing": {"page": {"total": 0, "products": []}}}
            }
        }
    }

    page = parse_search(html_with_state(state))

    assert page.is_empty
    assert page.outcome == "EMPTY_SEARCH_RESULT"


@pytest.mark.parametrize(
    "record",
    [
        {},
        {"result": {"listing": {}}},
        {"result": {"listing": {"page": {"total": 0, "products": {}}}}},
        {"result": {"listing": {"page": {"total": 2, "products": []}}}},
        {"result": {"listing": {"page": {"products": []}}}},
    ],
)
def test_parse_search_schema_drift_never_becomes_empty_market(record) -> None:
    state = {"_FAST_CACHE": {"SearchListingQuery({})": record}}

    with pytest.raises(ParserSchemaChanged):
        parse_search(html_with_state(state))


def test_parse_search_unrelated_apollo_record_is_schema_change() -> None:
    state = {
        "_FAST_CACHE": {
            "UnrelatedQuery({})": {
                "result": {"listing": {"page": {"total": 0, "products": []}}}
            }
        }
    }

    with pytest.raises(ParserSchemaChanged):
        parse_search(html_with_state(state))


@pytest.mark.parametrize(
    "products",
    [
        [None],
        [{}],
        [{"product": "not-an-object"}],
        [{"product": raw_product(id=1)}, {"unexpected": {}}],
    ],
)
def test_parse_search_never_silently_drops_malformed_product_elements(
    products,
) -> None:
    state = {
        "_FAST_CACHE": {
            "SearchListingQuery({})": {
                "result": {
                    "listing": {"page": {"total": len(products), "products": products}}
                }
            }
        }
    }

    with pytest.raises(ParserSchemaChanged):
        parse_search(html_with_state(state))


def test_parse_search_missing_apollo_state_is_parse_contract_failure() -> None:
    with pytest.raises(ParseError):
        parse_search("<html><body>no state</body></html>")


# parse_product_page


def test_parse_product_page_extracts_seed_and_buybox():
    state = {
        "_FAST_CACHE": {
            "ProductCardPageQuery({})": {
                "result": {
                    "product": raw_product(id=9),
                    "buyBox": {"companyCount": 3, "minPrice": 100, "maxPrice": 200},
                }
            }
        }
    }
    seed = parse_product_page(html_with_state(state))
    assert (seed.product.id, seed.seller_count, seed.min_price) == (9, 3, 100)


def test_parse_product_page_without_product_raises():
    state = {"_FAST_CACHE": {"ProductCardPageQuery({})": {"result": {"product": None}}}}
    with pytest.raises(ParseError):
        parse_product_page(html_with_state(state))
