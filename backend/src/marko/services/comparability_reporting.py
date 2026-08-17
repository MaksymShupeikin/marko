"""Run-level observability for the comparability-v2 advisory contour."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from math import ceil, sqrt
from typing import Any, Iterable, Mapping, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    CandidateComparabilityFeedback,
    CandidateComparabilityReview,
    MarketObservation,
    ObservationTierClassification,
    OfferProcessingOutcome,
    PricingDiscoveryReview,
    PricingRun,
    PricingRunItem,
)
from marko.services.llm_comparability import (
    ComparabilityVerdict,
    IdentityVerdict,
    LLM_COMPARABILITY_CONTRACT_VERSION,
    PricingAdmission,
    load_effective_review_map,
)
from marko.services.llm_call_budget import PROVIDER_CALL_BUDGET_EXHAUSTED


_PARSER_FAILURE_CODES = frozenset(
    {
        "REJECTED_SCHEMA_MISMATCH",
        "REJECTED_SERIALIZATION",
        "FAILED_INTERNAL_PROCESSING",
    }
)


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return Decimal("0")
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001"))


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


#: Token counters a provider answer may report. Named once because both paid
#: lanes book into the same totals.
_USAGE_TOKEN_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "uncached_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
)


def accumulate_provider_spend(
    records: Iterable[Any],
    *,
    token_totals: Counter[str],
    rate_versions: set[str],
) -> Decimal:
    """Add one lane's booked usage into the run totals and return its cost.

    Takes any row carrying ``usage`` / ``estimated_cost`` / ``rate_card_version``
    rather than one ORM class: the OE lane and the no-OE discovery lane store
    the same three fields on different tables, and a run that sums only one of
    them reports a bill that is not the bill.
    """

    total = Decimal("0")
    for record in records:
        usage = getattr(record, "usage", None) or {}
        for key in _USAGE_TOKEN_KEYS:
            value = usage.get(key)
            if isinstance(value, int) and value >= 0:
                token_totals[key] += value
        estimated_cost = getattr(record, "estimated_cost", None)
        if estimated_cost:
            total += _decimal(estimated_cost.get("total_usd"))
        rate_card_version = getattr(record, "rate_card_version", None)
        if rate_card_version:
            rate_versions.add(rate_card_version)
    return total


def _p95(values: Sequence[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, ceil(len(ordered) * 0.95) - 1)]


def _wilson_95(successes: int, denominator: int) -> dict[str, Decimal] | None:
    """Two-sided Wilson score interval for a binomial proportion."""

    if denominator <= 0 or successes < 0 or successes > denominator:
        return None
    z = Decimal("1.959963984540054")
    n = Decimal(denominator)
    observed = Decimal(successes) / n
    adjustment = Decimal(1) + z * z / n
    centre = (observed + z * z / (Decimal(2) * n)) / adjustment
    variance = (observed * (Decimal(1) - observed) + z * z / (Decimal(4) * n)) / n
    half_width = z * Decimal(str(sqrt(float(variance)))) / adjustment
    quantum = Decimal("0.0001")
    return {
        "lower": max(Decimal(0), centre - half_width).quantize(quantum),
        "upper": min(Decimal(1), centre + half_width).quantize(quantum),
    }


def _zero_event_upper_95(denominator: int) -> Decimal | None:
    """Exact one-sided Clopper-Pearson upper bound for zero events."""

    if denominator <= 0:
        return None
    return Decimal(str(1 - 0.05 ** (1 / denominator))).quantize(Decimal("0.0001"))


def _legacy_identity(record: CandidateComparabilityReview) -> IdentityVerdict:
    if record.identity_verdict:
        return IdentityVerdict(record.identity_verdict)
    return {
        ComparabilityVerdict.COMPARABLE.value: IdentityVerdict.MATCH,
        ComparabilityVerdict.NOT_COMPARABLE.value: IdentityVerdict.NOT_MATCH,
        ComparabilityVerdict.INSUFFICIENT_DATA.value: IdentityVerdict.MANUAL_REVIEW,
    }[record.verdict]


def _legacy_admission(record: CandidateComparabilityReview) -> PricingAdmission:
    if record.pricing_admission:
        return PricingAdmission(record.pricing_admission)
    return {
        ComparabilityVerdict.COMPARABLE.value: PricingAdmission.ADMITTED,
        ComparabilityVerdict.NOT_COMPARABLE.value: PricingAdmission.EXCLUDED,
        ComparabilityVerdict.INSUFFICIENT_DATA.value: PricingAdmission.MANUAL_REVIEW,
    }[record.verdict]


def _feedback_labels(
    record: CandidateComparabilityReview,
    feedback: CandidateComparabilityFeedback,
) -> tuple[IdentityVerdict, PricingAdmission]:
    predicted_identity = _legacy_identity(record)
    predicted_admission = _legacy_admission(record)
    if feedback.decision == "CONFIRM":
        return predicted_identity, predicted_admission
    if feedback.corrected_identity_verdict is not None:
        return (
            IdentityVerdict(feedback.corrected_identity_verdict),
            PricingAdmission(str(feedback.corrected_pricing_admission)),
        )
    corrected = ComparabilityVerdict(str(feedback.corrected_verdict))
    return (
        {
            ComparabilityVerdict.COMPARABLE: IdentityVerdict.MATCH,
            ComparabilityVerdict.NOT_COMPARABLE: IdentityVerdict.NOT_MATCH,
            ComparabilityVerdict.INSUFFICIENT_DATA: IdentityVerdict.MANUAL_REVIEW,
        }[corrected],
        {
            ComparabilityVerdict.COMPARABLE: PricingAdmission.ADMITTED,
            ComparabilityVerdict.NOT_COMPARABLE: PricingAdmission.EXCLUDED,
            ComparabilityVerdict.INSUFFICIENT_DATA: PricingAdmission.MANUAL_REVIEW,
        }[corrected],
    )


def _accuracy_block(
    records: Sequence[CandidateComparabilityReview],
    feedback_by_review: Mapping[UUID, CandidateComparabilityFeedback],
) -> dict[str, Any]:
    if not feedback_by_review:
        return {
            "status": "NOT_EVALUATED",
            "labelled_reviews": 0,
            "eligible_labelled_reviews": 0,
            "metrics": None,
        }

    labelled = 0
    evaluable = 0
    truth_matches = 0
    truth_not_matches = 0
    automatic_decisions = 0
    automatic_matches = 0
    false_matches = 0
    false_not_matches = 0
    pricing_eligible = 0
    pricing_ineligible = 0
    pricing_eligible_admitted = 0
    unsafe_admitted = 0
    for record in records:
        feedback = feedback_by_review.get(record.id)
        if feedback is None:
            continue
        labelled += 1
        truth_identity, truth_admission = _feedback_labels(record, feedback)
        if truth_identity is IdentityVerdict.MANUAL_REVIEW:
            continue
        evaluable += 1
        prediction = _legacy_identity(record)
        predicted_admission = _legacy_admission(record)
        if prediction is not IdentityVerdict.MANUAL_REVIEW:
            automatic_decisions += 1
        if truth_identity is IdentityVerdict.MATCH:
            truth_matches += 1
            if prediction is IdentityVerdict.MATCH:
                automatic_matches += 1
            if prediction is IdentityVerdict.NOT_MATCH:
                false_not_matches += 1
        else:
            truth_not_matches += 1
            if prediction is IdentityVerdict.MATCH:
                false_matches += 1
        if truth_admission is PricingAdmission.ADMITTED:
            pricing_eligible += 1
            if predicted_admission is PricingAdmission.ADMITTED:
                pricing_eligible_admitted += 1
        elif truth_admission is PricingAdmission.EXCLUDED:
            pricing_ineligible += 1
            if predicted_admission is PricingAdmission.ADMITTED:
                unsafe_admitted += 1

    if evaluable == 0:
        return {
            "status": "PARTIAL",
            "labelled_reviews": labelled,
            "eligible_labelled_reviews": 0,
            "metrics": None,
        }
    return {
        "status": "EVALUATED" if labelled == len(records) else "PARTIAL",
        "labelled_reviews": labelled,
        "eligible_labelled_reviews": evaluable,
        "metrics": {
            "truth_match_count": truth_matches,
            "truth_not_match_count": truth_not_matches,
            "false_match_count": false_matches,
            "false_not_match_count": false_not_matches,
            "false_match_rate": (
                _ratio(false_matches, truth_not_matches) if truth_not_matches else None
            ),
            "false_match_wilson_95": _wilson_95(false_matches, truth_not_matches),
            "zero_event_false_match_upper_95": (
                _zero_event_upper_95(truth_not_matches)
                if truth_not_matches and false_matches == 0
                else None
            ),
            "automatic_match_recall": (
                _ratio(automatic_matches, truth_matches) if truth_matches else None
            ),
            "automatic_match_recall_wilson_95": _wilson_95(
                automatic_matches, truth_matches
            ),
            "automatic_decision_coverage": _ratio(automatic_decisions, evaluable),
            "automatic_decision_coverage_wilson_95": _wilson_95(
                automatic_decisions, evaluable
            ),
            "pricing_eligible_count": pricing_eligible,
            "pricing_ineligible_count": pricing_ineligible,
            "pricing_eligible_admitted_count": pricing_eligible_admitted,
            "pricing_eligible_admission_rate": (
                _ratio(pricing_eligible_admitted, pricing_eligible)
                if pricing_eligible
                else None
            ),
            "pricing_eligible_admission_wilson_95": _wilson_95(
                pricing_eligible_admitted, pricing_eligible
            ),
            "unsafe_admitted_count": unsafe_admitted,
            "unsafe_admission_rate": (
                _ratio(unsafe_admitted, pricing_ineligible)
                if pricing_ineligible
                else None
            ),
            "unsafe_admission_wilson_95": _wilson_95(
                unsafe_admitted, pricing_ineligible
            ),
            "zero_event_unsafe_admission_upper_95": (
                _zero_event_upper_95(pricing_ineligible)
                if pricing_ineligible and unsafe_admitted == 0
                else None
            ),
        },
    }


def _latest_by_id(
    rows: Iterable[Any],
    *,
    key: str,
) -> dict[UUID, Any]:
    result: dict[UUID, Any] = {}
    for row in rows:
        result.setdefault(getattr(row, key), row)
    return result


async def build_comparability_run_report(
    session: AsyncSession,
    *,
    run: PricingRun,
) -> dict[str, Any]:
    """Build a tenant-scoped report without inventing unlabelled accuracy."""

    run_items = list(
        (
            await session.scalars(
                select(PricingRunItem)
                .where(PricingRunItem.pricing_run_id == run.id)
                .order_by(PricingRunItem.id)
            )
        ).all()
    )
    run_item_ids = [item.id for item in run_items]
    observations: list[MarketObservation] = []
    outcomes: list[OfferProcessingOutcome] = []
    if run_item_ids:
        observations = list(
            (
                await session.scalars(
                    select(MarketObservation)
                    .where(MarketObservation.pricing_run_item_id.in_(run_item_ids))
                    .order_by(MarketObservation.id)
                )
            ).all()
        )
        outcomes = list(
            (
                await session.scalars(
                    select(OfferProcessingOutcome).where(
                        OfferProcessingOutcome.pricing_run_item_id.in_(run_item_ids)
                    )
                )
            ).all()
        )

    observation_ids = [observation.id for observation in observations]
    effective = await load_effective_review_map(session, observation_ids)
    records: list[CandidateComparabilityReview] = []
    classifications: dict[UUID, ObservationTierClassification] = {}
    if observation_ids:
        review_rows = list(
            (
                await session.scalars(
                    select(CandidateComparabilityReview)
                    .where(
                        CandidateComparabilityReview.market_observation_id.in_(
                            observation_ids
                        )
                    )
                    .order_by(
                        CandidateComparabilityReview.market_observation_id,
                        CandidateComparabilityReview.reviewed_at.desc(),
                        CandidateComparabilityReview.id.desc(),
                    )
                )
            ).all()
        )
        records = list(_latest_by_id(review_rows, key="market_observation_id").values())
        classification_rows = list(
            (
                await session.scalars(
                    select(ObservationTierClassification)
                    .where(
                        ObservationTierClassification.market_observation_id.in_(
                            observation_ids
                        )
                    )
                    .order_by(
                        ObservationTierClassification.market_observation_id,
                        ObservationTierClassification.classified_at.desc(),
                        ObservationTierClassification.id.desc(),
                    )
                )
            ).all()
        )
        classifications = _latest_by_id(
            classification_rows,
            key="market_observation_id",
        )

    feedback_by_review: dict[UUID, CandidateComparabilityFeedback] = {}
    if records:
        feedback_rows = list(
            (
                await session.scalars(
                    select(CandidateComparabilityFeedback)
                    .where(
                        CandidateComparabilityFeedback.review_id.in_(
                            [record.id for record in records]
                        )
                    )
                    .order_by(
                        CandidateComparabilityFeedback.review_id,
                        CandidateComparabilityFeedback.created_at.desc(),
                        CandidateComparabilityFeedback.id.desc(),
                    )
                )
            ).all()
        )
        feedback_by_review = _latest_by_id(feedback_rows, key="review_id")

    identity_counts = Counter(
        review.identity_verdict.value for review in effective.values()
    )
    admission_counts = Counter(
        review.pricing_admission.value for review in effective.values()
    )
    reviewed = len(effective)
    automatic = (
        identity_counts[IdentityVerdict.MATCH.value]
        + identity_counts[IdentityVerdict.NOT_MATCH.value]
    )

    provider_records = [
        record
        for record in records
        if record.decision_source == "LLM" and record.status in {"COMPLETED", "FAILED"}
    ]
    provider_successes = sum(
        record.status == "COMPLETED" for record in provider_records
    )
    provider_errors = Counter(
        record.error_code or "UNKNOWN_PROVIDER_FAILURE"
        for record in provider_records
        if record.status == "FAILED"
    )
    budget_exhausted = sum(
        record.error_code == PROVIDER_CALL_BUDGET_EXHAUSTED for record in records
    )

    outcome_counts = Counter(outcome.outcome_code for outcome in outcomes)
    parser_failures = sum(
        count for code, count in outcome_counts.items() if code in _PARSER_FAILURE_CODES
    )

    seller_groups: dict[tuple[UUID, str], list[UUID]] = defaultdict(list)
    admitted_seller_groups: Counter[tuple[UUID, str]] = Counter()
    owned_candidates = 0
    owned_admitted = 0
    for observation in observations:
        seller_key = observation.seller_id.strip() or observation.source_listing_id
        group_key = (observation.pricing_run_item_id, seller_key.casefold())
        seller_groups[group_key].append(observation.id)
        review = effective.get(observation.id)
        if review is not None and review.pricing_admission is PricingAdmission.ADMITTED:
            admitted_seller_groups[group_key] += 1
        classification = classifications.get(observation.id)
        if classification is not None and classification.is_owned:
            owned_candidates += 1
            if (
                review is not None
                and review.pricing_admission is PricingAdmission.ADMITTED
            ):
                owned_admitted += 1
    duplicate_candidates = sum(max(0, len(ids) - 1) for ids in seller_groups.values())
    admitted_duplicate_candidates = sum(
        max(0, count - 1) for count in admitted_seller_groups.values()
    )

    token_totals: Counter[str] = Counter()
    rate_versions: set[str] = set()
    total_cost = accumulate_provider_spend(
        records, token_totals=token_totals, rate_versions=rate_versions
    )
    latencies = [
        max(0, record.latency_ms) for record in records if record.status == "COMPLETED"
    ]

    # The no-OE discovery lane pays the same provider through its own code
    # path. Leaving it out reported one lane's spend as the whole bill: on
    # 2026-08-17 a run showed $0.157 while discovery was still calling out.
    discovery_records = list(
        (
            await session.scalars(
                select(PricingDiscoveryReview).where(
                    PricingDiscoveryReview.pricing_run_id == run.id
                )
            )
        ).all()
    )
    total_cost += accumulate_provider_spend(
        discovery_records, token_totals=token_totals, rate_versions=rate_versions
    )

    item_status_counts = Counter(item.status for item in run_items)
    return {
        "run_id": run.id,
        "generated_at": datetime.now(UTC),
        "run_status": run.status,
        "contract_version": LLM_COMPARABILITY_CONTRACT_VERSION,
        "totals": {
            "run_items": len(run_items),
            "terminal_run_items": sum(
                count
                for status, count in item_status_counts.items()
                if status in {"calculated", "manual_review", "failed", "cancelled"}
            ),
            "market_candidates": len(observations),
            "reviewed_candidates": reviewed,
            "unreviewed_candidates": max(0, len(observations) - reviewed),
            "feedback_labels": len(feedback_by_review),
        },
        "identity_verdict_counts": dict(identity_counts),
        "pricing_admission_counts": dict(admission_counts),
        "automatic_decision_coverage": _ratio(automatic, reviewed),
        "abstention_rate": _ratio(
            identity_counts[IdentityVerdict.MANUAL_REVIEW.value], reviewed
        ),
        "provider": {
            "request_terminal_results": len(provider_records),
            "valid_terminal_results": provider_successes,
            "valid_terminal_rate": _ratio(provider_successes, len(provider_records)),
            "failures": len(provider_records) - provider_successes,
            "failure_codes": dict(provider_errors),
            "budget_exhausted": budget_exhausted,
            "unconfigured_outcomes": sum(
                record.decision_source == "UNCONFIGURED" for record in records
            ),
        },
        "parser": {
            "terminal_offer_outcomes": len(outcomes),
            "outcome_counts": dict(outcome_counts),
            "persisted_observations": outcome_counts.get("OBSERVATION_PERSISTED", 0),
            "parser_failures": parser_failures,
            "parser_failure_rate": _ratio(parser_failures, len(outcomes)),
        },
        "seller_integrity": {
            "unique_product_sellers": len(seller_groups),
            "duplicate_candidates": duplicate_candidates,
            "admitted_duplicate_candidates": admitted_duplicate_candidates,
            "duplicate_seller_excluded": (
                duplicate_candidates - admitted_duplicate_candidates
            ),
            "seller_deduplication_rate": (
                _ratio(
                    duplicate_candidates - admitted_duplicate_candidates,
                    duplicate_candidates,
                )
                if duplicate_candidates
                else None
            ),
            "owned_store_candidates": owned_candidates,
            "owned_store_admitted": owned_admitted,
            "owned_store_exclusion_rate": (
                _ratio(owned_candidates - owned_admitted, owned_candidates)
                if owned_candidates
                else None
            ),
        },
        "performance": {
            "completed_provider_samples": len(latencies),
            "latency_ms_average": (
                sum(latencies) // len(latencies) if latencies else None
            ),
            "latency_ms_p95": _p95(latencies),
            "token_usage": dict(token_totals),
        },
        "cost": {
            "currency": "USD",
            "estimated_total": str(total_cost),
            "rate_card_versions": sorted(rate_versions),
            "disclaimer": "ESTIMATE_NOT_BILLING_TRUTH",
        },
        "accuracy": _accuracy_block(records, feedback_by_review),
    }
