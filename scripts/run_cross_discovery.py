#!/usr/bin/env python3
"""Measure discovery-only lift from independently corroborated description crosses.

The output is intentionally not a pricing input.  It keeps exact-OE baseline,
cross-expanded discovery, human validation, tier validation, and recommendation
eligibility as separate states.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Mapping
import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any

from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.gateway import PromGateway
from marko.services.source_access import (
    require_live_prom_marketplace_collection,
    source_access_status,
)
from marko.services.parser_models import Product
from metis.pricing import (
    ConditionState,
    ProductTier,
    classify_condition,
    classify_tier,
    load_approved_brand_rules,
    normalize_brand,
)
from metis.pricing.crosses import normalize_cross_oem


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_DIR = PROJECT_ROOT / ".artifacts" / "metis_cross_coverage_20260719"
DEFAULT_DECISIONS = DEFAULT_ARTIFACT_DIR / "METIS_CROSSES_AB_DECISIONS.csv"
DEFAULT_BASELINE = (
    PROJECT_ROOT / ".artifacts" / "metis_next_steps_20260719" / "METIS_30_OE_COVERAGE.csv"
)
DEFAULT_OFFERS = DEFAULT_ARTIFACT_DIR / "METIS_30_OE_OFFERS_WITH_DESCRIPTIONS.csv"
DEFAULT_OWNED_SELLER_IDS = ("2847093",)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--offers", type=Path, default=DEFAULT_OFFERS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--owned-seller-id", action="append", default=[])
    parser.add_argument("--max-search-pages", type=int, default=3)
    parser.add_argument(
        "--max-queries",
        type=int,
        default=None,
        help="Bound the sorted eligible cross-OE set for a limited smoke run.",
    )
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--delay-jitter", type=float, default=0.25)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()

    if args.max_search_pages <= 0:
        raise SystemExit("--max-search-pages must be positive")
    if args.max_queries is not None and args.max_queries <= 0:
        raise SystemExit("--max-queries must be positive")
    output_dir = args.output_dir.resolve()
    search_dir = output_dir / "cross_search_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    search_dir.mkdir(parents=True, exist_ok=True)

    decisions = _read_csv(args.decisions.resolve())
    baseline_rows = _read_csv(args.baseline.resolve())
    offer_rows = _read_csv(args.offers.resolve())
    owned_seller_ids = set(args.owned_seller_id or DEFAULT_OWNED_SELLER_IDS)
    brand_rules = load_approved_brand_rules(
        PROJECT_ROOT / "backend" / "config" / "brands.yaml"
    )
    links = [
        row
        for row in decisions
        if row.get("automatic_eligible", "").casefold() == "true"
    ]
    links_by_cross: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in links:
        links_by_cross[row["extracted_oem_norm"]].append(row)
    if args.max_queries is not None:
        selected = set(sorted(links_by_cross)[: args.max_queries])
        links_by_cross = defaultdict(
            list,
            {
                cross_oe: rows
                for cross_oe, rows in links_by_cross.items()
                if cross_oe in selected
            },
        )

    config = ScrapeConfig(
        delay=args.delay,
        delay_jitter=args.delay_jitter,
        timeout=args.timeout,
        max_attempts=args.max_attempts,
        max_search_pages=args.max_search_pages,
    )
    gateway = PromGateway(config)
    raw_results: dict[str, list[dict[str, Any]]] = {}
    network_queries = 0
    replayed_queries = 0
    for index, cross_oe in enumerate(sorted(links_by_cross), start=1):
        path = search_dir / f"{index:03d}_{_safe_token(cross_oe)}.json"
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            products = list(payload.get("products") or [])
            replayed_queries += 1
        else:
            # A replay with complete retained query snapshots never crosses
            # the live-source boundary. Any physical request must be
            # explicitly permitted and reference-bound.
            require_live_prom_marketplace_collection()
            access = source_access_status()
            # Prom redirects a non-existent next page back to a shorter result
            # set.  The frozen client rejects redirects by design; non-strict
            # iteration therefore treats that response as the deterministic
            # end of this query while retaining already parsed pages.
            products = [
                product.as_dict()
                for product in gateway.search(cross_oe, strict=False)
            ]
            payload = {
                "schema_version": "metis-cross-discovery-search-v1",
                "captured_at": datetime.now(UTC).isoformat(),
                "query": cross_oe,
                "network_scope": "Prom search pages only",
                "source_access": access.as_dict(),
                "products": products,
            }
            _write_json(path, payload)
            network_queries += 1
        raw_results[cross_oe] = products
        if index % 10 == 0 or index == len(links_by_cross):
            print(
                f"queries={index}/{len(links_by_cross)} fetched={network_queries} "
                f"replayed={replayed_queries}",
                flush=True,
            )

    discovery_rows = _discovery_rows(
        links_by_cross=links_by_cross,
        raw_results=raw_results,
        owned_seller_ids=owned_seller_ids,
        brand_tiers=brand_rules.tiers,
    )
    discovery_path = output_dir / "METIS_CROSS_DISCOVERY_OFFERS.csv"
    _write_csv(discovery_path, discovery_rows, _discovery_fields())
    discovery_json_path = output_dir / "METIS_CROSS_DISCOVERY_OFFERS.json"
    _write_json(discovery_json_path, {"rows": discovery_rows})
    links_json_path = output_dir / "METIS_ELIGIBLE_CROSS_LINKS.json"
    _write_json(links_json_path, {"rows": links})
    target_rows = _target_comparison_rows(
        baseline_rows=baseline_rows,
        offer_rows=offer_rows,
        discovery_rows=discovery_rows,
        owned_seller_ids=owned_seller_ids,
    )
    target_path = output_dir / "METIS_CROSS_COVERAGE_BY_TARGET.csv"
    _write_csv(target_path, target_rows, _target_fields())
    target_json_path = output_dir / "METIS_CROSS_COVERAGE_BY_TARGET.json"
    _write_json(target_json_path, {"rows": target_rows})

    exact_counts = [int(row["exact_independent_sellers"]) for row in target_rows]
    expanded_counts = [int(row["oe_plus_cross_independent_sellers"]) for row in target_rows]
    summary = {
        "schema_version": "metis-cross-discovery-ab-summary-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "mode": "DISCOVERY_ONLY_NOT_PRICING",
            "sample_targets": len(target_rows),
            "one_hop_only": True,
            "minimum_independent_cross_sellers": 2,
            "owned_seller_ids": sorted(owned_seller_ids),
            "independent_kemp_policy": "RETAIN_AS_SEPARATE_SAME_TIER_SIGNAL",
        },
        "inputs": {
            "decisions_sha256": _sha256_file(args.decisions.resolve()),
            "baseline_sha256": _sha256_file(args.baseline.resolve()),
            "offers_sha256": _sha256_file(args.offers.resolve()),
        },
        "cross_links": {
            "eligible_links": len(links),
            "eligible_targets": len({row["our_oem_norm"] for row in links}),
            "unique_cross_queries": len(links_by_cross),
        },
        "search": {
            "network_queries": network_queries,
            "replayed_queries": replayed_queries,
            "candidates_scanned": sum(len(rows) for rows in raw_results.values()),
            "exact_cross_offer_rows": sum(
                row["exact_cross_detected"] == "true" for row in discovery_rows
            ),
            "discovery_candidate_offer_rows": sum(
                row["discovery_candidate"] == "true" for row in discovery_rows
            ),
            "independent_kemp_rows_retained": sum(
                row["independent_kemp"] == "true"
                and row["discovery_candidate"] == "true"
                for row in discovery_rows
            ),
        },
        "comparison": {
            "exact_oe": _coverage_metrics(exact_counts),
            "oe_plus_cross_discovery": _coverage_metrics(expanded_counts),
            "positions_with_added_independent_seller_candidates": sum(
                expanded > exact
                for exact, expanded in zip(exact_counts, expanded_counts, strict=True)
            ),
            "added_independent_seller_candidates_total": (
                sum(expanded_counts) - sum(exact_counts)
            ),
            "match_precision": None,
            "tier_precision": None,
            "positions_with_confident_recommendation": 0,
            "erroneous_upward_recommendations_emitted": 0,
        },
        "stop_gate": {
            "status": "READY_FOR_HUMAN_REVIEW",
            "automatic_pricing_allowed": False,
            "reason": (
                "Coverage discovery is measured, but cross-match and tier precision "
                "remain unlabeled. No recommendation was emitted."
            ),
        },
        "outputs": {
            "discovery_offers_csv": str(discovery_path),
            "discovery_offers_json": str(discovery_json_path),
            "eligible_cross_links_json": str(links_json_path),
            "target_comparison_csv": str(target_path),
            "target_comparison_json": str(target_json_path),
        },
    }
    summary_path = output_dir / "METIS_CROSS_COVERAGE_SUMMARY.json"
    _write_json(summary_path, summary)
    manifest = {
        "schema_version": "metis-cross-discovery-replay-manifest-v1",
        "summary_sha256": _sha256_file(summary_path),
        "target_comparison_sha256": _sha256_file(target_path),
        "discovery_offers_sha256": _sha256_file(discovery_path),
        "discovery_offers_json_sha256": _sha256_file(discovery_json_path),
        "eligible_cross_links_json_sha256": _sha256_file(links_json_path),
        "target_comparison_json_sha256": _sha256_file(target_json_path),
        "search_outputs": {
            path.name: _sha256_file(path) for path in sorted(search_dir.glob("*.json"))
        },
    }
    _write_json(output_dir / "METIS_CROSS_COVERAGE_MANIFEST.json", manifest)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def evaluate_product(
    product: Product,
    *,
    cross_oe: str,
    owned_seller_ids: set[str],
    brand_tiers: Mapping[str, ProductTier] | None = None,
) -> dict[str, Any]:
    exact = cross_oe in {
        normalize_cross_oem(product.sku),
        normalize_cross_oem(product.oe_raw),
    }
    seller_id = str(product.seller_id or "")
    is_owned = bool(seller_id and seller_id in owned_seller_ids)
    condition = classify_condition(
        title=product.name,
        description=product.description,
        explicit_condition=product.condition,
    )
    available = product.is_available is True
    tier = classify_tier(
        brand=product.brand,
        title=product.name or "",
        description=product.description,
        condition=product.condition,
        brand_tiers=brand_tiers,
    )
    reason_codes: list[str] = []
    if not exact:
        reason_codes.append("NOT_EXACT_CROSS_SKU_OR_OE")
    if is_owned:
        reason_codes.append("OWNED_SELLER")
    if not available:
        reason_codes.append("NOT_PROVEN_AVAILABLE")
    if condition.state is ConditionState.USED_OR_REFURBISHED:
        reason_codes.append("USED_OR_REFURBISHED")
    elif condition.state is ConditionState.CONFLICT:
        reason_codes.append("CONDITION_CONFLICT")
    discovery_candidate = not reason_codes
    pricing_block_reasons = [
        "MISSING_CATEGORY_VALIDATION",
        "MISSING_HUMAN_MATCH_LABEL",
        "MISSING_HUMAN_TIER_LABEL",
    ]
    return {
        "exact": exact,
        "owned": is_owned,
        "available": available,
        "condition_state": condition.state.value,
        "discovery_candidate": discovery_candidate,
        "pricing_eligible": False,
        "reason_codes": reason_codes,
        "pricing_block_reasons": pricing_block_reasons,
        "independent_kemp": normalize_brand(product.brand) == "KEMP" and not is_owned,
        "predicted_tier": tier.tier.value,
        "tier_confidence": str(tier.confidence),
        "tier_reasons": list(tier.reasons),
    }


def _discovery_rows(
    *,
    links_by_cross: dict[str, list[dict[str, str]]],
    raw_results: dict[str, list[dict[str, Any]]],
    owned_seller_ids: set[str],
    brand_tiers: Mapping[str, ProductTier],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for cross_oe in sorted(links_by_cross):
        # Search snapshots are already normalized through Product.as_dict().
        # Reapplying from_raw() would look for Apollo keys and silently erase
        # seller/SKU/availability evidence during replay.
        products = [
            Product.from_normalized_snapshot(raw) for raw in raw_results[cross_oe]
        ]
        for link in sorted(
            links_by_cross[cross_oe], key=lambda item: item["our_oem_norm"]
        ):
            for product in products:
                assessment = evaluate_product(
                    product,
                    cross_oe=cross_oe,
                    owned_seller_ids=owned_seller_ids,
                    brand_tiers=brand_tiers,
                )
                rows.append(
                    {
                        "our_oem_norm": link["our_oem_norm"],
                        "cross_oem_norm": cross_oe,
                        "cross_independent_seller_count": link[
                            "independent_seller_count"
                        ],
                        "cross_source_sellers": link["source_sellers"],
                        "candidate_product_id": str(product.id or ""),
                        "seller_id": str(product.seller_id or ""),
                        "seller_name": product.seller_name or "",
                        "brand_raw": product.brand or "",
                        "sku": product.sku or "",
                        "price_uah": product.price or "",
                        "currency": product.currency or "",
                        "url": product.url or "",
                        "title": product.name or "",
                        "exact_cross_detected": str(assessment["exact"]).lower(),
                        "owned_seller": str(assessment["owned"]).lower(),
                        "available": str(assessment["available"]).lower(),
                        "condition_state": assessment["condition_state"],
                        "predicted_tier": assessment["predicted_tier"],
                        "tier_confidence": assessment["tier_confidence"],
                        "tier_reasons": " | ".join(assessment["tier_reasons"]),
                        "independent_kemp": str(
                            assessment["independent_kemp"]
                        ).lower(),
                        "discovery_candidate": str(
                            assessment["discovery_candidate"]
                        ).lower(),
                        "pricing_eligible": str(
                            assessment["pricing_eligible"]
                        ).lower(),
                        "reason_codes": " | ".join(assessment["reason_codes"]),
                        "pricing_block_reasons": " | ".join(
                            assessment["pricing_block_reasons"]
                        ),
                    }
                )
    return rows


def _target_comparison_rows(
    *,
    baseline_rows: list[dict[str, str]],
    offer_rows: list[dict[str, str]],
    discovery_rows: list[dict[str, str]],
    owned_seller_ids: set[str],
) -> list[dict[str, str]]:
    exact_sellers: dict[str, set[str]] = defaultdict(set)
    independent_kemp: dict[str, set[str]] = defaultdict(set)
    for row in offer_rows:
        if row.get("exact_oe_detected", "").casefold() != "true":
            continue
        if row.get("used_marker_detected", "").casefold() == "true":
            continue
        seller_id = row.get("seller_id", "")
        if seller_id in owned_seller_ids:
            continue
        seller_key = seller_id or row.get("seller_name", "").strip().casefold()
        if not seller_key:
            continue
        target = normalize_cross_oem(row["target_oe"])
        exact_sellers[target].add(seller_key)
        if row.get("kemp_detected", "").casefold() == "true":
            independent_kemp[target].add(seller_key)

    cross_sellers: dict[str, set[str]] = defaultdict(set)
    cross_offers: dict[str, set[str]] = defaultdict(set)
    cross_links: dict[str, set[str]] = defaultdict(set)
    for row in discovery_rows:
        if row["discovery_candidate"] != "true":
            continue
        target = row["our_oem_norm"]
        seller_key = row["seller_id"] or row["seller_name"].strip().casefold()
        offer_key = row["candidate_product_id"] or row["url"]
        if seller_key:
            cross_sellers[target].add(seller_key)
        if offer_key:
            cross_offers[target].add(offer_key)
        cross_links[target].add(row["cross_oem_norm"])

    output: list[dict[str, str]] = []
    for row in sorted(baseline_rows, key=lambda item: int(item["sample_no"])):
        target = normalize_cross_oem(row["oe_norm"])
        exact = exact_sellers[target]
        added = cross_sellers[target] - exact
        union = exact | cross_sellers[target]
        output.append(
            {
                "sample_no": row["sample_no"],
                "category": row["category"],
                "oe_raw": row["oe_raw"],
                "oe_norm": target,
                "title": row["title"],
                "exact_independent_sellers": str(len(exact)),
                "independent_kemp_sellers_retained": str(
                    len(independent_kemp[target])
                ),
                "eligible_cross_links": str(len(cross_links[target])),
                "cross_discovery_offers": str(len(cross_offers[target])),
                "new_cross_independent_sellers": str(len(added)),
                "oe_plus_cross_independent_sellers": str(len(union)),
                "cross_match_label_state": (
                    "PENDING_HUMAN_REVIEW" if cross_links[target] else "NO_ELIGIBLE_CROSS"
                ),
                "tier_label_state": "PENDING_HUMAN_REVIEW",
                "recommendation_state": "INSUFFICIENT_VALIDATED_DATA",
            }
        )
    return output


def _coverage_metrics(counts: list[int]) -> dict[str, Any]:
    return {
        "positions_with_results": sum(value > 0 for value in counts),
        "positions_with_at_least_two_independent_sellers": sum(
            value >= 2 for value in counts
        ),
        "total_independent_sellers": sum(counts),
        "mean_independent_sellers": round(statistics.mean(counts), 4),
        "median_independent_sellers": statistics.median(counts),
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as source:
        return [dict(row) for row in csv.DictReader(source)]


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _safe_token(value: str) -> str:
    return "".join(character for character in value if character.isalnum())[:48]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _discovery_fields() -> list[str]:
    return [
        "our_oem_norm",
        "cross_oem_norm",
        "cross_independent_seller_count",
        "cross_source_sellers",
        "candidate_product_id",
        "seller_id",
        "seller_name",
        "brand_raw",
        "sku",
        "price_uah",
        "currency",
        "url",
        "title",
        "exact_cross_detected",
        "owned_seller",
        "available",
        "condition_state",
        "predicted_tier",
        "tier_confidence",
        "tier_reasons",
        "independent_kemp",
        "discovery_candidate",
        "pricing_eligible",
        "reason_codes",
        "pricing_block_reasons",
    ]


def _target_fields() -> list[str]:
    return [
        "sample_no",
        "category",
        "oe_raw",
        "oe_norm",
        "title",
        "exact_independent_sellers",
        "independent_kemp_sellers_retained",
        "eligible_cross_links",
        "cross_discovery_offers",
        "new_cross_independent_sellers",
        "oe_plus_cross_independent_sellers",
        "cross_match_label_state",
        "tier_label_state",
        "recommendation_state",
    ]


if __name__ == "__main__":
    raise SystemExit(main())
