"""Variation matrix for the resumable Gate 1 coverage measurement.

Three axes are exercised deliberately, per master-plan meta-rule 5: typical
input, boundary input (``n = 1, 2, 3`` and the exact ``share_ge3`` threshold),
and degenerate input (empty sample, every value identical, a single target).
The published 2026-07-19 baseline vector is replayed as a test so a change in
the metric code cannot silently move the number the whole gate is compared to.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from marko.catalog_coverage_measurement_cli import report_exit_code
from marko.infrastructure.db.models import CatalogDiscoveryOffer
from marko.services.parser_models import ListingPage
from marko.services import catalog_coverage_measurement as measurement
from marko.services.catalog_coverage_measurement import (
    COHORT_BASELINE,
    COHORT_IDENTITY,
    COHORT_PLAN_S,
    BatchIdentity,
    CoverageMeasurementError,
    MeasurementCheckpoint,
    TargetOutcome,
    cohort_counts,
    cohort_membership,
    coverage_metrics,
    load_coverage_targets,
    offer_facts,
    run_coverage_batch,
    scan_blocking_markers,
    summarize_request_telemetry,
)


# The published 2026-07-19 per-target cohort, reconstructed as
# ``exact_independent_sellers - independent_kemp_sellers_retained``.
BASELINE_VECTOR = (
    0,
    7,
    10,
    0,
    1,
    1,
    1,
    1,
    0,
    0,
    4,
    1,
    7,
    1,
    3,
    1,
    4,
    2,
    2,
    3,
    4,
    13,
    2,
    2,
    2,
    3,
    0,
    0,
    0,
    1,
)

WORKSPACE_ID = UUID("4ba8055e-b448-4c19-b90b-27c1f1b78001")


def _identity(**overrides: Any) -> BatchIdentity:
    base: dict[str, Any] = {
        "targets_sha256": "a" * 64,
        "workspace_id": str(WORKSPACE_ID),
        "search_page_limit": 10,
        "selection_config_sha256": "b" * 64,
        "brand_rules_dataset_id": "brands-v1",
        "request_delay_seconds": "1.0",
        "request_jitter_seconds": "0.5",
        "http_max_attempts": 4,
    }
    base.update(overrides)
    return BatchIdentity(**base)


def _outcome(
    sample_no: int, status: str = "completed", **overrides: Any
) -> TargetOutcome:
    base: dict[str, Any] = {
        "sample_no": sample_no,
        "oe_norm": f"OE{sample_no}",
        "status": status,
        "run_id": uuid4() if status == "completed" else None,
        "error_code": None if status == "completed" else "BOOM",
        "error_detail": None if status == "completed" else "boom",
        "duration_ms": 10,
        "recorded_at": "2026-07-26T00:00:00+00:00",
    }
    base.update(overrides)
    return TargetOutcome(**base)


def _targets_document(count: int = 3, **overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": measurement.COVERAGE_TARGETS_SCHEMA_VERSION,
        "source_sha256": "c" * 64,
        "targets": [
            {
                "sample_no": index,
                "category": "radiator",
                "oe_raw": f"09G 40906{index}",
                "oe_norm": f"09G40906{index}",
                "title": f"Радиатор {index}",
                "baseline_after_filter": index,
            }
            for index in range(1, count + 1)
        ],
    }
    document.update(overrides)
    return document


def _write_targets(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "targets.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def _offer(**overrides: Any) -> CatalogDiscoveryOffer:
    payload: dict[str, Any] = {
        "source_listing_id": "listing-1",
        "seller_id": "seller-1",
        "sku": "7E5827505A",
        "brand": "Polcar",
        "title": "Замок кришки багажника VW T5",
        "is_owned": False,
        "is_available": True,
        "selection_status": "REFERENCE_ONLY",
        "selection_details": {"gates": {"oem_identity": {"evidence": "ARTICLE_FIELD"}}},
        "raw_snapshot": {},
    }
    payload.update(overrides)
    return CatalogDiscoveryOffer(**payload)


# --------------------------------------------------------------------------
# §2.7 metrics — typical, boundary, degenerate
# --------------------------------------------------------------------------


def test_metrics_reproduce_the_published_2026_07_19_baseline() -> None:
    metrics = coverage_metrics(BASELINE_VECTOR)

    assert metrics.total == 76
    assert metrics.mean == Decimal("2.5333")
    assert metrics.median == Decimal("1.5000")
    assert metrics.share_ge3 == Decimal("0.3333")
    assert metrics.share_zero == Decimal("0.2333")
    assert metrics.distribution == {"0": 7, "1-2": 13, "3-4": 6, "5+": 4}


def test_metrics_on_empty_sample_do_not_divide_by_zero() -> None:
    metrics = coverage_metrics([])

    assert metrics.target_count == 0
    assert metrics.total == 0
    assert metrics.mean is None
    assert metrics.median is None
    assert metrics.share_ge3 is None
    assert metrics.share_zero is None
    assert metrics.distribution == {"0": 0, "1-2": 0, "3-4": 0, "5+": 0}


@pytest.mark.parametrize(
    ("counts", "mean", "median"),
    [
        ((0,), Decimal("0.0000"), Decimal("0.0000")),
        ((5,), Decimal("5.0000"), Decimal("5.0000")),
        ((1, 2), Decimal("1.5000"), Decimal("1.5000")),
        ((1, 2, 3), Decimal("2.0000"), Decimal("2.0000")),
        ((2, 2, 2, 2), Decimal("2.0000"), Decimal("2.0000")),
    ],
)
def test_metrics_boundary_sample_sizes(
    counts: tuple[int, ...],
    mean: Decimal,
    median: Decimal,
) -> None:
    metrics = coverage_metrics(counts)

    assert metrics.mean == mean
    assert metrics.median == median


def test_share_ge3_threshold_is_inclusive_at_three() -> None:
    assert coverage_metrics([2, 2]).share_ge3 == Decimal("0.0000")
    assert coverage_metrics([3, 3]).share_ge3 == Decimal("1.0000")
    assert coverage_metrics([2, 3]).share_ge3 == Decimal("0.5000")


def test_metrics_on_identical_values_report_zero_spread() -> None:
    metrics = coverage_metrics([4, 4, 4, 4, 4])

    assert metrics.mean == Decimal("4.0000")
    assert metrics.median == Decimal("4.0000")
    assert metrics.share_ge3 == Decimal("1.0000")
    assert metrics.share_zero == Decimal("0.0000")


# --------------------------------------------------------------------------
# Cohort predicates
# --------------------------------------------------------------------------


def test_exact_article_match_enters_the_baseline_cohort() -> None:
    facts = offer_facts(_offer(sku="7E5 827 505 A"))

    assert COHORT_BASELINE in cohort_membership("7E5827505A", facts)


def test_title_only_evidence_is_excluded_from_the_baseline_cohort() -> None:
    """The 2026-07-19 definition counted the article field, never the title."""

    facts = offer_facts(
        _offer(
            sku="POL-1234",
            title="Замок 7E5827505A VW T5",
            selection_details={"gates": {"oem_identity": {"evidence": "TITLE"}}},
        )
    )
    membership = cohort_membership("7E5827505A", facts)

    assert COHORT_BASELINE not in membership
    assert COHORT_IDENTITY in membership


def test_kemp_brand_is_excluded_from_every_cohort() -> None:
    facts = offer_facts(_offer(brand="KEMP", selection_status="PRICING_EVIDENCE"))

    assert cohort_membership("7E5827505A", facts) == frozenset()


def test_cyrillic_kemp_lookalike_is_still_excluded() -> None:
    facts = offer_facts(_offer(brand="КЕМП", selection_status="PRICING_EVIDENCE"))

    assert cohort_membership("7E5827505A", facts) == frozenset()


def test_used_marker_excludes_from_baseline_and_plan_cohorts() -> None:
    facts = offer_facts(
        _offer(
            title="Замок кришки багажника VW T5 б/у",
            selection_status="PRICING_EVIDENCE",
        )
    )
    membership = cohort_membership("7E5827505A", facts)

    assert COHORT_BASELINE not in membership
    assert COHORT_PLAN_S not in membership


def test_owned_seller_is_excluded_from_every_cohort() -> None:
    facts = offer_facts(_offer(is_owned=True, selection_status="PRICING_EVIDENCE"))

    assert cohort_membership("7E5827505A", facts) == frozenset()


def test_plan_cohort_requires_a_pricing_evidence_verdict() -> None:
    review = offer_facts(_offer(selection_status="REFERENCE_ONLY"))
    comparable = offer_facts(_offer(selection_status="PRICING_EVIDENCE"))

    assert COHORT_PLAN_S not in cohort_membership("7E5827505A", review)
    assert COHORT_PLAN_S in cohort_membership("7E5827505A", comparable)


def test_plan_cohort_drops_explicitly_unavailable_offers_but_keeps_unknown() -> None:
    unavailable = offer_facts(
        _offer(selection_status="PRICING_EVIDENCE", is_available=False)
    )
    unknown = offer_facts(
        _offer(selection_status="PRICING_EVIDENCE", is_available=None)
    )

    assert COHORT_PLAN_S not in cohort_membership("7E5827505A", unavailable)
    assert COHORT_PLAN_S in cohort_membership("7E5827505A", unknown)


def test_missing_identity_evidence_keeps_the_offer_out_of_cohort_b() -> None:
    facts = offer_facts(
        _offer(
            sku=None,
            selection_details={"gates": {"oem_identity": {"evidence": None}}},
        )
    )

    assert COHORT_IDENTITY not in cohort_membership("7E5827505A", facts)


def test_offer_facts_tolerates_absent_selection_details() -> None:
    facts = offer_facts(_offer(selection_details={}))

    assert facts.oem_evidence is None


def test_used_marker_in_description_is_read_from_the_raw_snapshot() -> None:
    facts = offer_facts(
        _offer(raw_snapshot={"description": "Знято з робочої машини, вживаний"})
    )

    assert COHORT_BASELINE not in cohort_membership("7E5827505A", facts)


# --------------------------------------------------------------------------
# Seller deduplication
# --------------------------------------------------------------------------


def test_one_seller_contributes_at_most_one_offer() -> None:
    offers = [
        offer_facts(_offer(source_listing_id="a", seller_id="seller-1")),
        offer_facts(_offer(source_listing_id="b", seller_id="seller-1")),
    ]

    assert cohort_counts("7E5827505A", offers)[COHORT_BASELINE] == 1


def test_offers_without_a_seller_id_are_not_collapsed_together() -> None:
    offers = [
        offer_facts(_offer(source_listing_id="a", seller_id="")),
        offer_facts(_offer(source_listing_id="b", seller_id="")),
    ]

    assert cohort_counts("7E5827505A", offers)[COHORT_BASELINE] == 2


def test_cohort_counts_on_an_empty_run_are_zero_not_missing() -> None:
    counts = cohort_counts("7E5827505A", [])

    assert counts == {
        COHORT_BASELINE: 0,
        COHORT_IDENTITY: 0,
        COHORT_PLAN_S: 0,
    }


# --------------------------------------------------------------------------
# Target list loading
# --------------------------------------------------------------------------


def test_targets_load_and_hash_the_exact_bytes_read(tmp_path: Path) -> None:
    path = _write_targets(tmp_path, _targets_document())
    targets = load_coverage_targets(path)

    assert len(targets) == 3
    assert targets.targets[0].oe_norm == "09G409061"
    assert len(targets.content_sha256) == 64


def test_targets_are_sorted_by_sample_number(tmp_path: Path) -> None:
    document = _targets_document()
    document["targets"].reverse()
    targets = load_coverage_targets(_write_targets(tmp_path, document))

    assert [target.sample_no for target in targets.targets] == [1, 2, 3]


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda doc: doc.update(schema_version="other"),
            "COVERAGE_TARGETS_SCHEMA_MISMATCH",
        ),
        (lambda doc: doc.update(targets=[]), "COVERAGE_TARGETS_EMPTY"),
    ],
)
def test_targets_reject_malformed_documents(
    tmp_path: Path,
    mutate: Any,
    code: str,
) -> None:
    document = _targets_document()
    mutate(document)

    with pytest.raises(CoverageMeasurementError) as error:
        load_coverage_targets(_write_targets(tmp_path, document))

    assert error.value.code == code


def test_targets_reject_a_duplicate_sample_number(tmp_path: Path) -> None:
    document = _targets_document(count=2)
    document["targets"][1]["sample_no"] = 1

    with pytest.raises(CoverageMeasurementError) as error:
        load_coverage_targets(_write_targets(tmp_path, document))

    assert error.value.code == "COVERAGE_TARGET_DUPLICATE"


def test_targets_reject_a_duplicate_oe(tmp_path: Path) -> None:
    document = _targets_document(count=2)
    document["targets"][1]["oe_norm"] = document["targets"][0]["oe_norm"]
    document["targets"][1]["oe_raw"] = document["targets"][0]["oe_raw"]

    with pytest.raises(CoverageMeasurementError) as error:
        load_coverage_targets(_write_targets(tmp_path, document))

    assert error.value.code == "COVERAGE_TARGET_DUPLICATE"


def test_targets_reject_a_row_without_a_usable_identifier(tmp_path: Path) -> None:
    document = _targets_document(count=1)
    document["targets"][0]["oe_raw"] = "---"
    document["targets"][0]["oe_norm"] = ""

    with pytest.raises(CoverageMeasurementError) as error:
        load_coverage_targets(_write_targets(tmp_path, document))

    assert error.value.code == "COVERAGE_TARGET_IDENTIFIER_REQUIRED"


def test_missing_targets_file_is_reported_by_code(tmp_path: Path) -> None:
    with pytest.raises(CoverageMeasurementError) as error:
        load_coverage_targets(tmp_path / "absent.json")

    assert error.value.code == "COVERAGE_TARGETS_MISSING"


# --------------------------------------------------------------------------
# Checkpoint
# --------------------------------------------------------------------------


def test_new_checkpoint_writes_a_header(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "checkpoint.jsonl"
    MeasurementCheckpoint.open(path, _identity())

    header = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert header["record"] == "header"
    assert header["identity"]["search_page_limit"] == 10


def test_checkpoint_reopens_and_reports_completed_targets(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.jsonl"
    first = MeasurementCheckpoint.open(path, _identity())
    first.record(_outcome(1))

    second = MeasurementCheckpoint.open(path, _identity())

    assert set(second.outcomes) == {1}
    assert second.outcomes[1].is_completed


def test_resume_refuses_a_different_page_limit(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.jsonl"
    MeasurementCheckpoint.open(path, _identity())

    with pytest.raises(CoverageMeasurementError) as error:
        MeasurementCheckpoint.open(path, _identity(search_page_limit=3))

    assert error.value.code == "COVERAGE_CHECKPOINT_IDENTITY_MISMATCH"
    assert "search_page_limit" in str(error.value)


def test_resume_refuses_a_different_target_list(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.jsonl"
    MeasurementCheckpoint.open(path, _identity())

    with pytest.raises(CoverageMeasurementError) as error:
        MeasurementCheckpoint.open(path, _identity(targets_sha256="f" * 64))

    assert error.value.code == "COVERAGE_CHECKPOINT_IDENTITY_MISMATCH"


def test_resume_refuses_a_different_selection_config(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.jsonl"
    MeasurementCheckpoint.open(path, _identity())

    with pytest.raises(CoverageMeasurementError) as error:
        MeasurementCheckpoint.open(path, _identity(selection_config_sha256="d" * 64))

    assert error.value.code == "COVERAGE_CHECKPOINT_IDENTITY_MISMATCH"


def test_last_record_for_a_target_wins(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.jsonl"
    checkpoint = MeasurementCheckpoint.open(path, _identity())
    checkpoint.record(_outcome(1, status="failed"))
    checkpoint.record(_outcome(1))

    reopened = MeasurementCheckpoint.open(path, _identity())

    assert reopened.outcomes[1].is_completed


def test_a_truncated_final_line_still_resumes(tmp_path: Path) -> None:
    """A kill during the last write must not strand the whole batch."""

    path = tmp_path / "checkpoint.jsonl"
    checkpoint = MeasurementCheckpoint.open(path, _identity())
    checkpoint.record(_outcome(1))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"record": "target", "sample_n')

    reopened = MeasurementCheckpoint.open(path, _identity())

    assert set(reopened.outcomes) == {1}


def test_a_corrupt_middle_line_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.jsonl"
    checkpoint = MeasurementCheckpoint.open(path, _identity())
    with path.open("a", encoding="utf-8") as handle:
        handle.write("not json\n")
    checkpoint.record(_outcome(2))

    with pytest.raises(CoverageMeasurementError) as error:
        MeasurementCheckpoint.open(path, _identity())

    assert error.value.code == "COVERAGE_CHECKPOINT_CORRUPT"


def test_empty_checkpoint_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.jsonl"
    path.write_text("", encoding="utf-8")

    with pytest.raises(CoverageMeasurementError) as error:
        MeasurementCheckpoint.open(path, _identity())

    assert error.value.code == "COVERAGE_CHECKPOINT_EMPTY"


def test_pending_skips_completed_and_retries_failed(tmp_path: Path) -> None:
    targets = load_coverage_targets(
        _write_targets(tmp_path, _targets_document(count=3))
    ).targets
    checkpoint = MeasurementCheckpoint.open(tmp_path / "cp.jsonl", _identity())
    # The OE must match the frozen list: pending() is fail-closed on it, so a
    # placeholder here would exercise the mismatch guard instead of resumption.
    checkpoint.record(_outcome(1, oe_norm=targets[0].oe_norm))
    checkpoint.record(_outcome(2, status="failed", oe_norm=targets[1].oe_norm))

    retried = checkpoint.pending(targets)
    left_alone = checkpoint.pending(targets, retry_failed=False)

    assert [target.sample_no for target in retried] == [2, 3]
    assert [target.sample_no for target in left_alone] == [3]


def test_pending_refuses_checkpoint_oe_mismatch(tmp_path: Path) -> None:
    targets = load_coverage_targets(
        _write_targets(tmp_path, _targets_document(count=1))
    ).targets
    checkpoint = MeasurementCheckpoint.open(tmp_path / "cp.jsonl", _identity())
    checkpoint.record(_outcome(1, oe_norm="DIFFERENT"))

    with pytest.raises(CoverageMeasurementError) as error:
        checkpoint.pending(targets)

    assert error.value.code == "COVERAGE_CHECKPOINT_TARGET_MISMATCH"


def test_pending_refuses_checkpoint_sample_outside_target_set(tmp_path: Path) -> None:
    targets = load_coverage_targets(
        _write_targets(tmp_path, _targets_document(count=1))
    ).targets
    checkpoint = MeasurementCheckpoint.open(tmp_path / "cp.jsonl", _identity())
    checkpoint.record(_outcome(99, oe_norm="UNLISTED"))

    with pytest.raises(CoverageMeasurementError) as error:
        checkpoint.pending(targets)

    assert error.value.code == "COVERAGE_CHECKPOINT_TARGET_MISMATCH"


# --------------------------------------------------------------------------
# Driver resumption
# --------------------------------------------------------------------------


@asynccontextmanager
async def _fake_session():
    yield object()


class _Snapshot:
    def __init__(self, run_id: UUID) -> None:
        self.run_id = run_id


async def test_batch_records_every_outcome_and_resumes_after_a_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = load_coverage_targets(
        _write_targets(tmp_path, _targets_document(count=3))
    )
    attempted: list[str] = []

    async def _collect(_session: Any, **kwargs: Any) -> _Snapshot:
        attempted.append(kwargs["oe"])
        if kwargs["oe"] == "09G 409062":
            raise RuntimeError("network died")
        return _Snapshot(uuid4())

    monkeypatch.setattr(measurement, "collect_catalog_discovery", _collect)

    checkpoint = MeasurementCheckpoint.open(tmp_path / "cp.jsonl", _identity())
    first = await run_coverage_batch(
        lambda: _fake_session(),
        targets=targets,
        checkpoint=checkpoint,
        workspace_id=WORKSPACE_ID,
        settings=object(),
    )

    assert (first.attempted, first.completed, first.failed) == (3, 2, 1)
    assert len(attempted) == 3

    # A fresh process reopens the same file and only the failure is left.
    attempted.clear()
    resumed_checkpoint = MeasurementCheckpoint.open(tmp_path / "cp.jsonl", _identity())
    second = await run_coverage_batch(
        lambda: _fake_session(),
        targets=targets,
        checkpoint=resumed_checkpoint,
        workspace_id=WORKSPACE_ID,
        settings=object(),
    )

    assert attempted == ["09G 409062"]
    assert (second.attempted, second.skipped) == (1, 2)


async def test_batch_limit_defers_the_remaining_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = load_coverage_targets(
        _write_targets(tmp_path, _targets_document(count=5))
    )

    async def _collect(_session: Any, **_kwargs: Any) -> _Snapshot:
        return _Snapshot(uuid4())

    monkeypatch.setattr(measurement, "collect_catalog_discovery", _collect)
    checkpoint = MeasurementCheckpoint.open(tmp_path / "cp.jsonl", _identity())

    progress = await run_coverage_batch(
        lambda: _fake_session(),
        targets=targets,
        checkpoint=checkpoint,
        workspace_id=WORKSPACE_ID,
        settings=object(),
        limit=2,
    )

    assert (progress.attempted, progress.completed, progress.skipped) == (2, 2, 3)
    assert set(checkpoint.outcomes) == {1, 2}


async def test_batch_waits_between_targets_but_not_before_the_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = load_coverage_targets(
        _write_targets(tmp_path, _targets_document(count=3))
    )
    slept: list[float] = []

    async def _collect(_session: Any, **_kwargs: Any) -> _Snapshot:
        return _Snapshot(uuid4())

    async def _sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(measurement, "collect_catalog_discovery", _collect)
    checkpoint = MeasurementCheckpoint.open(tmp_path / "cp.jsonl", _identity())

    await run_coverage_batch(
        lambda: _fake_session(),
        targets=targets,
        checkpoint=checkpoint,
        workspace_id=WORKSPACE_ID,
        settings=object(),
        target_delay_seconds=1.5,
        sleep=_sleep,
    )

    assert slept == [1.5, 1.5]


# --------------------------------------------------------------------------
# Anti-bot telemetry
# --------------------------------------------------------------------------


def test_telemetry_on_no_requests_returns_no_quantiles() -> None:
    telemetry = summarize_request_telemetry([])

    assert telemetry.request_count == 0
    assert telemetry.latency_p50_ms is None
    assert telemetry.latency_p95_ms is None
    assert telemetry.latency_max_ms is None
    assert telemetry.status_histogram == {}


def test_telemetry_counts_statuses_retries_and_latency() -> None:
    telemetry = summarize_request_telemetry(
        [(200, 1, 100), (200, 1, 200), (429, 3, 900), (200, 1, 300)]
    )

    assert telemetry.request_count == 4
    assert telemetry.status_histogram == {"200": 3, "429": 1}
    assert telemetry.retried_request_count == 1
    assert telemetry.attempts_total == 6
    assert telemetry.latency_p50_ms == 200
    assert telemetry.latency_p95_ms == 900
    assert telemetry.latency_max_ms == 900


def test_single_request_quantiles_name_that_request() -> None:
    telemetry = summarize_request_telemetry([(200, 1, 512)])

    assert telemetry.latency_p50_ms == 512
    assert telemetry.latency_p95_ms == 512
    assert telemetry.latency_max_ms == 512


def test_blocking_markers_are_detected_case_insensitively() -> None:
    assert scan_blocking_markers("<div>Please solve the CAPTCHA</div>") == ("captcha",)
    assert scan_blocking_markers("Занадто багато запитів") == ()
    assert "too many requests" in scan_blocking_markers("HTTP 429 Too Many Requests")


def test_clean_body_reports_no_markers() -> None:
    assert scan_blocking_markers("<html><body>Результати пошуку</body></html>") == ()


# A healthy Prom search page really does ship these two strings, measured on
# run a6ee441f-846d-448f-b544-f0aabbb27b68: five 200s, 123 products, five
# "recaptcha" hits.  A keyword-only detector called every one of them a block.
PROM_AMBIENT_CAPTCHA_MARKUP = (
    '{"id":"CHAT_385_SHOW_BUYER_RECAPTCHA_DESKTOP","value":false},'
    '{"context":{"recaptchaToken":"6Ld8EJcUAAAAAH3zNExLrNTQaYCdar_IideOVBah"}}'
)


def test_ambient_recaptcha_config_on_a_full_page_is_not_a_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        measurement,
        "parse_search",
        lambda *_a, **_k: ListingPage(
            products=[object()] * 29,
            total=29,
            lang="ua",
            outcome="RESULTS",
        ),
    )

    assessment = measurement.assess_capture_body(PROM_AMBIENT_CAPTCHA_MARKUP)

    assert assessment.product_count == 29
    assert assessment.parser_outcome == "RESULTS"
    assert assessment.markers == ()
    assert assessment.is_suspected_block is False
    assert assessment.yielded_no_products is False


def test_same_markers_on_a_page_without_products_are_a_suspected_block() -> None:
    assessment = measurement.assess_capture_body(PROM_AMBIENT_CAPTCHA_MARKUP)

    assert assessment.parser_outcome.startswith("UNPARSEABLE:")
    assert assessment.markers == ("captcha", "recaptcha")
    assert assessment.is_suspected_block is True


def test_valid_empty_market_with_ambient_recaptcha_is_not_a_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        measurement,
        "parse_search",
        lambda *_a, **_k: ListingPage(
            products=[],
            total=0,
            lang="ua",
            outcome="EMPTY_SEARCH_RESULT",
        ),
    )

    assessment = measurement.assess_capture_body(PROM_AMBIENT_CAPTCHA_MARKUP)

    assert assessment.product_count == 0
    assert assessment.parser_outcome == "EMPTY_SEARCH_RESULT"
    assert assessment.markers == ()
    assert assessment.yielded_no_products is True
    assert assessment.is_suspected_block is False


def test_empty_page_without_markers_is_counted_but_not_called_a_block() -> None:
    assessment = measurement.assess_capture_body("<html>Нічого не знайдено</html>")

    assert assessment.yielded_no_products is True
    assert assessment.is_suspected_block is False


def test_unparseable_body_counts_as_zero_products_without_raising() -> None:
    assert measurement.parsed_product_count("<<<not html at all") == 0


def test_telemetry_carries_block_counters() -> None:
    telemetry = summarize_request_telemetry(
        [(200, 1, 100)],
        blocking_marker_hits={"captcha": 1},
        suspected_block_count=1,
        pages_without_products=2,
        scanned_blob_count=3,
    )

    assert telemetry.suspected_block_count == 1
    assert telemetry.pages_without_products == 2
    assert telemetry.scanned_blob_count == 3
    assert telemetry.as_dict()["suspected_block_count"] == 1


def test_report_exit_code_fails_an_incomplete_checkpoint() -> None:
    complete = type("Report", (), {"failed_rows": ()})()
    incomplete = type("Report", (), {"failed_rows": (object(),)})()

    assert report_exit_code(complete) == 0
    assert report_exit_code(incomplete) == 1
