"""Frozen stratified sampling and six-metric gate for no-OE discovery.

This module is offline.  It neither performs Prom requests nor invokes Luna.
Positive model output remains a manual-review candidate and both automatic
identity and automatic pricing admission are hard-coded to zero.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
import hashlib
import json
from typing import Any

from semantic_discovery import assert_no_monetary_keys, redact_monetary_material


EVALUATION_SCHEMA_VERSION = "semantic-discovery-without-oe-evaluation-v1"
SAMPLE_SCHEMA_VERSION = "semantic-discovery-without-oe-sample-v1"
MANDATORY_UNTYPED_ROW_IDS = ("1230665005", "2179741467")
SEMANTIC_REVIEW_CANARY_FIELDS = (
    "row_id",
    "candidate_key",
    "seed_title",
    "seed_category",
    "candidate_title",
    "candidate_url",
    "candidate_seller",
    "candidate_description",
    "candidate_image",
    "evidence_sha256",
    "human_identity_truth",
    "evidence_notes",
)
SEMANTIC_SEED_REVIEW_FIELDS = (
    "row_id",
    "title",
    "category",
    "collection_attempted",
    "correct_candidate_retrieved",
    "review_complete",
    "detail_card_available",
    "usable_image_available",
    "independent_seller_count",
    "http_request_count",
    "luna_call_count",
    "runtime_seconds",
    "evidence_sha256",
    "evidence_notes",
)


class SemanticEvaluationError(ValueError):
    pass


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _row_id(row: Mapping[str, object]) -> str:
    return str(row.get("row_id") or "").strip()


def _stratum(row: Mapping[str, object]) -> str:
    category = str(row.get("category") or "<UNKNOWN_CATEGORY>").strip()
    family = str(row.get("part_family") or "<UNTYPED>").strip()
    return f"{category}\0{family}"


def build_stratified_sample(
    rows: Sequence[Mapping[str, object]],
    *,
    sample_size: int,
    selection_seed: str,
    mandatory_row_ids: Sequence[str] = MANDATORY_UNTYPED_ROW_IDS,
) -> tuple[dict[str, object], ...]:
    """Deterministic round-robin sample across category and part-family strata."""

    if sample_size <= 0 or sample_size > len(rows):
        raise SemanticEvaluationError("sample_size must be within 1..population")
    if not selection_seed.strip():
        raise SemanticEvaluationError("selection_seed must be non-empty")
    by_id: dict[str, dict[str, object]] = {}
    for raw in rows:
        row = dict(raw)
        identifier = _row_id(row)
        if not identifier:
            raise SemanticEvaluationError("every sample row requires row_id")
        if identifier in by_id:
            raise SemanticEvaluationError(f"duplicate sample row_id {identifier}")
        by_id[identifier] = row
    mandatory_ids = tuple(str(value).strip() for value in mandatory_row_ids)
    missing = [identifier for identifier in mandatory_ids if identifier not in by_id]
    if missing:
        raise SemanticEvaluationError(
            "mandatory sample rows are missing: " + ", ".join(missing)
        )
    if len(mandatory_ids) > sample_size:
        raise SemanticEvaluationError("mandatory rows exceed sample size")

    selected = [by_id[identifier] for identifier in mandatory_ids]
    selected_ids = set(mandatory_ids)
    strata: dict[str, list[dict[str, object]]] = defaultdict(list)
    for identifier, row in by_id.items():
        if identifier not in selected_ids:
            strata[_stratum(row)].append(row)
    for key, values in strata.items():
        values.sort(
            key=lambda row: hashlib.sha256(
                f"{selection_seed}\0row\0{key}\0{_row_id(row)}".encode("utf-8")
            ).hexdigest()
        )
    stratum_order = sorted(
        strata,
        key=lambda key: hashlib.sha256(
            f"{selection_seed}\0stratum\0{key}".encode("utf-8")
        ).hexdigest(),
    )
    cursor = {key: 0 for key in stratum_order}
    while len(selected) < sample_size:
        progressed = False
        for key in stratum_order:
            index = cursor[key]
            if index >= len(strata[key]):
                continue
            selected.append(strata[key][index])
            cursor[key] += 1
            progressed = True
            if len(selected) == sample_size:
                break
        if not progressed:
            raise SemanticEvaluationError("sample population exhausted unexpectedly")
    return tuple(
        sorted(
            selected,
            key=lambda row: hashlib.sha256(
                f"{selection_seed}\0final\0{_row_id(row)}".encode("utf-8")
            ).hexdigest(),
        )
    )


def validate_frozen_run_coverage(
    sample_ids: set[str],
    run_batches: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    """Require an exact, non-overlapping successful live partition of the sample."""

    expected = {str(value).strip() for value in sample_ids if str(value).strip()}
    if not expected or len(expected) != len(sample_ids):
        raise SemanticEvaluationError("frozen sample ids must be non-empty and unique")
    if not run_batches:
        raise SemanticEvaluationError("at least one completed live run is required")
    covered: set[str] = set()
    for batch_no, batch in enumerate(run_batches, 1):
        if batch.get("live") is not True:
            raise SemanticEvaluationError(f"run batch {batch_no} is not live")
        if batch.get("run_luna") is not True:
            raise SemanticEvaluationError(f"run batch {batch_no} did not run Luna")
        status = str(batch.get("run_status") or "")
        if status != "COMPLETED":
            raise SemanticEvaluationError(
                f"run batch {batch_no} is not COMPLETED: {status or '<missing>'}"
            )
        raw_ids = batch.get("row_ids")
        if not isinstance(raw_ids, (list, tuple)):
            raise SemanticEvaluationError(f"run batch {batch_no} has no row_ids")
        row_ids = tuple(str(value).strip() for value in raw_ids)
        if not row_ids or any(not value for value in row_ids):
            raise SemanticEvaluationError(
                f"run batch {batch_no} has empty row identifiers"
            )
        if len(set(row_ids)) != len(row_ids) or covered.intersection(row_ids):
            raise SemanticEvaluationError(
                f"run batch {batch_no} overlaps another batch"
            )
        try:
            selected_seeds = int(batch.get("selected_seeds") or 0)
        except (TypeError, ValueError) as exc:
            raise SemanticEvaluationError(
                f"run batch {batch_no} selected_seeds is invalid"
            ) from exc
        if selected_seeds != len(row_ids):
            raise SemanticEvaluationError(
                f"run batch {batch_no} profile count does not match selected_seeds"
            )
        unknown = set(row_ids) - expected
        if unknown:
            raise SemanticEvaluationError(
                f"run batch {batch_no} contains rows outside frozen sample: "
                + ", ".join(sorted(unknown))
            )
        covered.update(row_ids)
    missing = expected - covered
    if missing:
        raise SemanticEvaluationError(
            "completed runs do not cover the frozen sample: "
            + ", ".join(sorted(missing))
        )
    return {
        "status": "PASS",
        "sample_seeds": len(expected),
        "covered_seeds": len(covered),
        "run_batches": len(run_batches),
        "live": True,
        "run_luna": True,
        "all_runs_completed": True,
    }


def _ratio(numerator: int, denominator: int) -> str | None:
    if denominator <= 0:
        return None
    return str(
        (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.000001"))
    )


def _truth(value: object) -> str:
    return str(value or "").strip().upper()


def _semantic_evidence_sha256(
    row: Mapping[str, object],
    *,
    fields: Sequence[str],
    editable_fields: set[str],
) -> str:
    return _canonical_sha256(
        {
            field: str(row.get(field) or "")
            for field in fields
            if field not in editable_fields and field != "evidence_sha256"
        }
    )


def semantic_candidate_evidence_sha256(row: Mapping[str, object]) -> str:
    return _semantic_evidence_sha256(
        row,
        fields=SEMANTIC_REVIEW_CANARY_FIELDS,
        editable_fields={"human_identity_truth", "evidence_notes"},
    )


def semantic_seed_evidence_sha256(row: Mapping[str, object]) -> str:
    return _semantic_evidence_sha256(
        row,
        fields=SEMANTIC_SEED_REVIEW_FIELDS,
        editable_fields={
            "correct_candidate_retrieved",
            "review_complete",
            "evidence_notes",
        },
    )


def verify_semantic_review_evidence(
    seed_rows: Sequence[Mapping[str, object]],
    candidate_rows: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    """Detect evidence edits while allowing only the human label fields to change."""

    mismatches: list[dict[str, str]] = []
    for kind, rows, calculator in (
        ("seed", seed_rows, semantic_seed_evidence_sha256),
        ("candidate", candidate_rows, semantic_candidate_evidence_sha256),
    ):
        for row in rows:
            expected = str(row.get("evidence_sha256") or "").strip()
            actual = calculator(row)
            if expected != actual:
                mismatches.append(
                    {
                        "kind": kind,
                        "row_id": _row_id(row),
                        "candidate_key": str(row.get("candidate_key") or ""),
                        "expected_sha256": expected,
                        "actual_sha256": actual,
                    }
                )
    return {
        "verification_version": "semantic-review-evidence-v1",
        "status": "PASS" if not mismatches else "FAIL",
        "seed_rows": len(seed_rows),
        "candidate_rows": len(candidate_rows),
        "mismatches": mismatches,
    }


def build_semantic_review_canaries(
    canary_rows: Sequence[Mapping[str, object]],
    *,
    selection_seed: str,
) -> tuple[tuple[dict[str, str], ...], dict[str, Any]]:
    """Blind known-answer pairs for the human labelling batch."""

    if not selection_seed.strip():
        raise SemanticEvaluationError("canary selection seed must be non-empty")
    if not canary_rows:
        raise SemanticEvaluationError(
            "semantic review requires at least one known-answer canary"
        )
    output: list[dict[str, str]] = []
    key_rows: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for source in canary_rows:
        clean_source = redact_monetary_material(source)
        if not isinstance(clean_source, Mapping):
            raise SemanticEvaluationError("semantic canary must be a mapping")
        assert_no_monetary_keys(clean_source)
        canary_id = str(clean_source.get("canary_id") or "").strip()
        row_id = _row_id(clean_source)
        expected = _truth(clean_source.get("expected_identity_truth"))
        if not canary_id or canary_id in seen_ids:
            raise SemanticEvaluationError(
                "every semantic canary requires a unique canary_id"
            )
        if not row_id:
            raise SemanticEvaluationError("every semantic canary requires row_id")
        if expected not in {"MATCH", "NOT_MATCH"}:
            raise SemanticEvaluationError(
                "semantic canary truth must be MATCH or NOT_MATCH"
            )
        seen_ids.add(canary_id)
        opaque = hashlib.sha256(
            (
                f"{selection_seed}\0semantic-canary\0{canary_id}\0"
                f"{_canonical_sha256(clean_source)}"
            ).encode("utf-8")
        ).hexdigest()[:32]
        blinded = {
            field: (
                opaque
                if field == "candidate_key"
                else ""
                if field == "human_identity_truth"
                else str(clean_source.get(field) or "")
            )
            for field in SEMANTIC_REVIEW_CANARY_FIELDS
        }
        blinded["evidence_sha256"] = semantic_candidate_evidence_sha256(blinded)
        output.append(blinded)
        key_rows.append(
            {
                "canary_id": canary_id,
                "row_id": row_id,
                "opaque_candidate_key": opaque,
                "expected_identity_truth": expected,
            }
        )
    ordered = tuple(
        sorted(
            output,
            key=lambda row: hashlib.sha256(
                f"{selection_seed}\0final\0{row['candidate_key']}".encode("utf-8")
            ).hexdigest(),
        )
    )
    return ordered, {
        "schema_version": "semantic-review-canary-key-v1",
        "selection_seed_sha256": hashlib.sha256(
            selection_seed.encode("utf-8")
        ).hexdigest(),
        "canaries": key_rows,
    }


def verify_semantic_review_canaries(
    labelled_rows: Sequence[Mapping[str, object]],
    canary_key: Mapping[str, object],
) -> dict[str, Any]:
    """Verify human canary answers without including them in model metrics."""

    raw_key_rows = canary_key.get("canaries")
    if not isinstance(raw_key_rows, list):
        raise SemanticEvaluationError("semantic canary key has an invalid schema")
    labels: dict[tuple[str, str], Mapping[str, object]] = {}
    for row in labelled_rows:
        key = (_row_id(row), str(row.get("candidate_key") or "").strip())
        if key in labels:
            raise SemanticEvaluationError(
                f"semantic candidate labels contain duplicate key {key!r}"
            )
        labels[key] = row
    correct = 0
    mismatches: list[dict[str, Any]] = []
    for raw_key in raw_key_rows:
        if not isinstance(raw_key, Mapping):
            raise SemanticEvaluationError("semantic canary key contains an invalid row")
        key = (
            _row_id(raw_key),
            str(raw_key.get("opaque_candidate_key") or "").strip(),
        )
        expected = _truth(raw_key.get("expected_identity_truth"))
        labelled = labels.get(key)
        actual = _truth(labelled.get("human_identity_truth")) if labelled else ""
        if actual == expected and expected in {"MATCH", "NOT_MATCH"}:
            correct += 1
        else:
            mismatches.append(
                {
                    "canary_id": raw_key.get("canary_id"),
                    "row_id": key[0],
                    "opaque_candidate_key": key[1],
                    "expected_identity_truth": expected,
                    "actual_identity_truth": actual,
                }
            )
    expected_count = len(raw_key_rows)
    status = "PASS" if expected_count > 0 and correct == expected_count else "FAIL"
    return {
        "verification_version": "semantic-review-canary-verification-v1",
        "status": status,
        "canaries_expected": expected_count,
        "canaries_correct": correct,
        "mismatches": mismatches,
        "review_batch_accepted": status == "PASS",
    }


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().casefold()
    return normalized in {"1", "true", "yes", "y", "да", "так"}


def _nonnegative_int(value: object, *, field: str) -> int:
    try:
        result = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise SemanticEvaluationError(f"{field} must be an integer") from exc
    if result < 0:
        raise SemanticEvaluationError(f"{field} cannot be negative")
    return result


def _nonnegative_decimal(value: object, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value or 0))
    except Exception as exc:  # Decimal exposes several parse exceptions.
        raise SemanticEvaluationError(f"{field} must be numeric") from exc
    if not result.is_finite() or result < 0:
        raise SemanticEvaluationError(f"{field} must be finite and non-negative")
    return result


def evaluate_semantic_discovery_gate(
    seed_labels: Sequence[Mapping[str, object]],
    candidate_labels: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    """Compute the six required measurements without inventing missing truth."""

    seed_ids: set[str] = set()
    retrieval_yes = 0
    retrieval_denominator = 0
    complete_seed_reviews = 0
    collection_attempted_seeds = 0
    detail_available = 0
    image_available = 0
    independent_seller_covered = 0
    http_requests = 0
    luna_calls = 0
    runtime = Decimal("0")
    for row in seed_labels:
        identifier = _row_id(row)
        if not identifier or identifier in seed_ids:
            raise SemanticEvaluationError(
                f"seed labels contain missing/duplicate row_id {identifier!r}"
            )
        seed_ids.add(identifier)
        collection_attempted_seeds += int(_bool(row.get("collection_attempted")))
        review_complete = _bool(row.get("review_complete"))
        retrieval = _truth(row.get("correct_candidate_retrieved"))
        if review_complete and retrieval in {"YES", "NO"}:
            complete_seed_reviews += 1
            retrieval_denominator += 1
            retrieval_yes += int(retrieval == "YES")
        detail_available += int(_bool(row.get("detail_card_available")))
        image_available += int(_bool(row.get("usable_image_available")))
        independent_seller_covered += int(
            _nonnegative_int(
                row.get("independent_seller_count"),
                field="independent_seller_count",
            )
            > 0
        )
        http_requests += _nonnegative_int(
            row.get("http_request_count"), field="http_request_count"
        )
        luna_calls += _nonnegative_int(
            row.get("luna_call_count"), field="luna_call_count"
        )
        runtime += _nonnegative_decimal(
            row.get("runtime_seconds"), field="runtime_seconds"
        )

    candidate_keys: set[tuple[str, str]] = set()
    deterministic_rejections = 0
    correct_deterministic_rejections = 0
    false_rejects = 0
    luna_decisions = 0
    luna_matches = 0
    luna_correct_matches = 0
    luna_false_accepts = 0
    luna_false_not_matches = 0
    luna_abstentions = 0
    explicit_critical_flags = 0
    candidate_truth_complete = True
    for row in candidate_labels:
        identifier = _row_id(row)
        candidate_key = str(row.get("candidate_key") or "").strip()
        key = (identifier, candidate_key)
        if not identifier or identifier not in seed_ids:
            raise SemanticEvaluationError(
                f"candidate label references unknown seed {identifier!r}"
            )
        if not candidate_key or key in candidate_keys:
            raise SemanticEvaluationError(
                f"candidate labels contain missing/duplicate key {key!r}"
            )
        candidate_keys.add(key)
        truth = _truth(row.get("human_identity_truth"))
        if truth not in {"MATCH", "NOT_MATCH"}:
            candidate_truth_complete = False
        disposition = _truth(row.get("deterministic_disposition"))
        if disposition == "SEMANTIC_NOT_MATCH":
            deterministic_rejections += 1
            if truth == "NOT_MATCH":
                correct_deterministic_rejections += 1
            elif truth == "MATCH":
                false_rejects += 1
        verdict = _truth(row.get("luna_verdict"))
        if verdict in {"MATCH", "NOT_MATCH", "MANUAL_REVIEW"}:
            luna_decisions += 1
            luna_matches += int(verdict == "MATCH")
            luna_correct_matches += int(verdict == "MATCH" and truth == "MATCH")
            luna_false_accepts += int(verdict == "MATCH" and truth == "NOT_MATCH")
            luna_false_not_matches += int(verdict == "NOT_MATCH" and truth == "MATCH")
            luna_abstentions += int(verdict == "MANUAL_REVIEW")
        explicit_critical_flags += int(_bool(row.get("critical_false_accept")))

    seed_count = len(seed_labels)
    critical_false_accepts = max(luna_false_accepts, explicit_critical_flags)
    missing_requirements: list[str] = []
    if seed_count == 0:
        missing_requirements.append("EMPTY_FROZEN_SAMPLE")
    if collection_attempted_seeds != seed_count:
        missing_requirements.append("FROZEN_SEED_COLLECTION_INCOMPLETE")
    if complete_seed_reviews != seed_count:
        missing_requirements.append("SEED_HUMAN_REVIEW_INCOMPLETE")
    if not candidate_labels:
        missing_requirements.append("NO_CANDIDATE_PAIRS")
    if not candidate_truth_complete:
        missing_requirements.append("CANDIDATE_HUMAN_TRUTH_INCOMPLETE")
    if deterministic_rejections == 0:
        missing_requirements.append("NO_DETERMINISTIC_REJECTION_DENOMINATOR")
    if luna_decisions == 0:
        missing_requirements.append("NO_LUNA_TERMINAL_DECISION_DENOMINATOR")
    measurement_complete = not missing_requirements
    decision = (
        "LEAVE_AS_MANUAL_TOOL"
        if critical_false_accepts > 0
        else "MEASUREMENT_INCOMPLETE"
        if not measurement_complete
        else "OPERATOR_DECISION_REQUIRED"
    )
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "measurement_complete": measurement_complete,
        "missing_measurement_requirements": missing_requirements,
        "seed_count": seed_count,
        "candidate_count": len(candidate_labels),
        "run_coverage": {
            "collection_attempted_seeds": collection_attempted_seeds,
            "all_frozen_seeds_attempted": collection_attempted_seeds == seed_count,
        },
        "retrieval": {
            "reviewed_seeds": retrieval_denominator,
            "seeds_with_correct_candidate": retrieval_yes,
            "seed_recall": _ratio(retrieval_yes, retrieval_denominator),
        },
        "deterministic_rejections": {
            "labelled_rejections": deterministic_rejections,
            "correct_rejection_count": correct_deterministic_rejections,
            "precision": _ratio(
                correct_deterministic_rejections, deterministic_rejections
            ),
            "false_reject_count": false_rejects,
            "false_reject_rate": _ratio(false_rejects, deterministic_rejections),
        },
        "luna": {
            "terminal_decisions": luna_decisions,
            "match_count": luna_matches,
            "correct_match_count": luna_correct_matches,
            "false_accept_count": luna_false_accepts,
            "false_accept_rate": _ratio(luna_false_accepts, luna_matches),
            "false_not_match_count": luna_false_not_matches,
            "abstention_count": luna_abstentions,
            "abstention_rate": _ratio(luna_abstentions, luna_decisions),
        },
        "evidence_availability": {
            "detail_card_available_seeds": detail_available,
            "detail_card_rate": _ratio(detail_available, seed_count),
            "usable_image_available_seeds": image_available,
            "usable_image_rate": _ratio(image_available, seed_count),
        },
        "independent_sellers": {
            "covered_seeds": independent_seller_covered,
            "seed_coverage_rate": _ratio(independent_seller_covered, seed_count),
        },
        "budgets": {
            "http_requests_total": http_requests,
            "http_requests_per_seed": _ratio(http_requests, seed_count),
            "luna_calls_total": luna_calls,
            "luna_calls_per_seed": _ratio(luna_calls, seed_count),
            "runtime_seconds_total": str(runtime.quantize(Decimal("0.001"))),
            "runtime_seconds_per_seed": (
                str((runtime / Decimal(seed_count)).quantize(Decimal("0.001")))
                if seed_count
                else None
            ),
        },
        "critical_false_accept_count": critical_false_accepts,
        "decision": decision,
        "decision_options": (
            "SCALE_MANUAL_REVIEW_PILOT",
            "SCALE_WITH_HARDENING",
            "LEAVE_AS_MANUAL_TOOL",
        ),
        "automatic_identity_admission": 0,
        "automatic_pricing_admission": 0,
        "oe_numbers_inferred": [],
        "boundary": {
            "luna_match_is_identity": False,
            "luna_match_status": "SEMANTIC_MATCH_CANDIDATE_MANUAL_REVIEW",
            "prices_written": 0,
            "database_writes": 0,
        },
    }


__all__ = [
    "EVALUATION_SCHEMA_VERSION",
    "MANDATORY_UNTYPED_ROW_IDS",
    "SAMPLE_SCHEMA_VERSION",
    "SEMANTIC_REVIEW_CANARY_FIELDS",
    "SEMANTIC_SEED_REVIEW_FIELDS",
    "SemanticEvaluationError",
    "build_semantic_review_canaries",
    "build_stratified_sample",
    "evaluate_semantic_discovery_gate",
    "semantic_candidate_evidence_sha256",
    "semantic_seed_evidence_sha256",
    "validate_frozen_run_coverage",
    "verify_semantic_review_canaries",
    "verify_semantic_review_evidence",
]
