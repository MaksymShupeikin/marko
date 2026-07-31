"""Comparisons built from prom.ua's part-code listing instead of a text search.

The change this covers is a change of source, not of algorithm.  Searching the
marketplace for one Touareg radiator's OE returned 22 offers priced 1087 to
12968 on 2026-07-31; the matching was correct and the cohort was still four
different classes of radiator, and the minimum of it proposed cutting our price
79%.  prom.ua files that same normalized code with 114 offers behind it.

What must not change is everything downstream: retrieval still proves nothing
about comparability, the laterality check still runs, the cheapest offer per
seller is still what a comparison carries, and the cap is still the cap.
"""

from __future__ import annotations

from decimal import Decimal

from marko.parsers.prom.gateway import MOTORS_IDENTITY_SOURCE, PromGateway
from marko.services.parser_models import MotorsContext, SeedInfo

from factories import product

SEED_URL = "https://prom.ua/ua/p1153738393-radiator-folksvagen-tuareg.html"


def _seed(**overrides) -> SeedInfo:
    base = {
        "id": 1,
        "name": "Радіатор VW Touareg 2.5 TDI 710*549",
        "price": "5163",
        "company": {"id": 2847093, "name": "KEMP"},
    }
    base.update(overrides)
    return SeedInfo(
        product=product(**base), seller_count=2, min_price=None, max_price=None
    )


def _context(**overrides) -> MotorsContext:
    base = {
        "normalized_part_code": "7L6121253",
        "part_group_id": 109790,
        "oe_page_id": 1146851,
        "oe_page_alias": "7l6121253",
    }
    base.update(overrides)
    return MotorsContext(**base)


def _install(monkeypatch, *, context, candidates, search_candidates=()):
    monkeypatch.setattr(
        PromGateway,
        "_fetch_seed_with_motors",
        lambda self, client, url, lang: (_seed(), context),
    )
    monkeypatch.setattr(
        PromGateway,
        "_collect_oe_candidates",
        lambda self, client, ctx, lang: iter(candidates),
    )
    monkeypatch.setattr(
        PromGateway,
        "_collect_candidates",
        lambda self, client, query, lang, *, strict=False: iter(search_candidates),
    )


def _offer(index: int, price: str, **overrides):
    base = {
        "id": 100 + index,
        "name": "Радіатор охолодження Touareg",
        "price": price,
        "company": {"id": 300 + index, "name": f"Продавець {index}"},
    }
    base.update(overrides)
    return product(**base)


def test_the_part_code_listing_is_preferred_over_a_search(monkeypatch) -> None:
    _install(
        monkeypatch,
        context=_context(),
        candidates=[_offer(1, "1100"), _offer(2, "900")],
        search_candidates=[_offer(9, "50")],
    )

    comparison = PromGateway().compare(SEED_URL)

    assert comparison.source == MOTORS_IDENTITY_SOURCE
    assert comparison.query == "7L6121253"
    assert [str(offer.price) for offer in comparison.offers] == ["900", "1100"]


def test_a_card_without_a_part_code_page_still_searches(monkeypatch) -> None:
    """12 of 40 catalogue positions had no automotive page on 2026-07-31."""

    _install(
        monkeypatch,
        context=None,
        candidates=[],
        # Named like the seed on purpose: the search path still has to earn its
        # match on the wording, and this test is about the source, not the matcher.
        search_candidates=[
            _offer(9, "4000", name="Радіатор VW Touareg 2.5 TDI 710*549")
        ],
    )

    comparison = PromGateway().compare(SEED_URL, query="7L6121253")

    assert comparison.source == "SEARCH"
    assert [str(offer.price) for offer in comparison.offers] == ["4000"]


def test_the_seller_wording_no_longer_has_to_repeat_our_number(monkeypatch) -> None:
    """The correction the measurement forced: on the first run of this source,
    1887 of 2181 offers were discarded for not naming a number the marketplace
    had already used to group them."""

    _install(
        monkeypatch,
        context=_context(),
        candidates=[_offer(1, "1200", name="Радіатор основний Q7 дизель")],
    )

    comparison = PromGateway().compare(SEED_URL)

    assert len(comparison.offers) == 1
    assert comparison.offers[0].match.kind == MOTORS_IDENTITY_SOURCE


def test_a_left_part_beside_a_right_one_is_still_refused(monkeypatch) -> None:
    """The one retrieval check the source assertion does not switch off."""

    _install(
        monkeypatch,
        context=_context(),
        candidates=[
            _offer(1, "900", name="Радіатор лівий Touareg"),
            _offer(2, "1000", name="Радіатор Touareg"),
        ],
    )
    monkeypatch.setattr(
        PromGateway,
        "_fetch_seed_with_motors",
        lambda self, client, url, lang: (
            _seed(name="Радіатор правий Touareg"),
            _context(),
        ),
    )

    comparison = PromGateway().compare(SEED_URL)

    assert [str(offer.price) for offer in comparison.offers] == ["1000"]


def test_our_own_listing_and_our_own_seller_never_become_competitors(
    monkeypatch,
) -> None:
    _install(
        monkeypatch,
        context=_context(),
        candidates=[
            _offer(1, "100", id=1),
            _offer(2, "200", company={"id": 2847093, "name": "KEMP"}),
            _offer(3, "300"),
        ],
    )

    comparison = PromGateway().compare(SEED_URL)

    assert [str(offer.price) for offer in comparison.offers] == ["300"]


def test_one_seller_contributes_one_offer_and_it_is_the_cheapest(
    monkeypatch,
) -> None:
    _install(
        monkeypatch,
        context=_context(),
        candidates=[
            _offer(1, "1500", company={"id": 55, "name": "Один"}),
            _offer(2, "1200", company={"id": 55, "name": "Один"}),
            _offer(3, "1300", company={"id": 66, "name": "Другий"}),
        ],
    )

    comparison = PromGateway().compare(SEED_URL)

    assert [str(offer.price) for offer in comparison.offers] == ["1200", "1300"]


def test_the_cap_is_the_cheapest_sellers_not_the_first_seen(monkeypatch) -> None:
    """The cap is spent before the pricing gates run, so it must be spent on the
    cheap end — that is the half of the market the owner's rule reads."""

    _install(
        monkeypatch,
        context=_context(),
        candidates=[_offer(index, str(2000 - index * 10)) for index in range(1, 30)],
    )

    comparison = PromGateway().compare(SEED_URL)

    assert len(comparison.offers) == 10
    assert comparison.offers[0].price == Decimal("1710")
    assert comparison.prices == sorted(comparison.prices)


def test_every_candidate_seen_is_counted_even_when_capped(monkeypatch) -> None:
    _install(
        monkeypatch,
        context=_context(),
        candidates=[_offer(index, str(1000 + index)) for index in range(1, 30)],
    )

    comparison = PromGateway().compare(SEED_URL)

    assert comparison.candidates_scanned == 29
    assert len(comparison.offers) == 10


def test_a_context_without_a_page_falls_back_rather_than_returning_nothing(
    monkeypatch,
) -> None:
    _install(
        monkeypatch,
        context=_context(oe_page_id=None, oe_page_alias=None),
        candidates=[],
        search_candidates=[
            _offer(9, "4000", name="Радіатор VW Touareg 2.5 TDI 710*549")
        ],
    )

    comparison = PromGateway().compare(SEED_URL, query="7L6121253")

    assert comparison.source == "SEARCH"
    assert len(comparison.offers) == 1
