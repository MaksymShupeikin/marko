"""Reproduce the name-only PartSouq eligibility measurement without network."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys


REPOSITORY = Path(__file__).resolve().parents[2]
BACKEND = REPOSITORY / "backend"
sys.path.insert(0, str(BACKEND / "src"))

from marko.services.catalog_identity_reparse import (  # noqa: E402
    build_source_index,
    plan_identity,
)
from marko.services.xlsx_catalog import parse_catalog_xlsx  # noqa: E402
from metis.pricing.identity_graph import load_identity_graph_config  # noqa: E402
from metis.pricing.kemp_reference import load_article_brand_kinds  # noqa: E402
from metis.pricing.kemp_site import load_kemp_site_tokens  # noqa: E402
from partsouq_spike import FormalPartQuery, build_query_plan  # noqa: E402


def main() -> int:
    parsed = parse_catalog_xlsx(
        (BACKEND / "data/kemp_prom_catalog.xlsx").read_bytes(),
        sheet_name="Export Products Sheet",
    )
    config = load_identity_graph_config(BACKEND / "config/identity_graph.yaml")
    kinds = load_article_brand_kinds(BACKEND / "config/article_brand_kinds.yaml")
    tokens = load_kemp_site_tokens(BACKEND / "config/kemp_site_tokens.yaml")
    index = build_source_index(
        config=config,
        kinds=kinds,
        tokens=tokens,
        reference_paths=[
            BACKEND / "data/kemp_reference_map.csv",
            BACKEND / "data/kemp_oe_map.csv",
        ],
        site_path=BACKEND / "data/kemp_site_numbers.csv",
    )

    unresolved = []
    for row in parsed.rows:
        identity = plan_identity(
            own_code=row.oe_norm or "",
            code_raw=row.oe_raw or "",
            part_numbers_raw=row.part_numbers_raw,
            current_oe_norm=row.oe_norm or "",
            index=index,
            config=config,
            tokens=tokens,
        )
        if identity.identity_status == "UNRESOLVED":
            unresolved.append(row)

    query_plans = Counter()
    for row in unresolved:
        formal = FormalPartQuery(
            standardized_name=row.name,
            part_type=row.category,
            # The Prom product code is deliberately not promoted to an OE/MPN.
            known_identifiers=(),
            vehicle_makes=tuple(row.applicability_brands),
            vehicle_models=tuple(row.applicability_models),
        )
        query_plans[build_query_plan(formal).kind.value] += 1

    report = {
        "source_rows": parsed.total_rows,
        "parse_issues": len(parsed.issues),
        "unresolved_after_deterministic_reparse": len(unresolved),
        "unresolved_with_product_brand": sum(bool(row.brand) for row in unresolved),
        "unresolved_with_vehicle_make": sum(
            bool(row.applicability_brands) for row in unresolved
        ),
        "unresolved_with_vehicle_model": sum(
            bool(row.applicability_models) for row in unresolved
        ),
        "unresolved_with_description": sum(
            bool(row.description) for row in unresolved
        ),
        "partsouq_query_plan_counts": dict(sorted(query_plans.items())),
        "network_requests": 0,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
