#!/usr/bin/env python3
"""Mine archived competitor-prices:v11 payloads without network or Redis writes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any, Iterable
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from marko.services.matching import normalize_tokens, token_similarity  # noqa: E402

MIN_CONFIDENCE = 0.7
MIN_SAMPLE = 3
CATEGORY_URL_RE = re.compile(
    r"/search(?:[/?]|$)|/catalog/?(?:[?#]|$)|/category(?:[/?]|$)|[?&](?:q|search)=",
    re.I,
)
OUT_OF_STOCK_RE = re.compile(
    r"немає\s+в\s+наявності|нет\s+в\s+наличии|out\s+of\s+stock|відсутн",
    re.I,
)
SET_RE = re.compile(r"\bкомплект\w*|\bпара\b|\b2\s*шт\b", re.I)
MISSED_USED_RE = re.compile(r"\bшрот\w*|[зс]\s+проб[іе]г\w*", re.I)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _all_offers(report: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in report.get("sources") or []:
        for offer in source.get("offers") or []:
            item = dict(offer)
            item["source_result"] = source.get("source")
            result.append(item)
    return result


def _stats_offers(offers: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    offers = list(offers)
    strong = [offer for offer in offers if float(offer.get("confidence", 1.0)) >= MIN_CONFIDENCE]
    if len(strong) >= MIN_SAMPLE or len(offers) < MIN_SAMPLE:
        return (strong or offers), False
    return offers, True


def _norm_title(value: str | None) -> str:
    return re.sub(r"\W+", "", (value or "").casefold())


def _domain(url: str | None) -> str:
    return (urlsplit(url or "").hostname or "").casefold().removeprefix("www.")


def analyse_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    offers = _all_offers(report)
    stats_offers, fallback = _stats_offers(offers)
    stats_prices = [_decimal(offer["price"]) for offer in stats_offers]
    strong = [offer for offer in offers if float(offer.get("confidence", 1.0)) >= MIN_CONFIDENCE]
    weak = [offer for offer in offers if float(offer.get("confidence", 1.0)) < MIN_CONFIDENCE]
    actual_min = min(stats_prices) if stats_prices else None
    actual_median = Decimal(str(median(stats_prices))) if stats_prices else None
    min_drivers = [offer for offer in stats_offers if _decimal(offer["price"]) == actual_min]
    query_name = (report.get("query") or {}).get("name") or ""
    query_tokens = set(normalize_tokens(query_name))

    source_summaries: list[dict[str, Any]] = []
    for source in report.get("sources") or []:
        source_offers = list(source.get("offers") or [])
        source_stats, source_fallback = _stats_offers(source_offers)
        source_summaries.append(
            {
                "source": source.get("source"),
                "status": source.get("status"),
                "error": source.get("error"),
                "offers": len(source_offers),
                "strong": sum(
                    float(offer.get("confidence", 1.0)) >= MIN_CONFIDENCE
                    for offer in source_offers
                ),
                "stats_fallback_active": source_fallback,
                "stats_min_recomputed": (
                    str(min(_decimal(offer["price"]) for offer in source_stats))
                    if source_stats
                    else None
                ),
            }
        )

    exact_duplicates: list[dict[str, Any]] = []
    duplicate_groups: dict[tuple[str, Decimal], list[dict[str, Any]]] = defaultdict(list)
    for offer in offers:
        duplicate_groups[(_norm_title(offer.get("title")), _decimal(offer["price"]))].append(offer)
    for (title_key, price), group in duplicate_groups.items():
        sources = {offer.get("source_result") for offer in group}
        if title_key and len(sources) > 1:
            exact_duplicates.append(
                {
                    "price": str(price),
                    "sources": sorted(str(source) for source in sources),
                    "titles": sorted({str(offer.get("title")) for offer in group}),
                    "urls": sorted({str(offer.get("url")) for offer in group}),
                }
            )

    google_offers = [offer for offer in offers if offer.get("source_result") == "google"]
    category_urls = [
        offer for offer in google_offers if CATEGORY_URL_RE.search(offer.get("url") or "")
    ]
    out_of_stock = [
        offer for offer in offers if OUT_OF_STOCK_RE.search(offer.get("availability") or "")
    ]
    low_analogs = [
        offer
        for offer in offers
        if offer.get("is_analog")
        and actual_median is not None
        and _decimal(offer["price"]) < actual_median / 2
    ]
    oem_only = []
    for offer in strong:
        similarity = token_similarity(query_tokens, set(normalize_tokens(offer.get("title"))))
        if float(offer.get("confidence", 0)) >= 0.9 and similarity < MIN_CONFIDENCE:
            oem_only.append(
                {
                    "source": offer.get("source_result"),
                    "title": offer.get("title"),
                    "price": offer.get("price"),
                    "token_similarity": similarity,
                }
            )

    return {
        "fixture": str(path.relative_to(ROOT)),
        "observed_at": report.get("observed_at"),
        "query": report.get("query"),
        "reported_stats": report.get("stats"),
        "recomputed": {
            "offers": len(offers),
            "strong": len(strong),
            "weak": len(weak),
            "thin_market": len(strong) < MIN_SAMPLE,
            "stats_fallback_active": fallback,
            "min": str(actual_min) if actual_min is not None else None,
            "median": str(actual_median) if actual_median is not None else None,
            "min_drivers": [
                {
                    "source": offer.get("source_result"),
                    "title": offer.get("title"),
                    "price": offer.get("price"),
                    "confidence": offer.get("confidence"),
                    "is_analog": offer.get("is_analog"),
                    "availability": offer.get("availability"),
                    "condition": offer.get("condition"),
                    "image_url_present": bool(offer.get("image_url")),
                    "url": offer.get("url"),
                }
                for offer in min_drivers
            ],
        },
        "sources": source_summaries,
        "signals": {
            "category_or_search_google_urls": [offer.get("url") for offer in category_urls],
            "out_of_stock_offers": [offer.get("url") for offer in out_of_stock],
            "out_of_stock_min_driver": any(offer in min_drivers for offer in out_of_stock),
            "set_or_pair_titles": [offer.get("title") for offer in offers if SET_RE.search(offer.get("title") or "")],
            "missed_used_marker_titles": [offer.get("title") for offer in offers if MISSED_USED_RE.search(offer.get("title") or "")],
            "low_analog_candidates": [
                {
                    "source": offer.get("source_result"),
                    "title": offer.get("title"),
                    "price": offer.get("price"),
                    "confidence": offer.get("confidence"),
                    "url": offer.get("url"),
                }
                for offer in low_analogs
            ],
            "strong_oem_only_matches": oem_only,
            "exact_cross_source_duplicates": exact_duplicates,
            "exist_offer_urls": [offer.get("url") for offer in offers if _domain(offer.get("url")) == "exist.ua"],
            "google_image_coverage": {
                "with_image": sum(bool(offer.get("image_url")) for offer in google_offers),
                "without_image": sum(not offer.get("image_url") for offer in google_offers),
            },
            "avtopro_photo_blind": sum(
                offer.get("source_result") == "avtopro" and not offer.get("image_url")
                for offer in offers
            ),
        },
    }


def summarise(reports: list[dict[str, Any]]) -> dict[str, Any]:
    source_statuses: Counter[str] = Counter()
    total_offers = 0
    total_strong = 0
    total_weak = 0
    for report in reports:
        total_offers += report["recomputed"]["offers"]
        total_strong += report["recomputed"]["strong"]
        total_weak += report["recomputed"]["weak"]
        for source in report["sources"]:
            source_statuses[f"{source['source']}:{source['status']}"] += 1
    return {
        "reports": len(reports),
        "offers": total_offers,
        "strong_offers": total_strong,
        "weak_offers": total_weak,
        "thin_reports": sum(report["recomputed"]["thin_market"] for report in reports),
        "report_stats_fallbacks": sum(
            report["recomputed"]["stats_fallback_active"] for report in reports
        ),
        "source_stats_fallbacks": sum(
            source["stats_fallback_active"]
            for report in reports
            for source in report["sources"]
        ),
        "exist_skipped": source_statuses["exist:skipped"],
        "exist_offer_urls": sum(
            len(report["signals"]["exist_offer_urls"]) for report in reports
        ),
        "category_or_search_google_urls": sum(
            len(report["signals"]["category_or_search_google_urls"])
            for report in reports
        ),
        "out_of_stock_min_drivers": sum(
            report["signals"]["out_of_stock_min_driver"] for report in reports
        ),
        "low_analog_candidates": sum(
            len(report["signals"]["low_analog_candidates"]) for report in reports
        ),
        "exact_cross_source_duplicate_groups": sum(
            len(report["signals"]["exact_cross_source_duplicates"])
            for report in reports
        ),
        "source_statuses": dict(sorted(source_statuses.items())),
        "warning": "These are lower bounds from post-gate cached payloads, not prevalence estimates.",
    }


def analyse_photo_cache(paths: list[Path]) -> dict[str, Any]:
    snapshot_path = ROOT / "backend" / "tests" / "fixtures" / "audit" / "redis" / "photo-cache.json"
    if not snapshot_path.exists():
        return {"snapshot": None, "entries": 0, "correlated": [], "unmatched_keys": []}
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    by_key = {entry["key"]: entry for entry in snapshot.get("entries") or []}
    correlated: list[dict[str, Any]] = []
    matched_keys: set[str] = set()
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        for offer in _all_offers(report):
            url = offer.get("url") or ""
            key = f"photo-used:v1:{hashlib.sha1(url.encode('utf-8')).hexdigest()}"
            entry = by_key.get(key)
            if entry is None:
                continue
            matched_keys.add(key)
            correlated.append(
                {
                    "fixture": str(path.relative_to(ROOT)),
                    "source": offer.get("source_result"),
                    "title": offer.get("title"),
                    "price": offer.get("price"),
                    "confidence": offer.get("confidence"),
                    "condition_in_report": offer.get("condition"),
                    "image_url_present": bool(offer.get("image_url")),
                    "url": url,
                    "cached_verdict": entry.get("verdict"),
                    "ttl_seconds_at_capture": entry.get("ttl_seconds"),
                }
            )
    return {
        "snapshot": str(snapshot_path.relative_to(ROOT)),
        "captured_at": snapshot.get("captured_at"),
        "entries": len(by_key),
        "verdict_counts": dict(
            Counter(str(entry.get("verdict")) for entry in by_key.values())
        ),
        "correlated": correlated,
        "unmatched_keys": sorted(set(by_key) - matched_keys),
        "warning": "A cached verdict is not ground truth; only labelled false positives/negatives validate photo accuracy.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "fixture_dir",
        nargs="?",
        type=Path,
        default=ROOT / "backend" / "tests" / "fixtures" / "audit" / "redis",
    )
    args = parser.parse_args()
    paths = sorted(args.fixture_dir.glob("report-*.json"))
    reports = [analyse_report(path.resolve()) for path in paths]
    photo_cache = analyse_photo_cache([path.resolve() for path in paths])
    print(
        json.dumps(
            {"summary": summarise(reports), "reports": reports, "photo_cache": photo_cache},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
