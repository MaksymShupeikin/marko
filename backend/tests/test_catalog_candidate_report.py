from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from marko.services.catalog_candidate_report import (
    CandidateSelectionReport,
    _candidate_gate_metrics,
    format_candidate_selection_report,
)
from metis.pricing import CANDIDATE_GATE_ORDER


def test_candidate_report_contains_histogram_and_coverage_reason() -> None:
    report = CandidateSelectionReport(
        run_id=uuid4(),
        query="7E5827505A",
        histogram={
            "DISMANTLER_SELLER": 2,
            "OEM_NOT_FOUND": 1,
            "TIER_UNKNOWN (REVIEW)": 26,
        },
        comparable_count=0,
        review_count=26,
        skipped_count=3,
        prom_reported_total=90,
        retrieved_count=29,
        persisted_count=29,
        rejected_count=0,
        owned_excluded_count=0,
        search_pages_fetched=1,
        search_page_limit=1,
        unfetched_count=61,
        coverage_ratio=Decimal("0.322222"),
        coverage_reason="SEARCH_PAGE_LIMIT",
        method_version="deterministic-candidate-gates-v1",
        config_sha256="a" * 64,
        brand_rules_dataset_id="NO_BRAND_DICTIONARY_CONFIGURED",
        applicability_unknown_count=4,
        applicability_unknown_rate=Decimal("0.137931"),
        gate_metrics={
            "own_seller": {
                "reached": 29,
                "terminal": 0,
                "conditional_selectivity": "0.000000",
            }
        },
        cross_link_status_counts={
            "CONFIRMED": 0,
            "REVIEW": 0,
            "REJECTED": 0,
            "UNKNOWN": 0,
        },
    )

    text = format_candidate_selection_report(report)
    payload = report.as_dict()

    assert "TIER_UNKNOWN (REVIEW)" in text
    assert "29/90" in text
    assert "не загружено 61" in text
    assert "SEARCH_PAGE_LIMIT" in text
    assert "Applicability UNKNOWN: 4/29 (0.137931)" in text
    assert "CONFIRMED=0" in text
    assert "own_seller: reached=29" in text
    assert payload["status_counts"] == {
        "COMPARABLE": 0,
        "REVIEW": 26,
        "SKIP": 3,
    }


def test_candidate_gate_metrics_use_conditional_reached_denominator() -> None:
    comparable = SimpleNamespace(
        passed_gates=list(CANDIDATE_GATE_ORDER),
        selection_details={"stopped_gate": None},
    )
    own_skip = SimpleNamespace(
        passed_gates=[],
        selection_details={"stopped_gate": "own_seller"},
    )
    tier_review = SimpleNamespace(
        passed_gates=list(CANDIDATE_GATE_ORDER[:9]),
        selection_details={"stopped_gate": "tier"},
    )

    metrics = _candidate_gate_metrics([comparable, own_skip, tier_review])

    assert metrics["own_seller"] == {
        "reached": 3,
        "terminal": 1,
        "conditional_selectivity": "0.333333",
    }
    assert metrics["tier"] == {
        "reached": 2,
        "terminal": 1,
        "conditional_selectivity": "0.500000",
    }
    assert metrics["price_anomaly"] == {
        "reached": 1,
        "terminal": 0,
        "conditional_selectivity": "0.000000",
    }
