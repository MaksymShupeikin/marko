"""Evaluation of real, manually labeled brand-tier observations."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from .types import ProductTier


TIER_VALIDATION_SCHEMA_VERSION = "metis-real-tier-validation-v1"
_TIER_ORDER = tuple(tier.value for tier in ProductTier)


@dataclass(frozen=True, slots=True)
class TierValidationCase:
    source_listing_id: str
    gold_tier: ProductTier
    predicted_tier: ProductTier


def evaluate_tier_validation(
    cases: Iterable[TierValidationCase],
    *,
    min_labeled: int = 200,
    representative: bool,
    approved_by: str | None,
    domain_policy_approved: bool,
) -> dict[str, object]:
    """Measure accuracy without conflating measurement with activation."""

    if min_labeled < 1:
        raise ValueError("min_labeled must be positive")
    case_list = list(cases)
    identifiers = [case.source_listing_id for case in case_list]
    duplicate_ids = sorted(
        source_id for source_id, count in Counter(identifiers).items() if count > 1
    )
    contract_errors: list[str] = []
    if any(not source_id.strip() for source_id in identifiers):
        contract_errors.append("EMPTY_SOURCE_LISTING_ID")
    if duplicate_ids:
        contract_errors.append("DUPLICATE_SOURCE_LISTING_IDS")

    confusion = {
        gold: {predicted: 0 for predicted in _TIER_ORDER} for gold in _TIER_ORDER
    }
    correct = 0
    gold_counts: Counter[str] = Counter()
    for case in case_list:
        gold = case.gold_tier.value
        predicted = case.predicted_tier.value
        confusion[gold][predicted] += 1
        gold_counts[gold] += 1
        correct += int(case.gold_tier is case.predicted_tier)

    labeled = len(case_list)
    accuracy = Decimal(correct) / Decimal(labeled) if labeled else None
    per_tier_recall: dict[str, str | None] = {}
    for tier in _TIER_ORDER:
        denominator = gold_counts[tier]
        per_tier_recall[tier] = (
            str(Decimal(confusion[tier][tier]) / Decimal(denominator))
            if denominator
            else None
        )

    blockers: list[str] = []
    if labeled < min_labeled:
        blockers.append(f"LABELED_CASES_BELOW_MINIMUM:{labeled}/{min_labeled}")
    if not representative:
        blockers.append("REPRESENTATIVE_REAL_SAMPLE_NOT_APPROVED")
    if not (approved_by or "").strip():
        blockers.append("GOLD_SET_REVIEWER_NOT_RECORDED")
    if not domain_policy_approved:
        blockers.append("BRAND_DOMAIN_POLICY_NOT_APPROVED")

    if contract_errors:
        validation_gate = "FAIL"
    elif blockers:
        validation_gate = "BLOCKED"
    else:
        validation_gate = "PASS"

    return {
        "schema_version": TIER_VALIDATION_SCHEMA_VERSION,
        "data_class": "real_prom_manual_labels",
        "representative": representative,
        "approved_by": (approved_by or "").strip() or None,
        "counts": {
            "labeled": labeled,
            "correct": correct,
            "incorrect": labeled - correct,
            "minimum_required": min_labeled,
        },
        "metrics": {
            "accuracy": str(accuracy) if accuracy is not None else None,
            "per_tier_recall": per_tier_recall,
        },
        "confusion_matrix": confusion,
        "duplicate_source_listing_ids": duplicate_ids,
        "contract_errors": contract_errors,
        "activation_blockers": blockers,
        "validation_gate": validation_gate,
        "production_activation": "BLOCKED_SEPARATE_DECISION",
    }


__all__ = [
    "TIER_VALIDATION_SCHEMA_VERSION",
    "TierValidationCase",
    "evaluate_tier_validation",
]
