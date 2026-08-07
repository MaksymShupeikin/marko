"""Which failed HTTP request may discard a whole pricing target.

A competitor's product card is not a required request. ``PromGateway`` already
degrades a broken card to ``detail_status=FAILED`` and keeps the listing, so
failing the target on it discarded every search page and every other candidate
that did complete: one 404 on one competitor made the position permanently
uncollected, because ``upstream_4xx`` maps to ``retryable=False``.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
import requests

from marko.parsers.prom.client import HttpClient
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.exceptions import RequestFailed
from marko.services.market_collection import _raise_on_required_request_failure
from marko.services.scrape_runtime import ScrapeExecutionTrace, scrape_execution
from marko.services.scraper_contract import ScraperBoundaryError, ScraperErrorCode

_SEARCH_URL = "https://prom.ua/ua/search"
_CARD_URL = "https://prom.ua/ua/p{product_id}-product.html"


def _response(
    status: int,
    *,
    url: str,
    body: bytes = b"<html>ok</html>",
    location: str | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = url
    response._content = body  # noqa: SLF001 - requests test fixture
    response.encoding = "utf-8"
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    if location is not None:
        response.headers["Location"] = location
    return response


def _gate_stub() -> None:
    """Transport-level fixture; authorization is covered by its own suite."""


def _client(responses: list[requests.Response]) -> HttpClient:
    client = HttpClient(
        ScrapeConfig(delay=0, delay_jitter=0, max_attempts=1, backoff_factor=0),
        live_request_gate=_gate_stub,
    )
    client._session.get = Mock(side_effect=responses)  # noqa: SLF001
    return client


def _fetch_card(client: HttpClient, product_id: int) -> None:
    """Fetch one competitor card the way the gateway does: never propagating."""

    try:
        client.get_html(_CARD_URL.format(product_id=product_id))
    except RequestFailed:
        return


def test_a_broken_competitor_card_does_not_discard_the_target() -> None:
    trace = ScrapeExecutionTrace(item_kind="comparison_job", execution_no=1)
    client = _client(
        [
            _response(200, url=f"{_SEARCH_URL}?search_term=7E5827505A"),
            _response(200, url=_CARD_URL.format(product_id=1)),
            _response(404, url=_CARD_URL.format(product_id=2), body=b""),
        ]
    )

    with scrape_execution(trace):
        client.get_html(_SEARCH_URL, params={"search_term": "7E5827505A"})
        _fetch_card(client, 1)
        _fetch_card(client, 2)

    _raise_on_required_request_failure(trace)


def test_a_target_whose_every_card_failed_has_no_detail_evidence() -> None:
    """Search rows alone can never become automatically priceable."""

    trace = ScrapeExecutionTrace(item_kind="comparison_job", execution_no=1)
    client = _client(
        [
            _response(200, url=f"{_SEARCH_URL}?search_term=7E5827505A"),
            _response(404, url=_CARD_URL.format(product_id=1), body=b""),
            _response(404, url=_CARD_URL.format(product_id=2), body=b""),
        ]
    )

    with scrape_execution(trace):
        client.get_html(_SEARCH_URL, params={"search_term": "7E5827505A"})
        _fetch_card(client, 1)
        _fetch_card(client, 2)

    with pytest.raises(ScraperBoundaryError) as error:
        _raise_on_required_request_failure(trace)

    assert error.value.code is ScraperErrorCode.UPSTREAM_4XX


def test_a_failed_search_page_still_discards_the_target() -> None:
    trace = ScrapeExecutionTrace(item_kind="comparison_job", execution_no=1)
    client = _client([_response(500, url=f"{_SEARCH_URL}?search_term=X", body=b"")])

    with scrape_execution(trace), pytest.raises(RequestFailed):
        client.get_html(_SEARCH_URL, params={"search_term": "X"})

    with pytest.raises(ScraperBoundaryError) as error:
        _raise_on_required_request_failure(trace)

    assert error.value.code is ScraperErrorCode.RETRY_EXHAUSTED


def test_the_end_of_pagination_redirect_is_not_a_failed_search_page() -> None:
    """Prom answers a page past its own reported total with a canonical 301.

    ``_collect_candidates`` stops there and keeps everything already collected;
    the catalog-discovery path has tolerated the same probe since 2026-07-26.
    """

    trace = ScrapeExecutionTrace(item_kind="comparison_job", execution_no=1)
    client = _client(
        [
            _response(200, url=f"{_SEARCH_URL}?search_term=8E0121251L"),
            _response(
                301,
                url=f"{_SEARCH_URL}?search_term=8E0121251L&page=2",
                body=b"",
                location="/ua/search?search_term=8E0121251L",
            ),
        ]
    )

    with scrape_execution(trace):
        client.get_html(_SEARCH_URL, params={"search_term": "8E0121251L"})
        with pytest.raises(RequestFailed):
            client.get_html(
                _SEARCH_URL,
                params={"search_term": "8E0121251L", "page": 2},
            )

    _raise_on_required_request_failure(trace)


def test_a_challenge_redirect_is_not_an_end_of_pagination_probe() -> None:
    trace = ScrapeExecutionTrace(item_kind="comparison_job", execution_no=1)
    client = _client(
        [
            _response(200, url=f"{_SEARCH_URL}?search_term=X"),
            _response(
                301,
                url=f"{_SEARCH_URL}?search_term=X&page=2",
                body=b"",
                location="https://example.net/challenge",
            ),
        ]
    )

    with scrape_execution(trace):
        client.get_html(_SEARCH_URL, params={"search_term": "X"})
        with pytest.raises(RequestFailed):
            client.get_html(_SEARCH_URL, params={"search_term": "X", "page": 2})

    with pytest.raises(ScraperBoundaryError) as error:
        _raise_on_required_request_failure(trace)

    assert error.value.code is ScraperErrorCode.UPSTREAM_3XX
