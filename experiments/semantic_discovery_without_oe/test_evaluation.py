from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from evaluation import (
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
    verify_semantic_review_evidence,
    verify_semantic_review_canaries,
)
from evaluation_cli import candidate_image_available, main as evaluation_main


def test_stratified_sample_is_deterministic_and_forces_untyped_canaries() -> None:
    rows = [
        {
            "row_id": str(index),
            "category": f"category-{index % 4}",
            "part_family": f"family-{index % 5}",
            "title": f"Product {index}",
        }
        for index in range(1, 31)
    ]
    rows.extend(
        (
            {
                "row_id": "1230665005",
                "category": "untyped",
                "part_family": "",
                "title": "Защита",
            },
            {
                "row_id": "2179741467",
                "category": "untyped",
                "part_family": "",
                "title": "Прикуриватель в сборе Daewoo Lanos",
            },
        )
    )

    first = build_stratified_sample(rows, sample_size=12, selection_seed="gate-v1")
    second = build_stratified_sample(rows, sample_size=12, selection_seed="gate-v1")

    assert first == second
    assert len(first) == 12
    assert {"1230665005", "2179741467"}.issubset({row["row_id"] for row in first})
    assert len({row["category"] for row in first}) >= 4


def test_image_availability_requires_a_frozen_candidate_image() -> None:
    assert (
        candidate_image_available(
            ({"role": "OUR_PRODUCT", "sha256": "a" * 64},)
        )
        is False
    )
    assert (
        candidate_image_available(
            (
                {"role": "OUR_PRODUCT", "sha256": "a" * 64},
                {"role": "CANDIDATE", "sha256": "b" * 64},
            )
        )
        is True
    )


def test_gate_reports_all_six_measurements_and_stays_non_admitting() -> None:
    seed_labels = (
        {
            "row_id": "seed-1",
            "collection_attempted": True,
            "correct_candidate_retrieved": "YES",
            "review_complete": True,
            "detail_card_available": True,
            "usable_image_available": True,
            "independent_seller_count": 2,
            "http_request_count": 4,
            "luna_call_count": 1,
            "runtime_seconds": 12.5,
        },
        {
            "row_id": "seed-2",
            "collection_attempted": True,
            "correct_candidate_retrieved": "NO",
            "review_complete": True,
            "detail_card_available": False,
            "usable_image_available": False,
            "independent_seller_count": 0,
            "http_request_count": 2,
            "luna_call_count": 1,
            "runtime_seconds": 8.5,
        },
    )
    candidate_labels = (
        {
            "row_id": "seed-1",
            "candidate_key": "true",
            "human_identity_truth": "MATCH",
            "deterministic_disposition": "SEMANTIC_NEEDS_LUNA",
            "luna_verdict": "MATCH",
            "critical_false_accept": False,
        },
        {
            "row_id": "seed-1",
            "candidate_key": "false",
            "human_identity_truth": "NOT_MATCH",
            "deterministic_disposition": "SEMANTIC_NOT_MATCH",
            "luna_verdict": "NOT_RUN",
            "critical_false_accept": False,
        },
        {
            "row_id": "seed-2",
            "candidate_key": "unknown",
            "human_identity_truth": "NOT_MATCH",
            "deterministic_disposition": "SEMANTIC_NEEDS_LUNA",
            "luna_verdict": "MANUAL_REVIEW",
            "critical_false_accept": False,
        },
    )

    report = evaluate_semantic_discovery_gate(seed_labels, candidate_labels)

    assert report["retrieval"]["seed_recall"] == "0.500000"
    assert report["deterministic_rejections"]["precision"] == "1.000000"
    assert report["deterministic_rejections"]["false_reject_count"] == 0
    assert report["luna"]["false_accept_count"] == 0
    assert report["luna"]["abstention_rate"] == "0.500000"
    assert report["evidence_availability"]["detail_card_rate"] == "0.500000"
    assert report["evidence_availability"]["usable_image_rate"] == "0.500000"
    assert report["independent_sellers"]["seed_coverage_rate"] == "0.500000"
    assert report["budgets"]["http_requests_total"] == 6
    assert report["budgets"]["luna_calls_total"] == 2
    assert report["budgets"]["runtime_seconds_total"] == "21.000"
    assert report["automatic_identity_admission"] == 0
    assert report["automatic_pricing_admission"] == 0
    assert report["decision"] == "OPERATOR_DECISION_REQUIRED"


def test_any_critical_false_accept_forces_manual_tool_decision() -> None:
    report = evaluate_semantic_discovery_gate(
        (
            {
                "row_id": "seed",
                "collection_attempted": True,
                "correct_candidate_retrieved": "YES",
                "review_complete": True,
                "detail_card_available": True,
                "usable_image_available": True,
                "independent_seller_count": 1,
                "http_request_count": 1,
                "luna_call_count": 1,
                "runtime_seconds": 1,
            },
        ),
        (
            {
                "row_id": "seed",
                "candidate_key": "bad",
                "human_identity_truth": "NOT_MATCH",
                "deterministic_disposition": "SEMANTIC_NEEDS_LUNA",
                "luna_verdict": "MATCH",
                "critical_false_accept": True,
            },
        ),
    )

    assert report["luna"]["false_accept_count"] == 1
    assert report["critical_false_accept_count"] == 1
    assert report["decision"] == "LEAVE_AS_MANUAL_TOOL"
    assert report["automatic_identity_admission"] == 0
    assert report["automatic_pricing_admission"] == 0


def test_semantic_human_review_canary_is_blinded_and_verified_separately() -> None:
    canary_rows, key = build_semantic_review_canaries(
        (
            {
                "canary_id": "known-negative",
                "row_id": "seed-canary",
                "seed_title": "Known seed",
                "seed_category": "test",
                "candidate_title": "Known wrong candidate",
                "candidate_url": "https://example.test/canary",
                "candidate_description": "Ціна 1 250 грн; тип масляний",
                "price": "1250",
                "characteristics": [
                    {"name": "Ціна", "value": "1250"},
                    {"name": "Тип", "value": "Масляний"},
                ],
                "expected_identity_truth": "NOT_MATCH",
            },
        ),
        selection_seed="semantic-review-v1",
    )

    assert len(canary_rows) == 1
    assert "canary_id" not in canary_rows[0]
    assert "expected_identity_truth" not in canary_rows[0]
    assert canary_rows[0]["human_identity_truth"] == ""
    assert key["canaries"][0]["canary_id"] == "known-negative"
    assert len(canary_rows[0]["evidence_sha256"]) == 64
    rendered = json.dumps(canary_rows, ensure_ascii=False).casefold()
    assert "1250" not in rendered
    assert "1 250 грн" not in rendered
    assert "<price_redacted>" in rendered

    labelled = [{**canary_rows[0], "human_identity_truth": "NOT_MATCH"}]
    passed = verify_semantic_review_canaries(labelled, key)
    failed = verify_semantic_review_canaries(
        [{**canary_rows[0], "human_identity_truth": "MATCH"}],
        key,
    )

    assert passed["status"] == "PASS"
    assert failed["status"] == "FAIL"

    evidence_pass = verify_semantic_review_evidence((), canary_rows)
    evidence_fail = verify_semantic_review_evidence(
        (),
        ({**canary_rows[0], "candidate_title": "tampered"},),
    )
    assert evidence_pass["status"] == "PASS"
    assert evidence_fail["status"] == "FAIL"


def test_frozen_run_coverage_requires_exact_successful_live_luna_partition() -> None:
    batches = (
        {
            "row_ids": ("seed-1", "seed-2"),
            "selected_seeds": 2,
            "live": True,
            "run_luna": True,
            "run_status": "COMPLETED",
        },
        {
            "row_ids": ("seed-3",),
            "selected_seeds": 1,
            "live": True,
            "run_luna": True,
            "run_status": "COMPLETED",
        },
    )

    result = validate_frozen_run_coverage(
        {"seed-1", "seed-2", "seed-3"},
        batches,
    )

    assert result["status"] == "PASS"
    assert result["covered_seeds"] == 3

    with pytest.raises(SemanticEvaluationError, match="overlap"):
        validate_frozen_run_coverage(
            {"seed-1", "seed-2"},
            (
                batches[0],
                {**batches[1], "row_ids": ("seed-2",)},
            ),
        )
    with pytest.raises(SemanticEvaluationError, match="not COMPLETED"):
        validate_frozen_run_coverage(
            {"seed-1", "seed-2"},
            ({**batches[0], "run_status": "COMPLETED_WITH_ERRORS"},),
        )


def _write_csv(
    path: Path,
    rows: list[dict[str, str]],
    fieldnames: tuple[str, ...],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_evaluation_cli_keeps_canaries_out_of_six_metric_score(
    tmp_path: Path,
) -> None:
    sample_path = tmp_path / "sample.json"
    seed_path = tmp_path / "seeds.csv"
    candidate_path = tmp_path / "candidates.csv"
    predictions_path = tmp_path / "predictions.json"
    canary_key_path = tmp_path / "canary-key.json"
    label_manifest_path = tmp_path / "label-manifest.json"
    output_path = tmp_path / "evaluation.json"
    sample_path.write_text(
        json.dumps(
            {
                "schema_version": SAMPLE_SCHEMA_VERSION,
                "rows": [{"row_id": "seed-1"}, {"row_id": "seed-2"}],
            }
        ),
        encoding="utf-8",
    )
    seed_rows = [
        {
            "row_id": "seed-1",
            "title": "Seed one",
            "category": "A",
            "collection_attempted": "true",
            "correct_candidate_retrieved": "YES",
            "review_complete": "true",
            "detail_card_available": "true",
            "usable_image_available": "true",
            "independent_seller_count": "1",
            "http_request_count": "3",
            "luna_call_count": "0",
            "runtime_seconds": "1.0",
            "evidence_notes": "",
        },
        {
            "row_id": "seed-2",
            "title": "Seed two",
            "category": "B",
            "collection_attempted": "true",
            "correct_candidate_retrieved": "NO",
            "review_complete": "true",
            "detail_card_available": "true",
            "usable_image_available": "false",
            "independent_seller_count": "1",
            "http_request_count": "2",
            "luna_call_count": "1",
            "runtime_seconds": "1.5",
            "evidence_notes": "",
        },
    ]
    for row in seed_rows:
        row["evidence_sha256"] = semantic_seed_evidence_sha256(row)
    regular_candidates = [
        {
            "row_id": "seed-1",
            "candidate_key": "candidate-rejected",
            "seed_title": "Seed one",
            "seed_category": "A",
            "candidate_title": "Wrong candidate",
            "candidate_url": "https://example.test/rejected",
            "candidate_seller": "Seller A",
            "candidate_description": "",
            "candidate_image": "",
            "human_identity_truth": "NOT_MATCH",
            "evidence_notes": "",
        },
        {
            "row_id": "seed-2",
            "candidate_key": "candidate-luna",
            "seed_title": "Seed two",
            "seed_category": "B",
            "candidate_title": "Uncertain candidate",
            "candidate_url": "https://example.test/luna",
            "candidate_seller": "Seller B",
            "candidate_description": "",
            "candidate_image": "",
            "human_identity_truth": "NOT_MATCH",
            "evidence_notes": "",
        },
    ]
    for row in regular_candidates:
        row["evidence_sha256"] = semantic_candidate_evidence_sha256(row)
    canary_rows, canary_key = build_semantic_review_canaries(
        (
            {
                "canary_id": "known-negative",
                "row_id": "canary-seed",
                "seed_title": "Known seed",
                "seed_category": "canary",
                "candidate_title": "Known wrong",
                "candidate_url": "https://example.test/canary",
                "expected_identity_truth": "NOT_MATCH",
            },
        ),
        selection_seed="cli-evaluation-v1",
    )
    labelled_canary = {**canary_rows[0], "human_identity_truth": "NOT_MATCH"}
    _write_csv(seed_path, seed_rows, SEMANTIC_SEED_REVIEW_FIELDS)
    _write_csv(
        candidate_path,
        [*regular_candidates, labelled_canary],
        SEMANTIC_REVIEW_CANARY_FIELDS,
    )
    predictions_path.write_text(
        json.dumps(
            {
                "contains_human_truth": False,
                "rows": [
                    {
                        "row_id": "seed-1",
                        "candidate_key": "candidate-rejected",
                        "deterministic_disposition": "SEMANTIC_NOT_MATCH",
                        "luna_verdict": "NOT_RUN",
                    },
                    {
                        "row_id": "seed-2",
                        "candidate_key": "candidate-luna",
                        "deterministic_disposition": "SEMANTIC_NEEDS_LUNA",
                        "luna_verdict": "MANUAL_REVIEW",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    canary_key_path.write_text(json.dumps(canary_key), encoding="utf-8")
    label_manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": "semantic-discovery-label-batch-v1",
                "sample_sha256": hashlib.sha256(sample_path.read_bytes()).hexdigest(),
                "outputs": [
                    {
                        "path": str(predictions_path.resolve()),
                        "sha256": hashlib.sha256(
                            predictions_path.read_bytes()
                        ).hexdigest(),
                    },
                    {
                        "path": str(canary_key_path.resolve()),
                        "sha256": hashlib.sha256(
                            canary_key_path.read_bytes()
                        ).hexdigest(),
                    },
                ],
                "human_label_files_contain_system_predictions": False,
                "canary_key_outside_human_review_folder": True,
            }
        ),
        encoding="utf-8",
    )

    exit_code = evaluation_main(
        [
            "evaluate",
            "--sample",
            str(sample_path),
            "--seed-labels",
            str(seed_path),
            "--candidate-labels",
            str(candidate_path),
            "--system-predictions",
            str(predictions_path),
            "--canary-key",
            str(canary_key_path),
            "--label-manifest",
            str(label_manifest_path),
            "--output",
            str(output_path),
        ]
    )

    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert result["measurement_complete"] is True
    assert result["candidate_count"] == 2
    assert result["canary_verification"]["status"] == "PASS"
    assert result["evidence_verification"]["status"] == "PASS"
    assert result["decision"] == "OPERATOR_DECISION_REQUIRED"
    assert result["automatic_identity_admission"] == 0
    assert result["automatic_pricing_admission"] == 0

    predictions_path.write_text('{"contains_human_truth": false, "rows": []}')
    tampered_output = tmp_path / "tampered-evaluation.json"
    tampered_exit = evaluation_main(
        [
            "evaluate",
            "--sample",
            str(sample_path),
            "--seed-labels",
            str(seed_path),
            "--candidate-labels",
            str(candidate_path),
            "--system-predictions",
            str(predictions_path),
            "--canary-key",
            str(canary_key_path),
            "--label-manifest",
            str(label_manifest_path),
            "--output",
            str(tampered_output),
        ]
    )
    assert tampered_exit == 2
    assert not tampered_output.exists()
