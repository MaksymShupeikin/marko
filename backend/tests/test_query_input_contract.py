from pathlib import Path
from types import SimpleNamespace

import pytest

from marko.services.scraper_contract import (
    FrozenPromScraperAdapter,
    ProductSeedInput,
    QueryInput,
    ScrapeOutput,
    ScraperBoundaryError,
    ScraperErrorCode,
)
from marko.services.scraper_metrics import _target_offer_count


def test_query_input_is_deterministic_and_never_requires_a_url() -> None:
    first = QueryInput.build("  1k0  121 251  ", language="UA")
    second = QueryInput.build("1K0 121 251", language="ua")

    assert first == second
    assert first.input_kind == "query"
    assert first.query == "1K0 121 251"
    assert first.as_dict()["canonical_url"] is None
    assert len(first.input_hash) == 64


def test_query_hash_namespace_cannot_collide_with_product_seed() -> None:
    query = QueryInput.build("OE-123")
    product = ProductSeedInput.build(
        "https://prom.ua/ua/p123-part.html",
        "OE-123",
    )

    assert query.input_hash != product.input_hash


def test_query_context_is_frozen_but_never_relabels_the_identity_query() -> None:
    plain = QueryInput.build("25307", language="ua")
    focused = QueryInput.build(
        "25307",
        language="ua",
        search_context="  Шрус   VW Polo  ",
    )
    equivalent = QueryInput.build(
        "25307",
        language="UA",
        search_context="ШРУС VW POLO",
    )

    assert focused == equivalent
    assert focused.query == "25307"
    assert focused.search_context == "ШРУС VW POLO"
    assert focused.query_key != plain.query_key
    assert focused.input_hash != plain.input_hash
    assert focused.as_dict()["search_context"] == "ШРУС VW POLO"


def test_query_output_rejects_tampered_retrieval_context() -> None:
    scrape_input = QueryInput.build(
        "25307",
        search_context="Шрус GKN-Spidan VW Polo",
    )
    payload = ScrapeOutput.from_search(scrape_input, []).payload
    payload["input"]["search_context"] = "Тормозные колодки"

    with pytest.raises(
        ScraperBoundaryError,
        match="input_hash does not match its canonical input",
    ) as captured:
        ScrapeOutput.from_payload(payload)

    assert captured.value.code == ScraperErrorCode.ACQUISITION_CONTRACT


@pytest.mark.parametrize(
    "value",
    [None, "", "   ", "https://prom.ua/ua/p1-x.html", "invalid://placeholder"],
)
def test_query_rejects_empty_url_and_sentinel_values(value: str | None) -> None:
    with pytest.raises(ScraperBoundaryError) as captured:
        QueryInput.build(value)

    assert captured.value.code == ScraperErrorCode.INVALID_INPUT
    assert captured.value.retryable is False


def test_query_rejects_values_longer_than_255_characters() -> None:
    with pytest.raises(ScraperBoundaryError) as captured:
        QueryInput.build("X" * 256)

    assert captured.value.code == ScraperErrorCode.INVALID_INPUT


def test_query_adapter_calls_search_strictly_and_not_compare() -> None:
    calls: list[tuple[str, str, bool]] = []

    class Gateway:
        def __init__(self, _config) -> None:
            pass

        def search(self, query: str, *, lang: str, strict: bool):
            calls.append((query, lang, strict))
            return iter(())

        def compare(self, *_args, **_kwargs):
            raise AssertionError("query acquisition must not call compare")

    output = FrozenPromScraperAdapter(gateway_factory=Gateway).extract(
        QueryInput.build("1K0121251", language="ua")
    )

    assert calls == [("1K0121251", "ua", True)]
    assert output.payload["output"] == {
        "acquisition_outcome": "EMPTY_SEARCH_RESULT",
        # Пустая выдача всё равно называет, чем она была: текстовый поиск без
        # подготовленного URL и без запрошенного номера. Отсутствие блока и
        # пустой рынок — разные утверждения (F6).
        "acquisition": {
            "source": "SEARCH",
            "method": "TEXT_SEARCH",
            "queried_oe_norm": None,
            "via_oe_number": None,
            "is_widened": False,
            "source_url": None,
            "input_hash": QueryInput.build("1K0121251", language="ua").input_hash,
        },
        "candidates_scanned": 0,
        "records": [],
    }


def test_query_adapter_prefers_bounded_detail_search_when_gateway_supports_it() -> None:
    calls: list[tuple[str, str, bool, frozenset[str]]] = []

    class Gateway:
        def __init__(self, _config) -> None:
            pass

        def search_enriched(
            self,
            query: str,
            *,
            lang: str,
            strict: bool,
            excluded_seller_ids: frozenset[str],
        ):
            calls.append((query, lang, strict, excluded_seller_ids))
            return []

        def search(self, *_args, **_kwargs):
            raise AssertionError("detail-capable gateway must use search_enriched")

    FrozenPromScraperAdapter(
        gateway_factory=Gateway,
        excluded_seller_ids=frozenset({"3912822"}),
    ).extract(QueryInput.build("1086282", language="ua"))

    assert calls == [("1086282", "ua", True, frozenset({"3912822"}))]


def test_query_adapter_passes_frozen_context_only_to_detail_capable_gateway() -> None:
    calls: list[tuple[str, str | None]] = []

    class Gateway:
        def __init__(self, _config) -> None:
            pass

        def search_enriched(self, query: str, *, context: str | None, **_kwargs):
            calls.append((query, context))
            return []

    FrozenPromScraperAdapter(gateway_factory=Gateway).extract(
        QueryInput.build("25307", search_context="Шрус VW Polo")
    )

    assert calls == [("25307", "ШРУС VW POLO")]


def test_missing_product_url_sentinel_has_no_runtime_occurrence() -> None:
    source_root = Path(__file__).parents[1] / "src"
    forbidden = "invalid" + "://missing-product-url"
    occurrences = [
        path
        for path in source_root.rglob("*.py")
        if forbidden in path.read_text(encoding="utf-8")
    ]
    assert occurrences == []


def test_v2_candidate_records_are_visible_to_scaling_metrics() -> None:
    target = SimpleNamespace(
        payload={"output": {"records": [{}, {}, {}]}},
    )

    assert _target_offer_count(target) == 3


def test_confirmed_crosses_travel_with_the_query_and_are_frozen_into_its_hash() -> None:
    """A cross number may widen retrieval only if the run declared it.

    The customer's rule (2026-08-06): the original vehicle OE is the market
    identity, and a cross/OE relation is an allowed widening only with a
    confirmed source and provenance. Freezing the declared set into the input
    hash is what makes "the run declared it" checkable afterwards.
    """

    plain = QueryInput.build("31211128157", language="ua")
    widened = QueryInput.build(
        "31211128157",
        language="ua",
        fallback_queries=("  31 21 1 128 158 ", "1K0412249"),
    )
    equivalent = QueryInput.build(
        "31211128157",
        language="ua",
        fallback_queries=("31 21 1 128 158", "1k0412249"),
    )

    assert widened == equivalent
    assert widened.query == "31211128157"
    assert widened.fallback_queries == ("31 21 1 128 158", "1K0412249")
    assert widened.input_hash != plain.input_hash
    assert widened.query_key != plain.query_key
    assert widened.as_dict()["fallback_queries"] == ["31 21 1 128 158", "1K0412249"]


def test_the_declared_cross_order_is_part_of_the_identity() -> None:
    """Order decides which widening is tried first, so it cannot be free."""

    first = QueryInput.build("OE-1", fallback_queries=("A-1", "B-1"))
    second = QueryInput.build("OE-1", fallback_queries=("B-1", "A-1"))

    assert first.input_hash != second.input_hash


def test_a_query_declares_each_cross_once_and_never_itself() -> None:
    scrape_input = QueryInput.build(
        "31211128157",
        fallback_queries=("1K0412249", "1k0412249", " 31211128157 ", ""),
    )

    assert scrape_input.fallback_queries == ("1K0412249",)


def test_a_private_kemp_code_cannot_be_declared_as_a_widening() -> None:
    """``776…`` is a join key into the KEMP catalogue, never a market query."""

    with pytest.raises(ScraperBoundaryError) as error:
        QueryInput.build("31211128157", fallback_queries=("77641360",))

    assert error.value.code is ScraperErrorCode.INVALID_INPUT


def test_discovery_queries_are_a_separate_frozen_list_from_confirmed_crosses() -> None:
    """The two lists are not interchangeable, so the boundary keeps them apart.

    A confirmed cross asserts identity and may widen the priced market. A
    retrieval-only key — the row's public MPN, a characteristic part number —
    asserts nothing: it is allowed to *find* offers and never to price them.
    Merging them into one anonymous list would erase exactly the distinction
    the customer's namespace rule is built on.
    """

    crosses_only = QueryInput.build("31211128157", fallback_queries=("1K0412249",))
    discovery_only = QueryInput.build("31211128157", discovery_queries=("1K0412249",))
    both = QueryInput.build(
        "31211128157",
        fallback_queries=("1K0412249",),
        discovery_queries=("606554",),
    )

    assert discovery_only.discovery_queries == ("1K0412249",)
    assert discovery_only.fallback_queries == ()
    # Same number, different legal status: the hashes must not collide.
    assert discovery_only.input_hash != crosses_only.input_hash
    assert discovery_only.query_key != crosses_only.query_key
    assert both.as_dict()["discovery_queries"] == ["606554"]


def test_a_discovery_key_is_normalized_deduped_and_never_the_primary() -> None:
    scrape_input = QueryInput.build(
        "31211128157",
        discovery_queries=("  606 554 ", "606 554", " 31211128157 ", ""),
    )

    assert scrape_input.discovery_queries == ("606 554",)


def test_a_number_declared_as_a_confirmed_cross_is_not_repeated_as_discovery() -> None:
    """Otherwise the same query is issued twice and the weaker status wins."""

    scrape_input = QueryInput.build(
        "31211128157",
        fallback_queries=("1K0412249",),
        discovery_queries=("1k0412249", "606554"),
    )

    assert scrape_input.fallback_queries == ("1K0412249",)
    assert scrape_input.discovery_queries == ("606554",)


def test_a_private_kemp_code_cannot_be_declared_as_a_discovery_key() -> None:
    """The namespace rule does not soften for a weaker retrieval status."""

    with pytest.raises(ScraperBoundaryError) as error:
        QueryInput.build("31211128157", discovery_queries=("77641360",))

    assert error.value.code is ScraperErrorCode.INVALID_INPUT


def test_a_discovery_only_query_still_reaches_the_gateway_with_a_threshold() -> None:
    """The threshold is what makes either widening tier run at all.

    ``_extend_via_declared_widenings`` returns immediately on
    ``min_independent_sellers <= 0``.  Passing it only when confirmed crosses
    exist would leave the discovery tier frozen into the input hash and never
    issued — and rows carrying a public MPN without any confirmed cross are
    the common case, not the corner one.
    """

    calls: list[dict[str, object]] = []

    class Gateway:
        def __init__(self, _config) -> None:
            pass

        def search_enriched(self, query: str, **kwargs):
            calls.append({"query": query, **kwargs})
            return []

    FrozenPromScraperAdapter(
        gateway_factory=Gateway,
        min_independent_sellers=3,
    ).extract(QueryInput.build("1086282", discovery_queries=("TH652688J",)))

    assert calls[0]["discovery_queries"] == ("TH652688J",)
    assert calls[0]["min_independent_sellers"] == 3
    assert "fallback_queries" not in calls[0]
