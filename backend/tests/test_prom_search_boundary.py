from __future__ import annotations

import pytest

import marko.parsers.prom.gateway as gateway_module
from marko.parsers.prom.gateway import PromGateway

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
