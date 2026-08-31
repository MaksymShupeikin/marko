#!/usr/bin/env python3
"""Paid live comparison for the availability sandbox; run only after approval.

The probe performs two uncached reports per query (gate off/on). It replaces
both Redis caches with no-op clients, so neither shared v11 reports nor photo
verdicts are read or written; the database is not used. API keys are never
printed, and external-call counters have absolute ceilings.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from marko.core.config import get_settings
from marko.services import competitor_prices as cp


_FLAG = "COMPETITOR_AVAILABILITY_GATE_ENABLED"


def _bounded_budget(env_name: str, default: int) -> int:
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    return min(default, max(0, int(raw)))


_BUDGET = {
    "full_reports": 4,
    "serper_calls": _bounded_budget("AVAILABILITY_PROBE_SERPER_CAP", 30),
    "llm_calls": _bounded_budget("AVAILABILITY_PROBE_LLM_CAP", 60),
    "prom_pages": 100,
    "google_pages": 100,
    "avtopro_reports": 4,
}
_QUERIES = (
    cp.PartSearchQuery(
        listing_id="availability-probe:5202CY",
        oem_numbers=("5202CY",),
        brand="KEMP",
        name="Амортизатор передній Citroen C-4 Peugeot 307 02- газ L",
        source_url="https://kemp-cs2847093.prom.ua/p1153741470-amortizator-perednij-citroen.html",
    ),
    cp.PartSearchQuery(
        listing_id="availability-probe:211217",
        oem_numbers=("211217",),
        brand="Solgy",
        name="Амортизатор Solgy 211217",
        source_url="",
        manual=True,
    ),
)


class _NoopCache:
    async def get(self, _key: str) -> None:
        return None

    async def set(
        self, _key: str, _payload: dict[str, Any], _ttl_seconds: int
    ) -> None:
        return None


class _NoopPhotoCache:
    async def get(self, _key: str) -> None:
        return None

    async def set(self, _key: str, _value: str, *, ex: int) -> None:
        return None


def _set_gate(enabled: bool) -> None:
    os.environ[_FLAG] = "true" if enabled else "false"
    get_settings.cache_clear()


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "stats": payload.get("stats"),
        "sources": [
            {
                "source": source.get("source"),
                "status": source.get("status"),
                "offers": [
                    {
                        "title": offer.get("title"),
                        "price": offer.get("price"),
                        "currency": offer.get("currency"),
                        "availability": offer.get("availability"),
                        "confidence": offer.get("confidence"),
                        "url": offer.get("url"),
                    }
                    for offer in source.get("offers") or []
                ],
            }
            for source in payload.get("sources") or []
        ],
    }


def _availability_assertions(payload: dict[str, Any]) -> dict[str, Any]:
    offers = [
        offer
        for source in payload.get("sources") or []
        for offer in source.get("offers") or []
    ]
    strong_indexes = {
        index
        for index, offer in enumerate(offers)
        if float(offer.get("confidence") or 0) >= cp._MIN_STATS_CONFIDENCE
    }
    if len(strong_indexes) >= cp._MIN_STATS_SAMPLE:
        stats_indexes = strong_indexes
    elif len(offers) < cp._MIN_STATS_SAMPLE and strong_indexes:
        stats_indexes = strong_indexes
    else:
        # Exact current _stats_prices fallback, including the known C2 case.
        stats_indexes = set(range(len(offers)))

    unavailable_indexes = {
        index
        for index, offer in enumerate(offers)
        if cp.offer_gates.stock_of(offer.get("availability")) == "out_of_stock"
    }
    unavailable_in_stats = unavailable_indexes & stats_indexes
    all_demoted = all(
        float(offers[index].get("confidence") or 0)
        <= cp._UNVERIFIED_CONFIDENCE
        for index in unavailable_indexes
    )
    return {
        "offers_total": len(offers),
        "strong_offers": len(strong_indexes),
        "out_of_stock_detected": len(unavailable_indexes),
        "out_of_stock_urls": [
            offers[index].get("url") for index in sorted(unavailable_indexes)
        ],
        "out_of_stock_in_stats_urls": [
            offers[index].get("url") for index in sorted(unavailable_in_stats)
        ],
        "all_out_of_stock_demoted": all_demoted,
        "thin_market_fallback_active": (
            len(offers) >= cp._MIN_STATS_SAMPLE
            and len(strong_indexes) < cp._MIN_STATS_SAMPLE
        ),
        "passes": bool(unavailable_indexes)
        and all_demoted
        and not unavailable_in_stats,
    }


async def _report(query: cp.PartSearchQuery, *, enabled: bool) -> dict[str, Any]:
    _set_gate(enabled)
    return await cp.competitor_prices_for_query(query, refresh=True)


async def _safe_report(
    query: cp.PartSearchQuery, *, enabled: bool
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    try:
        return await _report(query, enabled=enabled), None
    except Exception as exc:
        return None, {
            "type": type(exc).__name__,
            "message": str(exc),
        }


async def main() -> None:
    if len(_QUERIES) > 2:
        raise RuntimeError("availability probe is hard-capped at two queries")

    initial = get_settings()
    configured = {
        "serper": bool(initial.serper_api_key),
        "llm": bool(initial.openai_api_key),
    }
    missing = [name for name, present in configured.items() if not present]
    if missing:
        raise RuntimeError(
            "live probe requires configured "
            + ", ".join(missing)
            + "; no external requests were made"
        )
    original_cache = cp._cache
    original_photo_cache = cp.photo_check._client
    original_flag = os.environ.get(_FLAG)
    original_ask = cp.llm_filter._ask_openai
    original_serp = cp.GooglePriceSource._serp
    original_google_page = cp.GooglePriceSource._page_price
    original_prom_page = cp.PromPriceSource._page_products
    original_avtopro_search = cp.AvtoproPriceSource.search
    usage = {name: 0 for name in _BUDGET}

    def consume(name: str) -> None:
        if usage[name] >= _BUDGET[name]:
            raise RuntimeError(f"live probe exhausted {name} budget")
        usage[name] += 1

    async def capped_ask(*args, **kwargs):
        consume("llm_calls")
        return await original_ask(*args, **kwargs)

    async def capped_serp(source, client, api_key, term):
        consume("serper_calls")
        return await original_serp(source, client, api_key, term)

    async def capped_google_page(source, client, url):
        consume("google_pages")
        return await original_google_page(source, client, url)

    async def capped_prom_page(source, client, term, number):
        consume("prom_pages")
        return await original_prom_page(source, client, term, number)

    async def capped_avtopro_search(source, query):
        consume("avtopro_reports")
        return await original_avtopro_search(source, query)

    cp._cache = _NoopCache()
    cp.photo_check._client = _NoopPhotoCache()
    cp.llm_filter._ask_openai = capped_ask
    cp.GooglePriceSource._serp = capped_serp
    cp.GooglePriceSource._page_price = capped_google_page
    cp.PromPriceSource._page_products = capped_prom_page
    cp.AvtoproPriceSource.search = capped_avtopro_search
    comparisons: list[dict[str, Any]] = []
    run_errors: list[dict[str, Any]] = []
    try:
        for query in _QUERIES:
            consume("full_reports")
            gate_off, gate_off_error = await _safe_report(query, enabled=False)
            if gate_off_error is not None:
                error = {
                    "query": query.listing_id,
                    "mode": "gate_off",
                    **gate_off_error,
                }
                run_errors.append(error)
                comparisons.append(
                    {
                        "query": query.as_json(),
                        "gate_off_error": gate_off_error,
                    }
                )
                break

            consume("full_reports")
            gate_on, gate_on_error = await _safe_report(query, enabled=True)
            if gate_on_error is not None:
                error = {
                    "query": query.listing_id,
                    "mode": "gate_on",
                    **gate_on_error,
                }
                run_errors.append(error)
                comparisons.append(
                    {
                        "query": query.as_json(),
                        "gate_off": _summary(gate_off),
                        "gate_on_error": gate_on_error,
                    }
                )
                break

            assertions = _availability_assertions(gate_on)
            comparisons.append(
                {
                    "query": query.as_json(),
                    "gate_off": _summary(gate_off),
                    "gate_on": _summary(gate_on),
                    "gate_on_availability_assertions": assertions,
                    "recommendation_changed": (
                        (gate_off.get("stats") or {}).get("recommended_price")
                        != (gate_on.get("stats") or {}).get("recommended_price")
                    ),
                }
            )
    finally:
        cp._cache = original_cache
        cp.photo_check._client = original_photo_cache
        cp.llm_filter._ask_openai = original_ask
        cp.GooglePriceSource._serp = original_serp
        cp.GooglePriceSource._page_price = original_google_page
        cp.PromPriceSource._page_products = original_prom_page
        cp.AvtoproPriceSource.search = original_avtopro_search
        if original_flag is None:
            os.environ.pop(_FLAG, None)
        else:
            os.environ[_FLAG] = original_flag
        get_settings.cache_clear()

    print(
        json.dumps(
            {
                "scope": "two live reports per query; gate off versus gate on",
                "warning": (
                    "Runs are independent; SERP and LLM drift can create differences "
                    "unrelated to the availability flag. Compare the marked offers, "
                    "not only the final recommendation."
                ),
                "configured": configured,
                "cache": "report and photo caches are no-op; no Redis reads or writes",
                "budget": _BUDGET,
                "usage": usage,
                "run_errors": run_errors,
                "comparisons": comparisons,
                "acceptance": {
                    "positive_cases": sum(
                        int(
                            comparison["gate_on_availability_assertions"][
                                "out_of_stock_detected"
                            ]
                            > 0
                        )
                        for comparison in comparisons
                        if "gate_on_availability_assertions" in comparison
                    ),
                    "passes": not run_errors
                    and bool(comparisons)
                    and any(
                        comparison["gate_on_availability_assertions"][
                            "out_of_stock_detected"
                        ]
                        > 0
                        for comparison in comparisons
                        if "gate_on_availability_assertions" in comparison
                    )
                    and all(
                        comparison["gate_on_availability_assertions"]["passes"]
                        for comparison in comparisons
                        if "gate_on_availability_assertions" in comparison
                        if comparison["gate_on_availability_assertions"][
                            "out_of_stock_detected"
                        ]
                        > 0
                    ),
                    "rule": (
                        "At least one real out-of-stock offer must be observed; every "
                        "observed one must stay visible, be demoted and remain outside "
                        "the exact current statistics selection."
                    ),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
