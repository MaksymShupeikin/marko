#!/usr/bin/env python3
"""Measure offline planning coverage over every current no-OE KEMP row."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from semantic_discovery import (
    CONTRACT_VERSION,
    build_query_plan,
    build_seed_profile,
    load_no_oe_catalog_seeds,
    sha256_file,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MASTER = REPO_ROOT.parent / "OE_каталог_2026-08-09.xlsx"
DEFAULT_SOURCE = REPO_ROOT / "backend/data/kemp_prom_catalog.xlsx"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master-workbook", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--source-workbook", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    return parser


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def main() -> int:
    args = _parser().parse_args()
    started = datetime.now(UTC)
    seeds, counts = load_no_oe_catalog_seeds(
        args.master_workbook,
        args.source_workbook,
        limit=100_000,
    )
    metrics: Counter[str] = Counter()
    families: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    query_sources: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    unknown_part_family_rows: list[dict[str, str]] = []

    for seed in seeds:
        categories[seed.category or "<UNKNOWN>"] += 1
        reasons[seed.no_oe_reason or "<UNKNOWN>"] += 1
        metrics["with_description"] += bool(seed.description)
        metrics["with_characteristics"] += bool(seed.characteristics)
        metrics["with_images"] += bool(seed.image_urls)
        metrics["with_mpn"] += bool(seed.mpn)
        metrics["with_unconfirmed_candidates"] += bool(seed.unconfirmed_candidates)
        try:
            profile = build_seed_profile(seed)
            family_values = profile["features"]["part_family"]["values"]
            if family_values:
                metrics["typed_part_family"] += 1
                for family in family_values:
                    families[str(family)] += 1
            else:
                metrics["unknown_part_family"] += 1
                unknown_part_family_rows.append(
                    {
                        "row_id": seed.row_id,
                        "title": seed.title,
                        "category": seed.category,
                    }
                )
            plan = build_query_plan(seed, profile)
            metrics["safe_query_plan"] += 1
            metrics["planned_query_variants"] += len(plan["queries"])
            for query in plan["queries"]:
                query_sources[str(query["source"])] += 1
        except Exception as exc:
            errors.append(
                {
                    "row_id": seed.row_id,
                    "title": seed.title,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

    total = len(seeds)
    result: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "audit_kind": "OFFLINE_QUERY_PLANNING_ONLY",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "inputs": {
            "master_workbook": {
                "path": str(args.master_workbook.resolve()),
                "sha256": sha256_file(args.master_workbook),
            },
            "source_workbook": {
                "path": str(args.source_workbook.resolve()),
                "sha256": sha256_file(args.source_workbook),
            },
        },
        "catalog_counts": counts,
        "total_no_oe_rows": total,
        "metrics": dict(sorted(metrics.items())),
        "rates": {
            "source_join": _rate(counts["joined_selected_rows"], total),
            "safe_query_plan": _rate(metrics["safe_query_plan"], total),
            "typed_part_family": _rate(metrics["typed_part_family"], total),
            "with_description": _rate(metrics["with_description"], total),
            "with_characteristics": _rate(metrics["with_characteristics"], total),
            "with_images": _rate(metrics["with_images"], total),
            "with_unconfirmed_candidates": _rate(
                metrics["with_unconfirmed_candidates"], total
            ),
        },
        "top_part_families": families.most_common(30),
        "top_categories": categories.most_common(30),
        "no_oe_reasons": reasons.most_common(),
        "query_sources": dict(sorted(query_sources.items())),
        "planning_errors": errors,
        "unknown_part_family_rows": unknown_part_family_rows,
        "live_requests": 0,
        "luna_calls": 0,
        "oe_assertions_created": 0,
        "prices_written": 0,
        "database_writes": 0,
        "automatic_pricing_admissions": 0,
        "representative_retrieval_precision_measured": False,
        "representative_retrieval_recall_measured": False,
    }
    rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output is not None:
        target = args.output.resolve()
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite existing audit: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
        print(target)
    else:
        print(rendered, end="")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
