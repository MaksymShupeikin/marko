from pathlib import Path
from types import SimpleNamespace

import pytest

from marko.services.scraper_contract import (
    FrozenPromScraperAdapter,
    ProductSeedInput,
    QueryInput,
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
