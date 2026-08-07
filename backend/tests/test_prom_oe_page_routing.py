"""A query-only position must be able to reach prom.ua's own part grouping.

``compare`` has taken that route since it was written, but only for a catalog
item carrying a seed URL. Everything else searched text and stopped there.
Measured 2026-07-31 over 28 identical OE numbers
(``.artifacts/prom_motors_source_20260731``): 4 of 28 positions reached three
retained sellers through search, 27 of 28 through the part-code listing.
"""

from __future__ import annotations

from dataclasses import replace

import marko.parsers.prom.gateway as gateway_module
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.gateway import PromGateway, _detail_metadata
from marko.services.parser_models import MotorsContext

from factories import product


class _FakeClient:
    def __init__(self, _config) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        pass


def _motors(
    *,
    part_code: str = "7E5827505A",
    oe_page_id: int | None = 4242,
    alias: str = "kryshka-bagazhnika",
    via: str | None = None,
) -> MotorsContext:
    return MotorsContext(
        normalized_part_code=part_code,
        part_group_id=77,
        oe_page_id=oe_page_id,
        oe_page_alias=alias,
        via_oe_number=via,
    )


def _enriched(item, motors: MotorsContext | None):
    return replace(
        item,
        detail_evidence=_detail_metadata(
            item,
            status="SUCCESS",
            selected=True,
            source_url=item.url,
            content_sha256="0" * 64,
            motors=motors,
        ),
    )


def test_detail_evidence_retains_the_link_to_the_part_grouping() -> None:
    """Without these two fields the grouping URL cannot be rebuilt later."""

    metadata = _detail_metadata(
        product(id=1, company={"id": 900, "name": "KEMP"}),
        status="SUCCESS",
        selected=True,
        motors=_motors(),
    )

    assert metadata["motors"]["oe_page_id"] == 4242
    assert metadata["motors"]["oe_page_alias"] == "kryshka-bagazhnika"


def test_a_query_only_search_follows_the_grouping_a_card_exposes(monkeypatch) -> None:
    found = product(id=1, company={"id": 900, "name": "KEMP"}, sku="7E5827505A")
    grouped = [
        product(id=2, company={"id": 901, "name": "Alpha"}),
        product(id=3, company={"id": 902, "name": "Beta"}),
    ]
    walked: list[str] = []

    monkeypatch.setattr(gateway_module, "HttpClient", _FakeClient)
    monkeypatch.setattr(
        PromGateway,
        "_collect_candidates",
        lambda self, _client, _query, _lang, *, strict: iter((found,)),
    )
    monkeypatch.setattr(
        PromGateway,
        "_fetch_candidate_detail",
        lambda self, _client, item, *, lang: _enriched(item, _motors()),
    )

    def fake_oe(self, _client, context, lang):
        walked.append(context.normalized_part_code or "")
        return iter(grouped)

    monkeypatch.setattr(PromGateway, "_collect_oe_candidates", fake_oe)

    results = PromGateway(ScrapeConfig(max_sellers=5)).search_enriched("7E5827505A")

    assert walked == ["7E5827505A"]
    assert [item.id for item in results] == [1, 2, 3]


def test_the_grouping_is_not_followed_for_a_private_kemp_code(monkeypatch) -> None:
    """A private ``776…`` shelf code leaks onto our own storefront cards.

    ``_motors_context_is_public`` already refuses it for ``compare``; the query
    route must refuse it for the same reason.
    """

    found = product(id=1, company={"id": 900, "name": "KEMP"})

    monkeypatch.setattr(gateway_module, "HttpClient", _FakeClient)
    monkeypatch.setattr(
        PromGateway,
        "_collect_candidates",
        lambda self, _client, _query, _lang, *, strict: iter((found,)),
    )
    monkeypatch.setattr(
        PromGateway,
        "_fetch_candidate_detail",
        lambda self, _client, item, *, lang: _enriched(
            item, _motors(part_code="77641360")
        ),
    )

    def fail(self, _client, _context, _lang):
        raise AssertionError("a private catalog code must not open the grouping")

    monkeypatch.setattr(PromGateway, "_collect_oe_candidates", fail)

    results = PromGateway().search_enriched("7E5827505A")

    assert [item.id for item in results] == [1]


def test_a_card_without_a_grouping_leaves_the_search_result_alone(monkeypatch) -> None:
    found = product(id=1, company={"id": 900, "name": "KEMP"})

    monkeypatch.setattr(gateway_module, "HttpClient", _FakeClient)
    monkeypatch.setattr(
        PromGateway,
        "_collect_candidates",
        lambda self, _client, _query, _lang, *, strict: iter((found,)),
    )
    monkeypatch.setattr(
        PromGateway,
        "_fetch_candidate_detail",
        lambda self, _client, item, *, lang: _enriched(
            item, _motors(oe_page_id=None)
        ),
    )

    def fail(self, _client, _context, _lang):
        raise AssertionError("there is no grouping to walk")

    monkeypatch.setattr(PromGateway, "_collect_oe_candidates", fail)

    assert [item.id for item in PromGateway().search_enriched("X")] == [1]


def test_the_grouping_shares_the_detail_budget_with_the_search(monkeypatch) -> None:
    """The seller cap is the budget; the grouping may not spend it twice."""

    found = product(id=1, company={"id": 900, "name": "KEMP"}, sku="7E5827505A")
    grouped = [
        product(id=2, company={"id": 901, "name": "Alpha"}),
        product(id=3, company={"id": 902, "name": "Beta"}),
    ]
    fetched: list[int] = []

    monkeypatch.setattr(gateway_module, "HttpClient", _FakeClient)
    monkeypatch.setattr(
        PromGateway,
        "_collect_candidates",
        lambda self, _client, _query, _lang, *, strict: iter((found,)),
    )

    def fake_detail(self, _client, item, *, lang):
        fetched.append(item.id or 0)
        return _enriched(item, _motors() if item.id == 1 else None)

    monkeypatch.setattr(PromGateway, "_fetch_candidate_detail", fake_detail)
    monkeypatch.setattr(
        PromGateway,
        "_collect_oe_candidates",
        lambda self, _client, _context, _lang: iter(grouped),
    )

    results = PromGateway(
        ScrapeConfig(max_detail_cards=2)
    ).search_enriched("7E5827505A")

    assert fetched == [1, 2]
    assert [item.id for item in results] == [1, 2, 3]
    assert results[2].detail_evidence["error_code"] == "DETAIL_BUDGET"


def test_the_grouping_page_cap_is_its_own_knob() -> None:
    """A grouping of several hundred offers must not inherit the search cap."""

    assert ScrapeConfig().max_oe_page_pages == 4
    assert ScrapeConfig(max_search_pages=1).max_oe_page_pages == 4


def test_a_grouping_row_says_which_route_produced_it(monkeypatch) -> None:
    found = product(id=1, company={"id": 900, "name": "KEMP"}, sku="7E5827505A")
    grouped = [product(id=2, company={"id": 901, "name": "Alpha"})]

    monkeypatch.setattr(gateway_module, "HttpClient", _FakeClient)
    monkeypatch.setattr(
        PromGateway,
        "_collect_candidates",
        lambda self, _client, _query, _lang, *, strict: iter((found,)),
    )
    monkeypatch.setattr(
        PromGateway,
        "_fetch_candidate_detail",
        lambda self, _client, item, *, lang: _enriched(
            item, _motors() if item.id == 1 else None
        ),
    )
    monkeypatch.setattr(
        PromGateway,
        "_collect_oe_candidates",
        lambda self, _client, _context, _lang: iter(grouped),
    )

    results = PromGateway(ScrapeConfig(max_sellers=5)).search_enriched("7E5827505A")

    assert "identity_origin" not in results[0].detail_evidence
    assert results[1].detail_evidence["identity_origin"] == "PROM_OE_PAGE"


def _external_sellers(items) -> set[str]:
    return {str(item.seller_id) for item in items}


def test_a_declared_cross_is_searched_only_when_the_primary_is_thin(
    monkeypatch,
) -> None:
    """One seller is not a market; the run already declared where else to look."""

    by_query: dict[str, list] = {
        "31211128157": [product(id=1, company={"id": 901, "name": "Alpha"})],
        "1K0412249": [
            product(id=2, company={"id": 902, "name": "Beta"}),
            product(id=3, company={"id": 903, "name": "Gamma"}),
        ],
    }
    asked: list[str] = []

    monkeypatch.setattr(gateway_module, "HttpClient", _FakeClient)

    def fake_collect(self, _client, query, _lang, *, strict):
        asked.append(query)
        return iter(by_query.get(query, ()))

    monkeypatch.setattr(PromGateway, "_collect_candidates", fake_collect)
    monkeypatch.setattr(
        PromGateway,
        "_fetch_candidate_detail",
        lambda self, _client, item, *, lang: _enriched(item, None),
    )

    results = PromGateway().search_enriched(
        "31211128157",
        fallback_queries=("1K0412249",),
        min_independent_sellers=3,
    )

    assert asked == ["31211128157", "1K0412249"]
    assert _external_sellers(results) == {"901", "902", "903"}


def test_a_rich_primary_never_spends_a_cross_query(monkeypatch) -> None:
    found = [
        product(id=1, company={"id": 901, "name": "Alpha"}),
        product(id=2, company={"id": 902, "name": "Beta"}),
        product(id=3, company={"id": 903, "name": "Gamma"}),
    ]
    asked: list[str] = []

    monkeypatch.setattr(gateway_module, "HttpClient", _FakeClient)

    def fake_collect(self, _client, query, _lang, *, strict):
        asked.append(query)
        return iter(found)

    monkeypatch.setattr(PromGateway, "_collect_candidates", fake_collect)
    monkeypatch.setattr(
        PromGateway,
        "_fetch_candidate_detail",
        lambda self, _client, item, *, lang: _enriched(item, None),
    )

    PromGateway().search_enriched(
        "31211128157",
        fallback_queries=("1K0412249", "6N0412249C"),
        min_independent_sellers=3,
    )

    assert asked == ["31211128157"]


def test_a_row_says_which_declared_query_found_it(monkeypatch) -> None:
    """Identity must be verified against the number that actually retrieved it."""

    by_query: dict[str, list] = {
        "31211128157": [product(id=1, company={"id": 901, "name": "Alpha"})],
        "1K0412249": [product(id=2, company={"id": 902, "name": "Beta"})],
    }

    monkeypatch.setattr(gateway_module, "HttpClient", _FakeClient)
    monkeypatch.setattr(
        PromGateway,
        "_collect_candidates",
        lambda self, _client, query, _lang, *, strict: iter(by_query.get(query, ())),
    )
    monkeypatch.setattr(
        PromGateway,
        "_fetch_candidate_detail",
        lambda self, _client, item, *, lang: _enriched(item, None),
    )

    results = PromGateway().search_enriched(
        "31211128157",
        fallback_queries=("1K0412249",),
        min_independent_sellers=3,
    )

    assert "found_by_query" not in results[0].detail_evidence
    assert results[1].detail_evidence["found_by_query"] == "1K0412249"


def test_owned_sellers_do_not_count_towards_the_independence_threshold(
    monkeypatch,
) -> None:
    """Our own four shops were 20.7% of page one on the 2026-08-05 shadow."""

    by_query: dict[str, list] = {
        "31211128157": [
            product(id=1, company={"id": 2847093, "name": "KEMP"}),
            product(id=2, company={"id": 4015921, "name": "АвтоБуст"}),
            product(id=3, company={"id": 901, "name": "Alpha"}),
        ],
        "1K0412249": [product(id=4, company={"id": 902, "name": "Beta"})],
    }
    asked: list[str] = []

    monkeypatch.setattr(gateway_module, "HttpClient", _FakeClient)

    def fake_collect(self, _client, query, _lang, *, strict):
        asked.append(query)
        return iter(by_query.get(query, ()))

    monkeypatch.setattr(PromGateway, "_collect_candidates", fake_collect)
    monkeypatch.setattr(
        PromGateway,
        "_fetch_candidate_detail",
        lambda self, _client, item, *, lang: _enriched(item, None),
    )

    PromGateway().search_enriched(
        "31211128157",
        fallback_queries=("1K0412249",),
        min_independent_sellers=2,
        excluded_seller_ids=frozenset({"2847093", "4015921"}),
    )

    assert asked == ["31211128157", "1K0412249"]


def test_a_discovery_key_is_tried_after_the_confirmed_crosses(monkeypatch) -> None:
    """Retrieval-only keys are the last resort, and they are marked as such.

    A confirmed cross asserts identity and may widen the priced market; the
    row's own public MPN asserts nothing. Spending the weaker query first
    would fill the shortlist with rows that can never price, and the market
    the run is allowed to use would go unsearched.
    """

    by_query: dict[str, list] = {
        "31211128157": [product(id=1, company={"id": 901, "name": "Alpha"})],
        "1K0412249": [product(id=2, company={"id": 902, "name": "Beta"})],
        "606554": [product(id=3, company={"id": 903, "name": "Gamma"})],
    }
    asked: list[str] = []

    monkeypatch.setattr(gateway_module, "HttpClient", _FakeClient)

    def fake_collect(self, _client, query, _lang, *, strict):
        asked.append(query)
        return iter(by_query.get(query, ()))

    monkeypatch.setattr(PromGateway, "_collect_candidates", fake_collect)
    monkeypatch.setattr(
        PromGateway,
        "_fetch_candidate_detail",
        lambda self, _client, item, *, lang: _enriched(item, None),
    )

    results = PromGateway().search_enriched(
        "31211128157",
        fallback_queries=("1K0412249",),
        discovery_queries=("606554",),
        min_independent_sellers=3,
    )

    assert asked == ["31211128157", "1K0412249", "606554"]
    assert _external_sellers(results) == {"901", "902", "903"}
    by_seller = {str(item.seller_id): item for item in results}
    assert "found_by_query" not in by_seller["901"].detail_evidence
    assert by_seller["902"].detail_evidence["found_by_query"] == "1K0412249"
    assert by_seller["903"].detail_evidence["found_by_query"] == "606554"


def test_a_discovery_key_is_not_spent_once_the_market_is_wide_enough(
    monkeypatch,
) -> None:
    """The threshold governs both tiers; the weaker one does not get a pass."""

    found = [
        product(id=1, company={"id": 901, "name": "Alpha"}),
        product(id=2, company={"id": 902, "name": "Beta"}),
        product(id=3, company={"id": 903, "name": "Gamma"}),
    ]
    asked: list[str] = []

    monkeypatch.setattr(gateway_module, "HttpClient", _FakeClient)

    def fake_collect(self, _client, query, _lang, *, strict):
        asked.append(query)
        return iter(found)

    monkeypatch.setattr(PromGateway, "_collect_candidates", fake_collect)
    monkeypatch.setattr(
        PromGateway,
        "_fetch_candidate_detail",
        lambda self, _client, item, *, lang: _enriched(item, None),
    )

    PromGateway().search_enriched(
        "31211128157",
        discovery_queries=("606554",),
        min_independent_sellers=3,
    )

    assert asked == ["31211128157"]
