"""CLI for the identity reparse (WP-6).

``plan`` reads the files and reports what the run would do without opening a
database at all, so the sources can be checked on their own. ``apply`` does the
same computation against a workspace and writes; ``--dry-run`` writes nothing
and prints the same report, because the two paths differ only in the commit.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
from uuid import UUID

from marko.core.config import get_settings
from marko.infrastructure.db.session import async_session_factory
from marko.services.catalog_discovery import resolve_backend_path
from marko.services.catalog_identity_safety import (
    identity_runtime_config_sha256,
    identity_runtime_implementation_sha256s,
)
from marko.services.catalog_identity_reparse import (
    CatalogIdentityReparseError,
    SourceIndex,
    build_source_index,
    plan_identity,
    reparse_workspace_identity,
)
from marko.services.catalog_identity_coverage import (
    build_catalog_coverage_report,
    load_optkiev_catalog_review,
    load_owner_candidate_review,
)
from marko.services.xlsx_catalog import CatalogImportError, parse_catalog_xlsx
from marko.services.semantic_candidate_features import (
    SEMANTIC_FEATURE_EXTRACTOR_VERSION,
)
from metis.pricing.identity_graph import (
    IdentityGraphConfigError,
    load_identity_graph_config,
)
from metis.pricing.kemp_reference import KempReferenceError, load_article_brand_kinds
from metis.pricing.kemp_site import load_kemp_site_tokens

DEFAULT_GRAPH_CONFIG = "config/identity_graph.yaml"
DEFAULT_BRAND_KINDS = "config/article_brand_kinds.yaml"
DEFAULT_TOKENS = "config/kemp_site_tokens.yaml"
DEFAULT_REFERENCES = ("data/kemp_reference_map.csv", "data/kemp_oe_map.csv")
DEFAULT_SITE = "data/kemp_site_numbers.csv"
#: Shipped with the repository and pinned by sha256 in identity_graph.yaml, so
#: it is part of the declared source set rather than an optional extra: leaving
#: it out silently reports a catalogue 178 codes poorer than the one we ship.
DEFAULT_SPARETO = "data/spareto_oe_confirmations.csv"
DEFAULT_CATALOG = "data/kemp_prom_catalog.xlsx"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catalog-identity-reparse",
        description="Seed catalog_identity_links from the reference files",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("plan", "Read the files and report, touching no database"),
        ("apply", "Reparse one workspace and write the links"),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("--graph-config", default=DEFAULT_GRAPH_CONFIG)
        sub.add_argument("--brand-kinds", default=DEFAULT_BRAND_KINDS)
        sub.add_argument("--tokens", default=DEFAULT_TOKENS)
        sub.add_argument(
            "--reference",
            action="append",
            dest="references",
            help="A reference edition; repeatable. Defaults to both shipped files.",
        )
        sub.add_argument("--site", default=DEFAULT_SITE)
        sub.add_argument(
            "--no-site",
            action="store_true",
            help="Leave the kemp.ua harvest out entirely",
        )
        sub.add_argument(
            "--spareto",
            action="append",
            dest="spareto_paths",
            help=(
                "spareto.com /oe/ confirmations; repeatable. Defaults to the "
                "shipped dataset."
            ),
        )
        sub.add_argument(
            "--no-spareto",
            action="store_true",
            help="Leave the independent catalogue confirmations out entirely",
        )
        sub.add_argument(
            "--catalog",
            default=DEFAULT_CATALOG,
            help="Full catalog workbook for the 4,901-row coverage report",
        )
        sub.add_argument(
            "--catalog-sheet",
            default=None,
            help="Workbook sheet; defaults to Export Products Sheet when present",
        )
        sub.add_argument(
            "--no-catalog",
            action="store_true",
            help="Emit only the 7,193-code reference plan",
        )
        sub.add_argument(
            "--owner-store",
            action="append",
            dest="owner_stores",
            default=[],
            help="Customer-owned Prom card export (.csv/.xlsx); repeatable",
        )
        sub.add_argument(
            "--owner-candidates",
            action="append",
            dest="owner_candidate_paths",
            default=[],
            help=(
                "Derived owner page-area candidate export for review only; "
                "repeatable"
            ),
        )
        sub.add_argument(
            "--optkiev-catalog",
            action="append",
            dest="optkiev_catalog_paths",
            default=[],
            help="OPTKiev/Avto.pro seller catalog for review-only overlap audit",
        )
        sub.add_argument(
            "--avtopro",
            action="append",
            dest="avtopro_paths",
            default=[],
            help="Strict avto.pro card harvest for review evidence; repeatable",
        )
        sub.add_argument("--json", type=Path, help="Write the report here as JSON")
        if name == "apply":
            sub.add_argument("--workspace", required=True, type=UUID)
            sub.add_argument(
                "--dry-run",
                action="store_true",
                help="Compute everything and commit nothing",
            )
    return parser


def _build_index(args: argparse.Namespace) -> SourceIndex:
    config = load_identity_graph_config(resolve_backend_path(args.graph_config))
    kinds = load_article_brand_kinds(resolve_backend_path(args.brand_kinds))
    tokens = load_kemp_site_tokens(resolve_backend_path(args.tokens))
    references = [
        resolve_backend_path(path)
        for path in (args.references or list(DEFAULT_REFERENCES))
    ]
    site = None if args.no_site else resolve_backend_path(args.site)
    owner_stores = [
        resolve_backend_path(path) for path in (args.owner_stores or [])
    ]
    avtopro_paths = [
        resolve_backend_path(path) for path in (args.avtopro_paths or [])
    ]
    spareto_paths = (
        []
        if args.no_spareto
        else [
            resolve_backend_path(path)
            for path in (args.spareto_paths or [DEFAULT_SPARETO])
        ]
    )
    index = build_source_index(
        config=config,
        kinds=kinds,
        tokens=tokens,
        reference_paths=references,
        site_path=site,
        owner_store_paths=owner_stores,
        avtopro_paths=avtopro_paths,
        spareto_paths=spareto_paths,
    )
    args.graph_config_loaded = config
    args.tokens_loaded = tokens
    return index


def _index_summary(index: SourceIndex) -> dict[str, object]:
    return {
        "sources_loaded": list(index.loaded_sources),
        "internal_codes_indexed": len(index.by_code),
        "reference_codes": len(index.reference_codes),
        "shared_articles": len(index.shared_articles),
        "mpn_only_rows": index.mpn_only_rows,
        "rows_without_code": index.rows_without_code,
        "supplier_number_claims": index.supplier_number_claims,
        "owner_rows_read": index.owner_rows_read,
        "owner_rows_bound": index.owner_rows_bound,
        "owner_cards_bound": index.owner_cards_bound,
        "owner_card_ambiguity_codes": index.owner_card_ambiguity_codes,
        "owner_noise_rows_rejected": index.owner_noise_rows,
        "owner_code_aliases": len(index.owner_by_code),
        "semantic_conflict_codes": len(index.semantic_conflicts),
        "semantic_conflicts": dict(sorted(index.semantic_conflicts.items())),
        "semantic_fanout_conflict_numbers": len(index.semantic_fanout_conflicts),
        "semantic_fanout_conflicts": dict(
            sorted(index.semantic_fanout_conflicts.items())
        ),
    }


def _contract_summary(config, tokens) -> dict[str, object]:
    """Pin the algorithm behind a source-only plan, not just its output."""

    return {
        "identity_graph_method_version": config.method_version,
        "identity_graph_config_sha256": config.source_sha256,
        "token_config_sha256": tokens.source_sha256,
        "semantic_feature_extractor_version": (
            SEMANTIC_FEATURE_EXTRACTOR_VERSION
        ),
        "implementation_sha256s": dict(
            identity_runtime_implementation_sha256s()
        ),
        "runtime_config_sha256": identity_runtime_config_sha256(config, tokens),
    }


def _plan_summary(index: SourceIndex, config, tokens) -> dict[str, object]:
    """What the files alone imply, before any catalogue row is consulted.

    Reported against the reference codes rather than the catalogue, and labelled
    as such: the catalogue joins on a code most of its rows do not carry, so
    presenting these as catalogue coverage would overstate it several times over.
    """

    statuses: dict[str, int] = {}
    anomalies: dict[str, int] = {}
    links = 0
    with_links = 0
    for code in sorted(index.reference_codes or index.by_code):
        plan = plan_identity(
            own_code=code,
            part_numbers_raw=(),
            current_oe_norm="",
            index=index,
            config=config,
            tokens=tokens,
        )
        statuses[plan.identity_status] = statuses.get(plan.identity_status, 0) + 1
        for anomaly in plan.graph.anomalies:
            anomalies[anomaly] = anomalies.get(anomaly, 0) + 1
        links += len(plan.links)
        with_links += 1 if plan.links else 0
    return {
        "scope": "reference_codes_only_not_catalogue_rows",
        "denominator": len(index.reference_codes or index.by_code),
        "identity_status_counts": dict(sorted(statuses.items())),
        "anomaly_counts": dict(sorted(anomalies.items())),
        "codes_with_links": with_links,
        "links": links,
    }


def _catalog_summary(args: argparse.Namespace, index: SourceIndex) -> dict[str, object]:
    if args.no_catalog:
        return {"scope": "catalog_coverage_disabled"}
    catalog_path = resolve_backend_path(args.catalog)
    if not catalog_path.is_file():
        raise CatalogIdentityReparseError(
            f"Catalog workbook does not exist: {catalog_path}"
        )
    raw = catalog_path.read_bytes()
    sheet_name = args.catalog_sheet
    if sheet_name is None:
        try:
            from io import BytesIO
            from openpyxl import load_workbook

            workbook = load_workbook(BytesIO(raw), read_only=True, data_only=True)
            if len(workbook.sheetnames) == 1:
                sheet_name = workbook.sheetnames[0]
            elif "Export Products Sheet" in workbook.sheetnames:
                sheet_name = "Export Products Sheet"
        except Exception:
            # parse_catalog_xlsx emits the precise container error below if the
            # workbook cannot be inspected here.
            sheet_name = None
    parsed = parse_catalog_xlsx(raw, sheet_name=sheet_name)
    # The final audit must expose the complete provenance queue.  The coverage
    # service keeps a bounded default for library callers, but the CLI knows the
    # workbook denominator and can safely request every row (including every
    # disputed/contradictory row and every accepted-OE delta).
    detail_limit = max(parsed.total_rows, 10_000)
    report = build_catalog_coverage_report(
        parsed,
        index=index,
        config=args.graph_config_loaded,
        tokens=args.tokens_loaded,
        detail_limit=detail_limit,
    )
    report["input"] = {
        "path": str(catalog_path),
        "content_sha256": hashlib.sha256(raw).hexdigest(),
        "sheet_rows": parsed.total_rows,
    }
    candidate_reports = []
    for candidate_path in args.owner_candidate_paths or []:
        candidate_reports.append(
            load_owner_candidate_review(
                resolve_backend_path(candidate_path),
                parsed=parsed,
                index=index,
                tokens=args.tokens_loaded,
                detail_limit=detail_limit,
            )
        )
    report["owner_candidate_review"] = candidate_reports
    for candidate in candidate_reports:
        report.setdefault("source_matrix", []).append(
            {
                "source": candidate["source"],
                "publisher": candidate["publisher"],
                "source_role": candidate["source_role"],
                "asserts_oe": candidate["asserts_oe"],
                "status": candidate["status"],
                "vintage": None,
                "loaded": True,
                "dataset_sha256s": [candidate["content_sha256"]],
                "unique_cards_or_urls": candidate["unique_card_urls"],
                "ingested_cards": candidate["unique_card_urls"],
                "unique_codes": candidate["unique_codes"],
                "source_unique_numbers": candidate["unique_numbers"],
                "source_duplicate_numbers": 0,
                "source_duplicate_rate_percent": candidate[
                    "duplicate_rate_percent"
                ],
                "catalog_rows_with_evidence": candidate[
                    "rows_with_exact_catalog_code"
                ],
                "catalog_rows_with_asserted_oe": 0,
                "catalog_rows_with_confirmed_oe": 0,
                "catalog_review_only_candidates": candidate["clean_rows"],
                "catalog_conflict_rows": 0,
                "catalog_unique_numbers": candidate["clean_unique_numbers"],
                "incremental_unique_confirmed_rows": 0,
                "discarded_or_noise_values": candidate["noise_rows"],
            }
        )
    optkiev_reports = []
    for optkiev_path in args.optkiev_catalog_paths or []:
        optkiev_reports.append(
            load_optkiev_catalog_review(
                resolve_backend_path(optkiev_path),
                parsed=parsed,
                index=index,
                tokens=args.tokens_loaded,
                detail_limit=detail_limit,
            )
        )
    report["optkiev_catalog_review"] = optkiev_reports
    for optkiev in optkiev_reports:
        report.setdefault("source_matrix", []).append(
            {
                "source": optkiev["source"],
                "publisher": optkiev["publisher"],
                "source_role": optkiev["source_role"],
                "asserts_oe": optkiev["asserts_oe"],
                "status": optkiev["status"],
                "vintage": None,
                "loaded": True,
                "dataset_sha256s": [optkiev["content_sha256"]],
                "unique_cards_or_urls": optkiev["unique_cards_or_urls"],
                "ingested_cards": optkiev["unique_cards_or_urls"],
                "unique_codes": optkiev["unique_codes"],
                "source_unique_numbers": optkiev["unique_numbers"],
                "source_duplicate_numbers": optkiev["duplicate_numbers"],
                "source_duplicate_rate_percent": optkiev[
                    "duplicate_rate_percent"
                ],
                "catalog_rows_with_evidence": optkiev[
                    "rows_with_exact_catalog_number"
                ],
                "catalog_rows_with_asserted_oe": 0,
                "catalog_rows_with_confirmed_oe": 0,
                "catalog_review_only_candidates": optkiev["rows_read"],
                "catalog_conflict_rows": optkiev[
                    "rows_with_multiple_catalog_rows"
                ],
                "catalog_unique_numbers": optkiev[
                    "unique_numbers_with_catalog_match"
                ],
                "incremental_unique_confirmed_rows": 0,
                "discarded_or_noise_values": 0,
            }
        )
    report.get("source_matrix", []).sort(key=lambda item: item["source"])
    return report


def _emit(payload: dict[str, object], destination: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    print(text)
    if destination is not None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text + "\n", encoding="utf-8")


async def _apply(args: argparse.Namespace) -> dict[str, object]:
    index = _build_index(args)
    get_settings()
    async with async_session_factory() as session:
        report = await reparse_workspace_identity(
            session,
            workspace_id=args.workspace,
            index=index,
            config=args.graph_config_loaded,
            tokens=args.tokens_loaded,
            dry_run=bool(args.dry_run),
        )
    return {
        "contract": _contract_summary(
            args.graph_config_loaded,
            args.tokens_loaded,
        ),
        "sources": _index_summary(index),
        "run": report.as_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            index = _build_index(args)
            payload = {
                "contract": _contract_summary(
                    args.graph_config_loaded,
                    args.tokens_loaded,
                ),
                "sources": _index_summary(index),
                "plan": _plan_summary(
                    index,
                    args.graph_config_loaded,
                    args.tokens_loaded,
                ),
                "catalog": _catalog_summary(args, index),
            }
        else:
            payload = asyncio.run(_apply(args))
    except (
        CatalogIdentityReparseError,
        CatalogImportError,
        IdentityGraphConfigError,
        KempReferenceError,
    ) as exc:
        print(f"reparse refused: {exc}", file=sys.stderr)
        return 2
    _emit(payload, args.json)
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
