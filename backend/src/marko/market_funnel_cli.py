"""Read-only OE market funnel, blinded review batch, and canary verification."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence
from uuid import UUID

from marko.infrastructure.db.session import async_session_factory
from marko.services.market_funnel import (
    MARKET_REVIEW_SOURCE_FIELDS,
    MarketFunnelError,
    build_blinded_review_batch,
    build_market_funnel_report,
    load_market_funnel_inputs,
    market_review_prediction_payload,
    market_review_source_rows,
    score_reviewed_market_pairs,
    verify_canary_labels,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    report = commands.add_parser("report")
    report.add_argument("--workspace-id", required=True, type=UUID)
    report.add_argument("--run-id", required=True, type=UUID)
    report.add_argument("--json-out", type=Path)
    report.add_argument("--rows-csv-out", type=Path)
    report.add_argument("--review-pool-csv-out", type=Path)
    report.add_argument("--prediction-json-out", type=Path)
    report.add_argument("--manifest-out", type=Path)

    prepare = commands.add_parser("prepare-review")
    prepare.add_argument("--market-pool-csv", required=True, type=Path)
    prepare.add_argument("--canary-source-csv", required=True, type=Path)
    prepare.add_argument("--batch-size", required=True, type=int)
    prepare.add_argument("--selection-seed", required=True)
    prepare.add_argument("--blinded-source-out", required=True, type=Path)
    prepare.add_argument("--canary-key-out", required=True, type=Path)
    prepare.add_argument("--manifest-out", type=Path)

    verify = commands.add_parser("verify-canaries")
    verify.add_argument("--reviewed-set", required=True, type=Path)
    verify.add_argument("--canary-key", required=True, type=Path)
    verify.add_argument("--output", type=Path)

    score = commands.add_parser("score-review")
    score.add_argument("--reviewed-set", required=True, type=Path)
    score.add_argument("--predictions", required=True, type=Path)
    score.add_argument("--canary-key", required=True, type=Path)
    score.add_argument("--report-manifest", required=True, type=Path)
    score.add_argument("--review-batch-manifest", required=True, type=Path)
    score.add_argument("--output", type=Path)
    return parser


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _refuse_overwrite(paths: Sequence[Path | None]) -> None:
    resolved = [path.resolve() for path in paths if path is not None]
    if len(resolved) != len(set(resolved)):
        raise MarketFunnelError("output paths must be distinct")
    existing = [str(path) for path in paths if path is not None and path.exists()]
    if existing:
        raise MarketFunnelError(
            "refusing to overwrite existing outputs: " + ", ".join(existing)
        )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketFunnelError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MarketFunnelError(f"JSON {path} must contain an object")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise MarketFunnelError(f"CSV has no header: {path}")
            return [dict(row) for row in reader]
    except OSError as exc:
        raise MarketFunnelError(f"cannot read CSV {path}: {exc}") from exc


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    *,
    fieldnames: Sequence[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_fieldnames = list(fieldnames or ())
    if not resolved_fieldnames:
        for row in rows:
            for key in row:
                if key not in resolved_fieldnames:
                    resolved_fieldnames.append(str(key))
    if not resolved_fieldnames:
        raise MarketFunnelError(f"cannot infer an empty CSV schema: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=resolved_fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))


def _output_entry(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _verify_manifest_output(
    manifest_path: Path,
    target_path: Path,
    *,
    expected_version: str,
) -> None:
    manifest = _read_json(manifest_path)
    if manifest.get("manifest_version") != expected_version:
        raise MarketFunnelError(
            f"unexpected manifest version in {manifest_path}: "
            f"{manifest.get('manifest_version')!r}"
        )
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise MarketFunnelError(f"manifest has no outputs: {manifest_path}")
    resolved_target = target_path.resolve()
    matches = [
        row
        for row in outputs
        if isinstance(row, Mapping)
        and Path(str(row.get("path") or "")).resolve() == resolved_target
    ]
    if len(matches) != 1:
        raise MarketFunnelError(
            f"manifest does not bind exactly one output for {resolved_target}"
        )
    expected_sha256 = str(matches[0].get("sha256") or "")
    try:
        actual_sha256 = _sha256(target_path)
    except OSError as exc:
        raise MarketFunnelError(
            f"cannot hash manifested output {resolved_target}: {exc}"
        ) from exc
    if not expected_sha256 or actual_sha256 != expected_sha256:
        raise MarketFunnelError(
            f"manifest hash mismatch for {resolved_target}: "
            f"expected {expected_sha256 or '<missing>'}, actual {actual_sha256}"
        )


async def _report(args: argparse.Namespace) -> int:
    _refuse_overwrite(
        (
            args.json_out,
            args.rows_csv_out,
            args.review_pool_csv_out,
            args.prediction_json_out,
            args.manifest_out,
        )
    )
    async with async_session_factory() as session:
        inputs = await load_market_funnel_inputs(
            session,
            workspace_id=args.workspace_id,
            run_id=args.run_id,
        )
    report = build_market_funnel_report(inputs)
    payload = report.as_dict()
    payload["workspace_id"] = str(args.workspace_id)
    payload["pricing_run_id"] = str(args.run_id)
    outputs: list[dict[str, Any]] = []
    if args.json_out is not None:
        _write_json(args.json_out, payload)
        outputs.append(_output_entry(args.json_out))
    if args.rows_csv_out is not None:
        rows = [
            {
                **row,
                "public_keys": json.dumps(
                    row["public_keys"], ensure_ascii=False, sort_keys=True
                ),
                "recommendation_actions": ";".join(row["recommendation_actions"]),
                "reason_codes": ";".join(row["reason_codes"]),
            }
            for row in payload["rows"]
        ]
        _write_csv(args.rows_csv_out, rows)
        outputs.append(_output_entry(args.rows_csv_out))
    if args.review_pool_csv_out is not None:
        review_rows = market_review_source_rows(inputs)
        _write_csv(
            args.review_pool_csv_out,
            review_rows,
            fieldnames=MARKET_REVIEW_SOURCE_FIELDS,
        )
        outputs.append(_output_entry(args.review_pool_csv_out))
    if args.prediction_json_out is not None:
        prediction_payload = market_review_prediction_payload(inputs)
        prediction_payload["workspace_id"] = str(args.workspace_id)
        prediction_payload["pricing_run_id"] = str(args.run_id)
        _write_json(args.prediction_json_out, prediction_payload)
        outputs.append(_output_entry(args.prediction_json_out))
    if args.manifest_out is not None:
        _write_json(
            args.manifest_out,
            {
                "manifest_version": "oe-market-funnel-manifest-v1",
                "workspace_id": str(args.workspace_id),
                "pricing_run_id": str(args.run_id),
                "report_version": report.report_version,
                "outputs": outputs,
            },
        )
    if args.json_out is None:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report.stage_counts_are_monotonic else 1


def _prepare_review(args: argparse.Namespace) -> int:
    if not 150 <= args.batch_size <= 300:
        raise MarketFunnelError("--batch-size must be within 150..300")
    _refuse_overwrite((args.blinded_source_out, args.canary_key_out, args.manifest_out))
    source_parent = args.blinded_source_out.resolve().parent
    key_parent = args.canary_key_out.resolve().parent
    if source_parent == key_parent:
        raise MarketFunnelError(
            "the canary answer key must be outside the blinded review folder"
        )
    market_rows = _read_csv(args.market_pool_csv)
    canary_rows = _read_csv(args.canary_source_csv)
    batch = build_blinded_review_batch(
        market_rows,
        canary_rows,
        batch_size=args.batch_size,
        selection_seed=args.selection_seed,
    )
    if len(batch.rows) != args.batch_size:
        raise MarketFunnelError(
            f"review pool produced {len(batch.rows)} rows, expected {args.batch_size}"
        )
    _write_csv(args.blinded_source_out, batch.rows)
    _write_json(args.canary_key_out, batch.canary_key)
    outputs = [
        _output_entry(args.blinded_source_out),
        _output_entry(args.canary_key_out),
    ]
    if args.manifest_out is not None:
        _write_json(
            args.manifest_out,
            {
                "manifest_version": "oe-market-review-batch-v1",
                "market_pool": _output_entry(args.market_pool_csv),
                "canary_source": _output_entry(args.canary_source_csv),
                "batch_size": len(batch.rows),
                "canary_count": batch.canary_count,
                "selection_seed_sha256": batch.canary_key["selection_seed_sha256"],
                "outputs": outputs,
                "contains_model_predictions": False,
                "contains_prices": False,
            },
        )
    print(
        json.dumps(
            {
                "rows": len(batch.rows),
                "canaries": batch.canary_count,
                "blinded_source": str(args.blinded_source_out.resolve()),
                "canary_key": str(args.canary_key_out.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _verify_canaries(args: argparse.Namespace) -> int:
    _refuse_overwrite((args.output,))
    result = verify_canary_labels(
        _read_json(args.reviewed_set),
        _read_json(args.canary_key),
    )
    if args.output is None:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        _write_json(args.output, result)
    return 0 if result["status"] == "PASS" else 1


def _score_review(args: argparse.Namespace) -> int:
    _refuse_overwrite((args.output,))
    _verify_manifest_output(
        args.report_manifest,
        args.predictions,
        expected_version="oe-market-funnel-manifest-v1",
    )
    _verify_manifest_output(
        args.review_batch_manifest,
        args.canary_key,
        expected_version="oe-market-review-batch-v1",
    )
    reviewed = _read_json(args.reviewed_set)
    predictions = _read_json(args.predictions)
    canary_key = _read_json(args.canary_key)
    canary_result = verify_canary_labels(reviewed, canary_key)
    score = score_reviewed_market_pairs(
        reviewed,
        predictions,
        canary_key=canary_key,
    )
    accepted = bool(
        canary_result["status"] == "PASS"
        and score["complete_pair_accounting"]
        and score["human_class_coverage_complete"]
        and score["review_batch_size_valid"]
        and score["critical_false_accept_gate_passed"]
        and score["unsafe_pricing_admission_count"] == 0
    )
    result = {
        "evaluation_version": "market-review-evaluation-v1",
        "canaries": canary_result,
        "model_score": score,
        "review_batch_accepted": accepted,
        "price_showing_ready": False,
        "operator_decision_required": True,
        "frozen_input_manifests": {
            "report_manifest_sha256": _sha256(args.report_manifest),
            "review_batch_manifest_sha256": _sha256(
                args.review_batch_manifest
            ),
        },
    }
    if args.output is None:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        _write_json(args.output, result)
    return 0 if accepted else 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "report":
            return asyncio.run(_report(args))
        if args.command == "prepare-review":
            return _prepare_review(args)
        if args.command == "verify-canaries":
            return _verify_canaries(args)
        return _score_review(args)
    except MarketFunnelError as exc:
        print(f"market funnel error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
