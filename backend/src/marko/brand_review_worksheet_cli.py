"""CLI for the brand markup worksheet and the fail-closed dictionary check.

``build`` collects live evidence into a reviewable worksheet and a draft
dictionary; it never assigns a tier. ``validate`` answers the only question
that matters after a human edits the dictionary: which rules would actually
become active, and if none, exactly why the file was refused.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from uuid import UUID

from marko.infrastructure.db.session import async_session_factory
from marko.services.brand_review_worksheet import (
    ASSIGNABLE_TIERS,
    BrandWorksheetError,
    build_brand_worksheet,
    load_brand_observations,
    load_existing_records,
    render_brands_draft_yaml,
    render_worksheet_csv,
    render_worksheet_table,
    utc_now,
)
from metis.pricing import (
    BrandRuleContractError,
    ProductTier,
    load_approved_brand_rules,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brand-review-worksheet",
        description="Prepare brand tier markup for a human reviewer",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser(
        "build",
        help="Aggregate live discovery evidence into a worksheet and draft",
    )
    build.add_argument("--workspace-id", required=True, type=UUID)
    build.add_argument("--out-dir", required=True, type=Path)
    build.add_argument(
        "--existing",
        type=Path,
        default=None,
        help="Existing brands.yaml whose human decisions must be preserved",
    )
    build.add_argument(
        "--dataset-id",
        default=None,
        help="dataset_id for the draft; defaults to a date-stamped identifier",
    )
    build.add_argument(
        "--min-offer-count",
        type=int,
        default=1,
        help="Drop brands seen fewer times than this (default 1: keep all)",
    )
    build.add_argument(
        "--example-urls",
        type=int,
        default=3,
        help="Evidence URLs to pre-fill per brand (default 3)",
    )
    build.add_argument(
        "--table-limit",
        type=int,
        default=40,
        help="Rows to print to stdout; the CSV always holds every brand",
    )

    validate = subparsers.add_parser(
        "validate",
        help="Report which brand rules a dictionary would activate, or why not",
    )
    validate.add_argument("--path", required=True, type=Path)
    validate.add_argument("--json", action="store_true", dest="as_json")
    return parser


async def _build(args: argparse.Namespace) -> int:
    existing = load_existing_records(args.existing) if args.existing else None
    async with async_session_factory() as session:
        observations = await load_brand_observations(
            session,
            workspace_id=args.workspace_id,
        )
    if not observations:
        print(
            "Наблюдений нет: в этом workspace нет завершённых прогонов discovery.",
            file=sys.stderr,
        )
        return 2

    generated_at = utc_now()
    worksheet = build_brand_worksheet(
        observations,
        generated_at=generated_at,
        example_urls=max(1, args.example_urls),
        min_offer_count=max(1, args.min_offer_count),
    )
    dataset_id = args.dataset_id or (
        f"metis-prom-ua-brand-review-{generated_at.date().isoformat()}"
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / "brands_review_worksheet.csv"
    yaml_path = args.out_dir / "brands_draft.yaml"
    json_path = args.out_dir / "brands_worksheet.json"

    csv_path.write_text(render_worksheet_csv(worksheet), encoding="utf-8")
    yaml_path.write_text(
        render_brands_draft_yaml(
            worksheet,
            dataset_id=dataset_id,
            existing=existing,
        ),
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps(worksheet.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(render_worksheet_table(worksheet, limit=args.table_limit))
    print()
    print(f"CSV для разметки:  {csv_path}")
    print(f"черновик словаря:  {yaml_path}")
    print(f"машиночитаемо:     {json_path}")
    print()
    print(
        "Tier'ы не проставлены — это работа человека. Допустимые значения: "
        + ", ".join(ASSIGNABLE_TIERS)
    )
    return 0


async def _validate(args: argparse.Namespace) -> int:
    try:
        rules = load_approved_brand_rules(args.path)
    except BrandRuleContractError as exc:
        payload = {
            "path": str(args.path),
            "accepted": False,
            "error": str(exc),
            "active_non_kemp_rules": 0,
        }
        if args.as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("СЛОВАРЬ ОТКЛОНЁН (fail-closed)")
            print(f"файл:    {args.path}")
            print(f"причина: {exc}")
            print()
            print(
                "Ни одно правило не применено. Это защита: частично "
                "оформленное утверждение молча не активируется."
            )
        return 1

    active = {
        brand: tier.value
        for brand, tier in sorted(rules.tiers.items())
        if tier is not ProductTier.KEMP
    }
    payload = {
        "path": str(args.path),
        "accepted": True,
        "dataset_id": rules.dataset_id,
        "source_sha256": rules.source_sha256,
        "domain_policy_approved": rules.domain_policy_approved,
        "approved_by": rules.approved_by,
        "approved_at": rules.approved_at,
        "active_non_kemp_rules": len(active),
        "active_tiers": active,
    }
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print("СЛОВАРЬ ПРИНЯТ")
    print(f"файл:             {args.path}")
    print(f"dataset_id:       {rules.dataset_id}")
    print(f"sha256:           {rules.source_sha256}")
    print(f"политика утв.:    {rules.domain_policy_approved}")
    print(f"кем/когда:        {rules.approved_by or '—'} / {rules.approved_at or '—'}")
    print(f"активных не-KEMP: {len(active)}")
    for brand, tier in active.items():
        print(f"   {brand}: {tier}")
    if not active:
        print()
        print(
            "Активных не-KEMP правил нет: движок продолжит выдавать "
            "TIER_UNKNOWN, а COMPARABLE останется недостижимым."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handler = _build if args.command == "build" else _validate
    try:
        return asyncio.run(handler(args))
    except BrandWorksheetError as exc:
        print(f"Ошибка [{exc.code}]: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
