"""Versioned comparability gold-set and leakage release-gate tests."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from metis.pricing.gold_set import evaluate_gold_set, load_gold_set


FIXTURE = Path(__file__).parent / "fixtures/comparability_gold_set_v1.json"


def test_engineering_gold_set_passes_without_claiming_production_activation() -> None:
    report = evaluate_gold_set(load_gold_set(FIXTURE))
    assert report["engineering_gate"] == "PASS"
    assert report["production_activation"] == "BLOCKED_DATA"
    assert report["counts"]["unsafe_automatic"] == 0
    assert report["metrics"]["unsafe_auto_rate"] == "0"
    assert report["metrics"]["comparability_precision"] == "1"
    assert report["metrics"]["conflict_recall"] == "1"
    assert report["split_leakage_detected"] is False
    assert report["mismatched_case_ids"] == []
    assert "REPRESENTATIVE_GOLD_SET_REQUIRED" in report["activation_blockers"]
    assert report["binomial_release_bound"]["p_upper"] is None


def test_split_leakage_is_rejected() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload = deepcopy(payload)
    payload["cases"][10]["product_family"] = payload["cases"][0]["product_family"]
    report = evaluate_gold_set(payload)
    assert report["engineering_gate"] == "FAIL"
    assert any("GOLD_SET_SPLIT_LEAKAGE" in item for item in report["contract_errors"])


def test_nonzero_unsafe_engineering_budget_is_rejected() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["release_policy"]["engineering_unsafe_auto_count_max"] = 1
    report = evaluate_gold_set(payload)
    assert report["engineering_gate"] == "FAIL"
    assert "GOLD_SET_ENGINEERING_GATE_MUST_BE_ZERO" in report["contract_errors"]


def test_exact_id_conflict_cases_reject_instead_of_bypassing_gates() -> None:
    report = evaluate_gold_set(load_gold_set(FIXTURE))
    exact_conflicts = [
        case
        for case in report["case_results"]
        if case["retrieval_kind"] in {"sku", "model"}
        and case["gold_label"] == "conflict"
    ]
    assert exact_conflicts
    assert all(case["actual_result"] == "REJECT" for case in exact_conflicts)
