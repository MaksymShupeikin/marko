from __future__ import annotations

from urllib.parse import urlencode

import pytest

import marko.parsers.prom.gateway as gateway_module
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.exceptions import RequestFailed
from marko.parsers.prom.gateway import PromGateway
from marko.services.parser_models import ListingPage

from factories import product


class _PageClient:
    def __init__(self, fail_from: int | None = None, status: int = 301) -> None:
        self.requested_pages: list[int] = []
        self._fail_from = fail_from
        self._status = status

    def get_html(self, _url: str, *, params: dict[str, object]) -> str:
        page_number = int(params.get("page", 1))
        self.requested_pages.append(page_number)
        if self._fail_from is not None and page_number >= self._fail_from:
            request_url = f"{_url}?{urlencode(params)}"
            canonical_params = {
                key: value for key, value in params.items() if key != "page"
            }
            raise RequestFailed(
                f"HTTP {self._status}",
                status_code=self._status,
                request_url=request_url,
                redirect_location=f"{_url}?{urlencode(canonical_params)}",
            )
        return str(page_number)


def _products(start: int, count: int):
    return [product(id=product_id) for product_id in range(start, start + count)]


def test_search_collects_variable_pages_until_reported_total(monkeypatch) -> None:
    pages = {
        1: ListingPage(products=_products(1, 29), total=90, lang="ua"),
        2: ListingPage(products=_products(30, 29), total=90, lang="ua"),
        3: ListingPage(products=_products(59, 32), total=90, lang="ua"),
    }
    client = _PageClient()
    monkeypatch.setattr(
        gateway_module,
        "parse_search",
        lambda html, _lang: pages[int(html)],
    )

    result = list(
        PromGateway(ScrapeConfig(max_search_pages=10))._collect_candidates(
            client,
            "7E5827505A",
            "ua",
            strict=True,
        )
    )

    assert len(result) == 90
    assert len({item.id for item in result}) == 90
    assert client.requested_pages == [1, 2, 3]


def test_search_with_unknown_total_stops_on_empty_page(monkeypatch) -> None:
    pages = {
        1: ListingPage(products=_products(1, 1), total=None, lang="ua"),
        2: ListingPage(products=_products(2, 2), total=None, lang="ua"),
        3: ListingPage(
            products=[],
            total=0,
            lang="ua",
            outcome="EMPTY_SEARCH_RESULT",
        ),
    }
    client = _PageClient()
    monkeypatch.setattr(
        gateway_module,
        "parse_search",
        lambda html, _lang: pages[int(html)],
    )

    result = list(
        PromGateway(ScrapeConfig(max_search_pages=5))._collect_candidates(
            client,
            "7E5827505A",
            "ua",
            strict=True,
        )
    )

    assert [item.id for item in result] == [1, 2, 3]
    assert client.requested_pages == [1, 2, 3]


def test_search_total_zero_is_one_empty_request(monkeypatch) -> None:
    client = _PageClient()
    monkeypatch.setattr(
        gateway_module,
        "parse_search",
        lambda _html, _lang: ListingPage(
            products=[],
            total=0,
            lang="ua",
            outcome="EMPTY_SEARCH_RESULT",
        ),
    )

    result = list(
        PromGateway(ScrapeConfig(max_search_pages=10))._collect_candidates(
            client,
            "7E5827505A",
            "ua",
            strict=True,
        )
    )

    assert result == []
    assert client.requested_pages == [1]


def test_search_stops_when_prom_repeats_the_same_page(monkeypatch) -> None:
    repeated = ListingPage(products=_products(1, 2), total=90, lang="ua")
    client = _PageClient()
    monkeypatch.setattr(
        gateway_module,
        "parse_search",
        lambda _html, _lang: repeated,
    )

    result = list(
        PromGateway(ScrapeConfig(max_search_pages=10))._collect_candidates(
            client,
            "7E5827505A",
            "ua",
            strict=True,
        )
    )

    assert [item.id for item in result] == [1, 2]
    assert client.requested_pages == [1, 2]


def test_redirect_past_the_last_page_keeps_everything_collected(monkeypatch) -> None:
    """Measured on 2026-07-26: query 8E0121251L reports 67 but serves 66.

    The stop-on-total condition never fires, page 4 answers 301, and before the
    fix that redirect discarded all 66 products already in hand.
    """

    pages = {
        1: ListingPage(products=_products(1, 29), total=67, lang="ua"),
        2: ListingPage(products=_products(30, 29), total=67, lang="ua"),
        3: ListingPage(products=_products(59, 8), total=67, lang="ua"),
    }
    client = _PageClient(fail_from=4)
    monkeypatch.setattr(
        gateway_module,
        "parse_search",
        lambda html, _lang: pages[int(html)],
    )

    result = list(
        PromGateway(ScrapeConfig(max_search_pages=10))._collect_candidates(
            client,
            "8E0121251L",
            "ua",
            strict=True,
        )
    )

    assert len(result) == 66
    assert client.requested_pages == [1, 2, 3, 4]


def test_redirect_on_the_first_page_still_raises_in_strict_mode() -> None:
    """Nothing was collected, so a first-page redirect must not be swallowed."""

    client = _PageClient(fail_from=1)

    with pytest.raises(RequestFailed):
        list(
            PromGateway(ScrapeConfig(max_search_pages=10))._collect_candidates(
                client,
                "8E0121251L",
                "ua",
                strict=True,
            )
        )

    assert client.requested_pages == [1]


@pytest.mark.parametrize("status", [403, 429, 500, 503])
def test_non_redirect_failure_past_page_one_still_raises(
    monkeypatch,
    status: int,
) -> None:
    """Only 3xx means "no such page"; a real fault must stay a failure."""

    pages = {1: ListingPage(products=_products(1, 29), total=90, lang="ua")}
    client = _PageClient(fail_from=2, status=status)
    monkeypatch.setattr(
        gateway_module,
        "parse_search",
        lambda html, _lang: pages[int(html)],
    )

    with pytest.raises(RequestFailed):
        list(
            PromGateway(ScrapeConfig(max_search_pages=10))._collect_candidates(
                client,
                "7E5827505A",
                "ua",
                strict=True,
            )
        )


def test_request_failed_without_a_status_code_is_not_a_pagination_end() -> None:
    assert RequestFailed("connection reset").is_redirect is False
    assert gateway_module._is_pagination_end(RequestFailed("boom"), 5) is False


def test_seller_catalog_last_page_redirect_is_a_pagination_end() -> None:
    error = RequestFailed(
        "HTTP 301",
        status_code=301,
        request_url="https://prom.ua/ua/c2847093-kemp.html?page=346",
        redirect_location="/ua/c2847093-kemp.html",
    )

    assert gateway_module._is_pagination_end(error, 346) is True


@pytest.mark.parametrize(
    ("status", "page_num", "location", "expected"),
    [
        (301, 2, "/ua/search?search_term=OE", True),
        (302, 9, "/ua/search?search_term=OE", False),
        (308, 2, "/ua/search?search_term=OE", False),
        (301, 1, "/ua/search?search_term=OE", False),
        (301, 2, "/ua/search?search_term=OTHER", False),
        (301, 2, "https://evil.example/challenge", False),
        (301, 2, None, False),
        (400, 2, "/ua/search?search_term=OE", False),
    ],
)
def test_pagination_end_boundaries(
    status: int,
    page_num: int,
    location: str | None,
    expected: bool,
) -> None:
    error = RequestFailed(
        f"HTTP {status}",
        status_code=status,
        request_url=f"https://prom.ua/ua/search?search_term=OE&page={page_num}",
        redirect_location=location,
    )

    assert gateway_module._is_pagination_end(error, page_num) is expected
