#!/usr/bin/env python3
"""Freeze the 60-100 seed gate, prepare blind labels, and compute six metrics."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal
import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

from evaluation import (
    MANDATORY_UNTYPED_ROW_IDS,
    SAMPLE_SCHEMA_VERSION,
    SEMANTIC_REVIEW_CANARY_FIELDS,
    SEMANTIC_SEED_REVIEW_FIELDS,
    SemanticEvaluationError,
    build_semantic_review_canaries,
    build_stratified_sample,
    evaluate_semantic_discovery_gate,
    semantic_candidate_evidence_sha256,
    semantic_seed_evidence_sha256,
    validate_frozen_run_coverage,
    verify_semantic_review_canaries,
    verify_semantic_review_evidence,
)
from semantic_discovery import (
    MAX_SEEDS_PER_RUN,
    build_query_plan,
    build_seed_profile,
    canonical_json,
    load_no_oe_catalog_seeds,
    sha256_file,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MASTER = REPO_ROOT.parent / "OE_каталог_2026-08-09.xlsx"
DEFAULT_SOURCE = REPO_ROOT / "backend/data/kemp_prom_catalog.xlsx"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    freeze = commands.add_parser("freeze")
    freeze.add_argument("--master-workbook", type=Path, default=DEFAULT_MASTER)
    freeze.add_argument("--source-workbook", type=Path, default=DEFAULT_SOURCE)
    freeze.add_argument("--sample-size", type=int, default=80)
    freeze.add_argument("--selection-seed", required=True)
    freeze.add_argument("--output", required=True, type=Path)

    labels = commands.add_parser("prepare-labels")
    labels.add_argument("--sample", required=True, type=Path)
    labels.add_argument("--run-dir", required=True, action="append", type=Path)
    labels.add_argument("--canary-source-csv", required=True, type=Path)
    labels.add_argument("--seed-labels-out", required=True, type=Path)
    labels.add_argument("--candidate-labels-out", required=True, type=Path)
    labels.add_argument("--system-predictions-out", required=True, type=Path)
    labels.add_argument("--canary-key-out", required=True, type=Path)
    labels.add_argument("--manifest-out", required=True, type=Path)

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--sample", required=True, type=Path)
    evaluate.add_argument("--seed-labels", required=True, type=Path)
    evaluate.add_argument("--candidate-labels", required=True, type=Path)
    evaluate.add_argument("--system-predictions", required=True, type=Path)
    evaluate.add_argument("--canary-key", required=True, type=Path)
    evaluate.add_argument("--label-manifest", required=True, type=Path)
    evaluate.add_argument("--output", required=True, type=Path)
    return parser


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _refuse_overwrite(paths: Sequence[Path | None]) -> None:
    resolved = [path.resolve() for path in paths if path is not None]
    if len(resolved) != len(set(resolved)):
        raise SemanticEvaluationError("output paths must be distinct")
    existing = [str(path) for path in paths if path is not None and path.exists()]
    if existing:
        raise SemanticEvaluationError(
            "refusing to overwrite existing outputs: " + ", ".join(existing)
        )


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SemanticEvaluationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SemanticEvaluationError(f"JSON {path} must contain an object")
    return value


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    *,
    fieldnames: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise SemanticEvaluationError(f"CSV has no header: {path}")
            return [dict(row) for row in reader]
    except OSError as exc:
        raise SemanticEvaluationError(f"cannot read CSV {path}: {exc}") from exc


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise SemanticEvaluationError(
                    f"{path}:{line_no} must contain a JSON object"
                )
            rows.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise SemanticEvaluationError(f"cannot read JSONL {path}: {exc}") from exc
    return rows


def _verify_manifest_output(
    manifest: Mapping[str, object],
    target_path: Path,
) -> None:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise SemanticEvaluationError("label manifest has no outputs")
    resolved_target = target_path.resolve()
    matches = [
        row
        for row in outputs
        if isinstance(row, Mapping)
        and Path(str(row.get("path") or "")).resolve() == resolved_target
    ]
    if len(matches) != 1:
        raise SemanticEvaluationError(
            f"label manifest does not bind exactly one output for {resolved_target}"
        )
    expected = str(matches[0].get("sha256") or "")
    actual = sha256_file(target_path)
    if not expected or actual != expected:
        raise SemanticEvaluationError(
            f"label manifest hash mismatch for {resolved_target}: "
            f"expected {expected or '<missing>'}, actual {actual}"
        )


def _verify_label_manifest(
    manifest_path: Path,
    *,
    sample_path: Path,
    predictions_path: Path,
    canary_key_path: Path,
) -> None:
    manifest = _read_json(manifest_path)
    if manifest.get("manifest_version") != "semantic-discovery-label-batch-v1":
        raise SemanticEvaluationError("label manifest has an invalid version")
    if str(manifest.get("sample_sha256") or "") != sha256_file(sample_path):
        raise SemanticEvaluationError("label manifest sample hash mismatch")
    if manifest.get("human_label_files_contain_system_predictions") is not False:
        raise SemanticEvaluationError(
            "label manifest must keep system predictions out of human files"
        )
    if manifest.get("canary_key_outside_human_review_folder") is not True:
        raise SemanticEvaluationError(
            "label manifest does not prove canary-key separation"
        )
    _verify_manifest_output(manifest, predictions_path)
    _verify_manifest_output(manifest, canary_key_path)


def _freeze(args: argparse.Namespace) -> int:
    if not 60 <= args.sample_size <= 100:
        raise SemanticEvaluationError("--sample-size must be within 60..100")
    _refuse_overwrite((args.output,))
    seeds, counts = load_no_oe_catalog_seeds(
        args.master_workbook,
        args.source_workbook,
        limit=100_000,
    )
    planning_rows: list[dict[str, object]] = []
    for seed in seeds:
        profile = build_seed_profile(seed)
        plan = build_query_plan(seed, profile)
        family = profile["features"]["part_family"]["values"]
        planning_rows.append(
            {
                "row_id": seed.row_id,
                "title": seed.title,
                "category": seed.category,
                "part_family": "|".join(str(value) for value in family),
                "no_oe_reason": seed.no_oe_reason,
                "product_url": seed.product_url,
                "description_available": bool(seed.description),
                "characteristics_available": bool(seed.characteristics),
                "source_image_count": len(seed.image_urls),
                "profile_sha256": _canonical_sha256(profile),
                "query_plan": plan,
                "query_plan_sha256": _canonical_sha256(plan),
            }
        )
    selected = build_stratified_sample(
        planning_rows,
        sample_size=args.sample_size,
        selection_seed=args.selection_seed,
    )
    batches = [
        {
            "batch_no": index // MAX_SEEDS_PER_RUN + 1,
            "row_ids": [
                str(row["row_id"])
                for row in selected[index : index + MAX_SEEDS_PER_RUN]
            ],
        }
        for index in range(0, len(selected), MAX_SEEDS_PER_RUN)
    ]
    stable_manifest: dict[str, Any] = {
        "schema_version": SAMPLE_SCHEMA_VERSION,
        "selection": {
            "algorithm": "category-part-family-round-robin-sha256-v1",
            "selection_seed_sha256": hashlib.sha256(
                args.selection_seed.encode("utf-8")
            ).hexdigest(),
            "population": len(planning_rows),
            "sample_size": len(selected),
            "mandatory_row_ids": list(MANDATORY_UNTYPED_ROW_IDS),
        },
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
        "rows": list(selected),
        "live_batches": batches,
        "live_requests": 0,
        "luna_calls": 0,
        "database_writes": 0,
        "automatic_identity_admission": 0,
        "automatic_pricing_admission": 0,
    }
    payload = {
        **stable_manifest,
        "created_at": datetime.now(UTC).isoformat(),
        "sample_manifest_sha256": _canonical_sha256(stable_manifest),
    }
    _write_json(args.output, payload)
    print(args.output.resolve())
    print(
        f"sha256={sha256_file(args.output)} rows={len(selected)} batches={len(batches)}"
    )
    return 0


def _verify_run_manifest(run_dir: Path) -> dict[str, Any]:
    root = run_dir.resolve()
    manifest = _read_json(root / "artifact_manifest.json")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise SemanticEvaluationError(f"run manifest has no artifacts: {root}")
    mismatches: list[str] = []
    for item in artifacts:
        if not isinstance(item, Mapping):
            mismatches.append("<invalid-manifest-row>")
            continue
        path = root / str(item.get("path") or "")
        expected = str(item.get("sha256") or "")
        if not path.is_file() or sha256_file(path) != expected:
            mismatches.append(str(item.get("path") or ""))
    if mismatches:
        raise SemanticEvaluationError(
            f"run artifact hash mismatch in {root}: {', '.join(mismatches[:10])}"
        )
    summary = _read_json(root / "summary.json")
    if sha256_file(root / "summary.json") != str(manifest.get("summary_sha256") or ""):
        raise SemanticEvaluationError(f"summary hash mismatch in {root}")
    return summary


def _duration_seconds(summary: Mapping[str, object]) -> Decimal:
    try:
        started = datetime.fromisoformat(str(summary.get("started_at") or ""))
        finished = datetime.fromisoformat(str(summary.get("finished_at") or ""))
    except ValueError as exc:
        raise SemanticEvaluationError("run summary has invalid timestamps") from exc
    return Decimal(str(max(0.0, (finished - started).total_seconds())))


def candidate_image_available(images: Sequence[Mapping[str, object]]) -> bool:
    """Require a frozen candidate image; the always-present seed image is not enough."""

    return any(
        str(image.get("role") or "").strip().upper() == "CANDIDATE"
        and bool(str(image.get("sha256") or "").strip())
        for image in images
    )


def _prepare_labels(args: argparse.Namespace) -> int:
    _refuse_overwrite(
        (
            args.seed_labels_out,
            args.candidate_labels_out,
            args.system_predictions_out,
            args.canary_key_out,
            args.manifest_out,
        )
    )
    if (
        args.canary_key_out.resolve().parent
        == args.candidate_labels_out.resolve().parent
    ):
        raise SemanticEvaluationError(
            "the semantic canary answer key must be outside the human review folder"
        )
    sample = _read_json(args.sample)
    sample_rows = sample.get("rows")
    if sample.get("schema_version") != SAMPLE_SCHEMA_VERSION or not isinstance(
        sample_rows, list
    ):
        raise SemanticEvaluationError("sample has an invalid schema")
    sample_by_id = {
        str(row.get("row_id") or ""): row
        for row in sample_rows
        if isinstance(row, Mapping)
    }
    seed_runtime: dict[str, dict[str, Any]] = {
        row_id: {
            "collection_attempted": False,
            "detail_card_available": False,
            "usable_image_available": False,
            "seller_ids": set(),
            "http_request_count": 0,
            "luna_call_count": 0,
            "runtime_seconds": Decimal("0"),
        }
        for row_id in sample_by_id
    }
    candidate_evidence: dict[tuple[str, str], dict[str, Any]] = {}
    system_predictions: dict[tuple[str, str], dict[str, Any]] = {}
    run_manifest_rows: list[dict[str, Any]] = []
    run_coverage_batches: list[dict[str, Any]] = []

    for raw_dir in args.run_dir:
        root = raw_dir.resolve()
        summary = _verify_run_manifest(root)
        profiles = _jsonl(root / "seed_profiles.jsonl")
        profile_ids = tuple(str(row.get("row_id") or "") for row in profiles)
        run_coverage_batches.append(
            {
                "row_ids": profile_ids,
                "selected_seeds": summary.get("selected_seeds"),
                "live": summary.get("live"),
                "run_luna": summary.get("run_luna"),
                "run_status": summary.get("run_status"),
            }
        )
        selected_count = int(summary.get("selected_seeds") or 0)
        runtime_share = (
            _duration_seconds(summary) / Decimal(selected_count)
            if selected_count > 0
            else Decimal("0")
        )
        candidates = {
            (str(row.get("row_id") or ""), str(row.get("candidate_key") or "")): row
            for row in _jsonl(root / "candidates_non_monetary.jsonl")
        }
        verdicts = _jsonl(root / "deterministic_verdicts.jsonl")
        predictions = {
            (str(row.get("row_id") or ""), str(row.get("candidate_key") or "")): row
            for row in _jsonl(root / "luna/predictions.jsonl")
        }
        raw_manifest = _jsonl(root / "raw_http_manifest.jsonl")
        images = _jsonl(root / "images/image_manifest.jsonl")
        artifact_seed_ids = {
            str(row.get("row_id") or "")
            for row in verdicts
            if str(row.get("row_id") or "")
        }
        artifact_seed_ids.update(
            str(row.get("row_id") or "")
            for row in raw_manifest
            if str(row.get("row_id") or "")
        )
        if artifact_seed_ids - set(profile_ids):
            raise SemanticEvaluationError(
                f"run artifacts reference a seed absent from profiles: {root}"
            )
        for row_id in profile_ids:
            if row_id in seed_runtime:
                seed_runtime[row_id]["collection_attempted"] = True
            else:
                raise SemanticEvaluationError(
                    f"run profile references a seed outside the frozen sample: {row_id}"
                )
            seed_runtime[row_id]["runtime_seconds"] += runtime_share
        for row in raw_manifest:
            row_id = str(row.get("row_id") or "")
            if row_id in seed_runtime:
                seed_runtime[row_id]["http_request_count"] += 1
        for image in images:
            row_id = str(image.get("row_id") or "")
            if row_id in seed_runtime and candidate_image_available((image,)):
                seed_runtime[row_id]["usable_image_available"] = True
        for row in verdicts:
            row_id = str(row.get("row_id") or "")
            candidate_key = str(row.get("candidate_key") or "")
            if row_id not in sample_by_id or not candidate_key:
                continue
            key = (row_id, candidate_key)
            candidate_row = candidates.get(key, {})
            candidate = candidate_row.get("candidate")
            candidate = candidate if isinstance(candidate, Mapping) else {}
            assessment = row.get("assessment")
            assessment = assessment if isinstance(assessment, Mapping) else {}
            disposition = str(assessment.get("disposition") or "")
            prediction = predictions.get(key)
            output = prediction.get("validated_output") if prediction else None
            luna_verdict = (
                str(output.get("verdict") or "")
                if isinstance(output, Mapping)
                else "NOT_RUN"
            )
            runner = prediction.get("runner") if prediction else None
            attempts = (
                int(runner.get("attempt_count") or 0)
                if isinstance(runner, Mapping)
                else 0
            )
            seed_runtime[row_id]["luna_call_count"] += attempts
            seller_id = str(row.get("seller_id") or candidate.get("seller_id") or "")
            if disposition != "OWNED_SELLER_EXCLUDED" and seller_id:
                seed_runtime[row_id]["seller_ids"].add(seller_id)
            detail = candidate.get("detail_evidence")
            if detail:
                seed_runtime[row_id]["detail_card_available"] = True
            candidate_row = {
                "row_id": row_id,
                "candidate_key": candidate_key,
                "seed_title": sample_by_id[row_id].get("title", ""),
                "seed_category": sample_by_id[row_id].get("category", ""),
                "candidate_title": row.get("candidate_name")
                or candidate.get("name")
                or "",
                "candidate_url": row.get("candidate_url") or candidate.get("url") or "",
                "candidate_seller": candidate.get("seller_name") or "",
                "candidate_description": candidate.get("description") or "",
                "candidate_image": candidate.get("image") or "",
                "human_identity_truth": "",
                "evidence_notes": "",
            }
            candidate_row["evidence_sha256"] = semantic_candidate_evidence_sha256(
                candidate_row
            )
            candidate_evidence[key] = candidate_row
            system_predictions[key] = {
                "row_id": row_id,
                "candidate_key": candidate_key,
                "deterministic_disposition": disposition,
                "luna_verdict": luna_verdict,
            }
        run_manifest_rows.append(
            {
                "path": str(root),
                "artifact_manifest_sha256": sha256_file(
                    root / "artifact_manifest.json"
                ),
                "run_status": summary.get("run_status"),
                "selected_seed_count": len(profile_ids),
            }
        )

    run_coverage = validate_frozen_run_coverage(
        set(sample_by_id),
        run_coverage_batches,
    )

    seed_rows = []
    for row_id, sample_row in sample_by_id.items():
        runtime = seed_runtime[row_id]
        seed_row = {
            "row_id": row_id,
            "title": sample_row.get("title", ""),
            "category": sample_row.get("category", ""),
            "collection_attempted": str(runtime["collection_attempted"]).lower(),
            "correct_candidate_retrieved": "",
            "review_complete": "",
            "detail_card_available": str(runtime["detail_card_available"]).lower(),
            "usable_image_available": str(runtime["usable_image_available"]).lower(),
            "independent_seller_count": len(runtime["seller_ids"]),
            "http_request_count": runtime["http_request_count"],
            "luna_call_count": runtime["luna_call_count"],
            "runtime_seconds": str(
                runtime["runtime_seconds"].quantize(Decimal("0.001"))
            ),
            "evidence_notes": "",
        }
        seed_row["evidence_sha256"] = semantic_seed_evidence_sha256(seed_row)
        seed_rows.append(seed_row)
    regular_candidate_rows = [
        candidate_evidence[key] for key in sorted(candidate_evidence)
    ]
    prediction_rows = [system_predictions[key] for key in sorted(system_predictions)]
    canary_rows, canary_key = build_semantic_review_canaries(
        _read_csv(args.canary_source_csv),
        selection_seed=str(sample.get("sample_manifest_sha256") or ""),
    )
    candidate_rows = sorted(
        [*regular_candidate_rows, *canary_rows],
        key=lambda row: hashlib.sha256(
            (
                f"{sample.get('sample_manifest_sha256')}\0"
                f"{row.get('row_id')}\0{row.get('candidate_key')}"
            ).encode("utf-8")
        ).hexdigest(),
    )
    _write_csv(
        args.seed_labels_out,
        seed_rows,
        fieldnames=SEMANTIC_SEED_REVIEW_FIELDS,
    )
    _write_csv(
        args.candidate_labels_out,
        candidate_rows,
        fieldnames=SEMANTIC_REVIEW_CANARY_FIELDS,
    )
    prediction_payload = {
        "schema_version": "semantic-discovery-system-predictions-v1",
        "contains_human_truth": False,
        "rows": prediction_rows,
    }
    _write_json(args.system_predictions_out, prediction_payload)
    _write_json(args.canary_key_out, canary_key)
    outputs = [
        args.seed_labels_out,
        args.candidate_labels_out,
        args.system_predictions_out,
        args.canary_key_out,
    ]
    if args.manifest_out is not None:
        _write_json(
            args.manifest_out,
            {
                "manifest_version": "semantic-discovery-label-batch-v1",
                "sample_sha256": sha256_file(args.sample),
                "canary_source": {
                    "path": str(args.canary_source_csv.resolve()),
                    "sha256": sha256_file(args.canary_source_csv),
                },
                "run_manifests": run_manifest_rows,
                "run_coverage": run_coverage,
                "outputs": [
                    {"path": str(path.resolve()), "sha256": sha256_file(path)}
                    for path in outputs
                ],
                "human_label_files_contain_system_predictions": False,
                "contains_prices": False,
                "canary_count": len(canary_rows),
                "canary_key_outside_human_review_folder": True,
            },
        )
    print(
        f"seed_rows={len(seed_rows)} candidate_rows={len(candidate_rows)} "
        f"canaries={len(canary_rows)} runs={len(args.run_dir)}"
    )
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    _refuse_overwrite((args.output,))
    _verify_label_manifest(
        args.label_manifest,
        sample_path=args.sample,
        predictions_path=args.system_predictions,
        canary_key_path=args.canary_key,
    )
    sample = _read_json(args.sample)
    sample_rows = sample.get("rows")
    if sample.get("schema_version") != SAMPLE_SCHEMA_VERSION or not isinstance(
        sample_rows, list
    ):
        raise SemanticEvaluationError("sample has an invalid schema")
    sample_ids = {
        str(row.get("row_id") or "") for row in sample_rows if isinstance(row, Mapping)
    }
    seed_labels = _read_csv(args.seed_labels)
    if (
        len(seed_labels) != len(sample_ids)
        or {str(row.get("row_id") or "") for row in seed_labels} != sample_ids
    ):
        raise SemanticEvaluationError(
            "seed labels do not cover the frozen sample exactly"
        )
    candidate_labels = _read_csv(args.candidate_labels)
    evidence_result = verify_semantic_review_evidence(
        seed_labels,
        candidate_labels,
    )
    if evidence_result["status"] != "PASS":
        _write_json(
            args.output,
            {
                "schema_version": "semantic-discovery-without-oe-evaluation-v1",
                "measurement_complete": False,
                "decision": "MEASUREMENT_INCOMPLETE",
                "evidence_verification": evidence_result,
                "automatic_identity_admission": 0,
                "automatic_pricing_admission": 0,
            },
        )
        return 1
    canary_key = _read_json(args.canary_key)
    canary_result = verify_semantic_review_canaries(candidate_labels, canary_key)
    raw_canaries = canary_key.get("canaries")
    if not isinstance(raw_canaries, list):
        raise SemanticEvaluationError("semantic canary key has an invalid schema")
    canary_pairs = {
        (
            str(row.get("row_id") or ""),
            str(row.get("opaque_candidate_key") or ""),
        )
        for row in raw_canaries
        if isinstance(row, Mapping)
    }
    candidate_labels_for_metrics = [
        row
        for row in candidate_labels
        if (
            str(row.get("row_id") or ""),
            str(row.get("candidate_key") or ""),
        )
        not in canary_pairs
    ]
    predictions = _read_json(args.system_predictions)
    if predictions.get("contains_human_truth") is not False:
        raise SemanticEvaluationError(
            "system predictions must explicitly exclude human truth"
        )
    prediction_rows = predictions.get("rows")
    if not isinstance(prediction_rows, list):
        raise SemanticEvaluationError("system predictions have an invalid schema")
    prediction_map = {
        (str(row.get("row_id") or ""), str(row.get("candidate_key") or "")): row
        for row in prediction_rows
        if isinstance(row, Mapping)
    }
    if len(prediction_map) != len(prediction_rows):
        raise SemanticEvaluationError(
            "system predictions contain invalid or duplicate pair keys"
        )
    label_map = {
        (str(row.get("row_id") or ""), str(row.get("candidate_key") or "")): row
        for row in candidate_labels_for_metrics
    }
    if len(label_map) != len(candidate_labels_for_metrics):
        raise SemanticEvaluationError(
            "candidate truth rows contain duplicate pair keys"
        )
    if set(label_map) != set(prediction_map):
        raise SemanticEvaluationError(
            "candidate truth rows and system predictions have different pair keys"
        )
    combined = []
    for key in sorted(label_map):
        label = label_map[key]
        prediction = prediction_map[key]
        truth = str(label.get("human_identity_truth") or "").strip().upper()
        verdict = str(prediction.get("luna_verdict") or "").strip().upper()
        combined.append(
            {
                "row_id": key[0],
                "candidate_key": key[1],
                "human_identity_truth": truth,
                "deterministic_disposition": prediction.get(
                    "deterministic_disposition"
                ),
                "luna_verdict": verdict,
                "critical_false_accept": verdict == "MATCH" and truth == "NOT_MATCH",
            }
        )
    result = evaluate_semantic_discovery_gate(seed_labels, combined)
    result["evidence_verification"] = evidence_result
    result["canary_verification"] = canary_result
    if canary_result["status"] != "PASS":
        result["measurement_complete_before_canary_check"] = result[
            "measurement_complete"
        ]
        result["measurement_complete"] = False
        result["decision"] = "MEASUREMENT_INCOMPLETE"
    result["provenance"] = {
        "sample_path": str(args.sample.resolve()),
        "sample_sha256": sha256_file(args.sample),
        "seed_labels_sha256": sha256_file(args.seed_labels),
        "candidate_labels_sha256": sha256_file(args.candidate_labels),
        "system_predictions_sha256": sha256_file(args.system_predictions),
        "canary_key_sha256": sha256_file(args.canary_key),
        "label_manifest_sha256": sha256_file(args.label_manifest),
    }
    _write_json(args.output, result)
    print(args.output.resolve())
    return 0 if result["decision"] != "MEASUREMENT_INCOMPLETE" else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "freeze":
            return _freeze(args)
        if args.command == "prepare-labels":
            return _prepare_labels(args)
        return _evaluate(args)
    except (SemanticEvaluationError, FileNotFoundError, ValueError) as exc:
        print(f"semantic evaluation error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
