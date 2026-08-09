from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from marko.market_funnel_cli import _refuse_overwrite, _write_csv, main
from marko.services.market_funnel import (
    MARKET_REVIEW_SOURCE_FIELDS,
    MarketFunnelError,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_empty_review_pool_is_written_as_a_header_only_artifact(
    tmp_path: Path,
) -> None:
    output = tmp_path / "empty-review-pool.csv"

    _write_csv(output, (), fieldnames=MARKET_REVIEW_SOURCE_FIELDS)

    with output.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows == [list(MARKET_REVIEW_SOURCE_FIELDS)]


def test_output_paths_must_be_distinct_even_before_they_exist(
    tmp_path: Path,
) -> None:
    output = tmp_path / "same-output.json"

    with pytest.raises(MarketFunnelError, match="distinct"):
        _refuse_overwrite((output, output))


def test_score_review_accepts_only_complete_biclass_batch_with_valid_canary(
    tmp_path: Path,
) -> None:
    tasks = []
    predictions = []
    for index in range(149):
        pair_id = f"observation-{index:03d}"
        truth = "MATCH" if index % 2 == 0 else "NOT_MATCH"
        admission = "ADMITTED" if truth == "MATCH" else "EXCLUDED"
        tasks.append(
            {
                "review_id": f"LR-{index:03d}",
                "source_refs": [{"source_rank": pair_id}],
                "labels": {
                    "identity_truth": truth,
                    "pricing_admission_truth": admission,
                },
            }
        )
        predictions.append(
            {
                "pair_id": pair_id,
                "identity_verdict": truth,
                "pricing_admission": admission,
                "review_status": "COMPLETED",
            }
        )
    tasks.append(
        {
            "review_id": "LR-canary",
            "source_refs": [{"source_rank": "opaque-canary"}],
            "labels": {
                "identity_truth": "NOT_MATCH",
                "pricing_admission_truth": "EXCLUDED",
            },
        }
    )
    reviewed_path = tmp_path / "reviewed.json"
    predictions_path = tmp_path / "predictions.json"
    key_path = tmp_path / "canary-key.json"
    report_manifest_path = tmp_path / "report-manifest.json"
    batch_manifest_path = tmp_path / "batch-manifest.json"
    output_path = tmp_path / "score.json"
    _write_json(reviewed_path, {"tasks": tasks})
    _write_json(predictions_path, {"pairs": predictions})
    _write_json(
        key_path,
        {
            "canaries": [
                {
                    "opaque_source_rank": "opaque-canary",
                    "expected_identity_truth": "NOT_MATCH",
                    "expected_pricing_admission_truth": "EXCLUDED",
                }
            ]
        },
    )
    _write_json(
        report_manifest_path,
        {
            "manifest_version": "oe-market-funnel-manifest-v1",
            "outputs": [
                {
                    "path": str(predictions_path.resolve()),
                    "sha256": hashlib.sha256(predictions_path.read_bytes()).hexdigest(),
                }
            ],
        },
    )
    _write_json(
        batch_manifest_path,
        {
            "manifest_version": "oe-market-review-batch-v1",
            "outputs": [
                {
                    "path": str(key_path.resolve()),
                    "sha256": hashlib.sha256(key_path.read_bytes()).hexdigest(),
                }
            ],
        },
    )

    exit_code = main(
        [
            "score-review",
            "--reviewed-set",
            str(reviewed_path),
            "--predictions",
            str(predictions_path),
            "--canary-key",
            str(key_path),
            "--report-manifest",
            str(report_manifest_path),
            "--review-batch-manifest",
            str(batch_manifest_path),
            "--output",
            str(output_path),
        ]
    )

    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert result["review_batch_accepted"] is True
    assert result["canaries"]["status"] == "PASS"
    assert result["model_score"]["review_batch_size_valid"] is True
    assert result["model_score"]["human_class_coverage_complete"] is True
    assert result["model_score"]["labelled_pairs"] == 149
    assert result["price_showing_ready"] is False

    predictions_path.write_text('{"pairs": []}', encoding="utf-8")
    tampered_output = tmp_path / "tampered-score.json"
    tampered_exit = main(
        [
            "score-review",
            "--reviewed-set",
            str(reviewed_path),
            "--predictions",
            str(predictions_path),
            "--canary-key",
            str(key_path),
            "--report-manifest",
            str(report_manifest_path),
            "--review-batch-manifest",
            str(batch_manifest_path),
            "--output",
            str(tampered_output),
        ]
    )
    assert tampered_exit == 2
    assert not tampered_output.exists()
