from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from marko.services.comparability_reporting import _accuracy_block


def _review(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid4(),
        "identity_verdict": "MATCH",
        "pricing_admission": "ADMITTED",
        "verdict": "COMPARABLE",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_accuracy_without_human_labels_is_not_evaluated() -> None:
    result = _accuracy_block([_review()], {})

    assert result == {
        "status": "NOT_EVALUATED",
        "labelled_reviews": 0,
        "eligible_labelled_reviews": 0,
        "metrics": None,
    }


def test_accuracy_keeps_identity_and_pricing_labels_independent() -> None:
    review = _review(pricing_admission="MANUAL_REVIEW", verdict="INSUFFICIENT_DATA")
    feedback = SimpleNamespace(
        decision="CORRECT",
        corrected_identity_verdict="MATCH",
        corrected_pricing_admission="EXCLUDED",
        corrected_verdict="NOT_COMPARABLE",
    )

    result = _accuracy_block([review], {review.id: feedback})

    assert result["status"] == "EVALUATED"
    assert result["metrics"]["truth_match_count"] == 1
    assert result["metrics"]["pricing_ineligible_count"] == 1
    assert result["metrics"]["unsafe_admitted_count"] == 0
    assert result["metrics"]["automatic_match_recall_wilson_95"] == {
        "lower": Decimal("0.2065"),
        "upper": Decimal("1.0000"),
    }
    assert result["metrics"]["zero_event_unsafe_admission_upper_95"] == Decimal(
        "0.9500"
    )


def test_accuracy_reports_sample_uncertainty_for_zero_false_matches() -> None:
    reviews = [
        _review(identity_verdict="NOT_MATCH", pricing_admission="EXCLUDED")
        for _ in range(10)
    ]
    feedback = {
        review.id: SimpleNamespace(
            decision="CONFIRM",
            corrected_identity_verdict=None,
            corrected_pricing_admission=None,
            corrected_verdict=None,
        )
        for review in reviews
    }

    result = _accuracy_block(reviews, feedback)

    assert result["metrics"]["false_match_count"] == 0
    assert result["metrics"]["false_match_rate"] == Decimal("0.0000")
    assert result["metrics"]["false_match_wilson_95"] == {
        "lower": Decimal("0.0000"),
        "upper": Decimal("0.2775"),
    }
    assert result["metrics"]["zero_event_false_match_upper_95"] == Decimal("0.2589")
