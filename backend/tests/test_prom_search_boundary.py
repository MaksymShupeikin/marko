from __future__ import annotations

from dataclasses import replace

import pytest

import marko.parsers.prom.gateway as gateway_module
from marko.parsers.prom.gateway import (
    PromGateway,
    _contextual_search_query,
    _detail_priority,
)

from factories import product


class _FakeClient:
    def __init__(self, _config) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        pass


def test_search_exposes_raw_results_without_comparison(monkeypatch) -> None:
    expected = product(id=42)
    observed: list[tuple[str, str, bool]] = []

    monkeypatch.setattr(gateway_module, "HttpClient", _FakeClient)

    def fake_collect(self, _client, query, lang, *, strict):
        observed.append((query, lang, strict))
        yield expected

    monkeypatch.setattr(PromGateway, "_collect_candidates", fake_collect)

    assert list(PromGateway().search("  1K0121251  ", lang="UA", strict=True)) == [
        expected
    ]
    assert observed == [("1K0121251", "ua", True)]


@pytest.mark.parametrize("query", ["", "   "])
def test_search_rejects_empty_query(query: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        list(PromGateway().search(query))


def test_search_rejects_invalid_language() -> None:
    with pytest.raises(ValueError, match="Unsupported Prom language"):
        list(PromGateway().search("1K0121251", lang="uk-UA"))


def test_short_numeric_article_gets_bounded_context_without_changing_the_code() -> None:
    assert (
        _contextual_search_query(
            "25307",
            "Шрус VW Polo/Golf/Octavia Fabia Audi A2 TT внутрішній",
        )
        == "25307 шрус vw polo golf octavia fabia"
    )
    assert _contextual_search_query("1J0498103K", "Шрус VW Polo") is None


def test_contextual_search_unions_both_passes_and_deduplicates_products(
    monkeypatch,
) -> None:
    exact = product(id=1, name="Рашпиль Vorel 25307", sku="25307")
    relevant = product(id=2, name="Шрус GKN VW Polo 25307", sku="25307")
    observed: list[str] = []

    monkeypatch.setattr(gateway_module, "HttpClient", _FakeClient)

    def fake_collect(self, _client, query, lang, *, strict):
        observed.append(query)
        return iter((exact,) if query == "25307" else (exact, relevant))

    monkeypatch.setattr(PromGateway, "_collect_candidates", fake_collect)
    monkeypatch.setattr(
        PromGateway,
        "_enrich_search_shortlist",
        lambda self, client, products, **kwargs: products,
    )

    results = PromGateway().search_enriched(
        "25307",
        context="Шрус VW Polo",
        strict=True,
    )

    assert observed == ["25307", "25307 шрус vw polo"]
    assert [item.id for item in results] == [1, 2]


def test_ambiguous_article_shortlist_prefers_semantic_context_over_exact_noise() -> (
    None
):
    noise = product(id=1, name="Рашпиль Vorel", sku="25307")
    relevant = product(id=2, name="Шрус GKN VW Polo", sku="GKN-25307")
    context = "Шрус VW Polo Golf внутрішній"

    assert _detail_priority(relevant, "25307", 1, context=context) < _detail_priority(
        noise,
        "25307",
        0,
        context=context,
    )


def test_detail_priority_does_not_treat_identifier_suffix_as_title_hit() -> None:
    suffix = product(id=1, name="Другая деталь 1K01212510")
    grouped = product(id=2, name="Другая деталь 1K0 121 251")

    assert _detail_priority(suffix, "1K0121251", 0) == (0, 2, 0, 0)
    assert _detail_priority(grouped, "1K0121251", 1) == (0, 1, 0, 1)


def test_detail_priority_prefers_exact_labelled_part_number() -> None:
    labelled = replace(
        product(id=1, name="Другая деталь"),
        part_numbers=("25307",),
    )
    title_only = product(id=2, name="Другая деталь 25307")

    assert _detail_priority(labelled, "25307", 0) == (0, 0, 0, 0)
    assert _detail_priority(title_only, "25307", 1) == (0, 2, 0, 1)


def test_detail_priority_prefers_exact_native_oe() -> None:
    native_oe = replace(
        product(id=1, name="Другая деталь"),
        oe_raw="25307",
    )

    assert _detail_priority(native_oe, "25307", 0) == (0, 0, 0, 0)


def test_detail_priority_requires_a_label_for_short_numeric_title_hits() -> None:
    unlabelled = product(id=1, name="Другая деталь 25307")
    labelled = product(id=2, name="Другая деталь OE 25307")
    hash_labelled = product(id=3, name="Другая деталь #25307")

    assert _detail_priority(unlabelled, "25307", 0) == (0, 2, 0, 0)
    assert _detail_priority(labelled, "25307", 1) == (0, 1, 0, 1)
    assert _detail_priority(hash_labelled, "25307", 2) == (0, 1, 0, 2)
