"""CLI for the identity reparse (WP-6).

``plan`` reads the files and reports what the run would do without opening a
database at all, so the sources can be checked on their own. ``apply`` does the
same computation against a workspace and writes; ``--dry-run`` writes nothing
and prints the same report, because the two paths differ only in the commit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from uuid import UUID

from marko.core.config import get_settings
from marko.infrastructure.db.session import async_session_factory
from marko.services.catalog_discovery import resolve_backend_path
from marko.services.catalog_identity_reparse import (
    CatalogIdentityReparseError,
    SourceIndex,
    build_source_index,
    plan_identity,
    reparse_workspace_identity,
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
    index = build_source_index(
        config=config,
        kinds=kinds,
        tokens=tokens,
        reference_paths=references,
        site_path=site,
    )
    args.graph_config_loaded = config
    args.tokens_loaded = tokens
    return index


def _index_summary(index: SourceIndex) -> dict[str, object]:
    return {
        "sources_loaded": list(index.loaded_sources),
        "internal_codes_indexed": len(index.by_code),
        "shared_articles": len(index.shared_articles),
        "mpn_only_rows": index.mpn_only_rows,
        "rows_without_code": index.rows_without_code,
        "supplier_number_claims": index.supplier_number_claims,
    }


def _plan_summary(index: SourceIndex, config) -> dict[str, object]:
    """What the files alone imply, before any catalogue row is consulted.

    Reported against the reference codes rather than the catalogue, and labelled
    as such: the catalogue joins on a code most of its rows do not carry, so
    presenting these as catalogue coverage would overstate it several times over.
    """

    statuses: dict[str, int] = {}
    anomalies: dict[str, int] = {}
    links = 0
    with_links = 0
    for code in index.by_code:
        plan = plan_identity(
            own_code=code,
            part_numbers_raw=(),
            current_oe_norm="",
            index=index,
            config=config,
        )
        statuses[plan.identity_status] = statuses.get(plan.identity_status, 0) + 1
        for anomaly in plan.graph.anomalies:
            anomalies[anomaly] = anomalies.get(anomaly, 0) + 1
        links += len(plan.links)
        with_links += 1 if plan.links else 0
    return {
        "scope": "reference_codes_only_not_catalogue_rows",
        "identity_status_counts": dict(sorted(statuses.items())),
        "anomaly_counts": dict(sorted(anomalies.items())),
        "codes_with_links": with_links,
        "links": links,
    }


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
    return {"sources": _index_summary(index), "run": report.as_dict()}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            index = _build_index(args)
            payload = {
                "sources": _index_summary(index),
                "plan": _plan_summary(index, args.graph_config_loaded),
            }
        else:
            payload = asyncio.run(_apply(args))
    except (
        CatalogIdentityReparseError,
        IdentityGraphConfigError,
        KempReferenceError,
    ) as exc:
        print(f"reparse refused: {exc}", file=sys.stderr)
        return 2
    _emit(payload, args.json)
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
