"""Competitor offers taken from prom.ua's own automotive catalogue.

Why this source exists at all is a measurement, not a preference. Searching the
marketplace for our OE number returned 22 "comparable" offers for one Touareg
radiator, priced 1087 to 12968; reading them showed the matching was correct and
the cohort was still four different classes of radiator, and the engine proposed
cutting our price 79% off the bottom of it.

prom.ua files that same radiator under a normalized part code with 114 offers
behind it. This module reads that listing, runs the gates, and orders what
survives by price — because the owner's rule needs the cheap end, and asking a
model about the expensive tail is money spent on offers that cannot set a price.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from marko.parsers.prom.parser import parse_motors_context, parse_oe_listing
from marko.services.parser_models import MotorsContext, Product
from marko.services.prom_motors import (
    MOTORS_IDENTITY_SOURCE,
    MotorsHarvest,
    as_candidate_item,
    collect_offers,
    harvest,
)
from metis.pricing.candidate_selection import (
    ReferenceItem,
    load_candidate_selection_config,
)
from metis.pricing.types import ProductTier

from pathlib import Path

from factories import html_with_state, raw_product

BACKEND = Path(__file__).resolve().parents[1]
CONFIG = load_candidate_selection_config(BACKEND / "config" / "comparability.yaml")
OWNED = frozenset({"2847093", "4015921"})

RADIATOR = ReferenceItem(
    oem="7L6121253",
    title="Радиатор VW Tuareg 2.5 TDI 710*549",
    price=Decimal("5163"),
    brand="KEMP",
    category="",
    tier=ProductTier.KEMP,
)


def _listing_html(products: list[dict], total: int | None = None) -> str:
    return html_with_state(
        {
            "_FAST_CACHE": {
                'MotorsOENumberListingQuery{"x":1}': {
                    "result": {
                        "listing": {
                            "page": {
                                "products": [{"product": item} for item in products],
                                "total": len(products) if total is None else total,
                            }
                        }
                    }
                }
            }
        }
    )


def _card_html(motors: dict | None, product: dict | None = None) -> str:
    return html_with_state(
        {
            "_FAST_CACHE": {
                'ProductCardPageQuery{"productId":1}': {
                    "result": {
                        "product": product or {"images": ["https://img/1.jpg"]},
                        "motorsProductPage": motors,
                    }
                }
            }
        }
    )


def _offer(**overrides) -> dict:
    base = raw_product()
    base.update(overrides)
    return base


# --------------------------------------------------------------- the card


def test_the_card_yields_the_code_the_supersessions_and_the_listing() -> None:
    html = _card_html(
        {
            "partGroupId": 109790,
            "normalizedPartCode": "7L6121253",
            "compatibleOENumbers": [
                {
                    "oeNumberNormalized": "7L6121253",
                    "oeNumberPage": {"id": 1146851, "alias": "7l6121253"},
                },
                {"oeNumberNormalized": "7L6121253C", "oeNumberPage": None},
            ],
            "compatibleVehicles": [
                {
                    "name": "3.0 TDI quattro",
                    "hp": 224,
                    "fuelType": "DIESEL",
                    "manufacturer": {"name": "Audi"},
                    "model": {
                        "name": "Q7 (4LB)",
                        "dateFrom": "2006-03-01",
                        "dateTo": "2016-01-31",
                    },
                }
            ],
        }
    )

    context = parse_motors_context(html)

    assert context is not None
    assert context.normalized_part_code == "7L6121253"
    assert context.compatible_oe_numbers == ("7L6121253", "7L6121253C")
    assert context.oe_page_url() == "https://prom.ua/ua/auto/oen/1146851-7l6121253"
    assert context.compatible_vehicles[0].caption == (
        "Audi Q7 (4LB) 3.0 TDI quattro 2006-03..2016-01"
    )


def test_a_related_numbers_listing_is_taken_but_marked_as_a_widening() -> None:
    """Refusing it outright was the first rule here, and the data overturned it.

    Measured 2026-07-31: 3 of the 12 positions with no listing of their own do
    have one under a number in their supersession chain, and for ``7P6121253``
    that number is ``95810613200`` — the Porsche side of the same radiator.
    Taking it is right; taking it silently is not, because the offers there are
    an analogue and not the same code.
    """

    html = _card_html(
        {
            "normalizedPartCode": "7L6121253",
            "compatibleOENumbers": [
                {
                    "oeNumberNormalized": "7L6121253C",
                    "oeNumberPage": {"id": 999, "alias": "7l6121253c"},
                }
            ],
        }
    )

    context = parse_motors_context(html)

    assert context is not None
    assert context.has_oe_page is True
    assert context.via_oe_number == "7L6121253C"
    assert context.is_widened is True


def test_our_own_code_is_preferred_over_a_related_one() -> None:
    """Order in the chain must not decide which market we compare against."""

    html = _card_html(
        {
            "normalizedPartCode": "7L6121253",
            "compatibleOENumbers": [
                {
                    "oeNumberNormalized": "7L6121253C",
                    "oeNumberPage": {"id": 999, "alias": "7l6121253c"},
                },
                {
                    "oeNumberNormalized": "7L6121253",
                    "oeNumberPage": {"id": 1146851, "alias": "7l6121253"},
                },
            ],
        }
    )

    context = parse_motors_context(html)

    assert context is not None
    assert context.oe_page_id == 1146851
    assert context.via_oe_number == "7L6121253"
    assert context.is_widened is False


def test_a_product_outside_the_automotive_vertical_is_not_an_error() -> None:
    """12 of 40 catalogue positions had no such block on 2026-07-31."""

    assert parse_motors_context(_card_html(None)) is None


def test_a_vehicle_without_a_make_or_model_is_dropped() -> None:
    html = _card_html(
        {
            "normalizedPartCode": "X",
            "compatibleOENumbers": [],
            "compatibleVehicles": [
                {"manufacturer": {"name": "Audi"}, "model": {}},
                {"manufacturer": {"name": "Audi"}, "model": {"name": "Q7"}},
            ],
        }
    )

    context = parse_motors_context(html)

    assert context is not None
    assert [v.model for v in context.compatible_vehicles] == ["Q7"]


# ------------------------------------------------------------- the listing


def test_the_listing_parses_with_the_shared_product_parser() -> None:
    html = _listing_html([_offer(id=1, price="100"), _offer(id=2, price="200")])

    page = parse_oe_listing(html)

    assert [product.id for product in page.products] == [1, 2]
    assert page.total == 2


# ---------------------------------------------------------------- the gates


def _collect(products, **kwargs):
    return collect_offers(
        [_listing_html(products)],
        reference=RADIATOR,
        config=CONFIG,
        owned_seller_ids=OWNED,
        **kwargs,
    )


def test_offers_come_back_cheapest_first() -> None:
    accepted, _, _, _ = _collect(
        [
            _offer(id=1, price="5000", company={"id": 11, "name": "A"}),
            _offer(id=2, price="1100", company={"id": 12, "name": "B"}),
            _offer(id=3, price="2500", company={"id": 13, "name": "C"}),
        ]
    )

    assert [str(candidate.price) for candidate in accepted] == ["1100", "2500", "5000"]


def test_the_identity_is_taken_from_the_source_not_the_title() -> None:
    """The correction the measurement forced: 1887 of 2181 offers were rejected
    as ``OEM_NOT_FOUND`` for not repeating a number the source had already used
    to group them."""

    accepted, rejected, _, _ = _collect(
        [_offer(id=1, price="1100", name="Радіатор охолодження Touareg", sku="")]
    )

    assert "OEM_NOT_FOUND" not in rejected
    assert len(accepted) == 1
    identity = accepted[0].verdict.details["gates"]["oem_identity"]
    assert identity["identity_asserted_by"] == MOTORS_IDENTITY_SOURCE


def test_our_own_storefronts_are_still_removed() -> None:
    """The trap this gate exists for: prom.ua's buyBox counted two sellers for
    our Touareg radiator and both of them were the customer's own shops, one of
    them 33% dearer, which reads as a competitor to raise towards."""

    accepted, rejected, _, _ = _collect(
        [
            _offer(id=1, price="1100", company={"id": 4015921, "name": "АвтоБуст"}),
            _offer(id=2, price="1200", company={"id": 99, "name": "Чужий"}),
        ]
    )

    assert rejected["OWN_SELLER"] == 1
    assert [candidate.seller_id for candidate in accepted] == ["99"]


def test_an_offer_without_a_usable_price_never_becomes_the_floor() -> None:
    """Zero would sort to the front and set the market minimum."""

    accepted, rejected, _, _ = _collect(
        [
            _offer(id=1, price=None, price_original=None),
            _offer(id=2, price="0"),
            _offer(id=3, price="1500"),
        ]
    )

    assert rejected["NO_USABLE_PRICE"] == 2
    assert [str(candidate.price) for candidate in accepted] == ["1500"]


def test_the_same_offer_on_two_pages_is_counted_once() -> None:
    page = _listing_html([_offer(id=7, price="900")])

    accepted, _, fetched, _ = collect_offers(
        [page, page], reference=RADIATOR, config=CONFIG, owned_seller_ids=OWNED
    )

    assert fetched == 1
    assert len(accepted) == 1


def test_rejections_are_counted_by_cause() -> None:
    accepted, rejected, _, _ = _collect(
        [
            _offer(id=1, price="900", name="Радіатор б/у розборка Touareg"),
            _offer(id=2, price="1000", name="Радіатор Touareg"),
        ]
    )

    assert sum(rejected.values()) == 1
    assert len(accepted) == 1


# ------------------------------------------------------------- the harvest


class _ScriptedClient:
    """Answers the URLs the harvest asks for, and records the order it asked."""

    def __init__(self, pages: dict[str, str]) -> None:
        self._pages = pages
        self.requested: list[str] = []

    def get_html(self, url: str) -> str:
        self.requested.append(url)
        if url not in self._pages:
            raise AssertionError(f"unexpected fetch: {url}")
        return self._pages[url]


def _harvest(client) -> MotorsHarvest:
    return harvest(
        client,
        product_url="https://prom.ua/ua/p1-x.html",
        reference=RADIATOR,
        config=CONFIG,
        owned_seller_ids=OWNED,
    )


def test_a_card_without_an_automotive_page_costs_one_request() -> None:
    client = _ScriptedClient({"https://prom.ua/ua/p1-x.html": _card_html(None)})

    result = _harvest(client)

    assert result.oe_page_url is None
    assert result.accepted == ()
    assert client.requested == ["https://prom.ua/ua/p1-x.html"]


def test_pagination_follows_the_reported_total() -> None:
    """prom.ua ignored every sort parameter tried, so the cheap end can only be
    found after the pages are in hand."""

    base = "https://prom.ua/ua/auto/oen/5-abc"
    card = _card_html(
        {
            "normalizedPartCode": "7L6121253",
            "compatibleOENumbers": [
                {
                    "oeNumberNormalized": "7L6121253",
                    "oeNumberPage": {"id": 5, "alias": "abc"},
                }
            ],
        }
    )
    client = _ScriptedClient(
        {
            "https://prom.ua/ua/p1-x.html": card,
            base: _listing_html([_offer(id=1, price="900")], total=61),
            f"{base}?page=2": _listing_html([_offer(id=2, price="800")], total=61),
            f"{base}?page=3": _listing_html([_offer(id=3, price="700")], total=61),
        }
    )

    result = _harvest(client)

    assert result.pages_fetched == 3
    assert result.total_reported == 61
    assert result.truncated is False
    assert [str(candidate.price) for candidate in result.accepted] == [
        "700",
        "800",
        "900",
    ]


def test_a_long_tail_is_truncated_and_says_so() -> None:
    base = "https://prom.ua/ua/auto/oen/5-abc"
    card = _card_html(
        {
            "normalizedPartCode": "7L6121253",
            "compatibleOENumbers": [
                {
                    "oeNumberNormalized": "7L6121253",
                    "oeNumberPage": {"id": 5, "alias": "abc"},
                }
            ],
        }
    )
    pages = {"https://prom.ua/ua/p1-x.html": card}
    pages[base] = _listing_html([_offer(id=1, price="900")], total=777)
    for number in range(2, 5):
        pages[f"{base}?page={number}"] = _listing_html(
            [_offer(id=number, price="900")], total=777
        )
    client = _ScriptedClient(pages)

    result = _harvest(client)

    assert result.pages_fetched == 4
    assert result.truncated is True


def test_cheapest_refuses_a_meaningless_limit() -> None:
    result = MotorsHarvest(context=None, oe_page_url=None)

    with pytest.raises(ValueError):
        result.cheapest(0)


def test_the_summary_reports_what_was_consulted_and_what_was_dropped() -> None:
    base = "https://prom.ua/ua/auto/oen/5-abc"
    card = _card_html(
        {
            "normalizedPartCode": "7L6121253",
            "compatibleOENumbers": [
                {
                    "oeNumberNormalized": "7L6121253",
                    "oeNumberPage": {"id": 5, "alias": "abc"},
                }
            ],
        }
    )
    client = _ScriptedClient(
        {
            "https://prom.ua/ua/p1-x.html": card,
            base: _listing_html(
                [
                    _offer(id=1, price="900", company={"id": 4015921, "name": "своя"}),
                    _offer(id=2, price="1000", company={"id": 5, "name": "чужа"}),
                ]
            ),
        }
    )

    summary = _harvest(client).as_dict()

    assert summary["normalized_part_code"] == "7L6121253"
    assert summary["accepted"] == 1
    assert summary["rejected"] == {"OWN_SELLER": 1}
    assert summary["oe_page_url"] == base


def test_a_candidate_item_carries_the_seller_and_the_category_path() -> None:
    product = Product.from_raw(
        _offer(
            id=1,
            price="100",
            company={"id": 77, "name": "S"},
            categoryId=120218,
            categoryIds=[0, 55, 120218],
        ),
        "ua",
    )

    item = as_candidate_item(product)

    assert item.seller_id == "77"
    assert item.category_id == 120218
    assert item.category_path == (0, 55, 120218)


def test_the_context_is_json_safe_for_a_review_payload() -> None:
    context = MotorsContext(
        normalized_part_code="X",
        part_group_id=1,
        oe_page_id=2,
        oe_page_alias="a",
    )

    assert json.dumps(
        {
            "code": context.normalized_part_code,
            "url": context.oe_page_url(),
        }
    )
