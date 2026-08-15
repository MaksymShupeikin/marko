"""Prom's own result total, read back out of the retained search pages.

The number lives only in the page body. A caller holding the frozen adapter
output cannot see it, which is why the pricing path had no coverage figure at
all and could not tell a thin market from a page cap.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json

import pytest

from marko.services.scrape_coverage import (
    coverage_summary,
    reported_total_from_search_pages,
)
from marko.services.scrape_runtime import LogicalRequestTrace

from factories import raw_product


def _search_body(total: int | None) -> bytes:
    count = 0 if total is None else min(total, 2)
    page: dict = {
        "products": [
            {"product": raw_product(id=index + 1)} for index in range(count)
        ],
        "total": 0 if total is None else total,
    }
    state = {
        "_FAST_CACHE": {
            "SearchListingQuery({})": {"result": {"listing": {"page": page}}}
        }
    }
    return (
        "<html><script>window.ApolloCacheState = "
        f"{json.dumps(state)};</script></html>"
    ).encode()


def _request(
    sequence_no: int,
    *,
    kind: str = "search_page",
    outcome: str = "success",
    body: bytes | None = None,
) -> LogicalRequestTrace:
    payload = _search_body(None) if body is None else body
    return LogicalRequestTrace(
        sequence_no=sequence_no,
        request_kind=kind,
        prepared_url=f"https://prom.ua/ua/search?search_term=OE&page={sequence_no}",
        request_key=f"key-{sequence_no}",
        started_at=datetime(2026, 8, 7, tzinfo=UTC),
        started_perf=0.0,
        outcome=outcome,
        response_status_code=200,
        response_encoding="utf-8",
        raw_body=payload,
        content_sha256=hashlib.sha256(payload).hexdigest(),
    )


def test_the_largest_reported_total_wins_across_pages() -> None:
    total, fetched = reported_total_from_search_pages(
        [
            _request(1, body=_search_body(90)),
            _request(2, body=_search_body(88)),
        ]
    )

    assert (total, fetched) == (90, 2)


def test_product_cards_are_not_search_pages() -> None:
    """With the detail budget unbounded these outnumber the pages many times."""

    total, fetched = reported_total_from_search_pages(
        [
            _request(1, body=_search_body(30)),
            _request(2, kind="product_page", body=b"<html></html>"),
            _request(3, kind="product_page", body=b"<html></html>"),
        ]
    )

    assert (total, fetched) == (30, 1)


def test_a_failed_page_is_neither_fetched_nor_a_total() -> None:
    total, fetched = reported_total_from_search_pages(
        [_request(1, outcome="terminal_failure", body=_search_body(90))]
    )

    assert (total, fetched) == (None, 0)


def test_an_unreadable_page_counts_as_fetched_but_reports_no_total() -> None:
    """A parser problem must not be recorded as "Prom reported nothing"."""

    total, fetched = reported_total_from_search_pages(
        [_request(1, body=b"<html>not apollo at all</html>")]
    )

    assert (total, fetched) == (None, 1)


@pytest.mark.parametrize(
    ("reported", "retrieved", "requests", "limit", "expected"),
    (
        (90, 58, 2, 2, "SEARCH_PAGE_HARD_CAP"),
        (90, 58, 1, 10, "UPSTREAM_RESULT_GAP"),
        (58, 58, 1, 10, "FULL_REPORTED_RESULT_SET"),
        (None, 58, 1, 10, "PROM_TOTAL_UNKNOWN"),
    ),
)
def test_the_cap_is_named_only_when_it_actually_bound(
    reported: int | None,
    retrieved: int,
    requests: int,
    limit: int,
    expected: str,
) -> None:
    _unfetched, _ratio, reason = coverage_summary(
        reported_total=reported,
        retrieved_count=retrieved,
        request_count=requests,
        search_page_limit=limit,
    )

    assert reason == expected


def test_a_code_group_expansion_does_not_push_the_ratio_out_of_range() -> None:
    """The part-code lane adds offers found off an OE page, not off the results.

    Measured live on 2026-08-14: a search reported 195 and the run held 266
    candidates, so the raw quotient was 1.364103.  ``coverage_ratio`` is
    constrained to [0, 1], so the discovery run failed to persist with a
    CheckViolationError and Celery retried it forever.
    """

    unfetched, ratio, reason = coverage_summary(
        reported_total=195,
        retrieved_count=266,
        request_count=7,
        search_page_limit=10,
    )

    assert ratio is not None
    assert Decimal(0) <= ratio <= Decimal(1)
    assert unfetched == 0
    assert reason == "RESULT_SET_EXPANDED_BEYOND_REPORTED"
