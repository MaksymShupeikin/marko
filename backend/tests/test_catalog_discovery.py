from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from marko.core.config import Settings
from marko.services.catalog_discovery import (
    CatalogDiscoveryError,
    _coverage_summary,
    catalog_discovery_query,
    catalog_product_key,
    usable_search_requests,
)
from marko.services.scrape_runtime import LogicalRequestTrace


def test_catalog_discovery_prefers_normalized_oe_over_sku() -> None:
    assert (
        catalog_discovery_query(
            sku="KEMP-LOCAL-ARTICLE",
            oe="7E5 827 505 A",
        )
        == "7E5827505A"
    )


def test_catalog_discovery_product_key_is_format_stable() -> None:
    formatted = catalog_product_key(
        sku="7E5 827 505 A",
        oe="7E5 827 505 A",
        brand="Volkswagen",
    )
    compact = catalog_product_key(
        sku="7E5827505A",
        oe="7E5827505A",
        brand="VOLKSWAGEN",
    )

    assert formatted == compact


def _trace(
    sequence_no: int,
    *,
    outcome: str = "success",
    status_code: int | None = 200,
    body: bytes | None = b"<html></html>",
    error_category: str | None = None,
) -> LogicalRequestTrace:
    return LogicalRequestTrace(
        sequence_no=sequence_no,
        request_kind="search",
        prepared_url=f"https://prom.ua/ua/search?page={sequence_no}",
        request_key=f"key-{sequence_no}",
        started_at=datetime(2026, 7, 26, tzinfo=UTC),
        started_perf=0.0,
        outcome=outcome,
        response_status_code=status_code,
        raw_body=body,
        error_category=error_category,
    )


def _redirect_trace(sequence_no: int) -> LogicalRequestTrace:
    return _trace(
        sequence_no,
        outcome="terminal_failure",
        status_code=301,
        body=None,
        error_category="upstream_3xx",
    )


def test_trailing_redirect_probe_does_not_invalidate_collected_pages() -> None:
    """8E0121251L reported 67 results but served 66; page 4 answered 301."""

    requests = (_trace(1), _trace(2), _trace(3), _redirect_trace(4))

    usable = usable_search_requests(requests)

    assert [request.sequence_no for request in usable] == [1, 2, 3]


def test_a_run_whose_only_request_redirected_has_no_evidence() -> None:
    with pytest.raises(CatalogDiscoveryError) as error:
        usable_search_requests((_redirect_trace(1),))

    assert error.value.code == "CATALOG_DISCOVERY_HTTP_INCOMPLETE"


@pytest.mark.parametrize("category", ["upstream_4xx", "upstream_5xx", None])
def test_a_non_redirect_failure_still_fails_the_run(category: str | None) -> None:
    requests = (
        _trace(1),
        _trace(
            2,
            outcome="terminal_failure",
            status_code=500,
            body=None,
            error_category=category,
        ),
    )

    with pytest.raises(CatalogDiscoveryError) as error:
        usable_search_requests(requests)

    assert error.value.code == "CATALOG_DISCOVERY_HTTP_INCOMPLETE"


def test_a_successful_request_without_a_body_is_not_usable() -> None:
    with pytest.raises(CatalogDiscoveryError):
        usable_search_requests((_trace(1, body=None),))


def test_identical_traces_are_not_deduplicated_by_equality() -> None:
    """Two pages can carry byte-identical fields; both must still count."""

    requests = (_trace(1), _trace(1))

    assert len(usable_search_requests(requests)) == 2


def test_catalog_discovery_rejects_product_without_identifier() -> None:
    with pytest.raises(CatalogDiscoveryError) as error:
        catalog_discovery_query(sku=" ", oe=None)

    assert error.value.code == "CATALOG_DISCOVERY_IDENTIFIER_REQUIRED"


@pytest.mark.parametrize(
    (
        "reported_total",
        "retrieved_count",
        "request_count",
        "page_limit",
        "expected",
    ),
    [
        (90, 90, 3, 10, (0, Decimal("1.000000"), "FULL_REPORTED_RESULT_SET")),
        (90, 58, 2, 2, (32, Decimal("0.644444"), "SEARCH_PAGE_HARD_CAP")),
        (90, 58, 2, 10, (32, Decimal("0.644444"), "UPSTREAM_RESULT_GAP")),
        (None, 29, 1, 10, (0, None, "PROM_TOTAL_UNKNOWN")),
        (0, 0, 1, 10, (0, None, "FULL_REPORTED_RESULT_SET")),
    ],
)
def test_catalog_discovery_coverage_summary(
    reported_total: int | None,
    retrieved_count: int,
    request_count: int,
    page_limit: int,
    expected: tuple[int, Decimal | None, str],
) -> None:
    assert (
        _coverage_summary(
            reported_total=reported_total,
            retrieved_count=retrieved_count,
            request_count=request_count,
            search_page_limit=page_limit,
        )
        == expected
    )


@pytest.mark.parametrize("value", [0, 51])
def test_catalog_discovery_page_hard_cap_is_bounded(value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(catalog_discovery_max_search_pages=value)


def test_catalog_discovery_page_hard_cap_defaults_to_ten() -> None:
    assert Settings().catalog_discovery_max_search_pages == 10
