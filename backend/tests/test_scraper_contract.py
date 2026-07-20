from concurrent.futures import ThreadPoolExecutor
import json
from threading import Lock

import pytest
import requests

from marko.parsers.prom.config import ScrapeConfig
from marko.services.scraper_contract import (
    FrozenPromScraperAdapter,
    ScrapeInput,
    ScrapeOutput,
    ScraperBoundaryError,
    ScraperErrorCode,
    classify_scraper_exception,
)

from factories import comparison_with_prices


def test_scrape_input_canonicalizes_url_and_query() -> None:
    value = ScrapeInput.build(
        "http://www.prom.ua/UA/p123-example.html?utm=x#fragment",
        "  oe   123 ",
    )

    assert value.canonical_url == "https://prom.ua/ua/p123-example.html"
    assert value.product_key == "prom:product:123"
    assert value.query == "OE 123"
    assert len(value.input_hash) == 64

    seller_value = ScrapeInput.build(
        "https://kemp-cs2847093.prom.ua/p123-example.html?utm=x",
        "oe 123",
    )
    assert seller_value.canonical_url == "https://prom.ua/ua/p123-example.html"
    assert seller_value.product_key == "prom:product:123"


@pytest.mark.parametrize(
    "url",
    [
        None,
        "https://example.com/ua/p1-product.html",
        "https://evilprom.ua/ua/p1-product.html",
        "https://prom.ua.example.com/ua/p1-product.html",
        "https://prom.ua/not-a-product",
    ],
)
def test_scrape_input_rejects_invalid_boundary(url) -> None:
    with pytest.raises(ScraperBoundaryError) as captured:
        ScrapeInput.build(url, "OE")

    assert captured.value.code == ScraperErrorCode.INVALID_INPUT
    assert captured.value.retryable is False


def test_scrape_output_is_deterministic_and_reports_completeness() -> None:
    scrape_input = ScrapeInput.build(
        "https://prom.ua/ua/p1-product.html",
        "OE-1",
    )
    comparison = comparison_with_prices([900, 950])

    first = ScrapeOutput.from_comparison(scrape_input, comparison)
    second = ScrapeOutput.from_comparison(scrape_input, comparison)

    assert first.content_sha256 == second.content_sha256
    assert first.payload == second.payload
    assert first.structured_completeness == 1
    record = first.payload["output"]["records"][0]
    assert record["product"]["product_id"] == 2
    assert "sku" in record["product"]
    assert "model_id" in record["product"]
    assert "is_available" in record["product"]
    expected_output_size = len(
        json.dumps(
            first.payload["output"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    )
    assert first.structured_size_bytes == expected_output_size


def test_stored_output_rejects_unsupported_schema() -> None:
    with pytest.raises(ScraperBoundaryError) as captured:
        ScrapeOutput.from_payload(
            {"schema_version": "wrong", "input": {}, "output": {"offers": []}}
        )

    assert captured.value.code == ScraperErrorCode.SERIALIZATION


def test_exception_taxonomy_separates_retryable_and_terminal_failures() -> None:
    timeout = classify_scraper_exception(requests.Timeout("slow"))
    invalid = classify_scraper_exception(ValueError("bad input"))

    assert (timeout.code, timeout.retryable) == (
        ScraperErrorCode.TIMEOUT,
        True,
    )
    assert (invalid.code, invalid.retryable) == (
        ScraperErrorCode.INVALID_INPUT,
        False,
    )


def test_frozen_adapter_uses_fresh_gateway_per_parallel_call() -> None:
    comparison = comparison_with_prices([900])
    created: list[object] = []
    lock = Lock()

    class Gateway:
        def compare(self, _url, query, *, strict):
            assert query == "OE-1"
            assert strict is True
            return comparison

    def factory(_config):
        gateway = Gateway()
        with lock:
            created.append(gateway)
        return gateway

    adapter = FrozenPromScraperAdapter(
        ScrapeConfig(delay=0, delay_jitter=0),
        gateway_factory=factory,
    )
    scrape_input = ScrapeInput.build(
        "https://prom.ua/ua/p1-product.html",
        "OE-1",
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs = list(pool.map(adapter.extract, [scrape_input] * 8))

    assert len(created) == 8
    assert len({id(gateway) for gateway in created}) == 8
    assert len({output.content_sha256 for output in outputs}) == 1


def test_scrape_config_names_physical_attempt_budget_unambiguously() -> None:
    config = ScrapeConfig(max_attempts=4)

    assert config.max_attempts == 4
    assert not hasattr(config, "max_retries")
