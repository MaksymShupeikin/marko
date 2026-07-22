from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import ClassVar

import pytest

from factories import html_with_state, raw_product
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.gateway import PromGateway

_SELLER_URL = "https://prom.ua/ua/c1-store.html"


def listing_html(
    product_ids: list[int],
    total: int | None,
    group_ids: tuple[str, ...] = (),
) -> str:
    state = {
        "_FAST_CACHE": {
            "CompanyListingQuery({})": {
                "result": {
                    "listing": {
                        "page": {
                            "total": total,
                            "products": [
                                {"product": raw_product(id=product_id)}
                                for product_id in product_ids
                            ],
                        }
                    }
                }
            }
        }
    }
    links = "".join(
        f'<a href="/ua/c1-store.html?product_group={group_id}">group</a>'
        for group_id in group_ids
    )
    return html_with_state(state) + links


class FakeAsyncHttpClient:
    pages: ClassVar[dict[tuple[str | None, int], str]] = {}
    calls: ClassVar[list[tuple[str | None, int]]] = []
    response_delay: ClassVar[float] = 0
    active_requests: ClassVar[int] = 0
    max_active_requests: ClassVar[int] = 0

    def __init__(self, _config: ScrapeConfig) -> None:
        pass

    async def __aenter__(self) -> FakeAsyncHttpClient:
        return self

    async def __aexit__(self, *_exc) -> None:
        pass

    async def get_html(self, _url: str, params: dict | None = None) -> str:
        query = params or {}
        key = (query.get("product_group"), query.get("page", 1))
        self.calls.append(key)
        client_type = type(self)
        client_type.active_requests += 1
        client_type.max_active_requests = max(
            client_type.max_active_requests,
            client_type.active_requests,
        )
        try:
            await asyncio.sleep(self.response_delay)
            return self.pages[key]
        finally:
            client_type.active_requests -= 1


@pytest.fixture(autouse=True)
def fake_async_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    FakeAsyncHttpClient.pages = {}
    FakeAsyncHttpClient.calls = []
    FakeAsyncHttpClient.response_delay = 0
    FakeAsyncHttpClient.active_requests = 0
    FakeAsyncHttpClient.max_active_requests = 0
    monkeypatch.setattr(
        "marko.parsers.prom.gateway.AsyncHttpClient",
        FakeAsyncHttpClient,
    )
    yield


async def collect_product_ids(gateway: PromGateway) -> list[int | None]:
    return [product.id async for product in gateway.scrape_strict_async(_SELLER_URL)]


async def test_capped_catalog_expands_groups_and_deduplicates_products():
    FakeAsyncHttpClient.pages = {
        (None, 1): listing_html([1, 2], 4, ("10", "20")),
        (None, 2): listing_html([3, 4], 4),
        ("10", 1): listing_html([1, 5], 2),
        ("20", 1): listing_html([4, 6], 2),
    }
    gateway = PromGateway(
        ScrapeConfig(
            delay=0,
            delay_jitter=0,
            page_concurrency=2,
            catalog_result_limit=4,
        )
    )

    assert await collect_product_ids(gateway) == [1, 2, 3, 4, 5, 6]


async def test_catalog_below_limit_does_not_fetch_redundant_groups():
    FakeAsyncHttpClient.pages = {
        (None, 1): listing_html([1, 2], 2, ("10",)),
    }
    gateway = PromGateway(ScrapeConfig(catalog_result_limit=4))

    await collect_product_ids(gateway)

    assert FakeAsyncHttpClient.calls == [(None, 1)]


async def test_max_pages_preserves_diagnostic_page_limit():
    FakeAsyncHttpClient.pages = {
        (None, 1): listing_html([1, 2], 4, ("10",)),
    }
    gateway = PromGateway(
        ScrapeConfig(max_pages=1, catalog_result_limit=4)
    )

    assert await collect_product_ids(gateway) == [1, 2]


async def test_known_pages_are_fetched_with_bounded_concurrency():
    FakeAsyncHttpClient.pages = {
        (None, 1): listing_html([1, 2], 6),
        (None, 2): listing_html([3, 4], 6),
        (None, 3): listing_html([5, 6], 6),
    }
    FakeAsyncHttpClient.response_delay = 0.01
    gateway = PromGateway(ScrapeConfig(page_concurrency=2))

    await collect_product_ids(gateway)

    assert FakeAsyncHttpClient.max_active_requests == 2


async def test_product_group_pages_share_one_interleaved_queue():
    FakeAsyncHttpClient.pages = {
        (None, 1): listing_html([1, 2], 4, ("10", "20")),
        (None, 2): listing_html([3, 4], 4),
        ("10", 1): listing_html([1, 5], 6),
        ("10", 2): listing_html([6, 7], 6),
        ("10", 3): listing_html([8, 9], 6),
        ("20", 1): listing_html([4, 10], 6),
        ("20", 2): listing_html([11, 12], 6),
        ("20", 3): listing_html([13, 14], 6),
    }
    gateway = PromGateway(
        ScrapeConfig(page_concurrency=2, catalog_result_limit=4)
    )

    await collect_product_ids(gateway)

    assert FakeAsyncHttpClient.calls == [
        (None, 1),
        (None, 2),
        ("10", 1),
        ("20", 1),
        ("10", 2),
        ("20", 2),
        ("10", 3),
        ("20", 3),
    ]


def test_default_page_concurrency_uses_eight_connections():
    assert ScrapeConfig().page_concurrency == 8


async def test_unknown_total_stops_when_prom_redirects_to_seen_page():
    FakeAsyncHttpClient.pages = {
        (None, 1): listing_html([1, 2], None),
        (None, 2): listing_html([3, 4], None),
        (None, 3): listing_html([1, 2], None),
    }
    gateway = PromGateway(ScrapeConfig())

    assert await collect_product_ids(gateway) == [1, 2, 3, 4]
