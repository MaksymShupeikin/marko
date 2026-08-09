"""Read-only report joining an imported catalog to all owned storefront cards."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping
from uuid import UUID

from marko.infrastructure.db.session import async_session_factory
from marko.services.catalog_internal_code_join import (
    catalog_internal_code_join_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True, type=UUID)
    parser.add_argument("--import-batch-id", required=True, type=UUID)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--csv-out", type=Path)
    parser.add_argument("--manifest-out", type=Path)
    return parser


def _refuse_overwrite(path: Path | None) -> None:
    if path is not None and path.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {path}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "catalog_item_id",
        "source_row",
        "internal_code_norm",
        "status",
        "listing_count",
        "listing_ids",
        "store_ids",
        "ambiguous_listing_ids",
        "requires_single_card_consumer_stop",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **{key: row.get(key) for key in fieldnames},
                    "listing_count": len(row.get("listing_ids") or []),
                    "listing_ids": ";".join(row.get("listing_ids") or []),
                    "store_ids": ";".join(row.get("store_ids") or []),
                    "ambiguous_listing_ids": ";".join(
                        row.get("ambiguous_listing_ids") or []
                    ),
                }
            )


async def _run(args: argparse.Namespace) -> int:
    output_paths = (args.json_out, args.csv_out, args.manifest_out)
    resolved = [path.resolve() for path in output_paths if path is not None]
    if len(resolved) != len(set(resolved)):
        raise ValueError("output paths must be distinct")
    for path in output_paths:
        _refuse_overwrite(path)
    async with async_session_factory() as session:
        report = await catalog_internal_code_join_report(
            session,
            workspace_id=args.workspace_id,
            import_batch_id=args.import_batch_id,
        )
    payload = report.as_dict()
    payload["workspace_id"] = str(args.workspace_id)
    payload["import_batch_id"] = str(args.import_batch_id)
    if args.json_out is None and args.csv_out is None:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    outputs: list[dict[str, Any]] = []
    if args.json_out is not None:
        _write_json(args.json_out, payload)
        outputs.append(
            {
                "path": str(args.json_out.resolve()),
                "bytes": args.json_out.stat().st_size,
                "sha256": _sha256(args.json_out),
            }
        )
    if args.csv_out is not None:
        _write_csv(args.csv_out, list(payload["rows"]))
        outputs.append(
            {
                "path": str(args.csv_out.resolve()),
                "bytes": args.csv_out.stat().st_size,
                "sha256": _sha256(args.csv_out),
            }
        )
    if args.manifest_out is not None:
        _write_json(
            args.manifest_out,
            {
                "report_version": payload["report_version"],
                "workspace_id": str(args.workspace_id),
                "import_batch_id": str(args.import_batch_id),
                "outputs": outputs,
            },
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(_run(_parser().parse_args(argv)))
    except (FileExistsError, ValueError) as exc:
        print(f"catalog internal-code join error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
