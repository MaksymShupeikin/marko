"""Evaluation contract for controlled scraper-scaling benchmark runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

from marko.services.scraper_scaling import parallel_efficiency


@dataclass(frozen=True)
class BenchmarkRun:
    concurrency: int
    item_kind: str
    workload_class: str
    configuration_fingerprint: str
    dataset_fingerprint: str
    valid_items: int
    terminal_items: int
    successful_items: int
    duration_seconds: float
    latency_p95_seconds: float
    latency_p99_seconds: float
    http_attempts_per_item: float
    source_utilization: float
    database_utilization: float
    error_rate: float
    rate_limited_attempt_rate: float
    evidence_coverage: float
    silent_loss: int
    worker_lost_total: int = 0

    def __post_init__(self) -> None:
        if self.concurrency < 1:
            raise ValueError("concurrency must be at least one")
        if not self.item_kind or not self.workload_class:
            raise ValueError("item kind and workload class are required")
        if not self.configuration_fingerprint or not self.dataset_fingerprint:
            raise ValueError("benchmark fingerprints are required")
        counts = (self.valid_items, self.terminal_items, self.successful_items)
        if any(value < 0 for value in counts):
            raise ValueError("benchmark item counts must be non-negative")
        if self.terminal_items > self.valid_items:
            raise ValueError("terminal items cannot exceed valid items")
        if self.successful_items > self.terminal_items:
            raise ValueError("successful items cannot exceed terminal items")
        if self.duration_seconds <= 0 or not math.isfinite(self.duration_seconds):
            raise ValueError("benchmark duration must be finite and positive")
        nonnegative = (
            self.latency_p95_seconds,
            self.latency_p99_seconds,
            self.http_attempts_per_item,
        )
        if any(value < 0 or not math.isfinite(value) for value in nonnegative):
            raise ValueError("latency and retry metrics must be finite")
        ratios = (
            self.source_utilization,
            self.database_utilization,
            self.error_rate,
            self.rate_limited_attempt_rate,
            self.evidence_coverage,
        )
        if any(not 0 <= value <= 1 or not math.isfinite(value) for value in ratios):
            raise ValueError("benchmark ratios must be finite and in [0, 1]")
        if self.silent_loss < 0 or self.worker_lost_total < 0:
            raise ValueError("loss counts must be non-negative")

    @property
    def terminal_capacity(self) -> float:
        return self.terminal_items / self.duration_seconds

    @property
    def successful_capacity(self) -> float:
        return self.successful_items / self.duration_seconds


@dataclass(frozen=True)
class BenchmarkAcceptance:
    required_terminal_capacity: float
    latency_p95_slo_seconds: float
    latency_p99_slo_seconds: float
    max_http_attempts_per_item: float
    required_successful_capacity: float | None = None
    minimum_success_rate: float = 0.95
    max_source_utilization: float = 0.70
    max_database_utilization: float = 0.70
    max_error_rate: float = 0.05
    max_rate_limited_attempt_rate: float = 0.01
    minimum_evidence_coverage: float = 1.0
    minimum_concurrency_levels: int = 2
    saturation_increment_threshold: float = 0.10

    def __post_init__(self) -> None:
        positive = (
            self.required_terminal_capacity,
            self.latency_p95_slo_seconds,
            self.latency_p99_slo_seconds,
            self.max_http_attempts_per_item,
        )
        if any(value <= 0 or not math.isfinite(value) for value in positive):
            raise ValueError("capacity, latency, and retry SLOs must be positive")
        ratios = (
            self.minimum_success_rate,
            self.max_source_utilization,
            self.max_database_utilization,
            self.max_error_rate,
            self.max_rate_limited_attempt_rate,
            self.minimum_evidence_coverage,
            self.saturation_increment_threshold,
        )
        if any(not 0 <= value <= 1 or not math.isfinite(value) for value in ratios):
            raise ValueError("acceptance ratios must be in [0, 1]")
        if self.required_successful_capacity is not None and (
            self.required_successful_capacity <= 0
            or not math.isfinite(self.required_successful_capacity)
        ):
            raise ValueError("required successful capacity must be positive")
        if self.minimum_concurrency_levels < 2:
            raise ValueError("at least two concurrency levels are required")


@dataclass(frozen=True)
class BenchmarkRunEvaluation:
    concurrency: int
    terminal_capacity: float
    successful_capacity: float
    system_parallel_efficiency: float
    worker_efficiency_interpretable: bool
    capacity_pass: bool
    successful_capacity_pass: bool
    latency_pass: bool
    retry_pass: bool
    source_headroom_pass: bool
    database_headroom_pass: bool
    error_pass: bool
    evidence_pass: bool
    reconciliation_pass: bool
    accepted: bool
    rejection_reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkDecision:
    item_kind: str
    workload_class: str
    configuration_fingerprint: str
    dataset_fingerprint: str
    evaluated_concurrency_levels: tuple[int, ...]
    evaluations: tuple[BenchmarkRunEvaluation, ...]
    selected_concurrency: int | None
    first_saturation_concurrency: int | None
    production_capacity_proven: bool
    stop_reason: str
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_benchmark_series(
    runs: list[BenchmarkRun],
    acceptance: BenchmarkAcceptance,
) -> BenchmarkDecision:
    """Select the smallest accepted concurrency from comparable runs."""

    if not runs:
        raise ValueError("at least one benchmark run is required")
    ordered = sorted(runs, key=lambda run: run.concurrency)
    baseline = next((run for run in ordered if run.concurrency == 1), None)
    if baseline is None or baseline.terminal_capacity <= 0:
        raise ValueError("a positive-capacity c=1 baseline is required")
    _validate_comparable_runs(ordered)
    evaluations: list[BenchmarkRunEvaluation] = []
    first_saturation: int | None = None
    previous = baseline
    for run in ordered:
        eta = parallel_efficiency(
            measured_capacity_at_c=run.terminal_capacity,
            worker_count=run.concurrency,
            measured_capacity_at_one=baseline.terminal_capacity,
        )
        interpretable = (
            run.source_utilization < acceptance.max_source_utilization
            and run.database_utilization < acceptance.max_database_utilization
        )
        checks = {
            "capacity_below_required": (
                run.terminal_capacity >= acceptance.required_terminal_capacity
            ),
            "successful_capacity_below_required": (
                run.successful_capacity
                >= (
                    acceptance.required_successful_capacity
                    if acceptance.required_successful_capacity is not None
                    else acceptance.required_terminal_capacity
                )
                and (run.successful_items / run.valid_items if run.valid_items else 0.0)
                >= acceptance.minimum_success_rate
            ),
            "latency_slo_failed": (
                run.latency_p95_seconds <= acceptance.latency_p95_slo_seconds
                and run.latency_p99_seconds <= acceptance.latency_p99_slo_seconds
            ),
            "retry_slo_failed": (
                run.http_attempts_per_item <= acceptance.max_http_attempts_per_item
            ),
            "source_headroom_failed": (
                run.source_utilization <= acceptance.max_source_utilization
            ),
            "database_headroom_failed": (
                run.database_utilization <= acceptance.max_database_utilization
            ),
            "error_slo_failed": (
                run.error_rate <= acceptance.max_error_rate
                and run.rate_limited_attempt_rate
                <= acceptance.max_rate_limited_attempt_rate
            ),
            "evidence_coverage_failed": (
                run.evidence_coverage >= acceptance.minimum_evidence_coverage
            ),
            "silent_loss_detected": (
                run.silent_loss == 0 and run.terminal_items == run.valid_items
            ),
        }
        rejection_reasons = tuple(
            reason for reason, passed in checks.items() if not passed
        )
        evaluations.append(
            BenchmarkRunEvaluation(
                concurrency=run.concurrency,
                terminal_capacity=round(run.terminal_capacity, 8),
                successful_capacity=round(run.successful_capacity, 8),
                system_parallel_efficiency=eta,
                worker_efficiency_interpretable=interpretable,
                capacity_pass=checks["capacity_below_required"],
                successful_capacity_pass=checks["successful_capacity_below_required"],
                latency_pass=checks["latency_slo_failed"],
                retry_pass=checks["retry_slo_failed"],
                source_headroom_pass=checks["source_headroom_failed"],
                database_headroom_pass=checks["database_headroom_failed"],
                error_pass=checks["error_slo_failed"],
                evidence_pass=checks["evidence_coverage_failed"],
                reconciliation_pass=checks["silent_loss_detected"],
                accepted=not rejection_reasons,
                rejection_reasons=rejection_reasons,
            )
        )
        if run is not baseline and first_saturation is None:
            capacity_gain = (
                run.terminal_capacity - previous.terminal_capacity
            ) / previous.terminal_capacity
            materially_worse = _material_rate_worsening(
                run.error_rate,
                previous.error_rate,
            ) or _material_rate_worsening(
                run.rate_limited_attempt_rate,
                previous.rate_limited_attempt_rate,
            )
            if (
                capacity_gain < acceptance.saturation_increment_threshold
                or materially_worse
            ):
                first_saturation = run.concurrency
        previous = run

    selected = next(
        (
            evaluation.concurrency
            for evaluation in evaluations
            if evaluation.accepted
            and (first_saturation is None or evaluation.concurrency < first_saturation)
        ),
        None,
    )
    warnings: list[str] = []
    if len(ordered) < acceptance.minimum_concurrency_levels:
        warnings.append("insufficient_concurrency_levels")
    if any(not value.worker_efficiency_interpretable for value in evaluations):
        warnings.append(
            "eta_is_full_system_efficiency_when_external_subsystem_is_saturated"
        )
    production_proven = (
        selected is not None and len(ordered) >= acceptance.minimum_concurrency_levels
    )
    if production_proven:
        stop_reason = "smallest_concurrency_meeting_all_acceptance_conditions"
    elif first_saturation is not None:
        stop_reason = "saturation_or_error_degradation_before_acceptance"
    else:
        stop_reason = "no_concurrency_level_met_all_acceptance_conditions"
    first = ordered[0]
    return BenchmarkDecision(
        item_kind=first.item_kind,
        workload_class=first.workload_class,
        configuration_fingerprint=first.configuration_fingerprint,
        dataset_fingerprint=first.dataset_fingerprint,
        evaluated_concurrency_levels=tuple(run.concurrency for run in ordered),
        evaluations=tuple(evaluations),
        selected_concurrency=selected,
        first_saturation_concurrency=first_saturation,
        production_capacity_proven=production_proven,
        stop_reason=stop_reason,
        warnings=tuple(warnings),
    )


def _material_rate_worsening(current: float, previous: float) -> bool:
    """Require both relative and meaningful absolute degradation."""

    return current - previous > max(0.01, previous * 0.25)


def _validate_comparable_runs(runs: list[BenchmarkRun]) -> None:
    first = runs[0]
    expected = (
        first.item_kind,
        first.workload_class,
        first.configuration_fingerprint,
        first.dataset_fingerprint,
    )
    concurrency_levels: set[int] = set()
    for run in runs:
        actual = (
            run.item_kind,
            run.workload_class,
            run.configuration_fingerprint,
            run.dataset_fingerprint,
        )
        if actual != expected:
            raise ValueError(
                "benchmark runs must use the same item kind, workload class, "
                "configuration, and dataset fingerprints"
            )
        if run.concurrency in concurrency_levels:
            raise ValueError("concurrency levels must be unique")
        concurrency_levels.add(run.concurrency)


__all__ = [
    "BenchmarkAcceptance",
    "BenchmarkDecision",
    "BenchmarkRun",
    "BenchmarkRunEvaluation",
    "evaluate_benchmark_series",
]
