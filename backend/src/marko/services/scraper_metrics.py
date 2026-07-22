"""Repository-backed scraper metrics, capacity, storage, and reconciliation."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import math
import time
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis as AsyncRedis

from marko.core.config import get_settings
from marko.infrastructure.db.models import (
    MarketObservation,
    ObservationTierClassification,
    OfferProcessingOutcome,
    PriceObservation,
    PricingRecommendation,
    PricingRun,
    PricingRunItem,
    RawMarketCapture,
    ScrapeAttempt,
    ScrapeEvidenceBlob,
    ScrapeHttpAttempt,
    ScrapeHttpRequest,
    ScrapeTarget,
    StoreSyncProductSnapshot,
    StoreSyncTaskExecution,
    SyncRun,
)
from marko.infrastructure.db.session import engine
from marko.services.pricing_runs import PricingRunNotFoundError
from marko.services.identity_health import (
    IDENTITY_HEALTH_POLICY_VERSION,
    IdentityHealthSnapshot,
    IdentityHealthThresholds,
    evaluate_identity_health,
)
from marko.services.scrape_journal import evidence_coverage_ratio
from marko.services.scraper_scaling import (
    AttemptMetricSample,
    TargetMetricSample,
    aggregate_collection_metrics,
    calculate_derived_capacity,
    calculate_measured_capacity,
    calculate_retry_amplification,
    calculate_storage,
    reconcile_items,
)
from marko.services.scraper_outbox import OutboxHealth, outbox_health
from marko.services.stores import SyncRunNotFoundError


async def get_store_sync_scraper_metrics(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    sync_run_id: UUID,
    arrival_rate_items_per_second: float = 0.0,
    parallel_efficiency: float = 1.0,
    database_write_capacity_per_second: float | None = None,
    queue_capacity_items_per_second: float | None = None,
) -> dict[str, Any]:
    run = await session.scalar(
        select(SyncRun).where(
            SyncRun.id == sync_run_id,
            SyncRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise SyncRunNotFoundError(str(sync_run_id))
    database_latency = await _database_probe_latency(session)
    dispatch_health = await outbox_health(session, workspace_id=workspace_id)
    settings = get_settings()
    now = datetime.now(UTC)
    requests = list(
        (
            await session.scalars(
                select(ScrapeHttpRequest)
                .where(ScrapeHttpRequest.sync_run_id == run.id)
                .order_by(
                    ScrapeHttpRequest.execution_no,
                    ScrapeHttpRequest.sequence_no,
                )
            )
        ).all()
    )
    request_ids = [request.id for request in requests]
    attempts = (
        list(
            (
                await session.scalars(
                    select(ScrapeHttpAttempt)
                    .where(ScrapeHttpAttempt.logical_request_id.in_(request_ids))
                    .order_by(
                        ScrapeHttpAttempt.logical_request_id,
                        ScrapeHttpAttempt.attempt_no,
                    )
                )
            ).all()
        )
        if request_ids
        else []
    )
    executions = list(
        (
            await session.scalars(
                select(StoreSyncTaskExecution)
                .where(StoreSyncTaskExecution.sync_run_id == run.id)
                .order_by(StoreSyncTaskExecution.execution_no)
            )
        ).all()
    )
    reconciliation = _store_reconciliation(run)
    retry = calculate_retry_amplification(
        unique_logical_items_total=1,
        logical_http_requests_total=len(requests),
        physical_http_attempts_total=len(attempts),
        task_executions_total=len(executions),
    )
    queue_depth, oldest_age = await _store_queue_health(session, now)
    terminal_worker_seconds = (
        sum(_execution_wall_ms(execution) for execution in executions) / 1000
    )
    source_budget = 1 / max(
        settings.pricing_collection_min_interval_seconds,
        0.001,
    )
    success_probability = 1.0 if run.scrape_state == "succeeded" else 0.0
    if run.scrape_state in {"succeeded", "failed", "cancelled"} and (
        terminal_worker_seconds > 0
    ):
        capacity = calculate_derived_capacity(
            arrival_rate_items_per_second=arrival_rate_items_per_second,
            mean_terminal_item_time_seconds=terminal_worker_seconds,
            worker_count=max(1, settings.store_sync_worker_count),
            parallel_efficiency=parallel_efficiency,
            average_http_attempts_per_item=retry.http_attempts_per_item,
            source_request_budget_per_second=source_budget,
            average_database_writes_per_item=float(run.scrape_database_writes),
            database_write_capacity_per_second=(database_write_capacity_per_second),
            queue_capacity_items_per_second=queue_capacity_items_per_second,
            success_probability=success_probability,
            backlog=queue_depth,
        )
    else:
        capacity = calculate_measured_capacity(
            measured_terminal_capacity_items_per_second=0.0,
            arrival_rate_items_per_second=arrival_rate_items_per_second,
            success_probability=success_probability,
            backlog=queue_depth,
            worker_count=max(1, settings.store_sync_worker_count),
            parallel_efficiency=parallel_efficiency,
        )
    storage = await _store_storage(
        session,
        run,
        requests,
        attempts,
        executions,
    )
    elapsed_seconds = _elapsed_seconds(run.created_at, run.finished_at or now)
    request_kinds = Counter(request.request_kind for request in requests)
    request_outcomes = Counter(
        (request.request_kind, request.outcome) for request in requests
    )
    request_kind_by_id = {request.id: request.request_kind for request in requests}
    attempt_outcomes = Counter(
        (
            request_kind_by_id.get(attempt.logical_request_id, "unknown"),
            attempt.outcome,
            attempt.status_class,
        )
        for attempt in attempts
    )
    execution_outcomes = Counter(execution.outcome for execution in executions)
    queue_waits = (
        [
            max(
                0.0,
                (
                    _aware(executions[0].started_at) - _aware(run.created_at)
                ).total_seconds(),
            )
        ]
        if executions
        else []
    )
    warnings = list(capacity.warnings)
    warnings.append("source_budget_is_configured_not_benchmark_proven")
    evidence_coverage = float(
        await evidence_coverage_ratio(
            session,
            sync_run_id=run.id,
            execution_no=(
                run.scrape_task_executions if run.scrape_task_executions > 0 else None
            ),
        )
    )
    if run.scrape_state == "succeeded" and evidence_coverage < 1:
        warnings.append("raw_evidence_coverage_below_one")
    if not reconciliation.reconciled:
        warnings.append("silent_loss_detected")
    if database_write_capacity_per_second is None:
        warnings.append("database_capacity_not_configured")
    if queue_capacity_items_per_second is None:
        warnings.append("broker_capacity_not_configured")
    warnings.append("database_write_count_excludes_uninstrumented_transaction_updates")
    if not storage["index_and_database_overhead_measured"]:
        warnings.append("storage_index_and_database_overhead_unmeasured")
    if (
        run.scrape_state == "succeeded"
        and storage["structured_snapshot_count"] != run.scrape_products_persisted
    ):
        warnings.append("structured_snapshot_count_mismatch")
    resource_metrics = _resource_dependency_metrics(
        executions=executions,
        requests=requests,
        database_probe_latency_seconds=database_latency,
        outbox=dispatch_health,
    )
    end_to_end_latency = _percentiles([elapsed_seconds])
    return {
        "generated_at": now,
        "scope_id": run.id,
        "item_kind": "store_sync",
        "item_version": run.scrape_item_version,
        "configuration_fingerprint": _configuration_fingerprint(
            {
                "item_version": run.scrape_item_version,
                "worker_count": settings.store_sync_worker_count,
                "max_task_executions": run.scrape_max_task_executions,
                "max_http_attempts": settings.store_sync_scraper_http_max_attempts,
                "global_min_interval": (
                    settings.pricing_collection_min_interval_seconds
                ),
                "replay_enabled": settings.scrape_raw_evidence_replay_enabled,
            }
        ),
        "dataset_fingerprint": run.scrape_input_fingerprint,
        "item_lifecycle": {
            "scrape_items_submitted_total": 1,
            "scrape_items_valid_total": 1,
            "scrape_items_deduplicated_total": (run.scrape_deduplicated_submissions),
            "scrape_items_terminal_total": {
                "success": int(run.scrape_state == "succeeded"),
                "failed": int(run.scrape_state in {"failed", "cancelled"}),
            },
            "scrape_items_inflight": {
                "queued": int(run.scrape_state == "queued"),
                "running": int(run.scrape_state == "running"),
                "retry_wait": int(run.scrape_state == "retry_wait"),
            },
        },
        "reconciliation": reconciliation.as_dict(),
        "retry": retry.as_dict(),
        "capacity": capacity.as_dict(),
        "latency_seconds": {
            "request": _latency_groups(
                requests,
                value=lambda row: row.latency_ms / 1000,
                label=lambda row: f"{row.request_kind}:{row.outcome}",
            ),
            "catalog_page": _percentiles(
                [
                    request.latency_ms / 1000
                    for request in requests
                    if request.request_kind == "catalog_page"
                ]
            ),
            "task_runtime": _latency_groups(
                executions,
                value=lambda row: row.wall_time_ms / 1000,
                label=lambda row: row.outcome,
            ),
            "queue_wait": _percentiles(queue_waits),
            "end_to_end_item": _percentiles([elapsed_seconds]),
        },
        "requests": {
            "scrape_logical_requests_total": _counter_rows(
                request_kinds,
                ("request_kind",),
            ),
            "logical_request_outcomes": _counter_rows(
                request_outcomes,
                ("request_kind", "outcome"),
            ),
            "scrape_http_attempts_total": _counter_rows(
                attempt_outcomes,
                ("request_kind", "outcome", "status_class"),
            ),
            "scrape_http_attempts_per_request": retry.http_attempts_per_request,
            "scrape_http_attempts_per_item": retry.http_attempts_per_item,
            "scrape_http_request_rate": (
                len(attempts) / elapsed_seconds if elapsed_seconds else 0.0
            ),
            "scrape_retry_backoff_seconds": sum(
                attempt.retry_backoff_ms for attempt in attempts
            )
            / 1000,
        },
        "queue_workers": {
            "scrape_queue_depth": queue_depth,
            "scrape_oldest_item_age_seconds": oldest_age,
            "scrape_worker_slots": {
                "configured": settings.store_sync_worker_count,
                "busy": sum(execution.outcome == "running" for execution in executions),
            },
            "scrape_task_executions_total": _counter_rows(
                execution_outcomes,
                ("outcome",),
            ),
            "scrape_task_redeliveries_total": run.scrape_task_redeliveries,
            "scrape_worker_lost_total": execution_outcomes.get("worker_lost", 0),
        },
        "domain_output": {
            "scrape_catalog_pages_total": run.scrape_catalog_pages,
            "catalog_page_outcomes": dict(
                Counter(
                    request.outcome
                    for request in requests
                    if request.request_kind == "catalog_page"
                )
            ),
            "scrape_products_extracted_total": run.scrape_products_extracted,
            "scrape_products_persisted_total": run.scrape_products_persisted,
            "scrape_duplicate_products_total": run.scrape_duplicate_products,
            "scrape_structured_completeness_ratio": float(
                run.scrape_structured_completeness or 0
            ),
            "scrape_evidence_coverage_ratio": evidence_coverage,
            "scrape_raw_evidence_bytes_total": storage["raw_unique_bytes"],
            "scrape_database_writes_total": run.scrape_database_writes,
        },
        "rates": {
            "store_syncs_per_hour": (
                3600 / elapsed_seconds
                if elapsed_seconds and run.scrape_state == "succeeded"
                else 0.0
            ),
            "catalog_pages_per_minute": _per_minute(
                run.scrape_catalog_pages,
                elapsed_seconds,
            ),
            "products_per_minute": _per_minute(
                run.scrape_products_persisted,
                elapsed_seconds,
            ),
            "logical_requests_per_minute": _per_minute(
                len(requests),
                elapsed_seconds,
            ),
            "physical_attempts_per_minute": _per_minute(
                len(attempts),
                elapsed_seconds,
            ),
        },
        "storage": storage,
        "resources_dependencies": resource_metrics,
        "compatibility_metrics": _compatibility_metrics(
            item_kind="store_sync",
            unique_urls_total=1,
            unique_inputs_total=1,
            attempts_total=len(attempts),
            success_total=reconciliation.success,
            retryable_failure_total=sum(
                attempt.outcome == "retryable_failure" for attempt in attempts
            ),
            terminal_failure_total=reconciliation.failed,
            duplicate_total=(
                run.scrape_deduplicated_submissions + run.scrape_duplicate_products
            ),
            throughput_per_minute=_per_minute(
                reconciliation.success,
                elapsed_seconds,
            ),
            latency=end_to_end_latency,
            retry_amplification=retry.http_attempts_per_item,
            structured_completeness=float(run.scrape_structured_completeness or 0),
            raw_storage_bytes=storage["raw_unique_bytes"],
            queue_depth=queue_depth,
            oldest_job_age=oldest_age,
            worker_count=max(1, settings.store_sync_worker_count),
            elapsed_seconds=elapsed_seconds,
            execution_wall_ms=sum(_execution_wall_ms(row) for row in executions),
            memory_peak=resource_metrics["process_resident_memory_bytes"],
            cpu_average=resource_metrics["process_cpu_utilization"] * 100,
        ),
        "warnings": list(dict.fromkeys(warnings)),
    }


async def get_pricing_run_scraper_metrics(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    run_id: UUID,
    arrival_rate_items_per_second: float = 0.0,
    parallel_efficiency: float = 1.0,
    database_write_capacity_per_second: float | None = None,
    queue_capacity_items_per_second: float | None = None,
) -> dict[str, Any]:
    run = await session.scalar(
        select(PricingRun).where(
            PricingRun.id == run_id,
            PricingRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise PricingRunNotFoundError(str(run_id))
    database_latency = await _database_probe_latency(session)
    dispatch_health = await outbox_health(session, workspace_id=workspace_id)
    settings = get_settings()
    now = datetime.now(UTC)
    targets = list(
        (
            await session.scalars(
                select(ScrapeTarget)
                .where(ScrapeTarget.pricing_run_id == run.id)
                .order_by(ScrapeTarget.created_at, ScrapeTarget.id)
            )
        ).all()
    )
    target_ids = [target.id for target in targets]
    dependent_counts = {
        target_id: int(count)
        for target_id, count in (
            await session.execute(
                select(
                    PricingRunItem.scrape_target_id,
                    func.count(PricingRunItem.id),
                )
                .where(PricingRunItem.pricing_run_id == run.id)
                .group_by(PricingRunItem.scrape_target_id)
            )
        ).all()
        if target_id is not None
    }
    task_attempts = (
        list(
            (
                await session.scalars(
                    select(ScrapeAttempt)
                    .where(ScrapeAttempt.scrape_target_id.in_(target_ids))
                    .order_by(
                        ScrapeAttempt.scrape_target_id,
                        ScrapeAttempt.delivery_no,
                    )
                )
            ).all()
        )
        if target_ids
        else []
    )
    task_executions = [
        attempt for attempt in task_attempts if attempt.status != "duplicate"
    ]
    requests = (
        list(
            (
                await session.scalars(
                    select(ScrapeHttpRequest)
                    .where(ScrapeHttpRequest.scrape_target_id.in_(target_ids))
                    .order_by(
                        ScrapeHttpRequest.scrape_target_id,
                        ScrapeHttpRequest.execution_no,
                        ScrapeHttpRequest.sequence_no,
                    )
                )
            ).all()
        )
        if target_ids
        else []
    )
    request_ids = [request.id for request in requests]
    http_attempts = (
        list(
            (
                await session.scalars(
                    select(ScrapeHttpAttempt)
                    .where(ScrapeHttpAttempt.logical_request_id.in_(request_ids))
                    .order_by(
                        ScrapeHttpAttempt.logical_request_id,
                        ScrapeHttpAttempt.attempt_no,
                    )
                )
            ).all()
        )
        if request_ids
        else []
    )
    target_samples = [
        TargetMetricSample(
            input_hash=target.input_hash,
            canonical_url=target.canonical_url,
            status=target.status,
            dependent_items=dependent_counts.get(target.id, 0),
            created_at=target.created_at,
            first_started_at=target.first_started_at,
            finished_at=target.finished_at,
            raw_size_bytes=target.raw_size_bytes,
            structured_size_bytes=target.structured_size_bytes,
            metadata_size_bytes=target.metadata_size_bytes,
            structured_completeness=(
                float(target.structured_completeness)
                if target.structured_completeness is not None
                else None
            ),
            item_key=str(target.id),
        )
        for target in targets
    ]
    attempt_samples = [
        AttemptMetricSample(
            status=attempt.status,
            network_attempted=attempt.network_attempted,
            wall_time_ms=_execution_wall_ms(attempt),
            cpu_time_ms=attempt.cpu_time_ms,
            memory_peak_bytes=attempt.memory_peak_bytes,
            item_key=str(attempt.scrape_target_id),
        )
        for attempt in task_attempts
    ]
    legacy_metrics = aggregate_collection_metrics(
        target_samples,
        attempt_samples,
        worker_count=max(1, settings.pricing_collection_worker_count),
        arrival_rate_urls_per_second=arrival_rate_items_per_second,
        now=now,
        item_kind="comparison_job",
    )
    retry = calculate_retry_amplification(
        unique_logical_items_total=len(targets),
        logical_http_requests_total=len(requests),
        physical_http_attempts_total=len(http_attempts),
        task_executions_total=len(task_executions),
    )
    reconciliation = reconcile_items(
        valid_total=len(targets),
        queued=sum(target.status == "queued" for target in targets),
        running=sum(target.status == "collecting" for target in targets),
        retry_wait=sum(target.status == "retryable_failure" for target in targets),
        success=sum(target.status == "succeeded" for target in targets),
        failed=sum(
            target.status in {"terminal_failure", "cancelled"} for target in targets
        ),
    )
    queue_depth = reconciliation.queued + reconciliation.retry_wait
    nonterminal_backlog = (
        reconciliation.queued + reconciliation.running + reconciliation.retry_wait
    )
    oldest_age = max(
        (
            max(0.0, (now - _aware(target.created_at)).total_seconds())
            for target in targets
            if target.status in {"queued", "retryable_failure"}
        ),
        default=0.0,
    )
    terminal_count = reconciliation.success + reconciliation.failed
    terminal_target_ids = {
        target.id
        for target in targets
        if target.status in {"succeeded", "terminal_failure", "cancelled"}
    }
    terminal_worker_seconds = (
        sum(
            _execution_wall_ms(attempt)
            for attempt in task_executions
            if attempt.scrape_target_id in terminal_target_ids
            and attempt.status != "duplicate"
        )
        / 1000
    )
    source_budget = 1 / max(
        settings.pricing_collection_min_interval_seconds,
        0.001,
    )
    database_writes = await _pricing_database_writes(
        session,
        run.id,
        target_ids,
        requests,
        http_attempts,
        task_attempts,
    )
    p_success = reconciliation.success / terminal_count if terminal_count else 0.0
    if terminal_count and terminal_worker_seconds > 0:
        mean_terminal_worker_time = terminal_worker_seconds / terminal_count
        capacity = calculate_derived_capacity(
            arrival_rate_items_per_second=arrival_rate_items_per_second,
            mean_terminal_item_time_seconds=mean_terminal_worker_time,
            worker_count=max(1, settings.pricing_collection_worker_count),
            parallel_efficiency=parallel_efficiency,
            average_http_attempts_per_item=retry.http_attempts_per_item,
            source_request_budget_per_second=source_budget,
            average_database_writes_per_item=(
                database_writes / len(targets) if targets else 0.0
            ),
            database_write_capacity_per_second=(database_write_capacity_per_second),
            queue_capacity_items_per_second=queue_capacity_items_per_second,
            success_probability=p_success,
            backlog=nonterminal_backlog,
        )
    else:
        capacity = calculate_measured_capacity(
            measured_terminal_capacity_items_per_second=0.0,
            arrival_rate_items_per_second=arrival_rate_items_per_second,
            success_probability=p_success,
            backlog=nonterminal_backlog,
            worker_count=max(1, settings.pricing_collection_worker_count),
            parallel_efficiency=parallel_efficiency,
        )
    request_kinds = Counter(request.request_kind for request in requests)
    request_outcomes = Counter(
        (request.request_kind, request.outcome) for request in requests
    )
    request_kind_by_id = {request.id: request.request_kind for request in requests}
    http_attempt_outcomes = Counter(
        (
            request_kind_by_id.get(attempt.logical_request_id, "unknown"),
            attempt.outcome,
            attempt.status_class,
        )
        for attempt in http_attempts
    )
    task_outcomes = Counter(attempt.status for attempt in task_executions)
    elapsed_seconds = _elapsed_seconds(run.created_at, run.finished_at or now)
    storage = await _pricing_storage(
        session,
        run.id,
        target_ids,
        requests,
        http_attempts,
        task_attempts,
    )
    warnings = list(legacy_metrics.warnings) + list(capacity.warnings)
    warnings.append("source_budget_is_configured_not_benchmark_proven")
    if not reconciliation.reconciled:
        warnings.append("silent_loss_detected")
    if database_write_capacity_per_second is None:
        warnings.append("database_capacity_not_configured")
    if queue_capacity_items_per_second is None:
        warnings.append("broker_capacity_not_configured")
    warnings.append("database_write_count_is_persisted_row_footprint")
    if not storage["index_and_database_overhead_measured"]:
        warnings.append("storage_index_and_database_overhead_unmeasured")
    resource_metrics = _resource_dependency_metrics(
        executions=task_executions,
        requests=requests,
        database_probe_latency_seconds=database_latency,
        outbox=dispatch_health,
    )
    identity_spine, identity_health = await _pricing_identity_spine(
        session,
        run.id,
        targets,
    )
    previous_run_id = await session.scalar(
        select(PricingRun.id)
        .where(
            PricingRun.workspace_id == run.workspace_id,
            PricingRun.created_at < run.created_at,
        )
        .order_by(PricingRun.created_at.desc(), PricingRun.id.desc())
        .limit(1)
    )
    baseline_health: IdentityHealthSnapshot | None = None
    if previous_run_id is not None:
        previous_targets = list(
            (
                await session.scalars(
                    select(ScrapeTarget).where(
                        ScrapeTarget.pricing_run_id == previous_run_id
                    )
                )
            ).all()
        )
        _, baseline_health = await _pricing_identity_spine(
            session,
            previous_run_id,
            previous_targets,
        )
    health_thresholds = IdentityHealthThresholds(
        parser_schema_changed_alert_count=(
            settings.pricing_parser_schema_changed_alert_count
        ),
        parser_schema_changed_critical_rate=(
            settings.pricing_parser_schema_changed_critical_rate
        ),
        offer_internal_failure_alert_count=(
            settings.pricing_offer_internal_failure_alert_count
        ),
        evidence_accounting_error_critical_count=(
            settings.pricing_evidence_accounting_error_critical_count
        ),
        verified_oe_drop_warning_delta=(
            settings.pricing_verified_oe_drop_warning_delta
        ),
        source_confidence_p50_drop_warning_delta=(
            settings.pricing_source_confidence_p50_drop_warning_delta
        ),
    )
    identity_spine["health"] = {
        "policy_version": IDENTITY_HEALTH_POLICY_VERSION,
        "baseline_run_id": (
            str(previous_run_id) if previous_run_id is not None else None
        ),
        "current": identity_health.as_dict(),
        "baseline": baseline_health.as_dict() if baseline_health else None,
        "thresholds": {
            "parser_schema_changed_alert_count": (
                health_thresholds.parser_schema_changed_alert_count
            ),
            "parser_schema_changed_critical_rate": format(
                health_thresholds.parser_schema_changed_critical_rate,
                "f",
            ),
            "offer_internal_failure_alert_count": (
                health_thresholds.offer_internal_failure_alert_count
            ),
            "evidence_accounting_error_critical_count": (
                health_thresholds.evidence_accounting_error_critical_count
            ),
            "verified_oe_drop_warning_delta": format(
                health_thresholds.verified_oe_drop_warning_delta,
                "f",
            ),
            "source_confidence_p50_drop_warning_delta": format(
                health_thresholds.source_confidence_p50_drop_warning_delta,
                "f",
            ),
        },
        "alerts": [
            alert.as_dict()
            for alert in evaluate_identity_health(
                identity_health,
                health_thresholds,
                baseline=baseline_health,
            )
        ],
    }
    return {
        "generated_at": now,
        "scope_id": run.id,
        "item_kind": "comparison_job",
        "item_version": run.parser_version,
        "configuration_fingerprint": _configuration_fingerprint(
            {
                "adapter_version": run.parser_version,
                "worker_count": settings.pricing_collection_worker_count,
                "max_task_executions": (
                    settings.pricing_collection_max_task_executions
                ),
                "max_http_attempts": (settings.pricing_scraper_http_max_attempts),
                "max_search_pages": settings.pricing_scraper_max_search_pages,
                "max_sellers": settings.pricing_scraper_max_sellers,
                "global_min_interval": (
                    settings.pricing_collection_min_interval_seconds
                ),
                "identity_health_policy_version": IDENTITY_HEALTH_POLICY_VERSION,
                "parser_schema_changed_critical_rate": (
                    settings.pricing_parser_schema_changed_critical_rate
                ),
                "verified_oe_drop_warning_delta": (
                    settings.pricing_verified_oe_drop_warning_delta
                ),
                "source_confidence_p50_drop_warning_delta": (
                    settings.pricing_source_confidence_p50_drop_warning_delta
                ),
            }
        ),
        "dataset_fingerprint": _configuration_fingerprint(
            sorted(target.input_hash for target in targets)
        ),
        "item_lifecycle": {
            "scrape_items_submitted_total": run.total_items,
            "scrape_items_valid_total": len(targets),
            "scrape_items_deduplicated_total": max(
                0,
                run.total_items - len(targets),
            ),
            "scrape_items_terminal_total": {
                "success": reconciliation.success,
                "failed": reconciliation.failed,
            },
            "scrape_items_inflight": {
                "queued": reconciliation.queued,
                "running": reconciliation.running,
                "retry_wait": reconciliation.retry_wait,
            },
        },
        "reconciliation": reconciliation.as_dict(),
        "retry": retry.as_dict(),
        "capacity": capacity.as_dict(),
        "latency_seconds": {
            "request": _latency_groups(
                requests,
                value=lambda row: row.latency_ms / 1000,
                label=lambda row: f"{row.request_kind}:{row.outcome}",
            ),
            "page": _percentiles(
                [
                    request.latency_ms / 1000
                    for request in requests
                    if request.request_kind in {"search_page", "product_page"}
                ]
            ),
            "task_runtime": _latency_groups(
                task_attempts,
                value=lambda row: row.wall_time_ms / 1000,
                label=lambda row: row.status,
            ),
            "queue_wait": _percentiles(
                [
                    max(
                        0.0,
                        (
                            _aware(target.first_started_at) - _aware(target.created_at)
                        ).total_seconds(),
                    )
                    for target in targets
                    if target.first_started_at is not None
                ]
            ),
            "end_to_end_item": {
                "p50": legacy_metrics.latency_p50,
                "p95": legacy_metrics.latency_p95,
                "p99": legacy_metrics.latency_p99,
            },
        },
        "requests": {
            "scrape_logical_requests_total": _counter_rows(
                request_kinds,
                ("request_kind",),
            ),
            "logical_request_outcomes": _counter_rows(
                request_outcomes,
                ("request_kind", "outcome"),
            ),
            "scrape_http_attempts_total": _counter_rows(
                http_attempt_outcomes,
                ("request_kind", "outcome", "status_class"),
            ),
            "scrape_http_attempts_per_request": retry.http_attempts_per_request,
            "scrape_http_attempts_per_item": retry.http_attempts_per_item,
            "scrape_http_request_rate": (
                len(http_attempts) / elapsed_seconds if elapsed_seconds else 0.0
            ),
            "scrape_retry_backoff_seconds": sum(
                attempt.retry_backoff_ms for attempt in http_attempts
            )
            / 1000,
        },
        "queue_workers": {
            "scrape_queue_depth": queue_depth,
            "scrape_oldest_item_age_seconds": oldest_age,
            "scrape_worker_slots": {
                "configured": settings.pricing_collection_worker_count,
                "busy": reconciliation.running,
            },
            "scrape_task_executions_total": _counter_rows(
                task_outcomes,
                ("outcome",),
            ),
            "scrape_task_redeliveries_total": sum(
                max(0, target.delivery_count - 1) for target in targets
            ),
            "scrape_worker_lost_total": task_outcomes.get("worker_lost", 0),
        },
        "domain_output": {
            "scrape_catalog_pages_total": 0,
            "catalog_page_outcomes": {},
            "scrape_products_extracted_total": sum(
                _target_offer_count(target) for target in targets
            ),
            "scrape_products_persisted_total": await _count_run_observations(
                session,
                run.id,
            ),
            "scrape_duplicate_products_total": max(
                0,
                run.total_items - len(targets),
            ),
            "scrape_structured_completeness_ratio": (
                legacy_metrics.structured_completeness
            ),
            "scrape_evidence_coverage_ratio": await _pricing_evidence_coverage(
                session,
                target_ids,
            ),
            "scrape_raw_evidence_bytes_total": (legacy_metrics.raw_storage_bytes),
            "scrape_database_writes_total": database_writes,
        },
        "rates": {
            "comparison_jobs_per_hour": _per_minute(
                reconciliation.success,
                elapsed_seconds,
            )
            * 60,
            "search_pages_per_minute": _per_minute(
                request_kinds.get("search_page", 0),
                elapsed_seconds,
            ),
            "offers_per_minute": _per_minute(
                sum(_target_offer_count(target) for target in targets),
                elapsed_seconds,
            ),
            "logical_requests_per_minute": _per_minute(
                len(requests),
                elapsed_seconds,
            ),
            "physical_attempts_per_minute": _per_minute(
                len(http_attempts),
                elapsed_seconds,
            ),
        },
        "storage": storage,
        "resources_dependencies": resource_metrics,
        "identity_spine": identity_spine,
        "compatibility_metrics": _compatibility_metrics(
            item_kind="comparison_job",
            unique_urls_total=legacy_metrics.unique_urls_total,
            unique_inputs_total=len(targets),
            attempts_total=len(http_attempts),
            success_total=reconciliation.success,
            retryable_failure_total=sum(
                attempt.outcome == "retryable_failure" for attempt in http_attempts
            ),
            terminal_failure_total=reconciliation.failed,
            duplicate_total=legacy_metrics.duplicate_total,
            throughput_per_minute=legacy_metrics.throughput_urls_per_minute,
            latency={
                "p50": legacy_metrics.latency_p50,
                "p95": legacy_metrics.latency_p95,
                "p99": legacy_metrics.latency_p99,
            },
            retry_amplification=retry.http_attempts_per_item,
            structured_completeness=(legacy_metrics.structured_completeness),
            raw_storage_bytes=storage["raw_unique_bytes"],
            queue_depth=queue_depth,
            oldest_job_age=oldest_age,
            worker_count=max(1, settings.pricing_collection_worker_count),
            elapsed_seconds=elapsed_seconds,
            execution_wall_ms=sum(row.wall_time_ms for row in task_attempts),
            memory_peak=resource_metrics["process_resident_memory_bytes"],
            cpu_average=resource_metrics["process_cpu_utilization"] * 100,
        ),
        "warnings": list(dict.fromkeys(warnings)),
    }


def render_prometheus(snapshot: dict[str, Any]) -> str:
    """Render the mandatory metric family without adding a client dependency."""

    kind = str(snapshot["item_kind"])
    lifecycle = snapshot["item_lifecycle"]
    retry = snapshot["retry"]
    queue = snapshot["queue_workers"]
    domain = snapshot["domain_output"]
    requests = snapshot["requests"]
    resources = snapshot["resources_dependencies"]
    latency = snapshot["latency_seconds"]
    lines: list[str] = []

    def metric(name: str, value: Any, **labels: Any) -> None:
        numeric = _prom_number(value)
        label_text = ""
        normalized_labels = {"item_kind": kind, **labels}
        if normalized_labels:
            encoded = ",".join(
                f'{key}="{_escape_label(str(item))}"'
                for key, item in sorted(normalized_labels.items())
            )
            label_text = f"{{{encoded}}}"
        lines.append(f"{name}{label_text} {numeric}")

    metric(
        "scrape_items_submitted_total",
        lifecycle["scrape_items_submitted_total"],
    )
    metric("scrape_items_valid_total", lifecycle["scrape_items_valid_total"])
    metric(
        "scrape_items_deduplicated_total",
        lifecycle["scrape_items_deduplicated_total"],
    )
    for status, value in lifecycle["scrape_items_terminal_total"].items():
        metric("scrape_items_terminal_total", value, status=status)
    for state, value in lifecycle["scrape_items_inflight"].items():
        metric("scrape_items_inflight", value, state=state)
    for stage, quantiles in latency.items():
        if isinstance(quantiles, dict) and all(
            key in {"p50", "p95", "p99"} for key in quantiles
        ):
            for quantile, value in quantiles.items():
                metric(
                    "scrape_item_latency_seconds",
                    value,
                    stage=stage,
                    quantile=quantile,
                )
    for label, quantiles in latency.get("request", {}).items():
        request_kind, outcome = label.split(":", 1)
        for quantile, value in quantiles.items():
            metric(
                "scrape_http_request_latency_seconds",
                value,
                request_kind=request_kind,
                outcome=outcome,
                quantile=quantile,
            )
    for outcome, quantiles in latency.get("task_runtime", {}).items():
        for quantile, value in quantiles.items():
            metric(
                "scrape_task_runtime_seconds",
                value,
                outcome=outcome,
                quantile=quantile,
            )
    for row in requests["scrape_logical_requests_total"]:
        metric(
            "scrape_logical_requests_total",
            row["value"],
            request_kind=row["request_kind"],
        )
    for row in requests["scrape_http_attempts_total"]:
        metric(
            "scrape_http_attempts_total",
            row["value"],
            request_kind=row["request_kind"],
            outcome=row["outcome"],
            status_class=row["status_class"],
        )
    metric(
        "scrape_http_attempts_per_request",
        retry["http_attempts_per_request"],
    )
    metric(
        "scrape_http_attempts_per_item",
        retry["http_attempts_per_item"],
    )
    metric(
        "scrape_http_request_rate",
        requests["scrape_http_request_rate"],
    )
    metric(
        "scrape_retry_backoff_seconds",
        requests["scrape_retry_backoff_seconds"],
    )
    metric("scrape_queue_depth", queue["scrape_queue_depth"], queue=kind)
    metric(
        "scrape_oldest_item_age_seconds",
        queue["scrape_oldest_item_age_seconds"],
        queue=kind,
    )
    for state, value in queue["scrape_worker_slots"].items():
        metric("scrape_worker_slots", value, state=state)
    for row in queue["scrape_task_executions_total"]:
        metric(
            "scrape_task_executions_total",
            row["value"],
            outcome=row["outcome"],
        )
    metric(
        "scrape_task_redeliveries_total",
        queue["scrape_task_redeliveries_total"],
        reason="all",
    )
    metric("scrape_worker_lost_total", queue["scrape_worker_lost_total"])
    catalog_outcomes = domain.get("catalog_page_outcomes", {})
    if catalog_outcomes:
        for outcome, value in catalog_outcomes.items():
            metric("scrape_catalog_pages_total", value, outcome=outcome)
    else:
        metric(
            "scrape_catalog_pages_total",
            domain["scrape_catalog_pages_total"],
            outcome="all",
        )
    for name in (
        "scrape_products_extracted_total",
        "scrape_products_persisted_total",
        "scrape_duplicate_products_total",
        "scrape_structured_completeness_ratio",
        "scrape_evidence_coverage_ratio",
        "scrape_raw_evidence_bytes_total",
    ):
        metric(name, domain[name])
    metric(
        "scrape_database_writes_total",
        domain["scrape_database_writes_total"],
        entity="all",
    )
    metric(
        "process_cpu_utilization",
        resources["process_cpu_utilization"],
    )
    metric(
        "process_resident_memory_bytes",
        resources["process_resident_memory_bytes"],
    )
    metric("database_pool_in_use", resources["database_pool_in_use"])
    metric(
        "database_probe_latency_seconds",
        resources["database_probe_latency_seconds"],
        available=str(resources["database_probe_latency_seconds"] is not None).lower(),
    )
    metric(
        "database_transaction_latency_seconds",
        resources["database_transaction_latency_seconds"],
        available="false",
    )
    metric(
        "broker_publish_latency_seconds",
        resources["broker_publish_latency_seconds"],
        available="false",
    )
    metric(
        "broker_consumer_lag",
        resources["broker_consumer_lag"],
        available="false",
    )
    metric("scrape_outbox_pending", resources.get("outbox_pending", 0))
    metric("scrape_outbox_dispatching", resources.get("outbox_dispatching", 0))
    metric(
        "scrape_outbox_terminal_failed",
        resources.get("outbox_terminal_failed", 0),
    )
    metric(
        "scrape_outbox_oldest_pending_age_seconds",
        resources.get("outbox_oldest_pending_age_seconds", 0),
    )
    metric(
        "object_storage_write_latency_seconds",
        resources["object_storage_write_latency_seconds"],
        available="false",
    )
    return "\n".join(lines) + "\n"


async def render_latest_operational_prometheus(session: AsyncSession) -> str:
    """Render the latest store and pricing snapshots for internal Prometheus.

    This endpoint is deployment-scoped rather than user-scoped. The production
    edge must not expose it publicly; Prometheus reaches the API directly over
    the private Compose network.
    """

    latest_sync = await session.scalar(
        select(SyncRun)
        .where(SyncRun.workspace_id.is_not(None))
        .order_by(SyncRun.created_at.desc(), SyncRun.id.desc())
        .limit(1)
    )
    latest_pricing = await session.scalar(
        select(PricingRun)
        .order_by(PricingRun.created_at.desc(), PricingRun.id.desc())
        .limit(1)
    )
    sections = [
        "# HELP marko_metrics_snapshot_available Whether a latest operational snapshot exists.",
        "# TYPE marko_metrics_snapshot_available gauge",
    ]
    settings = get_settings()
    redis = AsyncRedis.from_url(settings.celery_broker_url, decode_responses=True)
    try:
        scheduler_token = await redis.get(settings.scheduler_singleton_lock_key)
        scheduler_ttl = await redis.ttl(settings.scheduler_singleton_lock_key)
    except Exception:
        scheduler_token = None
        scheduler_ttl = -1
        scheduler_probe_success = 0
    else:
        scheduler_probe_success = 1
    finally:
        await redis.aclose()
    sections.extend(
        (
            "# HELP marko_scheduler_lease_probe_success Whether Redis lease state could be read.",
            "# TYPE marko_scheduler_lease_probe_success gauge",
            f"marko_scheduler_lease_probe_success {scheduler_probe_success}",
            "# HELP marko_scheduler_lease_present Whether a scheduler lease currently exists.",
            "# TYPE marko_scheduler_lease_present gauge",
            f"marko_scheduler_lease_present {int(bool(scheduler_token) and scheduler_ttl > 0)}",
            "# HELP marko_scheduler_lease_ttl_seconds Remaining scheduler lease TTL.",
            "# TYPE marko_scheduler_lease_ttl_seconds gauge",
            f"marko_scheduler_lease_ttl_seconds {max(0, int(scheduler_ttl))}",
        )
    )
    if latest_sync is None or latest_sync.workspace_id is None:
        sections.append(
            'marko_metrics_snapshot_available{item_kind="store_sync"} 0'
        )
    else:
        sections.append(
            'marko_metrics_snapshot_available{item_kind="store_sync"} 1'
        )
        sections.append(
            render_prometheus(
                await get_store_sync_scraper_metrics(
                    session,
                    workspace_id=latest_sync.workspace_id,
                    sync_run_id=latest_sync.id,
                )
            ).rstrip()
        )
    if latest_pricing is None:
        sections.append(
            'marko_metrics_snapshot_available{item_kind="comparison_job"} 0'
        )
    else:
        sections.append(
            'marko_metrics_snapshot_available{item_kind="comparison_job"} 1'
        )
        sections.append(
            render_prometheus(
                await get_pricing_run_scraper_metrics(
                    session,
                    workspace_id=latest_pricing.workspace_id,
                    run_id=latest_pricing.id,
                )
            ).rstrip()
        )
    return "\n".join(sections) + "\n"


def _store_reconciliation(run: SyncRun):
    state = run.scrape_state
    return reconcile_items(
        valid_total=1,
        queued=int(state == "queued"),
        running=int(state == "running"),
        retry_wait=int(state == "retry_wait"),
        success=int(state == "succeeded"),
        failed=int(state in {"failed", "cancelled"}),
    )


async def _store_queue_health(
    session: AsyncSession,
    now: datetime,
) -> tuple[int, float]:
    active = list(
        (
            await session.scalars(
                select(SyncRun).where(
                    SyncRun.scrape_state.in_(("queued", "retry_wait"))
                )
            )
        ).all()
    )
    oldest = max(
        (max(0.0, (now - _aware(run.created_at)).total_seconds()) for run in active),
        default=0.0,
    )
    return len(active), round(oldest, 3)


async def _store_storage(
    session: AsyncSession,
    run: SyncRun,
    requests: list[ScrapeHttpRequest],
    attempts: list[ScrapeHttpAttempt],
    executions: list[StoreSyncTaskExecution],
) -> dict[str, Any]:
    snapshots = list(
        (
            await session.scalars(
                select(StoreSyncProductSnapshot).where(
                    StoreSyncProductSnapshot.sync_run_id == run.id
                )
            )
        ).all()
    )
    observations = list(
        (
            await session.scalars(
                select(PriceObservation).where(PriceObservation.sync_run_id == run.id)
            )
        ).all()
    )
    structured_bytes = sum(row.structured_size_bytes for row in snapshots)
    observation_bytes = sum(
        _json_bytes(
            {
                "listing_id": str(observation.listing_id),
                "price": str(observation.price),
                "currency": observation.currency,
                "is_available": observation.is_available,
                "observed_at": observation.observed_at.isoformat(),
            }
        )
        for observation in observations
    )
    journal_bytes = (
        sum(_request_journal_bytes(row) for row in requests)
        + sum(_attempt_journal_bytes(row) for row in attempts)
        + sum(
            _json_bytes(
                {
                    "execution_no": row.execution_no,
                    "outcome": row.outcome,
                    "wall_time_ms": _execution_wall_ms(row),
                    "error_category": row.error_category,
                }
            )
            for row in executions
        )
    )
    raw_unique, raw_stored = await _raw_blob_sizes_for_requests(
        session,
        requests,
    )
    compression = raw_stored / raw_unique if raw_unique else 0.0
    model = calculate_storage(
        raw_unique_bytes=raw_unique,
        compression_ratio=compression,
        structured_bytes=structured_bytes,
        attempt_journal_bytes=journal_bytes,
        observation_bytes=observation_bytes,
        recommendation_lineage_bytes=0,
        index_and_database_overhead_bytes=0,
    )
    payload = model.as_dict()
    payload["structured_snapshot_count"] = len(snapshots)
    payload["index_and_database_overhead_measured"] = False
    return payload


async def _pricing_storage(
    session: AsyncSession,
    run_id: UUID,
    target_ids: list[UUID],
    requests: list[ScrapeHttpRequest],
    attempts: list[ScrapeHttpAttempt],
    task_attempts: list[ScrapeAttempt],
) -> dict[str, Any]:
    targets = (
        list(
            (
                await session.scalars(
                    select(ScrapeTarget).where(ScrapeTarget.id.in_(target_ids))
                )
            ).all()
        )
        if target_ids
        else []
    )
    structured_bytes = sum(
        target.structured_size_bytes + target.metadata_size_bytes for target in targets
    )
    observations = list(
        (
            await session.scalars(
                select(MarketObservation)
                .join(
                    PricingRunItem,
                    PricingRunItem.id == MarketObservation.pricing_run_item_id,
                )
                .where(PricingRunItem.pricing_run_id == run_id)
            )
        ).all()
    )
    captures = list(
        (
            await session.scalars(
                select(RawMarketCapture)
                .join(
                    PricingRunItem,
                    PricingRunItem.id == RawMarketCapture.pricing_run_item_id,
                )
                .where(PricingRunItem.pricing_run_id == run_id)
            )
        ).all()
    )
    classifications = list(
        (
            await session.scalars(
                select(ObservationTierClassification)
                .join(
                    MarketObservation,
                    MarketObservation.id
                    == ObservationTierClassification.market_observation_id,
                )
                .join(
                    PricingRunItem,
                    PricingRunItem.id == MarketObservation.pricing_run_item_id,
                )
                .where(PricingRunItem.pricing_run_id == run_id)
            )
        ).all()
    )
    observation_bytes = sum(
        _json_bytes(
            {
                "id": str(row.id),
                "seller_id": row.seller_id,
                "price": str(row.price),
                "currency": row.currency,
                "url": row.url,
                "observed_at": row.observed_at.isoformat(),
            }
        )
        for row in observations
    )
    observation_bytes += sum(
        _json_bytes(
            {
                "id": str(row.id),
                "pricing_run_item_id": str(row.pricing_run_item_id),
                "scrape_target_id": (
                    str(row.scrape_target_id)
                    if row.scrape_target_id is not None
                    else None
                ),
                "capture_kind": row.capture_kind,
                "payload": row.payload,
                "content_sha256": row.content_sha256,
                "captured_at": row.captured_at.isoformat(),
            }
        )
        for row in captures
    )
    observation_bytes += sum(
        _json_bytes(
            {
                "market_observation_id": str(row.market_observation_id),
                "tier": row.tier,
                "tier_confidence": str(row.tier_confidence),
                "is_used": row.is_used,
                "is_kemp": row.is_kemp,
                "is_owned": row.is_owned,
                "is_dumping": row.is_dumping,
                "exclusion_reason": row.exclusion_reason,
                "reason_codes": row.reason_codes,
                "method_version": row.method_version,
            }
        )
        for row in classifications
    )
    recommendations = list(
        (
            await session.scalars(
                select(PricingRecommendation).where(
                    PricingRecommendation.pricing_run_id == run_id
                )
            )
        ).all()
    )
    recommendation_lineage_bytes = sum(
        _json_bytes(
            {
                "context_snapshot": row.context_snapshot,
                "calculation_trace": row.calculation_trace,
                "policy_version": row.policy_version,
                "parser_version": row.parser_version,
                "classifier_version": row.classifier_version,
                "coefficient_version": row.coefficient_version,
            }
        )
        for row in recommendations
    )
    journal_bytes = (
        sum(_request_journal_bytes(row) for row in requests)
        + sum(_attempt_journal_bytes(row) for row in attempts)
        + sum(
            _json_bytes(
                {
                    "target_id": str(row.scrape_target_id),
                    "delivery_no": row.delivery_no,
                    "status": row.status,
                    "wall_time_ms": row.wall_time_ms,
                    "error_category": row.error_category,
                }
            )
            for row in task_attempts
        )
    )
    raw_unique, raw_stored = await _raw_blob_sizes_for_requests(
        session,
        requests,
    )
    compression = raw_stored / raw_unique if raw_unique else 0.0
    model = calculate_storage(
        raw_unique_bytes=raw_unique,
        compression_ratio=compression,
        structured_bytes=structured_bytes,
        attempt_journal_bytes=journal_bytes,
        observation_bytes=observation_bytes,
        recommendation_lineage_bytes=recommendation_lineage_bytes,
        index_and_database_overhead_bytes=0,
    )
    payload = model.as_dict()
    payload["index_and_database_overhead_measured"] = False
    return payload


async def _raw_blob_sizes_for_requests(
    session: AsyncSession,
    requests: list[ScrapeHttpRequest],
) -> tuple[int, int]:
    blob_ids = {
        request.evidence_blob_id
        for request in requests
        if request.evidence_blob_id is not None
    }
    if not blob_ids:
        return 0, 0
    raw, stored = (
        await session.execute(
            select(
                func.coalesce(func.sum(ScrapeEvidenceBlob.raw_size_bytes), 0),
                func.coalesce(func.sum(ScrapeEvidenceBlob.stored_size_bytes), 0),
            ).where(ScrapeEvidenceBlob.id.in_(blob_ids))
        )
    ).one()
    return int(raw), int(stored)


async def _pricing_identity_spine(
    session: AsyncSession,
    run_id: UUID,
    targets: list[ScrapeTarget],
) -> tuple[dict[str, Any], IdentityHealthSnapshot]:
    outcome_counts = Counter(
        {
            code: int(count)
            for code, count in (
                await session.execute(
                    select(
                        OfferProcessingOutcome.outcome_code,
                        func.count(OfferProcessingOutcome.id),
                    )
                    .join(
                        PricingRunItem,
                        PricingRunItem.id == OfferProcessingOutcome.pricing_run_item_id,
                    )
                    .where(PricingRunItem.pricing_run_id == run_id)
                    .group_by(OfferProcessingOutcome.outcome_code)
                )
            ).all()
        }
    )
    observation_rows = list(
        (
            await session.execute(
                select(
                    MarketObservation.oe_verification_status,
                    MarketObservation.source_confidence,
                )
                .join(
                    PricingRunItem,
                    PricingRunItem.id == MarketObservation.pricing_run_item_id,
                )
                .where(PricingRunItem.pricing_run_id == run_id)
            )
        ).all()
    )
    verification_counts = Counter(status for status, _ in observation_rows)
    confidence_values = sorted(
        Decimal(str(confidence)) for _, confidence in observation_rows
    )
    confidence_p50 = _decimal_median(confidence_values)
    parser_schema_changed = sum(
        target.error_category == "parser_schema_changed" for target in targets
    )
    accounting_errors = sum(
        "EVIDENCE_ACCOUNTING_ERROR" in (target.reason_codes or []) for target in targets
    )
    internal_failures = outcome_counts.get("FAILED_INTERNAL_PROCESSING", 0)
    retrieved = sum(outcome_counts.values())
    observations_persisted = outcome_counts.get("OBSERVATION_PERSISTED", 0)
    rejected = retrieved - observations_persisted - internal_failures
    empty_results = sum(
        isinstance(target.payload, dict)
        and isinstance(target.payload.get("output"), dict)
        and target.payload["output"].get("acquisition_outcome") == "EMPTY_SEARCH_RESULT"
        for target in targets
    )
    verified = verification_counts.get("VERIFIED_EXACT", 0) + verification_counts.get(
        "VERIFIED_CROSS",
        0,
    )
    health = IdentityHealthSnapshot(
        parsed_pages=sum(
            target.parse_status in {"SUCCEEDED", "FAILED"} for target in targets
        ),
        parser_schema_changed=parser_schema_changed,
        offer_internal_failures=internal_failures,
        evidence_accounting_errors=accounting_errors,
        observations=len(observation_rows),
        verified_observations=verified,
        source_confidence_p50=confidence_p50,
    )
    return (
        {
            "pricing_query_only_targets_total": sum(
                target.input_kind == "query" for target in targets
            ),
            "pricing_product_seed_targets_total": sum(
                target.input_kind == "product_seed" for target in targets
            ),
            "prom_empty_search_result_total": empty_results,
            "prom_parser_schema_changed_total": parser_schema_changed,
            "offer_retrieved_total": retrieved,
            "offer_observation_persisted_total": observations_persisted,
            "offer_rejected_total": max(0, rejected),
            "offer_internal_failure_total": internal_failures,
            "offer_outcome_counts": dict(sorted(outcome_counts.items())),
            "oe_verification_total": dict(sorted(verification_counts.items())),
            "oe_verified_exact_total": verification_counts.get("VERIFIED_EXACT", 0),
            "oe_verified_cross_total": verification_counts.get("VERIFIED_CROSS", 0),
            "oe_unknown_total": verification_counts.get("UNKNOWN", 0),
            "oe_conflict_total": verification_counts.get("CONFLICT", 0),
            "oe_ambiguous_total": verification_counts.get("AMBIGUOUS", 0),
            "evidence_accounting_error_total": accounting_errors,
            "source_confidence_p50": (
                format(confidence_p50, "f") if confidence_p50 is not None else None
            ),
        },
        health,
    )


def _decimal_median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    midpoint = len(values) // 2
    if len(values) % 2:
        return values[midpoint]
    return (values[midpoint - 1] + values[midpoint]) / Decimal("2")


async def _pricing_database_writes(
    session: AsyncSession,
    run_id: UUID,
    target_ids: list[UUID],
    requests: list[ScrapeHttpRequest],
    http_attempts: list[ScrapeHttpAttempt],
    task_attempts: list[ScrapeAttempt],
) -> int:
    captures = int(
        await session.scalar(
            select(func.count(RawMarketCapture.id))
            .join(
                PricingRunItem,
                PricingRunItem.id == RawMarketCapture.pricing_run_item_id,
            )
            .where(PricingRunItem.pricing_run_id == run_id)
        )
        or 0
    )
    observations = await _count_run_observations(session, run_id)
    outcomes = int(
        await session.scalar(
            select(func.count(OfferProcessingOutcome.id))
            .join(
                PricingRunItem,
                PricingRunItem.id == OfferProcessingOutcome.pricing_run_item_id,
            )
            .where(PricingRunItem.pricing_run_id == run_id)
        )
        or 0
    )
    classifications = int(
        await session.scalar(
            select(func.count(ObservationTierClassification.id))
            .join(
                MarketObservation,
                MarketObservation.id
                == ObservationTierClassification.market_observation_id,
            )
            .join(
                PricingRunItem,
                PricingRunItem.id == MarketObservation.pricing_run_item_id,
            )
            .where(PricingRunItem.pricing_run_id == run_id)
        )
        or 0
    )
    return (
        len(target_ids)
        + len(task_attempts)
        + len(requests)
        + len(http_attempts)
        + captures
        + observations
        + outcomes
        + classifications
    )


async def _count_run_observations(
    session: AsyncSession,
    run_id: UUID,
) -> int:
    return int(
        await session.scalar(
            select(func.count(MarketObservation.id))
            .join(
                PricingRunItem,
                PricingRunItem.id == MarketObservation.pricing_run_item_id,
            )
            .where(PricingRunItem.pricing_run_id == run_id)
        )
        or 0
    )


async def _pricing_evidence_coverage(
    session: AsyncSession,
    target_ids: list[UUID],
) -> float:
    if not target_ids:
        return 0.0
    succeeded_target_ids = set(
        (
            await session.scalars(
                select(ScrapeTarget.id).where(
                    ScrapeTarget.id.in_(target_ids),
                    ScrapeTarget.status == "succeeded",
                )
            )
        ).all()
    )
    if not succeeded_target_ids:
        return 0.0
    succeeded_deliveries = {
        target_id: delivery_no
        for target_id, delivery_no in (
            await session.execute(
                select(
                    ScrapeAttempt.scrape_target_id,
                    func.max(ScrapeAttempt.delivery_no),
                )
                .where(
                    ScrapeAttempt.scrape_target_id.in_(succeeded_target_ids),
                    ScrapeAttempt.status == "succeeded",
                )
                .group_by(ScrapeAttempt.scrape_target_id)
            )
        ).all()
    }
    request_rows = list(
        (
            await session.execute(
                select(
                    ScrapeHttpRequest.scrape_target_id,
                    ScrapeHttpRequest.execution_no,
                    ScrapeHttpRequest.outcome,
                    ScrapeHttpRequest.evidence_blob_id,
                ).where(ScrapeHttpRequest.scrape_target_id.in_(succeeded_target_ids))
            )
        ).all()
    )
    by_target: dict[UUID, list[tuple[str, UUID | None]]] = {}
    for target_id, execution_no, outcome, blob_id in request_rows:
        if target_id is None:
            continue
        if succeeded_deliveries.get(target_id) != execution_no:
            continue
        by_target.setdefault(target_id, []).append((outcome, blob_id))
    covered = sum(
        bool(rows)
        and all(
            outcome in {"success", "replayed"} and blob_id is not None
            for outcome, blob_id in rows
        )
        for target_id in succeeded_target_ids
        for rows in [by_target.get(target_id, [])]
    )
    return covered / len(succeeded_target_ids)


def _target_offer_count(target: ScrapeTarget) -> int:
    if not isinstance(target.payload, dict):
        return 0
    output = target.payload.get("output")
    if not isinstance(output, dict):
        return 0
    records = output.get("records")
    if isinstance(records, list):
        return len(records)
    offers = output.get("offers")
    return len(offers) if isinstance(offers, list) else 0


def _resource_dependency_metrics(
    *,
    executions: list[Any],
    requests: list[ScrapeHttpRequest],
    database_probe_latency_seconds: float | None,
    outbox: OutboxHealth,
) -> dict[str, Any]:
    wall_ms = sum(_execution_wall_ms(row) for row in executions)
    cpu_ms = sum(max(0, int(row.cpu_time_ms)) for row in executions)
    memory_peak = max(
        (max(0, int(row.memory_peak_bytes)) for row in executions),
        default=0,
    )
    pool_in_use = 0
    checkedout = getattr(engine.pool, "checkedout", None)
    if callable(checkedout):
        try:
            pool_in_use = int(checkedout())
        except Exception:
            pool_in_use = 0
    return {
        "process_cpu_utilization": cpu_ms / wall_ms if wall_ms else 0.0,
        "process_resident_memory_bytes": memory_peak,
        "database_pool_in_use": pool_in_use,
        "database_probe_latency_seconds": database_probe_latency_seconds,
        "database_transaction_latency_seconds": None,
        "broker_publish_latency_seconds": None,
        "broker_consumer_lag": None,
        "outbox_pending": outbox.pending,
        "outbox_dispatching": outbox.dispatching,
        "outbox_terminal_failed": outbox.terminal_failed,
        "outbox_oldest_pending_age_seconds": outbox.oldest_pending_age_seconds,
        "object_storage_write_latency_seconds": None,
        "request_rate_wait_seconds": sum(row.rate_wait_ms for row in requests) / 1000,
    }


async def _database_probe_latency(
    session: AsyncSession,
) -> float | None:
    started = time.perf_counter()
    try:
        await session.execute(select(1))
    except Exception:
        return None
    return round(time.perf_counter() - started, 6)


def _execution_wall_ms(row: Any) -> int:
    measured = max(0, int(getattr(row, "wall_time_ms", 0) or 0))
    if measured:
        return measured
    started_at = getattr(row, "started_at", None)
    finished_at = getattr(row, "finished_at", None)
    if started_at is None or finished_at is None:
        return 0
    return max(
        0,
        round((_aware(finished_at) - _aware(started_at)).total_seconds() * 1000),
    )


def _compatibility_metrics(
    *,
    item_kind: str,
    unique_urls_total: int,
    unique_inputs_total: int,
    attempts_total: int,
    success_total: int,
    retryable_failure_total: int,
    terminal_failure_total: int,
    duplicate_total: int,
    throughput_per_minute: float,
    latency: dict[str, float | None],
    retry_amplification: float,
    structured_completeness: float,
    raw_storage_bytes: int,
    queue_depth: int,
    oldest_job_age: float,
    worker_count: int,
    elapsed_seconds: float,
    execution_wall_ms: int,
    memory_peak: int,
    cpu_average: float,
) -> dict[str, Any]:
    utilization = (
        execution_wall_ms / 1000 / (worker_count * elapsed_seconds)
        if elapsed_seconds
        else 0.0
    )
    return {
        "item_kind": item_kind,
        "unique_urls_total": unique_urls_total,
        "unique_inputs_total": unique_inputs_total,
        "attempts_total": attempts_total,
        "success_total": success_total,
        "retryable_failure_total": retryable_failure_total,
        "terminal_failure_total": terminal_failure_total,
        "duplicate_total": duplicate_total,
        "throughput_urls_per_minute": round(throughput_per_minute, 6),
        "latency_p50": latency.get("p50"),
        "latency_p95": latency.get("p95"),
        "latency_p99": latency.get("p99"),
        "retry_amplification": round(retry_amplification, 6),
        "structured_completeness": round(structured_completeness, 6),
        "raw_storage_bytes": raw_storage_bytes,
        "queue_depth": queue_depth,
        "oldest_job_age": round(oldest_job_age, 3),
        "worker_utilization": round(min(1.0, max(0.0, utilization)), 6),
        "memory_peak": memory_peak,
        "cpu_average": round(cpu_average, 6),
    }


def _latency_groups(rows, *, value, label) -> dict[str, dict[str, float | None]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        grouped.setdefault(str(label(row)), []).append(float(value(row)))
    return {key: _percentiles(values) for key, values in grouped.items()}


def _percentiles(values: list[float]) -> dict[str, float | None]:
    return {
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
    }


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 6)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 6)
    weight = position - lower
    return round(
        ordered[lower] * (1 - weight) + ordered[upper] * weight,
        6,
    )


def _counter_rows(counter: Counter, labels: tuple[str, ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for key, value in sorted(counter.items(), key=lambda row: str(row[0])):
        values = key if isinstance(key, tuple) else (key,)
        result.append(
            {
                **dict(zip(labels, values, strict=True)),
                "value": int(value),
            }
        )
    return result


def _request_journal_bytes(request: ScrapeHttpRequest) -> int:
    return _json_bytes(
        {
            "execution_no": request.execution_no,
            "sequence_no": request.sequence_no,
            "request_kind": request.request_kind,
            "request_key": request.request_key,
            "prepared_url": request.prepared_url,
            "outcome": request.outcome,
            "attempt_count": request.attempt_count,
            "latency_ms": request.latency_ms,
            "rate_wait_ms": request.rate_wait_ms,
            "backoff_ms": request.backoff_ms,
            "error_category": request.error_category,
        }
    )


def _attempt_journal_bytes(attempt: ScrapeHttpAttempt) -> int:
    return _json_bytes(
        {
            "attempt_no": attempt.attempt_no,
            "outcome": attempt.outcome,
            "status_code": attempt.status_code,
            "latency_ms": attempt.latency_ms,
            "local_rate_wait_ms": attempt.local_rate_wait_ms,
            "global_rate_wait_ms": attempt.global_rate_wait_ms,
            "retry_backoff_ms": attempt.retry_backoff_ms,
            "error_category": attempt.error_category,
        }
    )


def _json_bytes(value: Any) -> int:
    return len(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode()
    )


def _configuration_fingerprint(value: Any) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _elapsed_seconds(start: datetime, end: datetime) -> float:
    return max(0.0, (_aware(end) - _aware(start)).total_seconds())


def _per_minute(count: int, elapsed_seconds: float) -> float:
    return round(60 * count / elapsed_seconds, 6) if elapsed_seconds else 0.0


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _prom_number(value: Any) -> str:
    if value is None:
        return "NaN"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "NaN"
    if math.isnan(number):
        return "NaN"
    if math.isinf(number):
        return "+Inf" if number > 0 else "-Inf"
    return format(number, ".12g")


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


__all__ = [
    "get_pricing_run_scraper_metrics",
    "get_store_sync_scraper_metrics",
    "render_latest_operational_prometheus",
    "render_prometheus",
]
