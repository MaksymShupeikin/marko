#!/usr/bin/env python3
"""Run Metis description-cross stages A+B on a pinned CSV replay only."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Any

from metis.pricing import (
    CrossListing,
    CrossStageCBlocked,
    CrossValidationStatus,
    evaluate_real_fixture_checks,
    load_approved_brand_rules,
    load_cross_config,
    require_stage_c_brand_dictionary,
    run_cross_stages_ab,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    PROJECT_ROOT
    / ".artifacts"
    / "metis_cross_coverage_20260719"
    / "METIS_30_OE_OFFERS_WITH_DESCRIPTIONS.csv"
)
DEFAULT_CONFIG = PROJECT_ROOT / "backend" / "config" / "crosses.yaml"
DEFAULT_BRANDS = PROJECT_ROOT / "backend" / "config" / "brands.yaml"
DEFAULT_OUTPUT = PROJECT_ROOT / ".artifacts" / "metis_cross_coverage_20260719"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--brands", type=Path, default=DEFAULT_BRANDS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--expected-listings", type=int, default=146)
    args = parser.parse_args()

    input_path = args.input.resolve()
    config = load_cross_config(args.config)
    rows = _read_rows(input_path)
    listings = tuple(_listing(row) for row in rows)
    result = run_cross_stages_ab(listings, config)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    decisions_path = output_dir / "METIS_CROSSES_AB_DECISIONS.csv"
    rejections_path = output_dir / "METIS_CROSSES_AB_REJECTIONS.csv"
    review_path = output_dir / "METIS_CROSSES_AB_HUMAN_REVIEW.json"
    availability_path = output_dir / "METIS_CROSSES_AB_DATA_AVAILABILITY.csv"
    availability_json_path = output_dir / "METIS_CROSSES_AB_DATA_AVAILABILITY.json"
    summary_path = output_dir / "METIS_CROSSES_AB_SUMMARY.json"
    manifest_path = output_dir / "METIS_CROSSES_AB_REPLAY_MANIFEST.json"

    _write_decisions(decisions_path, result.pair_decisions)
    _write_rejections(rejections_path, result.rejections)
    _write_review_json(review_path, result.pair_decisions)
    _write_availability(availability_path, rows)
    _write_json(availability_json_path, {"rows": _availability_rows(rows)})

    real_fixture_checks = evaluate_real_fixture_checks(result, rows)
    stage_c_status, stage_c_reason = _stage_c_preflight(args.brands, config)
    exact_input_count = len(rows) == args.expected_listings
    description_input_available = result.descriptions_available > 0
    stop_gate_status = (
        "READY_FOR_HUMAN_REVIEW"
        if exact_input_count
        and description_input_available
        and all(real_fixture_checks.values())
        else "BLOCKED_INPUT_DESCRIPTIONS"
    )
    summary = {
        "schema_version": "metis-description-crosses-ab-summary-v1",
        "stage": "METIS_DESCRIPTION_CROSSES_AB",
        "network_requests_performed": 0,
        "input": {
            "path": str(input_path),
            "sha256": _sha256(input_path),
            "expected_listings": args.expected_listings,
            "actual_listings": len(rows),
            "unique_listing_ids": len({row["listing_id"] for row in rows}),
            "unique_urls": len({row["url"] for row in rows if row.get("url")}),
            "nonempty_descriptions": result.descriptions_available,
            "empty_or_short_descriptions": result.descriptions_empty_or_short,
        },
        "stage_a": {
            "candidates_extracted": len(result.candidates),
            "rejections_total": len(result.rejections),
            "rejections_by_reason": dict(result.rejection_counts),
        },
        "stage_b": {
            "source_decisions": len(result.source_decisions),
            "deduplicated_pairs": len(result.pair_decisions),
            "status_counts": {
                status.value: int(result.status_counts.get(status.value, 0))
                for status in CrossValidationStatus
            },
            "confirmed_and_review_for_human": sum(
                item.validation_status
                in {CrossValidationStatus.CONFIRMED, CrossValidationStatus.REVIEW}
                for item in result.pair_decisions
            ),
        },
        "mandatory_real_fixture_checks": real_fixture_checks,
        "stage_c_preflight": {
            "status": stage_c_status,
            "reason": stage_c_reason,
        },
        "stop_gate_ab": {
            "status": stop_gate_status,
            "human_review_required": True,
            "human_review_completed": False,
            "blocking_reasons": [
                reason
                for condition, reason in (
                    (
                        not exact_input_count,
                        "replay_listing_count_does_not_equal_expected_146",
                    ),
                    (
                        not description_input_available,
                        "all_146_saved_listing_descriptions_are_empty",
                    ),
                    (
                        not all(real_fixture_checks.values()),
                        "mandatory_positive_real_description_fixtures_unavailable",
                    ),
                )
                if condition
            ],
        },
        "outputs": {
            "decisions_csv": str(decisions_path),
            "rejections_csv": str(rejections_path),
            "human_review_json": str(review_path),
            "data_availability_csv": str(availability_path),
            "data_availability_json": str(availability_json_path),
        },
    }
    _write_json(summary_path, summary)
    manifest = {
        "schema_version": "metis-description-crosses-ab-replay-manifest-v1",
        "input_sha256": _sha256(input_path),
        "config_sha256": config.source_sha256,
        "implementation_sha256": _sha256(
            PROJECT_ROOT / "backend" / "src" / "metis" / "pricing" / "crosses.py"
        ),
        "network_requests_performed": 0,
        "deterministic_sort": ["our_oem_norm", "listing_id", "source_url"],
        "outputs": {
            path.name: _sha256(path)
            for path in (
                decisions_path,
                rejections_path,
                review_path,
                availability_path,
                availability_json_path,
                summary_path,
            )
        },
    }
    _write_json(manifest_path, manifest)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise SystemExit(f"Replay input does not exist: {path}")
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        required = {
            "listing_id",
            "target_oe",
            "category",
            "seller_name",
            "price_uah",
            "url",
            "description",
        }
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise SystemExit(f"Replay input is missing columns: {sorted(missing)}")
        rows = [dict(row) for row in reader]
    if len({row["listing_id"] for row in rows}) != len(rows):
        raise SystemExit("Replay input contains duplicate listing_id values")
    return rows


def _listing(row: dict[str, str]) -> CrossListing:
    try:
        price = Decimal(row["price_uah"])
    except (InvalidOperation, ValueError) as exc:
        raise SystemExit(
            f"Invalid price_uah for listing {row['listing_id']}: {row['price_uah']!r}"
        ) from exc
    # The replay category is Yuri's target category, not independently observed
    # source-listing evidence. Passing it as source_category would fake B1.
    return CrossListing(
        listing_id=row["listing_id"],
        our_oem_norm=row["target_oe"],
        description=row.get("description") or None,
        source_listing_url=row["url"],
        source_seller=row["seller_name"],
        source_seller_id=row.get("seller_id") or None,
        price=price,
        our_category=row.get("category") or None,
        source_category=None,
    )


def _stage_c_preflight(brands_path: Path, config) -> tuple[str, str | None]:
    rules = load_approved_brand_rules(brands_path)
    try:
        count = require_stage_c_brand_dictionary(rules.tiers, config)
    except CrossStageCBlocked as exc:
        return "BLOCKED", str(exc)
    return "READY", f"approved_non_kemp_tiers={count}"


def _write_decisions(path: Path, decisions) -> None:
    fieldnames = [
        "our_oem_norm",
        "extracted_oem_norm",
        "validation_status",
        "rejection_reason",
        "extraction_method",
        "source_seller",
        "raw_context",
        "source_listing_url",
        "reciprocal_evidence_url",
        "source_count",
        "independent_seller_count",
        "source_seller_ids",
        "source_sellers",
        "automatic_eligible",
    ]
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for item in decisions:
            writer.writerow(
                {
                    "our_oem_norm": item.our_oem_norm,
                    "extracted_oem_norm": item.extracted_oem_norm,
                    "validation_status": item.validation_status.value,
                    "rejection_reason": (
                        item.rejection_reason.value if item.rejection_reason else ""
                    ),
                    "extraction_method": item.extraction_method,
                    "source_seller": item.source_seller,
                    "raw_context": item.raw_context,
                    "source_listing_url": item.source_listing_url,
                    "reciprocal_evidence_url": item.reciprocal_evidence_url or "",
                    "source_count": item.validation_details["source_count"],
                    "independent_seller_count": item.validation_details[
                        "independent_seller_count"
                    ],
                    "source_seller_ids": " | ".join(
                        item.validation_details["source_seller_ids"]
                    ),
                    "source_sellers": " | ".join(
                        item.validation_details["source_sellers"]
                    ),
                    "automatic_eligible": str(item.automatic_eligible).lower(),
                }
            )


def _write_rejections(path: Path, rejections) -> None:
    fieldnames = [
        "listing_id",
        "our_oem_norm",
        "raw_token",
        "normalized_token",
        "reason",
        "raw_context",
    ]
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for item in rejections:
            payload = asdict(item)
            payload["reason"] = item.reason.value
            writer.writerow(payload)


def _write_review_json(path: Path, decisions) -> None:
    review_rows = [
        {
            "our_oem": item.our_oem_norm,
            "extracted": item.extracted_oem_norm,
            "status": item.validation_status.value,
            "raw_context": item.raw_context,
            "url": item.source_listing_url,
            "seller": item.source_seller,
            "extraction_method": item.extraction_method,
            "reciprocal_evidence_url": item.reciprocal_evidence_url,
            "source_count": item.validation_details["source_count"],
            "independent_seller_count": item.validation_details[
                "independent_seller_count"
            ],
            "source_seller_ids": item.validation_details["source_seller_ids"],
            "source_sellers": item.validation_details["source_sellers"],
            "automatic_eligible": item.automatic_eligible,
        }
        for item in decisions
        if item.validation_status
        in {CrossValidationStatus.CONFIRMED, CrossValidationStatus.REVIEW}
    ]
    _write_json(path, {"rows": review_rows, "row_count": len(review_rows)})


def _write_availability(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "listing_id",
        "target_oe",
        "category",
        "seller_name",
        "url",
        "description_available",
        "description_length",
    ]
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in _availability_rows(rows):
            writer.writerow(
                {
                    **row,
                    "description_available": str(row["description_available"]).lower(),
                }
            )


def _availability_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        description = row.get("description") or ""
        result.append(
            {
                "listing_id": row["listing_id"],
                "target_oe": row["target_oe"],
                "category": row["category"],
                "seller_name": row["seller_name"],
                "url": row["url"],
                "description_available": bool(description.strip()),
                "description_length": len(description),
            }
        )
    return result


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
