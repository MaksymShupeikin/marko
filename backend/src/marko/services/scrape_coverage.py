"""How much of what Prom reported a run actually read.

Catalog discovery has carried this since 2026-07-26; the pricing path had no
equivalent, so the cost of its page cap was assumed rather than measured. The
summary lives here because both paths need the same arithmetic and neither is
the other's dependency.
"""

from __future__ import annotations

from decimal import Decimal

from marko.parsers.prom.parser import parse_search
from marko.services.scrape_runtime import LogicalRequestTrace


def coverage_summary(
    *,
    reported_total: int | None,
    retrieved_count: int,
    request_count: int,
    search_page_limit: int,
) -> tuple[int, Decimal | None, str]:
    unfetched_count = max(0, (reported_total or retrieved_count) - retrieved_count)
    # A run may legitimately hold more candidates than the search reported: the
    # part-code group lane adds offers found off an OE page rather than off the
    # result set.  The ratio answers "how much of the reported set did we read",
    # so those additions belong in ``retrieved_count`` but not in this quotient
    # -- and the column is constrained to [0, 1].  Left unclamped it raised a
    # CheckViolationError that failed the whole discovery run, which then
    # retried forever.  Cap the quotient and let the reason carry the fact.
    expanded_beyond_reported = (
        reported_total is not None and retrieved_count > reported_total
    )
    coverage_ratio = (
        min(
            Decimal(retrieved_count) / Decimal(reported_total),
            Decimal(1),
        ).quantize(Decimal("0.000001"))
        if reported_total is not None and reported_total > 0
        else None
    )
    if reported_total is None:
        reason = "PROM_TOTAL_UNKNOWN"
    elif expanded_beyond_reported:
        reason = "RESULT_SET_EXPANDED_BEYOND_REPORTED"
    elif unfetched_count and request_count >= search_page_limit:
        reason = "SEARCH_PAGE_HARD_CAP"
    elif unfetched_count:
        reason = "UPSTREAM_RESULT_GAP"
    else:
        reason = "FULL_REPORTED_RESULT_SET"
    return unfetched_count, coverage_ratio, reason


def reported_total_from_search_pages(
    requests: list[LogicalRequestTrace],
    *,
    language: str = "ua",
) -> tuple[int | None, int]:
    """Read Prom's own result total back out of the retained search pages.

    The number exists only in the page body, so a caller holding the frozen
    adapter output cannot see it. A page that no longer parses is counted as
    fetched but contributes no total: an unreadable page is a parser problem,
    and silently treating it as "Prom reported nothing" would turn that into a
    coverage claim.
    """

    totals: list[int] = []
    fetched = 0
    for request in requests:
        if request.request_kind != "search_page":
            continue
        if request.outcome not in {"success", "replayed"} or request.raw_body is None:
            continue
        fetched += 1
        try:
            page = parse_search(
                request.raw_body.decode(
                    request.response_encoding or "utf-8",
                    errors="replace",
                ),
                language,
            )
        except Exception:  # noqa: BLE001 - a broken page is not a market total
            continue
        if page.total is not None:
            totals.append(page.total)
    return (max(totals) if totals else None), fetched


__all__ = ["coverage_summary", "reported_total_from_search_pages"]
