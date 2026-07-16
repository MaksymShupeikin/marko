import pytest

from marko.services.scraper_benchmark import (
    BenchmarkAcceptance,
    BenchmarkRun,
    evaluate_benchmark_series,
)


def _run(concurrency, terminal, duration, **overrides):
    values = {
        "concurrency": concurrency,
        "item_kind": "store_sync",
        "workload_class": "medium_store",
        "configuration_fingerprint": "config",
        "dataset_fingerprint": "dataset",
        "valid_items": 100,
        "terminal_items": terminal,
        "successful_items": terminal,
        "duration_seconds": duration,
        "latency_p95_seconds": 10,
        "latency_p99_seconds": 15,
        "http_attempts_per_item": 2,
        "source_utilization": 0.5,
        "database_utilization": 0.4,
        "error_rate": 0,
        "rate_limited_attempt_rate": 0,
        "evidence_coverage": 1,
        "silent_loss": 0,
    }
    values.update(overrides)
    return BenchmarkRun(**values)


def _acceptance():
    return BenchmarkAcceptance(
        required_terminal_capacity=1.5,
        latency_p95_slo_seconds=20,
        latency_p99_slo_seconds=30,
        max_http_attempts_per_item=3,
    )


def test_benchmark_selects_smallest_accepted_concurrency() -> None:
    decision = evaluate_benchmark_series(
        [
            _run(1, terminal=100, duration=100),
            _run(2, terminal=100, duration=50),
            _run(4, terminal=100, duration=30),
        ],
        _acceptance(),
    )

    assert decision.selected_concurrency == 2
    assert decision.production_capacity_proven is True
    assert decision.evaluations[1].system_parallel_efficiency == 1
    assert (
        decision.stop_reason
        == "smallest_concurrency_meeting_all_acceptance_conditions"
    )


def test_benchmark_rejects_capacity_that_hurts_success_or_source_headroom() -> None:
    decision = evaluate_benchmark_series(
        [
            _run(1, terminal=100, duration=100),
            _run(
                2,
                terminal=100,
                duration=40,
                successful_items=70,
                error_rate=0.3,
                source_utilization=0.9,
                rate_limited_attempt_rate=0.2,
            ),
        ],
        _acceptance(),
    )

    second = decision.evaluations[1]
    assert second.terminal_capacity == 2.5
    assert second.successful_capacity == 1.75
    assert second.accepted is False
    assert "source_headroom_failed" in second.rejection_reasons
    assert "error_slo_failed" in second.rejection_reasons
    assert decision.production_capacity_proven is False


def test_benchmark_requires_comparable_fingerprints() -> None:
    with pytest.raises(ValueError, match="same item kind"):
        evaluate_benchmark_series(
            [
                _run(1, 100, 100),
                _run(2, 100, 50, dataset_fingerprint="other"),
            ],
            _acceptance(),
        )


def test_benchmark_requires_useful_successful_capacity() -> None:
    decision = evaluate_benchmark_series(
        [
            _run(1, terminal=100, duration=100),
            _run(
                2,
                terminal=100,
                duration=40,
                successful_items=50,
            ),
        ],
        BenchmarkAcceptance(
            required_terminal_capacity=1.5,
            required_successful_capacity=1.5,
            minimum_success_rate=0.90,
            latency_p95_slo_seconds=20,
            latency_p99_slo_seconds=30,
            max_http_attempts_per_item=3,
        ),
    )

    second = decision.evaluations[1]
    assert second.capacity_pass is True
    assert second.successful_capacity == 1.25
    assert second.successful_capacity_pass is False
    assert (
        "successful_capacity_below_required"
        in second.rejection_reasons
    )
    assert second.accepted is False


def test_tiny_error_after_zero_does_not_create_false_saturation() -> None:
    decision = evaluate_benchmark_series(
        [
            _run(1, terminal=100, duration=100, error_rate=0),
            _run(2, terminal=100, duration=50, error_rate=0.000001),
        ],
        _acceptance(),
    )

    assert decision.first_saturation_concurrency is None
    assert decision.selected_concurrency == 2
    assert decision.production_capacity_proven is True


def test_first_materially_degraded_level_is_not_selected() -> None:
    decision = evaluate_benchmark_series(
        [
            _run(1, terminal=100, duration=100, error_rate=0),
            _run(2, terminal=100, duration=50, error_rate=0.02),
        ],
        BenchmarkAcceptance(
            required_terminal_capacity=1.5,
            latency_p95_slo_seconds=20,
            latency_p99_slo_seconds=30,
            max_http_attempts_per_item=3,
            max_error_rate=0.05,
        ),
    )

    assert decision.first_saturation_concurrency == 2
    assert decision.selected_concurrency is None
    assert decision.production_capacity_proven is False
