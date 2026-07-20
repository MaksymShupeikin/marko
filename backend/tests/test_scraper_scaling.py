from datetime import UTC, datetime, timedelta

import pytest

from marko.services.scraper_scaling import (
    AttemptMetricSample,
    TargetMetricSample,
    aggregate_collection_metrics,
    calculate_capacity,
    calculate_completeness_distribution,
    calculate_derived_capacity,
    calculate_retry_amplification,
    calculate_storage,
    estimate_batch_completion,
    parallel_efficiency,
    reconcile_items,
    reconcile_submission_cohort,
    request_retry_sanity_check,
    required_capacity_plan,
    wilson_confidence_interval,
)


def test_retry_amplification_uses_direct_telemetry_counts() -> None:
    result = calculate_retry_amplification(
        unique_logical_items_total=10,
        logical_http_requests_total=30,
        physical_http_attempts_total=36,
        task_executions_total=12,
    )

    assert result.http_attempts_per_request == 1.2
    assert result.task_executions_per_item == 1.2
    assert result.http_attempts_per_item == 3.6


def test_terminal_worker_capacity_is_not_divided_by_retries_twice() -> None:
    result = calculate_capacity(
        arrival_rate_urls_per_second=0.1,
        service_rate_per_worker=0.2,
        worker_count=4,
        average_attempts_per_unique_url=3,
        backlog=8,
    )

    assert result.terminal_capacity_items_per_second == 0.8
    assert result.queue_drain_seconds_with_arrivals == pytest.approx(
        8 / (0.8 - 0.1),
        abs=1e-3,
    )


def test_effective_capacity_selects_source_bottleneck_and_success_capacity() -> None:
    result = calculate_derived_capacity(
        arrival_rate_items_per_second=0.1,
        mean_terminal_item_time_seconds=5,
        worker_count=2,
        parallel_efficiency=0.8,
        average_http_attempts_per_item=3.6,
        source_request_budget_per_second=1,
        average_database_writes_per_item=10,
        database_write_capacity_per_second=10,
        queue_capacity_items_per_second=2,
        success_probability=0.9,
        backlog=10,
    )

    assert result.worker_capacity_items_per_second == 0.32
    assert result.source_capacity_items_per_second == pytest.approx(
        1 / 3.6,
        abs=1e-8,
    )
    assert result.limiting_subsystems == ("source",)
    assert result.successful_capacity_items_per_second == 0.25
    assert result.engineering_target_met is True


def test_reconciliation_detects_silent_loss() -> None:
    result = reconcile_items(
        valid_total=10,
        queued=1,
        running=1,
        retry_wait=1,
        success=5,
        failed=1,
    )

    assert result.silent_loss == 1
    assert result.reconciled is False
    assert result.terminal_rate == 0.6


def test_retry_sanity_model_uses_bounded_attempt_count() -> None:
    result = request_retry_sanity_check(
        attempt_success_probability=0.5,
        max_physical_attempts=3,
    )

    assert result.request_success_probability == 0.875
    assert result.expected_physical_attempts == 1.75


def test_parallel_efficiency_and_batch_lower_bound() -> None:
    assert (
        parallel_efficiency(
            measured_capacity_at_c=3,
            worker_count=4,
            measured_capacity_at_one=1,
        )
        == 0.75
    )
    result = estimate_batch_completion(
        terminal_item_times_seconds=[10, 20, 30],
        worker_count=2,
        parallel_efficiency_value=0.75,
        physical_http_attempts_total=100,
        source_request_budget_per_second=2,
        database_writes_total=600,
        database_write_capacity_per_second=20,
        scheduler_overhead_seconds=5,
        tail_seconds=7,
    )

    assert result.worker_lower_bound_seconds == 40
    assert result.source_lower_bound_seconds == 50
    assert result.database_lower_bound_seconds == 30
    assert result.estimated_seconds == 62


def test_parallel_efficiency_is_bounded_for_superlinear_measurement() -> None:
    assert (
        parallel_efficiency(
            measured_capacity_at_c=3,
            worker_count=2,
            measured_capacity_at_one=1,
        )
        == 1
    )


def test_required_capacity_checks_external_subsystems() -> None:
    result = required_capacity_plan(
        peak_logical_items=1000,
        completion_slo_seconds=100,
        mean_terminal_item_time_seconds=2,
        assumed_parallel_efficiency=0.8,
        source_capacity_items_per_second=8,
        database_capacity_items_per_second=20,
        queue_capacity_items_per_second=12,
    )

    assert result.required_terminal_capacity_items_per_second == 10
    assert result.initial_worker_count == 25
    assert result.source_sufficient is False
    assert result.feasible_without_subsystem_changes is False


def test_required_capacity_is_not_feasible_when_subsystem_limits_are_unknown() -> None:
    result = required_capacity_plan(
        peak_logical_items=100,
        completion_slo_seconds=100,
        mean_terminal_item_time_seconds=1,
        assumed_parallel_efficiency=0.8,
        source_capacity_items_per_second=None,
        database_capacity_items_per_second=None,
        queue_capacity_items_per_second=None,
    )

    assert result.source_sufficient is None
    assert result.database_sufficient is None
    assert result.queue_sufficient is None
    assert result.feasible_without_subsystem_changes is False


def test_derived_capacity_does_not_claim_stability_with_unknown_limits() -> None:
    result = calculate_derived_capacity(
        arrival_rate_items_per_second=0.1,
        mean_terminal_item_time_seconds=1,
        worker_count=2,
        parallel_efficiency=1,
        average_http_attempts_per_item=1,
        source_request_budget_per_second=10,
        average_database_writes_per_item=1,
        database_write_capacity_per_second=None,
        queue_capacity_items_per_second=None,
        success_probability=1,
        backlog=1,
    )

    assert result.stable is False
    assert result.engineering_target_met is False
    assert "subsystem_capacity_unknown_stability_not_proven" in result.warnings


def test_storage_model_keeps_raw_and_structured_layers_separate() -> None:
    result = calculate_storage(
        raw_unique_bytes=1000,
        compression_ratio=0.4,
        structured_bytes=200,
        attempt_journal_bytes=100,
        observation_bytes=300,
        recommendation_lineage_bytes=50,
        index_and_database_overhead_bytes=25,
    )

    assert result.raw_stored_bytes == 400
    assert result.net_storage_bytes == 1075


def test_comparison_aggregate_reconciles_targets_and_uses_terminal_time() -> None:
    created = datetime(2026, 7, 16, tzinfo=UTC)
    targets = [
        TargetMetricSample(
            input_hash="a",
            canonical_url="https://prom.ua/ua/p1-a.html",
            status="succeeded",
            dependent_items=2,
            created_at=created,
            first_started_at=created + timedelta(seconds=1),
            finished_at=created + timedelta(seconds=5),
            raw_size_bytes=100,
            structured_size_bytes=50,
            metadata_size_bytes=20,
            structured_completeness=1,
            item_key="a",
        ),
        TargetMetricSample(
            input_hash="b",
            canonical_url="https://prom.ua/ua/p2-b.html",
            status="retryable_failure",
            dependent_items=1,
            created_at=created,
            first_started_at=created + timedelta(seconds=2),
            finished_at=None,
            raw_size_bytes=10,
            structured_size_bytes=0,
            metadata_size_bytes=20,
            structured_completeness=None,
            item_key="b",
        ),
    ]
    attempts = [
        AttemptMetricSample(
            status="succeeded",
            network_attempted=True,
            wall_time_ms=1000,
            cpu_time_ms=100,
            memory_peak_bytes=1024,
            item_key="a",
        ),
        AttemptMetricSample(
            status="retryable_failure",
            network_attempted=True,
            wall_time_ms=2000,
            cpu_time_ms=200,
            memory_peak_bytes=2048,
            item_key="b",
        ),
    ]

    result = aggregate_collection_metrics(
        targets,
        attempts,
        worker_count=1,
        arrival_rate_urls_per_second=0,
        now=created + timedelta(seconds=10),
    )

    assert result.unique_inputs_total == 2
    assert result.duplicate_input_total == 1
    assert result.reconciliation.reconciled is True
    assert result.reconciliation.retry_wait == 1
    assert result.capacity.mean_terminal_item_time_seconds == 1


def test_submission_cohort_reconciliation_accounts_for_every_admitted_item() -> None:
    result = reconcile_submission_cohort(
        submitted=12,
        deduplicated=2,
        rejected=1,
        admitted=9,
        queued=1,
        running=1,
        retry_wait=1,
        success=5,
        failed=1,
        cancelled=0,
    )

    assert result.unaccounted_loss == 0
    assert result.reconciled is True


def test_submission_cohort_reconciliation_rejects_an_invalid_admission_equation() -> (
    None
):
    with pytest.raises(
        ValueError,
        match="submitted must equal deduplicated \\+ rejected \\+ admitted",
    ):
        reconcile_submission_cohort(
            submitted=12,
            deduplicated=2,
            rejected=1,
            admitted=8,
            queued=1,
            running=1,
            retry_wait=1,
            success=4,
            failed=1,
            cancelled=0,
        )


def test_submission_cohort_reconciliation_exposes_silent_loss() -> None:
    result = reconcile_submission_cohort(
        submitted=10,
        deduplicated=0,
        rejected=0,
        admitted=10,
        queued=1,
        running=1,
        retry_wait=1,
        success=5,
        failed=1,
        cancelled=0,
    )

    assert result.unaccounted_loss == 1
    assert result.reconciled is False


def test_wilson_interval_reports_uncertainty_without_normal_approximation_edges() -> (
    None
):
    result = wilson_confidence_interval(successes=95, sample_size=100)

    assert result.estimate == 0.95
    assert result.lower == pytest.approx(0.88825, abs=1e-5)
    assert result.upper == pytest.approx(0.97846, abs=1e-5)
    assert result.lower < result.estimate < result.upper


def test_wilson_interval_for_an_empty_cohort_is_explicitly_unknown() -> None:
    result = wilson_confidence_interval(successes=0, sample_size=0)

    assert result.estimate is None
    assert result.lower is None
    assert result.upper is None


def test_completeness_distribution_is_weighted_and_tracks_critical_fields() -> None:
    result = calculate_completeness_distribution(
        [
            {
                "source_url": "https://prom.ua/p1",
                "raw_capture_id": "capture-1",
                "price": "100.00",
            },
            {
                "source_url": "https://prom.ua/p2",
                "raw_capture_id": "capture-2",
                "price": None,
            },
            {
                "source_url": "https://prom.ua/p3",
                "raw_capture_id": None,
                "price": "120.00",
            },
        ],
        field_weights={"source_url": 2, "raw_capture_id": 2, "price": 1},
        critical_fields={"source_url", "raw_capture_id"},
    )

    assert result.count == 3
    assert result.minimum == 0.6
    assert result.p50 == 0.8
    assert result.critical_field_missing_rate == pytest.approx(1 / 3, abs=1e-8)
    assert result.per_field_missing_rate == {
        "source_url": 0.0,
        "raw_capture_id": pytest.approx(1 / 3, abs=1e-8),
        "price": pytest.approx(1 / 3, abs=1e-8),
    }
