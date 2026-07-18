"""Mathematical contract for black-box scraper scaling.

The module deliberately separates:

* logical queue items;
* logical HTTP requests;
* physical HTTP attempts;
* derived subsystem capacity;
* measured end-to-end capacity.

Terminal item time already includes waits, HTTP retries, parsing, persistence,
and task re-execution.  Consequently worker capacity is never divided by retry
amplification a second time.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import math
from typing import Any, Iterable


ENGINEERING_HEADROOM_TARGET = 0.70
ENGINEERING_UTILIZATION_TARGET = ENGINEERING_HEADROOM_TARGET


@dataclass(frozen=True)
class RetryAmplification:
    unique_logical_items_total: int
    logical_http_requests_total: int
    physical_http_attempts_total: int
    task_executions_total: int
    http_attempts_per_request: float
    task_executions_per_item: float
    http_attempts_per_item: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_retry_amplification(
    *,
    unique_logical_items_total: int,
    logical_http_requests_total: int,
    physical_http_attempts_total: int,
    task_executions_total: int,
) -> RetryAmplification:
    """Return directly measured A_http, A_task, and A_total."""

    values = (
        unique_logical_items_total,
        logical_http_requests_total,
        physical_http_attempts_total,
        task_executions_total,
    )
    if any(value < 0 for value in values):
        raise ValueError("telemetry counts must be non-negative")
    items = unique_logical_items_total
    requests = logical_http_requests_total
    return RetryAmplification(
        unique_logical_items_total=items,
        logical_http_requests_total=requests,
        physical_http_attempts_total=physical_http_attempts_total,
        task_executions_total=task_executions_total,
        http_attempts_per_request=round(
            physical_http_attempts_total / requests if requests else 0.0,
            8,
        ),
        task_executions_per_item=round(
            task_executions_total / items if items else 0.0,
            8,
        ),
        http_attempts_per_item=round(
            physical_http_attempts_total / items if items else 0.0,
            8,
        ),
    )


@dataclass(frozen=True)
class RequestRetrySanityCheck:
    attempt_success_probability: float
    max_physical_attempts: int
    request_success_probability: float
    expected_physical_attempts: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def request_retry_sanity_check(
    *,
    attempt_success_probability: float,
    max_physical_attempts: int,
) -> RequestRetrySanityCheck:
    """Independent-Bernoulli sanity check, not a production capacity model."""

    p = attempt_success_probability
    k = max_physical_attempts
    if not 0 <= p <= 1:
        raise ValueError("attempt success probability must be in [0, 1]")
    if k < 1:
        raise ValueError("max physical attempts must be at least one")
    request_success = 1 - (1 - p) ** k
    expected_attempts = request_success / p if p > 0 else float(k)
    return RequestRetrySanityCheck(
        attempt_success_probability=round(p, 8),
        max_physical_attempts=k,
        request_success_probability=round(request_success, 8),
        expected_physical_attempts=round(expected_attempts, 8),
    )


@dataclass(frozen=True)
class ReconciliationSnapshot:
    valid_total: int
    queued: int
    running: int
    retry_wait: int
    success: int
    failed: int
    terminal_rate: float
    success_rate: float
    silent_loss: int
    reconciled: bool
    batch_terminal: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SubmissionReconciliation:
    submitted: int
    deduplicated: int
    rejected: int
    admitted: int
    queued: int
    running: int
    retry_wait: int
    success: int
    failed: int
    cancelled: int
    unaccounted_loss: int
    reconciled: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def reconcile_submission_cohort(
    *,
    submitted: int,
    deduplicated: int,
    rejected: int,
    admitted: int,
    queued: int,
    running: int,
    retry_wait: int,
    success: int,
    failed: int,
    cancelled: int,
) -> SubmissionReconciliation:
    values = (
        submitted,
        deduplicated,
        rejected,
        admitted,
        queued,
        running,
        retry_wait,
        success,
        failed,
        cancelled,
    )
    if any(value < 0 for value in values):
        raise ValueError("submission reconciliation counts must be non-negative")
    if submitted != deduplicated + rejected + admitted:
        raise ValueError("submitted must equal deduplicated + rejected + admitted")
    accounted = queued + running + retry_wait + success + failed + cancelled
    loss = admitted - accounted
    return SubmissionReconciliation(
        submitted=submitted,
        deduplicated=deduplicated,
        rejected=rejected,
        admitted=admitted,
        queued=queued,
        running=running,
        retry_wait=retry_wait,
        success=success,
        failed=failed,
        cancelled=cancelled,
        unaccounted_loss=loss,
        reconciled=loss == 0,
    )


@dataclass(frozen=True)
class BinomialConfidenceInterval:
    successes: int
    sample_size: int
    estimate: float | None
    lower: float | None
    upper: float | None
    confidence_level: float
    method: str = "wilson"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def wilson_confidence_interval(
    *,
    successes: int,
    sample_size: int,
    confidence_level: float = 0.95,
    z_score: float = 1.959963984540054,
) -> BinomialConfidenceInterval:
    if sample_size < 0 or successes < 0 or successes > sample_size:
        raise ValueError("binomial counts are inconsistent")
    if not 0 < confidence_level < 1 or z_score <= 0:
        raise ValueError("confidence level and z score must be positive and bounded")
    if sample_size == 0:
        return BinomialConfidenceInterval(
            successes=0,
            sample_size=0,
            estimate=None,
            lower=None,
            upper=None,
            confidence_level=confidence_level,
        )
    estimate = successes / sample_size
    z2 = z_score**2
    denominator = 1 + z2 / sample_size
    center = (estimate + z2 / (2 * sample_size)) / denominator
    margin = (
        z_score
        * math.sqrt(
            estimate * (1 - estimate) / sample_size
            + z2 / (4 * sample_size**2)
        )
        / denominator
    )
    return BinomialConfidenceInterval(
        successes=successes,
        sample_size=sample_size,
        estimate=round(estimate, 8),
        lower=round(max(0.0, center - margin), 8),
        upper=round(min(1.0, center + margin), 8),
        confidence_level=confidence_level,
    )


@dataclass(frozen=True)
class CompletenessDistribution:
    count: int
    minimum: float | None
    p05: float | None
    p50: float | None
    p95: float | None
    critical_field_missing_rate: float | None
    per_field_missing_rate: dict[str, float | None]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_completeness_distribution(
    records: Iterable[dict[str, Any]],
    *,
    field_weights: dict[str, float],
    critical_fields: set[str],
) -> CompletenessDistribution:
    rows = list(records)
    if not field_weights or any(
        weight <= 0 or not math.isfinite(weight) for weight in field_weights.values()
    ):
        raise ValueError("completeness weights must be finite and positive")
    unknown_critical = critical_fields - set(field_weights)
    if unknown_critical:
        raise ValueError("every critical field must have a declared weight")
    if not rows:
        return CompletenessDistribution(
            count=0,
            minimum=None,
            p05=None,
            p50=None,
            p95=None,
            critical_field_missing_rate=None,
            per_field_missing_rate={field: None for field in field_weights},
        )
    weight_sum = sum(field_weights.values())
    scores: list[float] = []
    missing_by_field = {field: 0 for field in field_weights}
    critical_failures = 0
    for row in rows:
        present: dict[str, bool] = {}
        for field in field_weights:
            value = row.get(field)
            valid = value is not None and value != "" and value != []
            present[field] = valid
            if not valid:
                missing_by_field[field] += 1
        if any(not present[field] for field in critical_fields):
            critical_failures += 1
        scores.append(
            sum(field_weights[field] * present[field] for field in field_weights)
            / weight_sum
        )
    return CompletenessDistribution(
        count=len(rows),
        minimum=round(min(scores), 8),
        p05=_percentile(scores, 0.05),
        p50=_percentile(scores, 0.50),
        p95=_percentile(scores, 0.95),
        critical_field_missing_rate=round(critical_failures / len(rows), 8),
        per_field_missing_rate={
            field: round(missing / len(rows), 8)
            for field, missing in missing_by_field.items()
        },
    )


def reconcile_items(
    *,
    valid_total: int,
    queued: int,
    running: int,
    retry_wait: int,
    success: int,
    failed: int,
) -> ReconciliationSnapshot:
    """Enforce N_valid = queued + running + retry + success + failed."""

    values = (valid_total, queued, running, retry_wait, success, failed)
    if any(value < 0 for value in values):
        raise ValueError("reconciliation counts must be non-negative")
    accounted = queued + running + retry_wait + success + failed
    silent_loss = valid_total - accounted
    terminal = success + failed
    return ReconciliationSnapshot(
        valid_total=valid_total,
        queued=queued,
        running=running,
        retry_wait=retry_wait,
        success=success,
        failed=failed,
        terminal_rate=round(terminal / valid_total if valid_total else 0.0, 8),
        success_rate=round(success / valid_total if valid_total else 0.0, 8),
        silent_loss=silent_loss,
        reconciled=silent_loss == 0,
        batch_terminal=accounted == terminal == valid_total,
    )


@dataclass(frozen=True)
class CapacityModel:
    model_kind: str
    arrival_rate_items_per_second: float
    worker_count: int
    parallel_efficiency: float
    mean_terminal_item_time_seconds: float | None
    terminal_service_rate_per_worker: float | None
    average_http_attempts_per_item: float
    average_database_writes_per_item: float
    source_request_budget_per_second: float | None
    database_write_capacity_per_second: float | None
    queue_capacity_items_per_second: float | None
    worker_capacity_items_per_second: float | None
    source_capacity_items_per_second: float | None
    database_capacity_items_per_second: float | None
    terminal_capacity_items_per_second: float
    success_probability: float
    successful_capacity_items_per_second: float
    item_utilization: float | None
    source_utilization: float | None
    database_utilization: float | None
    maximum_utilization: float | None
    stable: bool
    engineering_headroom_target: float
    engineering_target_met: bool
    backlog: int
    queue_drain_seconds_no_arrivals: float | None
    queue_drain_seconds_with_arrivals: float | None
    limiting_subsystems: tuple[str, ...]
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    # Backward-compatible aliases for the earlier, smaller response contract.
    @property
    def capacity_urls_per_second(self) -> float:
        return self.terminal_capacity_items_per_second

    @property
    def utilization_rho(self) -> float | None:
        return self.maximum_utilization

    @property
    def queue_drain_seconds(self) -> float | None:
        return self.queue_drain_seconds_with_arrivals


def calculate_derived_capacity(
    *,
    arrival_rate_items_per_second: float,
    mean_terminal_item_time_seconds: float,
    worker_count: int,
    parallel_efficiency: float,
    average_http_attempts_per_item: float,
    source_request_budget_per_second: float | None,
    average_database_writes_per_item: float,
    database_write_capacity_per_second: float | None,
    queue_capacity_items_per_second: float | None,
    success_probability: float,
    backlog: int,
    engineering_headroom_target: float = ENGINEERING_HEADROOM_TARGET,
) -> CapacityModel:
    """Compute C_terminal = min(C_worker, C_source, C_db, C_queue).

    ``mean_terminal_item_time_seconds`` already contains retry and redelivery
    cost.  Retry amplification is used only for source capacity/utilization.
    """

    _validate_capacity_common(
        arrival_rate=arrival_rate_items_per_second,
        worker_count=worker_count,
        efficiency=parallel_efficiency,
        success_probability=success_probability,
        backlog=backlog,
        target=engineering_headroom_target,
    )
    if mean_terminal_item_time_seconds <= 0 or not math.isfinite(
        mean_terminal_item_time_seconds
    ):
        raise ValueError("mean terminal item time must be finite and positive")
    _validate_nonnegative_finite(
        average_http_attempts_per_item,
        "average HTTP attempts per item",
    )
    _validate_nonnegative_finite(
        average_database_writes_per_item,
        "average database writes per item",
    )
    _validate_optional_positive_capacity(
        source_request_budget_per_second,
        "source request budget",
    )
    _validate_optional_positive_capacity(
        database_write_capacity_per_second,
        "database write capacity",
    )
    _validate_optional_positive_capacity(
        queue_capacity_items_per_second,
        "queue capacity",
    )

    mu_terminal = 1 / mean_terminal_item_time_seconds
    worker_capacity = worker_count * parallel_efficiency * mu_terminal
    source_capacity = _per_item_capacity(
        source_request_budget_per_second,
        average_http_attempts_per_item,
    )
    database_capacity = _per_item_capacity(
        database_write_capacity_per_second,
        average_database_writes_per_item,
    )
    candidates = {
        "worker": worker_capacity,
        "source": source_capacity,
        "database": database_capacity,
        "queue": queue_capacity_items_per_second,
    }
    finite_candidates = {
        name: value for name, value in candidates.items() if value is not None
    }
    terminal_capacity = min(finite_candidates.values(), default=0.0)
    limiting = tuple(
        name
        for name, value in finite_candidates.items()
        if math.isclose(value, terminal_capacity, rel_tol=1e-9, abs_tol=1e-12)
    )
    return _capacity_result(
        model_kind="derived",
        arrival_rate=arrival_rate_items_per_second,
        worker_count=worker_count,
        efficiency=parallel_efficiency,
        mean_terminal_time=mean_terminal_item_time_seconds,
        mu_terminal=mu_terminal,
        attempts_per_item=average_http_attempts_per_item,
        writes_per_item=average_database_writes_per_item,
        source_budget=source_request_budget_per_second,
        database_budget=database_write_capacity_per_second,
        queue_capacity=queue_capacity_items_per_second,
        worker_capacity=worker_capacity,
        source_capacity=source_capacity,
        database_capacity=database_capacity,
        terminal_capacity=terminal_capacity,
        success_probability=success_probability,
        backlog=backlog,
        target=engineering_headroom_target,
        limiting=limiting,
    )


def calculate_measured_capacity(
    *,
    measured_terminal_capacity_items_per_second: float,
    arrival_rate_items_per_second: float,
    success_probability: float,
    backlog: int,
    worker_count: int,
    parallel_efficiency: float = 1.0,
    engineering_headroom_target: float = ENGINEERING_HEADROOM_TARGET,
) -> CapacityModel:
    """Represent a full-system measured capacity without double penalties."""

    _validate_capacity_common(
        arrival_rate=arrival_rate_items_per_second,
        worker_count=worker_count,
        efficiency=parallel_efficiency,
        success_probability=success_probability,
        backlog=backlog,
        target=engineering_headroom_target,
    )
    if measured_terminal_capacity_items_per_second < 0 or not math.isfinite(
        measured_terminal_capacity_items_per_second
    ):
        raise ValueError("measured terminal capacity must be finite and non-negative")
    return _capacity_result(
        model_kind="measured",
        arrival_rate=arrival_rate_items_per_second,
        worker_count=worker_count,
        efficiency=parallel_efficiency,
        mean_terminal_time=None,
        mu_terminal=None,
        attempts_per_item=0.0,
        writes_per_item=0.0,
        source_budget=None,
        database_budget=None,
        queue_capacity=None,
        worker_capacity=None,
        source_capacity=None,
        database_capacity=None,
        terminal_capacity=measured_terminal_capacity_items_per_second,
        success_probability=success_probability,
        backlog=backlog,
        target=engineering_headroom_target,
        limiting=("measured_system",),
    )


def calculate_capacity(
    *,
    arrival_rate_urls_per_second: float,
    service_rate_per_worker: float,
    worker_count: int,
    average_attempts_per_unique_url: float,
    backlog: int,
) -> CapacityModel:
    """Compatibility wrapper with corrected terminal-throughput semantics.

    ``service_rate_per_worker`` is terminal items/sec and already includes
    retries.  The attempts argument is retained as telemetry only; it does not
    divide worker throughput.
    """

    if service_rate_per_worker < 0 or not math.isfinite(service_rate_per_worker):
        raise ValueError("service rate must be finite and non-negative")
    if average_attempts_per_unique_url <= 0 or not math.isfinite(
        average_attempts_per_unique_url
    ):
        raise ValueError("average attempts must be finite and positive")
    return calculate_measured_capacity(
        measured_terminal_capacity_items_per_second=(
            worker_count * service_rate_per_worker
        ),
        arrival_rate_items_per_second=arrival_rate_urls_per_second,
        success_probability=1.0,
        backlog=backlog,
        worker_count=worker_count,
    )


def parallel_efficiency(
    *,
    measured_capacity_at_c: float,
    worker_count: int,
    measured_capacity_at_one: float,
) -> float:
    """eta(c) = C_measured(c) / (c × C_measured(1))."""

    if worker_count < 1:
        raise ValueError("worker count must be at least one")
    if measured_capacity_at_c < 0 or not math.isfinite(measured_capacity_at_c):
        raise ValueError("measured capacity must be finite and non-negative")
    if measured_capacity_at_one <= 0 or not math.isfinite(
        measured_capacity_at_one
    ):
        raise ValueError("single-worker capacity must be finite and positive")
    measured = measured_capacity_at_c / (
        worker_count * measured_capacity_at_one
    )
    return round(min(1.0, measured), 8)


@dataclass(frozen=True)
class BatchCompletionEstimate:
    worker_lower_bound_seconds: float
    source_lower_bound_seconds: float | None
    database_lower_bound_seconds: float | None
    lower_bound_seconds: float
    scheduler_overhead_seconds: float
    tail_seconds: float
    estimated_seconds: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_batch_completion(
    *,
    terminal_item_times_seconds: Iterable[float],
    worker_count: int,
    parallel_efficiency_value: float,
    physical_http_attempts_total: int,
    source_request_budget_per_second: float | None,
    database_writes_total: int,
    database_write_capacity_per_second: float | None,
    scheduler_overhead_seconds: float = 0.0,
    tail_seconds: float = 0.0,
) -> BatchCompletionEstimate:
    """Estimate finite-batch time from worker, source, and DB lower bounds."""

    if worker_count < 1:
        raise ValueError("worker count must be at least one")
    if not 0 < parallel_efficiency_value <= 1:
        raise ValueError("parallel efficiency must be in (0, 1]")
    if physical_http_attempts_total < 0 or database_writes_total < 0:
        raise ValueError("attempt and write counts must be non-negative")
    _validate_nonnegative_finite(scheduler_overhead_seconds, "scheduler overhead")
    _validate_nonnegative_finite(tail_seconds, "tail")
    values = list(terminal_item_times_seconds)
    if any(value < 0 or not math.isfinite(value) for value in values):
        raise ValueError("terminal item times must be finite and non-negative")
    worker_bound = sum(values) / (worker_count * parallel_efficiency_value)
    source_bound = _division_bound(
        physical_http_attempts_total,
        source_request_budget_per_second,
    )
    database_bound = _division_bound(
        database_writes_total,
        database_write_capacity_per_second,
    )
    lower_bound = max(
        worker_bound,
        source_bound or 0.0,
        database_bound or 0.0,
    )
    return BatchCompletionEstimate(
        worker_lower_bound_seconds=round(worker_bound, 3),
        source_lower_bound_seconds=_rounded_optional(source_bound),
        database_lower_bound_seconds=_rounded_optional(database_bound),
        lower_bound_seconds=round(lower_bound, 3),
        scheduler_overhead_seconds=round(scheduler_overhead_seconds, 3),
        tail_seconds=round(tail_seconds, 3),
        estimated_seconds=round(
            lower_bound + scheduler_overhead_seconds + tail_seconds,
            3,
        ),
    )


@dataclass(frozen=True)
class RequiredCapacityPlan:
    peak_logical_items: int
    completion_slo_seconds: float
    required_terminal_capacity_items_per_second: float
    assumed_parallel_efficiency: float
    mean_terminal_item_time_seconds: float
    initial_worker_count: int
    source_sufficient: bool | None
    database_sufficient: bool | None
    queue_sufficient: bool | None
    feasible_without_subsystem_changes: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def required_capacity_plan(
    *,
    peak_logical_items: int,
    completion_slo_seconds: float,
    mean_terminal_item_time_seconds: float,
    assumed_parallel_efficiency: float,
    source_capacity_items_per_second: float | None,
    database_capacity_items_per_second: float | None,
    queue_capacity_items_per_second: float | None,
) -> RequiredCapacityPlan:
    if peak_logical_items < 0:
        raise ValueError("peak logical items must be non-negative")
    if completion_slo_seconds <= 0 or not math.isfinite(completion_slo_seconds):
        raise ValueError("completion SLO must be finite and positive")
    if mean_terminal_item_time_seconds <= 0 or not math.isfinite(
        mean_terminal_item_time_seconds
    ):
        raise ValueError("mean terminal item time must be finite and positive")
    if not 0 < assumed_parallel_efficiency <= 1:
        raise ValueError("assumed parallel efficiency must be in (0, 1]")
    required = peak_logical_items / completion_slo_seconds
    workers = math.ceil(
        required
        * mean_terminal_item_time_seconds
        / assumed_parallel_efficiency
    )
    checks = tuple(
        None if capacity is None else required <= capacity
        for capacity in (
            source_capacity_items_per_second,
            database_capacity_items_per_second,
            queue_capacity_items_per_second,
        )
    )
    return RequiredCapacityPlan(
        peak_logical_items=peak_logical_items,
        completion_slo_seconds=round(completion_slo_seconds, 3),
        required_terminal_capacity_items_per_second=round(required, 8),
        assumed_parallel_efficiency=round(assumed_parallel_efficiency, 8),
        mean_terminal_item_time_seconds=round(
            mean_terminal_item_time_seconds,
            8,
        ),
        initial_worker_count=max(1, workers),
        source_sufficient=checks[0],
        database_sufficient=checks[1],
        queue_sufficient=checks[2],
        feasible_without_subsystem_changes=all(value is True for value in checks),
    )


@dataclass(frozen=True)
class StorageModel:
    raw_unique_bytes: int
    compression_ratio: float
    structured_bytes: int
    attempt_journal_bytes: int
    observation_bytes: int
    recommendation_lineage_bytes: int
    index_and_database_overhead_bytes: int
    raw_stored_bytes: int
    net_storage_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_storage(
    *,
    raw_unique_bytes: int,
    compression_ratio: float,
    structured_bytes: int,
    attempt_journal_bytes: int,
    observation_bytes: int,
    recommendation_lineage_bytes: int,
    index_and_database_overhead_bytes: int,
) -> StorageModel:
    byte_values = (
        raw_unique_bytes,
        structured_bytes,
        attempt_journal_bytes,
        observation_bytes,
        recommendation_lineage_bytes,
        index_and_database_overhead_bytes,
    )
    if any(value < 0 for value in byte_values):
        raise ValueError("storage byte counts must be non-negative")
    if not 0 <= compression_ratio <= 1 or not math.isfinite(compression_ratio):
        raise ValueError("compression ratio must be finite and in [0, 1]")
    raw_stored = round(raw_unique_bytes * compression_ratio)
    net = raw_stored + sum(byte_values[1:])
    return StorageModel(
        raw_unique_bytes=raw_unique_bytes,
        compression_ratio=round(compression_ratio, 8),
        structured_bytes=structured_bytes,
        attempt_journal_bytes=attempt_journal_bytes,
        observation_bytes=observation_bytes,
        recommendation_lineage_bytes=recommendation_lineage_bytes,
        index_and_database_overhead_bytes=index_and_database_overhead_bytes,
        raw_stored_bytes=raw_stored,
        net_storage_bytes=net,
    )


def estimate_storage_batch(
    *,
    unique_inputs: int,
    average_raw_size_bytes: float,
    average_structured_size_bytes: float,
    average_metadata_size_bytes: float,
) -> int:
    """Compatibility estimate for homogeneous direct-product batches."""

    if unique_inputs < 0:
        raise ValueError("unique inputs must be non-negative")
    sizes = (
        average_raw_size_bytes,
        average_structured_size_bytes,
        average_metadata_size_bytes,
    )
    if any(value < 0 or not math.isfinite(value) for value in sizes):
        raise ValueError("storage sizes must be finite and non-negative")
    return round(unique_inputs * sum(sizes))


@dataclass(frozen=True)
class TargetMetricSample:
    input_hash: str
    canonical_url: str | None
    status: str
    dependent_items: int
    created_at: datetime
    first_started_at: datetime | None
    finished_at: datetime | None
    raw_size_bytes: int
    structured_size_bytes: int
    metadata_size_bytes: int
    structured_completeness: float | None
    item_key: str | None = None


@dataclass(frozen=True)
class AttemptMetricSample:
    status: str
    network_attempted: bool
    wall_time_ms: int
    cpu_time_ms: int
    memory_peak_bytes: int
    item_key: str | None = None


@dataclass(frozen=True)
class CollectionMetrics:
    generated_at: datetime
    item_kind: str
    unique_urls_total: int
    unique_inputs_total: int
    attempts_total: int
    success_total: int
    retryable_failure_total: int
    terminal_failure_total: int
    duplicate_total: int
    duplicate_input_total: int
    duplicate_delivery_total: int
    throughput_urls_per_minute: float
    latency_p50: float | None
    latency_p95: float | None
    latency_p99: float | None
    retry_amplification: float
    structured_completeness: float
    raw_storage_bytes: int
    queue_depth: int
    oldest_job_age: float
    worker_utilization: float
    memory_peak: int
    cpu_average: float
    success_rate: float
    storage_batch_bytes: int
    average_raw_size_bytes: float
    average_structured_size_bytes: float
    average_metadata_size_bytes: float
    reconciliation: ReconciliationSnapshot
    retry: RetryAmplification
    capacity: CapacityModel
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["generated_at"] = self.generated_at
        return payload


def aggregate_collection_metrics(
    targets: list[TargetMetricSample],
    attempts: list[AttemptMetricSample],
    *,
    worker_count: int,
    arrival_rate_urls_per_second: float = 0.0,
    now: datetime | None = None,
    item_kind: str = "comparison_job",
) -> CollectionMetrics:
    """Aggregate direct-product target metrics without retry double-counting."""

    if worker_count < 1:
        raise ValueError("worker count must be at least one")
    if arrival_rate_urls_per_second < 0:
        raise ValueError("arrival rate must be non-negative")
    now = _aware_utc(now or datetime.now(UTC))
    unique_urls = {
        target.canonical_url for target in targets if target.canonical_url
    }
    success_targets = [target for target in targets if target.status == "succeeded"]
    failed_targets = [
        target for target in targets if target.status == "terminal_failure"
    ]
    queued_targets = [target for target in targets if target.status == "queued"]
    running_targets = [target for target in targets if target.status == "collecting"]
    retry_targets = [
        target for target in targets if target.status == "retryable_failure"
    ]
    network_attempts = [attempt for attempt in attempts if attempt.network_attempted]
    task_executions = [
        attempt for attempt in attempts if attempt.status != "duplicate"
    ]
    duplicate_input_total = sum(
        max(0, target.dependent_items - 1) for target in targets
    )
    duplicate_delivery_total = sum(
        attempt.status == "duplicate" for attempt in attempts
    )
    retryable_failure_total = sum(
        attempt.status == "retryable_failure" for attempt in attempts
    )
    terminal_failure_total = sum(
        attempt.status == "terminal_failure" for attempt in attempts
    )
    completed_latencies = [
        max(
            0.0,
            (
                _aware_utc(target.finished_at) - _aware_utc(target.created_at)
            ).total_seconds(),
        )
        for target in targets
        if target.finished_at is not None
        and target.status in {"succeeded", "terminal_failure"}
    ]
    terminal_targets = success_targets + failed_targets
    terminal_keys = {
        target.item_key for target in terminal_targets if target.item_key is not None
    }
    occupancy_attempts = [
        attempt
        for attempt in attempts
        if attempt.status != "duplicate" and attempt.wall_time_ms > 0
    ]
    if terminal_keys and all(
        attempt.item_key is not None for attempt in occupancy_attempts
    ):
        terminal_times = [
            sum(
                attempt.wall_time_ms
                for attempt in occupancy_attempts
                if attempt.item_key == target.item_key
            )
            / 1000
            for target in terminal_targets
        ]
    elif terminal_targets:
        terminal_times = [
            sum(attempt.wall_time_ms for attempt in occupancy_attempts)
            / 1000
            / len(terminal_targets)
        ]
    else:
        terminal_times = []
    mean_terminal_time = (
        sum(terminal_times) / len(terminal_times) if terminal_times else None
    )
    started_at = min(
        (_aware_utc(target.created_at) for target in targets),
        default=now,
    )
    ended_at = max(
        (
            _aware_utc(target.finished_at)
            for target in targets
            if target.finished_at is not None
        ),
        default=now,
    )
    if queued_targets or running_targets or retry_targets:
        ended_at = now
    elapsed_seconds = max(0.0, (ended_at - started_at).total_seconds())
    throughput = (
        60 * len(success_targets) / elapsed_seconds if elapsed_seconds else 0.0
    )
    completeness = [
        target.structured_completeness
        for target in success_targets
        if target.structured_completeness is not None
    ]
    oldest_job_age = max(
        (
            max(0.0, (now - _aware_utc(target.created_at)).total_seconds())
            for target in queued_targets + running_targets + retry_targets
        ),
        default=0.0,
    )
    busy_seconds = sum(
        attempt.wall_time_ms / 1000
        for attempt in occupancy_attempts
        if attempt.wall_time_ms > 0
    )
    worker_utilization_raw = (
        busy_seconds / (worker_count * elapsed_seconds)
        if elapsed_seconds
        else 0.0
    )
    wall_ms = sum(max(0, attempt.wall_time_ms) for attempt in occupancy_attempts)
    cpu_ms = sum(max(0, attempt.cpu_time_ms) for attempt in occupancy_attempts)
    raw_total = sum(max(0, target.raw_size_bytes) for target in targets)
    structured_total = sum(
        max(0, target.structured_size_bytes) for target in targets
    )
    metadata_total = sum(max(0, target.metadata_size_bytes) for target in targets)
    unique_inputs = len(targets)
    retry = calculate_retry_amplification(
        unique_logical_items_total=unique_inputs,
        logical_http_requests_total=0,
        physical_http_attempts_total=len(network_attempts),
        task_executions_total=len(task_executions),
    )
    reconciliation = reconcile_items(
        valid_total=unique_inputs,
        queued=len(queued_targets),
        running=len(running_targets),
        retry_wait=len(retry_targets),
        success=len(success_targets),
        failed=len(failed_targets),
    )
    terminal_count = len(success_targets) + len(failed_targets)
    p_success = len(success_targets) / terminal_count if terminal_count else 0.0
    if mean_terminal_time is None:
        capacity = calculate_measured_capacity(
            measured_terminal_capacity_items_per_second=0.0,
            arrival_rate_items_per_second=arrival_rate_urls_per_second,
            success_probability=p_success,
            backlog=len(queued_targets) + len(running_targets) + len(retry_targets),
            worker_count=worker_count,
        )
    else:
        capacity = calculate_derived_capacity(
            arrival_rate_items_per_second=arrival_rate_urls_per_second,
            mean_terminal_item_time_seconds=mean_terminal_time,
            worker_count=worker_count,
            parallel_efficiency=1.0,
            average_http_attempts_per_item=retry.http_attempts_per_item,
            source_request_budget_per_second=None,
            average_database_writes_per_item=0.0,
            database_write_capacity_per_second=None,
            queue_capacity_items_per_second=None,
            success_probability=p_success,
            backlog=len(queued_targets) + len(running_targets) + len(retry_targets),
        )
    warnings = list(capacity.warnings)
    if targets and not terminal_times:
        warnings.append("terminal_service_rate_unavailable_until_terminal_item")
    if worker_utilization_raw > 1:
        warnings.append("configured_worker_count_below_observed_concurrency")
    if any(target.canonical_url is None for target in targets):
        warnings.append("invalid_or_missing_url_targets_present")
    if not reconciliation.reconciled:
        warnings.append("silent_loss_detected")
    divisor = unique_inputs or 1
    return CollectionMetrics(
        generated_at=now,
        item_kind=item_kind,
        unique_urls_total=len(unique_urls),
        unique_inputs_total=unique_inputs,
        attempts_total=len(network_attempts),
        success_total=len(success_targets),
        retryable_failure_total=retryable_failure_total,
        terminal_failure_total=terminal_failure_total,
        duplicate_total=duplicate_input_total + duplicate_delivery_total,
        duplicate_input_total=duplicate_input_total,
        duplicate_delivery_total=duplicate_delivery_total,
        throughput_urls_per_minute=round(throughput, 6),
        latency_p50=_percentile(completed_latencies, 0.50),
        latency_p95=_percentile(completed_latencies, 0.95),
        latency_p99=_percentile(completed_latencies, 0.99),
        retry_amplification=retry.http_attempts_per_item,
        structured_completeness=round(
            sum(completeness) / len(completeness) if completeness else 0.0,
            6,
        ),
        raw_storage_bytes=raw_total,
        queue_depth=len(queued_targets) + len(retry_targets),
        oldest_job_age=round(oldest_job_age, 3),
        worker_utilization=round(
            min(1.0, max(0.0, worker_utilization_raw)),
            6,
        ),
        memory_peak=max(
            (attempt.memory_peak_bytes for attempt in attempts),
            default=0,
        ),
        cpu_average=round(100 * cpu_ms / wall_ms if wall_ms else 0.0, 6),
        success_rate=round(p_success, 6),
        storage_batch_bytes=raw_total + structured_total + metadata_total,
        average_raw_size_bytes=round(raw_total / divisor, 3),
        average_structured_size_bytes=round(structured_total / divisor, 3),
        average_metadata_size_bytes=round(metadata_total / divisor, 3),
        reconciliation=reconciliation,
        retry=retry,
        capacity=capacity,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _capacity_result(
    *,
    model_kind: str,
    arrival_rate: float,
    worker_count: int,
    efficiency: float,
    mean_terminal_time: float | None,
    mu_terminal: float | None,
    attempts_per_item: float,
    writes_per_item: float,
    source_budget: float | None,
    database_budget: float | None,
    queue_capacity: float | None,
    worker_capacity: float | None,
    source_capacity: float | None,
    database_capacity: float | None,
    terminal_capacity: float,
    success_probability: float,
    backlog: int,
    target: float,
    limiting: tuple[str, ...],
) -> CapacityModel:
    item_rho = arrival_rate / terminal_capacity if terminal_capacity > 0 else None
    source_rho = (
        arrival_rate * attempts_per_item / source_budget
        if source_budget is not None and source_budget > 0
        else None
    )
    database_rho = (
        arrival_rate * writes_per_item / database_budget
        if database_budget is not None and database_budget > 0
        else None
    )
    utilizations = [
        value for value in (item_rho, source_rho, database_rho) if value is not None
    ]
    maximum = max(utilizations) if utilizations else None
    unknown_required_capacity = model_kind == "derived" and any(
        value is None
        for value in (source_budget, database_budget, queue_capacity)
    )
    stable = (
        not unknown_required_capacity
        and terminal_capacity > arrival_rate
        and all(value < 1 for value in utilizations)
    )
    target_met = bool(
        stable and maximum is not None and maximum <= target
    )
    no_arrivals = (
        backlog / terminal_capacity
        if terminal_capacity > 0 and not unknown_required_capacity
        else None
    )
    with_arrivals = (
        backlog / (terminal_capacity - arrival_rate)
        if (
            terminal_capacity > arrival_rate
            and not unknown_required_capacity
        )
        else None
    )
    warnings: list[str] = []
    if terminal_capacity <= 0:
        warnings.append("terminal_capacity_unavailable")
    if maximum is not None and maximum > target:
        warnings.append("utilization_above_engineering_headroom")
    if not stable and backlog > 0:
        warnings.append("queue_not_drainable_at_current_arrival_rate")
    if model_kind == "derived" and efficiency == 1:
        warnings.append("parallel_efficiency_is_unmeasured_baseline")
    if unknown_required_capacity:
        warnings.append("subsystem_capacity_unknown_stability_not_proven")
    return CapacityModel(
        model_kind=model_kind,
        arrival_rate_items_per_second=round(arrival_rate, 8),
        worker_count=worker_count,
        parallel_efficiency=round(efficiency, 8),
        mean_terminal_item_time_seconds=_rounded_optional(
            mean_terminal_time,
            digits=8,
        ),
        terminal_service_rate_per_worker=_rounded_optional(mu_terminal, digits=8),
        average_http_attempts_per_item=round(attempts_per_item, 8),
        average_database_writes_per_item=round(writes_per_item, 8),
        source_request_budget_per_second=_rounded_optional(source_budget, digits=8),
        database_write_capacity_per_second=_rounded_optional(
            database_budget,
            digits=8,
        ),
        queue_capacity_items_per_second=_rounded_optional(
            queue_capacity,
            digits=8,
        ),
        worker_capacity_items_per_second=_rounded_optional(
            worker_capacity,
            digits=8,
        ),
        source_capacity_items_per_second=_rounded_optional(
            source_capacity,
            digits=8,
        ),
        database_capacity_items_per_second=_rounded_optional(
            database_capacity,
            digits=8,
        ),
        terminal_capacity_items_per_second=round(terminal_capacity, 8),
        success_probability=round(success_probability, 8),
        successful_capacity_items_per_second=round(
            terminal_capacity * success_probability,
            8,
        ),
        item_utilization=_rounded_optional(item_rho, digits=8),
        source_utilization=_rounded_optional(source_rho, digits=8),
        database_utilization=_rounded_optional(database_rho, digits=8),
        maximum_utilization=_rounded_optional(maximum, digits=8),
        stable=stable,
        engineering_headroom_target=round(target, 8),
        engineering_target_met=target_met,
        backlog=backlog,
        queue_drain_seconds_no_arrivals=_rounded_optional(no_arrivals),
        queue_drain_seconds_with_arrivals=_rounded_optional(with_arrivals),
        limiting_subsystems=limiting,
        warnings=tuple(warnings),
    )


def _validate_capacity_common(
    *,
    arrival_rate: float,
    worker_count: int,
    efficiency: float,
    success_probability: float,
    backlog: int,
    target: float,
) -> None:
    _validate_nonnegative_finite(arrival_rate, "arrival rate")
    if worker_count < 1:
        raise ValueError("worker count must be at least one")
    if not 0 < efficiency <= 1 or not math.isfinite(efficiency):
        raise ValueError("parallel efficiency must be finite and in (0, 1]")
    if not 0 <= success_probability <= 1 or not math.isfinite(
        success_probability
    ):
        raise ValueError("success probability must be finite and in [0, 1]")
    if backlog < 0:
        raise ValueError("backlog must be non-negative")
    if not 0 < target < 1 or not math.isfinite(target):
        raise ValueError("engineering headroom target must be in (0, 1)")


def _validate_nonnegative_finite(value: float, label: str) -> None:
    if value < 0 or not math.isfinite(value):
        raise ValueError(f"{label} must be finite and non-negative")


def _validate_optional_positive_capacity(
    value: float | None,
    label: str,
) -> None:
    if value is not None and (value <= 0 or not math.isfinite(value)):
        raise ValueError(f"{label} must be finite and positive when provided")


def _per_item_capacity(
    subsystem_capacity: float | None,
    units_per_item: float,
) -> float | None:
    if subsystem_capacity is None:
        return None
    if units_per_item == 0:
        return None
    return subsystem_capacity / units_per_item


def _division_bound(count: int, capacity: float | None) -> float | None:
    if capacity is None:
        return None
    if capacity <= 0 or not math.isfinite(capacity):
        raise ValueError("subsystem capacity must be finite and positive")
    return count / capacity


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 3)
    weight = position - lower
    return round(
        ordered[lower] * (1 - weight) + ordered[upper] * weight,
        3,
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _rounded_optional(
    value: float | None,
    *,
    digits: int = 3,
) -> float | None:
    return round(value, digits) if value is not None else None


__all__ = [
    "AttemptMetricSample",
    "BatchCompletionEstimate",
    "BinomialConfidenceInterval",
    "CapacityModel",
    "CollectionMetrics",
    "CompletenessDistribution",
    "ENGINEERING_HEADROOM_TARGET",
    "ENGINEERING_UTILIZATION_TARGET",
    "ReconciliationSnapshot",
    "RequestRetrySanityCheck",
    "RequiredCapacityPlan",
    "RetryAmplification",
    "StorageModel",
    "SubmissionReconciliation",
    "TargetMetricSample",
    "aggregate_collection_metrics",
    "calculate_capacity",
    "calculate_completeness_distribution",
    "calculate_derived_capacity",
    "calculate_measured_capacity",
    "calculate_retry_amplification",
    "calculate_storage",
    "estimate_batch_completion",
    "estimate_storage_batch",
    "parallel_efficiency",
    "reconcile_items",
    "reconcile_submission_cohort",
    "request_retry_sanity_check",
    "required_capacity_plan",
    "wilson_confidence_interval",
]
