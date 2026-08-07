#!/usr/bin/env python3
"""Collect a bounded, non-monetary Prom pool for locked-review expansion.

This utility is an evidence collector, not a matcher.  It searches the explicit
query supplied for each frozen seed, removes owned sellers, retains every
non-monetary listing result and exports at most one deterministic candidate per
seed in the CSV shape accepted by ``prepare-locked-review-set``.

No identity label, semantic-gate output, price or pricing decision is written.
The source-access boundary is checked before the first physical request.
"""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from marko.parsers.prom import PromGateway, ScrapeConfig
from marko.services.parser_models import Product
from marko.services.source_access import (
    require_live_prom_marketplace_collection,
    source_access_status,
)


SCHEMA_VERSION = "metis-locked-review-live-expansion-v1"
DEFAULT_OWNED_SELLERS = ("2847093", "3325174", "3912822", "4015921")
MAX_QUERY_LIMIT = 20

SEED_COLUMNS = (
    "our_oe",
    "our_title",
    "our_sku",
    "our_brand",
    "our_category",
    "our_mpn",
    "our_part_numbers",
    "our_applicability",
    "our_characteristics",
    "our_product_url",
    "our_image_urls",
    "our_description",
    "query",
)

REVIEW_COLUMNS = (
    "rank",
    "our_oe",
    "our_title",
    "our_sku",
    "our_brand",
    "our_category",
    "our_mpn",
    "our_part_numbers",
    "our_applicability",
    "our_characteristics",
    "our_product_url",
    "our_image_urls",
    "our_description",
    "offer_id",
    "offer_title",
    "offer_sku",
    "offer_brand",
    "offer_url",
    "offer_seller_name",
    "offer_image_url",
    "offer_category",
    "offer_category_path",
    "offer_measure_unit",
    "offer_availability",
    "offer_condition",
    "offer_package_quantity",
    "offer_oe_raw",
    "offer_fitment",
    "offer_engine",
    "offer_year_from",
    "offer_year_to",
    "offer_body_variant",
    "offer_side",
    "offer_position",
    "offer_description",
    "offer_characteristics",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--owned-seller-id", action="append", default=[])
    parser.add_argument("--max-queries", type=int, default=MAX_QUERY_LIMIT)
    parser.add_argument("--max-search-pages", type=int, default=1)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--delay-jitter", type=float, default=0.15)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_seeds(path: Path, *, max_queries: int) -> list[dict[str, str]]:
    if max_queries <= 0 or max_queries > MAX_QUERY_LIMIT:
        raise ValueError(f"--max-queries must be between 1 and {MAX_QUERY_LIMIT}")
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        missing = sorted(set(SEED_COLUMNS) - set(reader.fieldnames or ()))
        if missing:
            raise ValueError(f"Seed CSV is missing columns: {', '.join(missing)}")
        rows = [
            {column: str(row.get(column) or "").strip() for column in SEED_COLUMNS}
            for row in reader
        ]
    if not rows:
        raise ValueError("Seed CSV is empty")
    if len(rows) > max_queries:
        raise ValueError(
            f"Seed CSV has {len(rows)} rows, above --max-queries={max_queries}"
        )
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not row["our_oe"] or not row["our_title"] or not row["query"]:
            raise ValueError(
                f"Seed row {index} requires our_oe, our_title and query"
            )
        canonical = "".join(char for char in row["our_oe"].upper() if char.isalnum())
        if canonical in seen:
            raise ValueError(f"Duplicate seed OE in input: {row['our_oe']}")
        seen.add(canonical)
    return rows


def _non_monetary_product(product: Product) -> dict[str, Any]:
    """Return review evidence while structurally excluding every price field."""

    return {
        "id": product.id,
        "name": product.name,
        "sku": product.sku,
        "mpn": product.mpn,
        "url": product.url,
        "seller_id": product.seller_id,
        "seller_name": product.seller_name,
        "seller_slug": product.seller_slug,
        "brand": product.brand,
        "image": product.image,
        "category_id": product.category_id,
        "category_ids": product.category_ids,
        "category": product.category,
        "presence": product.presence,
        "is_available": product.is_available,
        "measure_unit": product.measure_unit,
        "oe_raw": product.oe_raw,
        "fitment": product.fitment,
        "vehicle_generation": product.vehicle_generation,
        "year_from": product.year_from,
        "year_to": product.year_to,
        "engine": product.engine,
        "body_variant": product.body_variant,
        "side": product.side,
        "position": product.position,
        "condition": product.condition,
        "package_quantity": product.package_quantity,
        "characteristics": product.characteristics,
        "description": product.description,
        "detail_evidence": product.detail_evidence,
    }


def _review_row(
    seed: dict[str, str],
    product: Product,
    *,
    rank: int,
) -> dict[str, Any]:
    return {
        "rank": f"LIVE-{rank:03d}",
        **{column: seed[column] for column in SEED_COLUMNS if column != "query"},
        "offer_id": product.id or "",
        "offer_title": product.name or "",
        "offer_sku": product.sku or "",
        "offer_brand": product.brand or "",
        "offer_url": product.url or "",
        "offer_seller_name": product.seller_name or "",
        "offer_image_url": product.image or "",
        "offer_category": product.category or "",
        "offer_category_path": json.dumps(
            product.category_ids or [], ensure_ascii=False, separators=(",", ":")
        ),
        "offer_measure_unit": product.measure_unit or "",
        "offer_availability": (
            "true"
            if product.is_available is True
            else "false"
            if product.is_available is False
            else ""
        ),
        "offer_condition": product.condition or "",
        "offer_package_quantity": product.package_quantity or "",
        "offer_oe_raw": product.oe_raw or "",
        "offer_fitment": product.fitment or "",
        "offer_engine": product.engine or "",
        "offer_year_from": product.year_from or "",
        "offer_year_to": product.year_to or "",
        "offer_body_variant": product.body_variant or "",
        "offer_side": product.side or "",
        "offer_position": product.position or "",
        "offer_description": product.description or "",
        "offer_characteristics": json.dumps(
            product.characteristics or [],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = _parser().parse_args()
    seed_csv = args.seed_csv.resolve()
    output_dir = args.output_dir.resolve()
    capture_path = output_dir / "live_capture.json"
    review_path = output_dir / "live_review_source.csv"
    if not seed_csv.is_file():
        raise SystemExit(f"Seed CSV does not exist: {seed_csv}")
    if not args.overwrite and (capture_path.exists() or review_path.exists()):
        raise SystemExit("Output already exists; use --overwrite explicitly")
    seeds = _read_seeds(seed_csv, max_queries=args.max_queries)
    require_live_prom_marketplace_collection()
    access = source_access_status()
    owned = {
        str(value).strip()
        for value in (args.owned_seller_id or DEFAULT_OWNED_SELLERS)
        if str(value).strip()
    }
    gateway = PromGateway(
        ScrapeConfig(
            max_search_pages=args.max_search_pages,
            delay=args.delay,
            delay_jitter=args.delay_jitter,
            timeout=args.timeout,
            max_attempts=args.max_attempts,
        )
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    review_rows: list[dict[str, Any]] = []
    captures: list[dict[str, Any]] = []
    for index, seed in enumerate(seeds, start=1):
        record: dict[str, Any] = {
            "seed_oe": seed["our_oe"],
            "seed_title": seed["our_title"],
            "query": seed["query"],
            "parser_outcome": "SUCCESS",
            "products": [],
            "external_products": 0,
            "selected_offer_id": None,
        }
        try:
            products = list(gateway.search(seed["query"], strict=True))
        except Exception as exc:  # parser/network taxonomy is retained verbatim
            record["parser_outcome"] = type(exc).__name__
            record["error"] = str(exc)[:1000]
            captures.append(record)
            continue
        record["products"] = [_non_monetary_product(item) for item in products]
        external = [
            item
            for item in products
            if str(item.seller_id or "").strip() not in owned
            and item.id is not None
            and item.url
        ]
        record["external_products"] = len(external)
        if external:
            selected = external[0]
            record["selected_offer_id"] = selected.id
            review_rows.append(_review_row(seed, selected, rank=index))
        captures.append(record)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": datetime.now(UTC).isoformat(),
        "network_retrieval_performed": True,
        "source_access": access.as_dict(),
        "bounds": {
            "queries": len(seeds),
            "max_queries": args.max_queries,
            "max_search_pages": args.max_search_pages,
            "timeout_seconds": args.timeout,
            "max_attempts": args.max_attempts,
        },
        "seed_csv": {"path": str(seed_csv), "sha256": _sha256(seed_csv)},
        "owned_seller_ids": sorted(owned),
        "contains_prices": False,
        "contains_model_predictions": False,
        "contains_identity_labels": False,
        "selected_review_rows": len(review_rows),
        "queries": captures,
    }
    _write_json(capture_path, payload)
    _write_csv(review_path, review_rows)
    print(
        f"queries={len(seeds)} selected_review_rows={len(review_rows)} "
        f"capture={capture_path} review_source={review_path}"
    )
    return 0 if review_rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
