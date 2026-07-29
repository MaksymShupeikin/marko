from unittest.mock import Mock

import pytest
import requests

from marko.parsers.prom.client import HttpClient
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.exceptions import RequestFailed
from marko.services.scrape_runtime import (
    ReplayEvidence,
    ReplayIntegrityError,
    ScrapeExecutionTrace,
    request_fingerprint,
    scrape_execution,
)
from marko.services.scraper_contract import (
    ScraperErrorCode,
    classify_scraper_exception,
)


def _response(
    status: int,
    body: bytes = b"<html>ok</html>",
    *,
    url: str = "https://prom.ua/ua/p1-product.html",
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


def test_http_trace_separates_logical_request_and_physical_attempts() -> None:
    client = HttpClient(
        ScrapeConfig(
            delay=0,
            delay_jitter=0,
            max_attempts=2,
            backoff_factor=0,
        )
    )
    client._session.get = Mock(  # noqa: SLF001 - black-box HTTP boundary test
        side_effect=[_response(503), _response(200)]
    )
    trace = ScrapeExecutionTrace(item_kind="comparison_job", execution_no=1)

    with scrape_execution(trace):
        html = client.get_html("https://prom.ua/ua/p1-product.html")

    requests_traced = trace.drain_completed_requests()
    assert html == "<html>ok</html>"
    assert len(requests_traced) == 1
    assert requests_traced[0].outcome == "success"
    assert [attempt.outcome for attempt in requests_traced[0].attempts] == [
        "retryable_failure",
        "success",
    ]


def test_max_attempts_is_total_physical_attempts_not_extra_retries() -> None:
    client = HttpClient(
        ScrapeConfig(
            delay=0,
            delay_jitter=0,
            max_attempts=2,
            backoff_factor=0,
        )
    )
    get = Mock(side_effect=[_response(503), _response(503)])
    client._session.get = get  # noqa: SLF001
    trace = ScrapeExecutionTrace(item_kind="store_sync", execution_no=1)

    with scrape_execution(trace), pytest.raises(RequestFailed):
        client.get_html("https://prom.ua/ua/c1-store.html")

    assert get.call_count == 2
    request = trace.drain_completed_requests()[0]
    assert len(request.attempts) == 2
    assert request.outcome == "retryable_failure"


def test_raw_evidence_replay_skips_network_and_physical_attempt() -> None:
    url = "https://prom.ua/ua/p1-product.html"
    key = request_fingerprint("product_page", url)
    trace = ScrapeExecutionTrace(
        item_kind="comparison_job",
        execution_no=2,
        replay_cache={
            key: ReplayEvidence(
                request_key=key,
                body=b"<html>replayed</html>",
                encoding="utf-8",
                content_type="text/html",
            )
        },
    )
    client = HttpClient(ScrapeConfig(delay=0, delay_jitter=0))
    get = Mock(side_effect=AssertionError("network must not be called"))
    client._session.get = get  # noqa: SLF001

    with scrape_execution(trace):
        html = client.get_html(url)

    request = trace.drain_completed_requests()[0]
    assert html == "<html>replayed</html>"
    assert get.call_count == 0
    assert request.replayed is True
    assert request.attempts == []


def test_raw_evidence_replay_rejects_hash_mismatch() -> None:
    url = "https://prom.ua/ua/p1-product.html"
    key = request_fingerprint("product_page", url)
    trace = ScrapeExecutionTrace(
        item_kind="comparison_job",
        execution_no=2,
        replay_cache={
            key: ReplayEvidence(
                request_key=key,
                body=b"<html>tampered</html>",
                content_sha256="0" * 64,
            )
        },
    )
    client = HttpClient(ScrapeConfig(delay=0, delay_jitter=0))
    client._session.get = Mock(side_effect=AssertionError("no network"))  # noqa: SLF001

    with scrape_execution(trace), pytest.raises(ReplayIntegrityError):
        client.get_html(url)

    failed = trace.drain_completed_requests()
    assert len(failed) == 1
    assert failed[0].outcome == "terminal_failure"
    assert failed[0].error_category == "evidence_integrity"


def test_timeout_taxonomy_survives_http_client_retry_wrapper() -> None:
    client = HttpClient(
        ScrapeConfig(
            delay=0,
            delay_jitter=0,
            max_attempts=1,
        )
    )
    client._session.get = Mock(side_effect=requests.Timeout("slow"))  # noqa: SLF001

    with pytest.raises(RequestFailed) as captured:
        client.get_html("https://prom.ua/ua/p1-product.html")

    boundary = classify_scraper_exception(captured.value)
    assert boundary.code == ScraperErrorCode.TIMEOUT
    assert boundary.retryable is True


def test_global_request_wait_is_recorded_per_physical_attempt() -> None:
    class Guard:
        def __init__(self):
            self.successes = 0
            self.closed = False

        def wait_for_slot(self):
            return 0.25

        def record_success(self):
            self.successes += 1

        def record_failure(self):
            raise AssertionError("unexpected failure")

        def close(self):
            self.closed = True

    guard = Guard()
    trace = ScrapeExecutionTrace(
        item_kind="comparison_job",
        execution_no=1,
        guard=guard,
    )
    client = HttpClient(ScrapeConfig(delay=0, delay_jitter=0))
    client._session.get = Mock(return_value=_response(200))  # noqa: SLF001

    with scrape_execution(trace):
        client.get_html("https://prom.ua/ua/p1-product.html")
    request = trace.drain_completed_requests()[0]
    trace.close()

    assert request.attempts[0].global_rate_wait_ms == 250
    assert guard.successes == 1
    assert guard.closed is True


def test_terminal_http_failure_does_not_open_retry_circuit() -> None:
    class Guard:
        def __init__(self):
            self.failures = 0

        def wait_for_slot(self):
            return 0

        def record_success(self):
            raise AssertionError("unexpected success")

        def record_failure(self):
            self.failures += 1

        def close(self):
            return None

    guard = Guard()
    trace = ScrapeExecutionTrace(
        item_kind="comparison_job",
        execution_no=1,
        guard=guard,
    )
    client = HttpClient(ScrapeConfig(delay=0, delay_jitter=0, max_attempts=1))
    client._session.get = Mock(return_value=_response(404))  # noqa: SLF001

    with scrape_execution(trace), pytest.raises(RequestFailed):
        client.get_html("https://prom.ua/ua/p1-product.html")

    assert guard.failures == 0


def test_terminal_redirect_retains_bounded_body_and_location_in_trace() -> None:
    url = "https://prom.ua/ua/search?search_term=OE&page=4"
    response = _response(
        301,
        b"",
        url=url,
        location="/ua/search?search_term=OE",
    )
    client = HttpClient(ScrapeConfig(delay=0, delay_jitter=0, max_attempts=1))
    client._session.get = Mock(return_value=response)  # noqa: SLF001
    trace = ScrapeExecutionTrace(item_kind="catalog_discovery", execution_no=1)

    with scrape_execution(trace), pytest.raises(RequestFailed) as captured:
        client.get_html(url)

    request = trace.drain_completed_requests()[0]
    assert captured.value.status_code == 301
    assert captured.value.request_url == url
    assert captured.value.redirect_location == "/ua/search?search_term=OE"
    assert request.response_status_code == 301
    assert request.response_redirect_location == "/ua/search?search_term=OE"
    assert request.raw_body == b""
    assert request.content_sha256 == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (301, ScraperErrorCode.UPSTREAM_3XX, False),
        (408, ScraperErrorCode.TIMEOUT, True),
        (501, ScraperErrorCode.UPSTREAM_5XX, True),
    ],
)
def test_http_status_taxonomy_uses_the_actual_status_class(
    status: int,
    code: ScraperErrorCode,
    retryable: bool,
) -> None:
    client = HttpClient(
        ScrapeConfig(
            delay=0,
            delay_jitter=0,
            max_attempts=1,
        )
    )
    client._session.get = Mock(return_value=_response(status))  # noqa: SLF001

    with pytest.raises(RequestFailed) as captured:
        client.get_html("https://prom.ua/ua/p1-product.html")

    boundary = classify_scraper_exception(captured.value)
    assert (boundary.code, boundary.retryable) == (code, retryable)


def test_any_successful_http_2xx_response_reaches_the_parser_boundary() -> None:
    client = HttpClient(ScrapeConfig(delay=0, delay_jitter=0, max_attempts=1))
    client._session.get = Mock(return_value=_response(206, b"partial"))  # noqa: SLF001

    assert client.get_html("https://prom.ua/ua/p1-product.html") == "partial"


def test_redirects_are_not_followed_without_per_hop_admission() -> None:
    response = _response(302)
    response.headers["Location"] = "http://127.0.0.1/internal"
    client = HttpClient(ScrapeConfig(delay=0, delay_jitter=0, max_attempts=1))
    get = Mock(return_value=response)
    client._session.get = get  # noqa: SLF001

    with pytest.raises(RequestFailed):
        client.get_html("https://prom.ua/ua/p1-product.html")

    assert get.call_args.kwargs["allow_redirects"] is False
    assert get.call_args.kwargs["stream"] is True


def test_response_size_limit_is_terminal_and_evidence_safe() -> None:
    response = _response(200, b"x" * 11)
    response.headers["Content-Length"] = "11"
    client = HttpClient(
        ScrapeConfig(
            delay=0,
            delay_jitter=0,
            max_attempts=3,
            max_response_bytes=10,
        )
    )
    get = Mock(return_value=response)
    client._session.get = get  # noqa: SLF001

    with pytest.raises(RequestFailed) as captured:
        client.get_html("https://prom.ua/ua/p1-product.html")

    boundary = classify_scraper_exception(captured.value)
    assert boundary.code == ScraperErrorCode.UNSAFE_RESPONSE
    assert boundary.retryable is False
    assert get.call_count == 1


def test_retry_after_is_bounded_by_policy() -> None:
    response = _response(429)
    response.headers["Retry-After"] = "999"
    client = HttpClient(
        ScrapeConfig(
            delay=0,
            delay_jitter=0,
            max_attempts=2,
            backoff_max=7,
        )
    )
    client._session.get = Mock(  # noqa: SLF001
        side_effect=[response, _response(200)]
    )
    client._sleep_backoff = Mock()  # type: ignore[method-assign]

    assert client.get_html("https://prom.ua/ua/p1-product.html")
    client._sleep_backoff.assert_called_once_with(7)
