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

from dataclasses import replace
from decimal import Decimal

from marko.parsers.prom.gateway import (
    MOTORS_IDENTITY_SOURCE,
    PromGateway,
    _motors_context_is_public,
)
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


def test_gateway_canonicalizes_owned_seller_host_before_fetch(monkeypatch) -> None:
    seen_urls: list[str] = []
    monkeypatch.setattr(
        PromGateway,
        "_fetch_seed_with_motors",
        lambda self, client, url, lang: (
            seen_urls.append(url) or (_seed(), _context())
        ),
    )
    monkeypatch.setattr(
        PromGateway,
        "_collect_oe_candidates",
        lambda self, client, context, lang: iter([_offer(1, "1100")]),
    )
    monkeypatch.setattr(
        PromGateway,
        "_collect_candidates",
        lambda self, client, query, lang, *, strict=False: iter(()),
    )

    PromGateway().compare(
        "https://kemp-cs2847093.prom.ua/p1153738393-radiator-folksvagen-tuareg.html"
    )

    assert seen_urls == [
        "https://prom.ua/ua/p1153738393-radiator-folksvagen-tuareg.html"
    ]


def test_detail_discount_replaces_stale_listing_price(monkeypatch) -> None:
    _install(
        monkeypatch,
        context=_context(),
        candidates=[_offer(1, "412")],
    )

    def detail(self, client, listing, *, lang):
        del self, client, lang
        return replace(
            listing,
            price="412",
            discounted_price="330",
            price_original="412",
        )

    monkeypatch.setattr(PromGateway, "_fetch_candidate_detail", detail)

    comparison = PromGateway().compare(SEED_URL)

    assert comparison.prices == [Decimal("330")]
    assert comparison.as_dict()["offers"][0]["reference_price"] == "412"


def test_detail_inverted_discount_does_not_inflate_price(monkeypatch) -> None:
    _install(
        monkeypatch,
        context=_context(),
        candidates=[_offer(1, "330")],
    )

    def detail(self, client, listing, *, lang):
        del self, client, lang
        return replace(
            listing,
            price="330",
            discounted_price="412",
            price_original="412",
        )

    monkeypatch.setattr(PromGateway, "_fetch_candidate_detail", detail)

    comparison = PromGateway().compare(SEED_URL)

    assert comparison.prices == [Decimal("330")]
    assert comparison.as_dict()["offers"][0]["reference_price"] == "412"


def test_detail_mpn_conflict_is_removed_from_comparison(monkeypatch) -> None:
    """A title hit cannot survive a conflicting manufacturer number on detail."""

    _install(
        monkeypatch,
        context=None,
        candidates=[],
        search_candidates=[
            _offer(
                1,
                "400",
                name="7E5827505A замок кришки багажника Volkswagen T5",
            )
        ],
    )

    def detail(self, client, listing, *, lang):
        del self, client, lang
        return replace(
            listing,
            mpn="7E5827505B",
            detail_evidence={
                "schema_version": "prom-product-detail-evidence-v1",
                "status": "SUCCESS",
                "selected": True,
                "conflicts": {},
            },
        )

    monkeypatch.setattr(PromGateway, "_fetch_candidate_detail", detail)

    comparison = PromGateway().compare(SEED_URL, query="7E5827505A")

    assert comparison.offers == []


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


def test_natural_language_query_is_not_collapsed_into_search_number(monkeypatch) -> None:
    """A phrase keeps fuzzy retrieval available even when a card has an MPN."""

    _install(
        monkeypatch,
        context=None,
        candidates=[],
        search_candidates=[
            _offer(
                1,
                "1200",
                name="Радіатор VW Touareg 2.5 TDI",
                identifiers={"mpn": "OTHER-123"},
            )
        ],
    )

    comparison = PromGateway().compare(
        SEED_URL,
        query="Радіатор VW Touareg 2.5 TDI",
    )

    assert len(comparison.offers) == 1
    assert comparison.offers[0].match.kind == "fuzzy"


def test_vehicle_context_with_year_is_not_treated_as_an_identifier(monkeypatch) -> None:
    _install(
        monkeypatch,
        context=None,
        candidates=[],
        search_candidates=[
            _offer(
                1,
                "1200",
                name="Радіатор VW Touareg 2.5 TDI 2006",
                identifiers={"mpn": "OTHER-123"},
            )
        ],
    )

    comparison = PromGateway().compare(SEED_URL, query="VW Transporter T5 2006")

    assert len(comparison.offers) == 1
    assert comparison.offers[0].match.kind == "fuzzy"


def test_prom_public_search_rejects_private_kemp_code_before_http() -> None:
    gateway = PromGateway()

    try:
        list(gateway.search("776414"))
    except ValueError as exc:
        assert "public OE/MPN" in str(exc)
    else:  # pragma: no cover - the assertion is the boundary under test
        raise AssertionError("private KEMP code reached the Prom search adapter")


def test_private_motors_context_cannot_be_used_as_market_grouping() -> None:
    assert _motors_context_is_public(_context()) is True
    assert _motors_context_is_public(
        _context(normalized_part_code="776414")
    ) is False
    assert _motors_context_is_public(
        _context(via_oe_number="776414")
    ) is False


def test_private_compare_query_rebuilds_from_public_seed_mpn(monkeypatch) -> None:
    queries: list[str] = []
    seed = _seed()
    seed = replace(
        seed,
        product=product(
            id=1,
            name=seed.product.name,
            price="5163",
            company={"id": 2847093, "name": "KEMP"},
            identifiers={"mpn": "TH652688J"},
        ),
    )
    monkeypatch.setattr(
        PromGateway,
        "_fetch_seed_with_motors",
        lambda self, client, url, lang: (seed, None),
    )
    monkeypatch.setattr(
        PromGateway,
        "_collect_candidates",
        lambda self, client, query, lang, *, strict=False: (
            queries.append(query) or iter([_offer(1, "1200")])
        ),
    )
    monkeypatch.setattr(
        PromGateway,
        "_fetch_candidate_detail",
        lambda self, client, listing, *, lang: listing,
    )

    PromGateway().compare(SEED_URL, query="776414")

    assert queries == ["TH652688J"]
