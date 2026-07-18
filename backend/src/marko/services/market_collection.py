"""Scalable run adapter around the existing frozen Prom parser.

This module treats ``PromGateway`` as a black box.  It persists the gateway's
structured output before deriving observations, so retries can resume without
repeating a successful network collection.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Mapping
from uuid import UUID

from sqlalchemy import func, or_, select

from marko.core.config import get_settings
from marko.infrastructure.db.models import (
    BrandTierRule,
    CatalogItem,
    MarketObservation,
    MarketplaceStore,
    ObservationTierClassification,
    PricingRecommendation,
    PricingRun,
    PricingRunItem,
    RawMarketCapture,
    ScrapeAttempt,
    ScrapeEvidenceBlob,
    ScrapeHttpRequest,
    ScrapeTarget,
    StoreKind,
    WorkspaceStore,
)
from marko.infrastructure.db.session import async_session_factory
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.gateway import PromGateway
from metis.pricing import (
    CalibrationPair,
    CoefficientModel,
    CompetitorOffer,
    DEFAULT_BRAND_TIERS,
    ProductTier,
    RecommendationAction,
    TierClassification,
    bind_persisted_provenance,
    classify_tier,
    cluster_diagnostic_to_dict,
    comparison_evidence_from_dict,
    comparison_evidence_to_dict,
    HardGateResult,
    normalize_brand,
    recommend_price,
    robust_dispersion_trace,
)
from metis.pricing.statistics import median as decimal_median
from metis.pricing.observability import pricing_event
from marko.services.collection_guard import DistributedCollectionGuard
from marko.services.decision_fingerprint import (
    build_decision_fingerprint_payload,
    canonical_sha256,
)
from marko.services.matching import PriceComparison
from marko.services.pricing_runs import (
    build_pricing_context,
    activation_artifact_verified,
    calibrate_tier_coefficients,
    get_latest_override,
    load_target_tier_coefficients,
    persist_run_calibration_pairs,
    policy_from_dict,
    require_activated_run_policy,
)
from marko.services.scrape_journal import (
    evidence_coverage_ratio,
    load_replay_cache,
    persist_http_traces,
    retained_raw_evidence_bytes,
)
from marko.services.scrape_runtime import (
    ScrapeExecutionTrace,
    scrape_execution,
)
from marko.services.scraper_contract import (
    AttemptMeasurement,
    AttemptResourceProbe,
    FrozenPromScraperAdapter,
    ScrapeInput,
    ScrapeOutput,
    ScraperBoundaryError,
    ScraperErrorCode,
    classify_scraper_exception,
)
from marko.services.scraper_outbox import enqueue_dispatch
from marko.services.source_access import require_live_prom_marketplace_collection


class PricingItemNotFoundError(LookupError):
    pass


class PermanentCollectionError(RuntimeError):
    pass


CollectionAction = Literal[
    "legacy_collect",
    "target_collect",
    "target_materialize",
    "target_terminal",
    "target_busy",
]


@dataclass(frozen=True)
class CollectionClaim:
    action: CollectionAction
    run_id: UUID
    run_item_id: UUID
    catalog_item_id: UUID
    product_url: str | None
    oe_norm: str
    scrape_target_id: UUID | None = None
    scrape_attempt_id: UUID | None = None
    delivery_no: int = 0
    fencing_token: int = 0
    execution_no: int = 0
    task_id: str | None = None
    scrape_input: ScrapeInput | None = None
    stored_output: ScrapeOutput | None = None
    terminal_error: ScraperBoundaryError | None = None


async def prepare_run_dispatch(run_id: UUID) -> list[UUID]:
    """Move a run to collecting and durably enqueue one item per target."""
    async with async_session_factory() as session:
        run = await session.scalar(
            select(PricingRun).where(PricingRun.id == run_id).with_for_update()
        )
        if run is None:
            raise PricingItemNotFoundError(f"Pricing run {run_id} does not exist")
        if run.status in {"completed", "partial", "failed", "cancelled"}:
            return []
        if run.cancel_requested:
            items = list(
                (
                    await session.scalars(
                        select(PricingRunItem).where(
                            PricingRunItem.pricing_run_id == run_id,
                            PricingRunItem.status.not_in(
                                ("calculated", "manual_review", "failed", "cancelled")
                            ),
                        )
                    )
                ).all()
            )
            now = datetime.now(UTC)
            for item in items:
                item.status = "cancelled"
                item.finished_at = now
            targets = list(
                (
                    await session.scalars(
                        select(ScrapeTarget).where(
                            ScrapeTarget.pricing_run_id == run_id,
                            ScrapeTarget.status.not_in(
                                ("succeeded", "terminal_failure", "cancelled")
                            ),
                        )
                    )
                ).all()
            )
            for target in targets:
                target.status = "cancelled"
                target.finished_at = now
                target.owner_task_id = None
                target.lease_expires_at = None
            run.status = "cancelled"
            run.finished_at = now
            await session.commit()
            return []
        if run.started_at is None:
            run.started_at = datetime.now(UTC)
        run.status = "collecting"
        rows = list(
            (
                await session.execute(
                    select(PricingRunItem.id, PricingRunItem.scrape_target_id)
                    .where(
                        PricingRunItem.pricing_run_id == run_id,
                        PricingRunItem.status.in_(
                            ("queued", "collecting", "collected")
                        ),
                    )
                    .order_by(PricingRunItem.created_at, PricingRunItem.id)
                )
            ).all()
        )
        ids: list[UUID] = []
        dispatched_targets: set[UUID] = set()
        for item_id, target_id in rows:
            if target_id is None:
                ids.append(item_id)
                continue
            if target_id in dispatched_targets:
                continue
            dispatched_targets.add(target_id)
            ids.append(item_id)
        event_ids: list[UUID] = []
        for item_id in ids:
            event = await enqueue_dispatch(
                session,
                event_key=f"pricing-run:{run.id}:collect:{item_id}:v1",
                aggregate_type="pricing_run_item",
                aggregate_id=item_id,
                workspace_id=run.workspace_id,
                task_name="marko.worker.process_pricing_item",
                task_args=[str(item_id)],
                queue="pricing",
            )
            event_ids.append(event.id)
        await session.commit()
        return event_ids


async def enqueue_collection_finalizer_dispatch(
    run_id: UUID,
    *,
    trigger_key: str,
) -> UUID:
    """Durably enqueue one idempotent finalizer probe for a completed trigger."""

    async with async_session_factory() as session:
        run = await session.get(PricingRun, run_id)
        if run is None:
            raise PricingItemNotFoundError(str(run_id))
        event = await enqueue_dispatch(
            session,
            event_key=f"pricing-run:{run.id}:finalize:{trigger_key}:v1",
            aggregate_type="pricing_run",
            aggregate_id=run.id,
            workspace_id=run.workspace_id,
            task_name="marko.worker.finalize_pricing_collection",
            task_args=[str(run.id)],
            queue="celery",
        )
        await session.commit()
        return event.id


async def process_pricing_item(
    run_item_id: UUID,
    *,
    task_id: str | None = None,
    is_redelivery: bool = False,
) -> UUID | None:
    claim = await _claim_item(
        run_item_id,
        task_id=task_id,
        is_redelivery=is_redelivery,
    )
    if claim is None:
        return await _run_id_for_statuses(run_item_id, ("classified",))
    if claim.action == "target_busy":
        pricing_event(
            "scrape_target_duplicate_delivery",
            pricing_run_id=str(claim.run_id),
            scrape_target_id=str(claim.scrape_target_id),
            pricing_run_item_id=str(claim.run_item_id),
        )
        return claim.run_id
    if claim.action == "target_terminal":
        if claim.scrape_target_id is None or claim.terminal_error is None:
            raise RuntimeError("Invalid terminal target claim")
        await _mark_target_group_classified(
            claim.scrape_target_id,
            reason=claim.terminal_error.code.value,
            error=claim.terminal_error,
        )
        return claim.run_id
    if claim.action == "target_materialize":
        if claim.scrape_target_id is None:
            raise RuntimeError("Target materialization claim has no target")
        await _materialize_target_evidence(claim.scrape_target_id)
        return claim.run_id
    if claim.action == "target_collect":
        if (
            claim.scrape_target_id is None
            or claim.scrape_attempt_id is None
            or claim.scrape_input is None
        ):
            raise RuntimeError("Target collection claim is incomplete")
        settings = get_settings()
        if (
            settings.environment.strip().casefold() == "e2e"
            and settings.e2e_task_hold_seconds > 0
        ):
            await asyncio.sleep(settings.e2e_task_hold_seconds)
        return await _process_target_collection(claim)

    if await _has_capture(run_item_id):
        await _mark_classified(run_item_id, reason="resumed_from_capture")
        return claim.run_id
    if not claim.product_url:
        await _mark_classified(run_item_id, reason="missing_product_url")
        return claim.run_id
    try:
        comparison = await asyncio.to_thread(
            _collect_comparison,
            claim.product_url,
            claim.oe_norm,
        )
    except ValueError as exc:
        raise PermanentCollectionError(str(exc)) from exc
    await _persist_comparison(
        run_id=claim.run_id,
        run_item_id=run_item_id,
        catalog_item_id=claim.catalog_item_id,
        comparison=comparison,
    )
    return claim.run_id


async def _process_target_collection(claim: CollectionClaim) -> UUID:
    if (
        claim.scrape_target_id is None
        or claim.scrape_attempt_id is None
        or claim.scrape_input is None
    ):
        raise RuntimeError("Target collection claim is incomplete")
    scrape_target_id = claim.scrape_target_id
    scrape_input = claim.scrape_input
    settings = get_settings()
    probe = AttemptResourceProbe()
    trace: ScrapeExecutionTrace | None = None
    try:
        async with async_session_factory() as session:
            replay_cache = await load_replay_cache(
                session,
                scrape_target_id=scrape_target_id,
            )
        trace = ScrapeExecutionTrace(
            item_kind="comparison_job",
            execution_no=claim.delivery_no,
            replay_cache=replay_cache,
            guard=DistributedCollectionGuard(settings, namespace="prom"),
            live_request_gate=require_live_prom_marketplace_collection,
        )
        output = await asyncio.to_thread(
            _collect_target_output,
            scrape_input,
            trace,
        )
    except Exception as exc:
        measurement = probe.finish()
        error = (
            exc
            if isinstance(exc, ScraperBoundaryError)
            else classify_scraper_exception(exc)
        )
        if trace is None:
            trace = ScrapeExecutionTrace(
                item_kind="comparison_job",
                execution_no=claim.delivery_no,
            )
        persisted = await _persist_target_failure(
            claim,
            trace,
            measurement,
            error,
        )
        if not persisted:
            return claim.run_id
        if error.retryable:
            raise error
        await _mark_target_group_classified(
            scrape_target_id,
            reason=error.code.value,
            error=error,
        )
        return claim.run_id
    else:
        measurement = probe.finish()
        persisted = await _persist_target_success(
            claim,
            trace,
            measurement,
            output,
        )
        if persisted:
            await _materialize_target_evidence(scrape_target_id)
        return claim.run_id
    finally:
        try:
            await _refresh_target_attempt_measurement(
                claim,
                probe.finish(),
            )
        except Exception as measurement_error:
            pricing_event(
                "scrape_measurement_persistence_failed",
                item_kind="comparison_job",
                pricing_run_id=str(claim.run_id),
                scrape_target_id=str(claim.scrape_target_id),
                delivery_no=claim.delivery_no,
                error_type=type(measurement_error).__name__,
            )
        if trace is not None:
            trace.close()


def _collect_target_output(
    scrape_input: ScrapeInput,
    trace: ScrapeExecutionTrace,
) -> ScrapeOutput:
    settings = get_settings()
    config = ScrapeConfig(
        delay=settings.pricing_scraper_request_delay_seconds,
        delay_jitter=settings.pricing_scraper_request_jitter_seconds,
        timeout=settings.pricing_scraper_http_timeout_seconds,
        max_attempts=max(1, settings.pricing_scraper_http_max_attempts),
        max_sellers=max(1, settings.pricing_scraper_max_sellers),
        max_search_pages=max(1, settings.pricing_scraper_max_search_pages),
    )
    with scrape_execution(trace):
        output = FrozenPromScraperAdapter(config).extract(scrape_input)
    _raise_on_required_request_failure(trace)
    return output


def _raise_on_required_request_failure(trace: ScrapeExecutionTrace) -> None:
    failures = trace.failed_requests(
        request_kinds={"product_page", "search_page"},
    )
    if not failures:
        return
    failure = failures[0]
    mapping = {
        "rate_limited": (ScraperErrorCode.RATE_LIMITED, True),
        "timeout": (ScraperErrorCode.TIMEOUT, True),
        "upstream_5xx": (ScraperErrorCode.UPSTREAM_5XX, True),
        "retry_exhausted": (ScraperErrorCode.RETRY_EXHAUSTED, True),
        "upstream_3xx": (ScraperErrorCode.UPSTREAM_3XX, False),
        "upstream_4xx": (ScraperErrorCode.UPSTREAM_4XX, False),
        "parse_contract": (ScraperErrorCode.PARSE_CONTRACT, False),
    }
    code, retryable = mapping.get(
        failure.error_category or "",
        (ScraperErrorCode.NETWORK, failure.outcome == "retryable_failure"),
    )
    raise ScraperBoundaryError(
        code,
        "Required comparison request did not complete: "
        f"{failure.request_kind} {failure.error_detail or failure.outcome}",
        retryable=retryable,
    )


def _verified_target_output(target: ScrapeTarget) -> ScrapeOutput:
    if target.payload is None:
        raise ScraperBoundaryError(
            ScraperErrorCode.EVIDENCE_PERSISTENCE,
            "Succeeded target has no structured payload",
            retryable=False,
        )
    output = ScrapeOutput.from_payload(target.payload)
    if target.content_sha256 is None:
        raise ScraperBoundaryError(
            ScraperErrorCode.EVIDENCE_PERSISTENCE,
            "Succeeded target has no structured content identity",
            retryable=False,
        )
    if target.content_sha256 != output.content_sha256:
        raise ScraperBoundaryError(
            ScraperErrorCode.EVIDENCE_PERSISTENCE,
            "Stored target payload SHA-256 does not match its content identity",
            retryable=False,
        )
    return output


def _collect_comparison(product_url: str, oe_norm: str) -> PriceComparison:
    settings = get_settings()
    require_live_prom_marketplace_collection(settings)
    with DistributedCollectionGuard(settings) as guard:
        guard.wait_for_slot()
        try:
            comparison = PromGateway().compare(product_url, query=oe_norm)
        except Exception:
            guard.record_failure()
            raise
        guard.record_success()
        return comparison


async def _claim_item(
    run_item_id: UUID,
    *,
    task_id: str | None,
    is_redelivery: bool,
) -> CollectionClaim | None:
    async with async_session_factory() as session:
        item = await session.scalar(
            select(PricingRunItem)
            .where(PricingRunItem.id == run_item_id)
            .with_for_update()
        )
        if item is None:
            raise PricingItemNotFoundError(
                f"Pricing run item {run_item_id} does not exist"
            )
        if item.status in {"calculated", "manual_review", "failed", "cancelled"}:
            return None
        if item.status not in {"queued", "collecting", "collected"}:
            return None
        run = await session.get(PricingRun, item.pricing_run_id)
        catalog_item = await session.get(CatalogItem, item.catalog_item_id)
        if run is None or catalog_item is None:
            raise PricingItemNotFoundError("Pricing run item dependencies are missing")
        if run.cancel_requested:
            item.status = "cancelled"
            item.finished_at = datetime.now(UTC)
            await session.commit()
            await finalize_pricing_run(run.id)
            return None
        if item.scrape_target_id is not None:
            return await _claim_target_item(
                session,
                item=item,
                run=run,
                catalog_item=catalog_item,
                task_id=task_id,
                is_redelivery=is_redelivery,
            )
        if item.status == "collecting" and item.task_id and item.task_id != task_id:
            return None
        item.status = "collecting"
        item.task_id = task_id or item.task_id
        item.attempts += 1
        item.started_at = item.started_at or datetime.now(UTC)
        item.error = None
        item.checkpoint = {"stage": "collecting", "at": datetime.now(UTC).isoformat()}
        await session.commit()
        return CollectionClaim(
            action="legacy_collect",
            run_id=run.id,
            run_item_id=item.id,
            catalog_item_id=catalog_item.id,
            product_url=catalog_item.product_url,
            oe_norm=catalog_item.oe_norm,
        )


async def _claim_target_item(
    session,
    *,
    item: PricingRunItem,
    run: PricingRun,
    catalog_item: CatalogItem,
    task_id: str | None,
    is_redelivery: bool,
) -> CollectionClaim:
    target = await session.scalar(
        select(ScrapeTarget)
        .where(ScrapeTarget.id == item.scrape_target_id)
        .with_for_update()
    )
    if target is None:
        raise PricingItemNotFoundError("Scrape target dependency is missing")
    now = datetime.now(UTC)

    if target.status == "succeeded" and target.payload is not None:
        attempt = await _create_target_delivery_attempt(
            session,
            target=target,
            item=item,
            task_id=task_id,
            now=now,
        )
        try:
            output = _verified_target_output(target)
        except ScraperBoundaryError as exc:
            target.status = "terminal_failure"
            _set_terminal_target_contract(
                target,
                reason=exc.code.value,
                raw_available=target.raw_size_bytes > 0,
                parse_failed=True,
            )
            target.error_category = exc.code.value
            target.error_detail = str(exc)[:4000]
            target.owner_task_id = None
            target.lease_expires_at = None
            target.finished_at = now
            attempt.status = "terminal_failure"
            attempt.error_category = exc.code.value
            attempt.error_detail = str(exc)[:4000]
            attempt.finished_at = now
            await session.commit()
            return CollectionClaim(
                action="target_terminal",
                run_id=run.id,
                run_item_id=item.id,
                catalog_item_id=catalog_item.id,
                product_url=catalog_item.product_url,
                oe_norm=catalog_item.oe_norm,
                scrape_target_id=target.id,
                scrape_attempt_id=attempt.id,
                delivery_no=attempt.delivery_no,
                terminal_error=exc,
            )
        attempt.status = "duplicate"
        attempt.finished_at = now
        await session.commit()
        return CollectionClaim(
            action="target_materialize",
            run_id=run.id,
            run_item_id=item.id,
            catalog_item_id=catalog_item.id,
            product_url=catalog_item.product_url,
            oe_norm=catalog_item.oe_norm,
            scrape_target_id=target.id,
            scrape_attempt_id=attempt.id,
            delivery_no=attempt.delivery_no,
            stored_output=output,
        )

    if target.status == "terminal_failure":
        attempt = await _create_target_delivery_attempt(
            session,
            target=target,
            item=item,
            task_id=task_id,
            now=now,
        )
        try:
            error_code = ScraperErrorCode(
                target.error_category or ScraperErrorCode.UNEXPECTED.value
            )
        except ValueError:
            error_code = ScraperErrorCode.UNEXPECTED
        error = ScraperBoundaryError(
            error_code,
            target.error_detail or "Scrape target is terminal",
            retryable=False,
        )
        attempt.status = "duplicate"
        attempt.error_category = error.code.value
        attempt.error_detail = str(error)[:4000]
        attempt.finished_at = now
        await session.commit()
        return CollectionClaim(
            action="target_terminal",
            run_id=run.id,
            run_item_id=item.id,
            catalog_item_id=catalog_item.id,
            product_url=catalog_item.product_url,
            oe_norm=catalog_item.oe_norm,
            scrape_target_id=target.id,
            scrape_attempt_id=attempt.id,
            delivery_no=attempt.delivery_no,
            terminal_error=error,
        )

    if _target_delivery_is_busy(
        target,
        now,
        is_redelivery=is_redelivery,
    ):
        attempt = await _create_target_delivery_attempt(
            session,
            target=target,
            item=item,
            task_id=task_id,
            now=now,
        )
        attempt.status = "duplicate"
        attempt.error_category = ScraperErrorCode.TARGET_BUSY.value
        attempt.error_detail = "Another delivery owns the unexpired target lease"
        attempt.finished_at = now
        await session.commit()
        return CollectionClaim(
            action="target_busy",
            run_id=run.id,
            run_item_id=item.id,
            catalog_item_id=catalog_item.id,
            product_url=catalog_item.product_url,
            oe_norm=catalog_item.oe_norm,
            scrape_target_id=target.id,
            scrape_attempt_id=attempt.id,
            delivery_no=attempt.delivery_no,
        )

    superseded_owner = target.status == "collecting"
    if superseded_owner:
        lost_attempts = list(
            (
                await session.scalars(
                    select(ScrapeAttempt).where(
                        ScrapeAttempt.scrape_target_id == target.id,
                        ScrapeAttempt.status == "running",
                    )
                )
            ).all()
        )
        for lost_attempt in lost_attempts:
            lost_attempt.status = "worker_lost"
            lost_attempt.error_category = "worker_lost"
            lost_attempt.error_detail = (
                "Target execution was superseded by a broker redelivery, "
                "bounded retry, or expired lease"
            )
            lost_attempt.finished_at = now
            if lost_attempt.wall_time_ms == 0:
                lost_attempt.wall_time_ms = max(
                    0,
                    round(
                        (now - _aware_datetime(lost_attempt.started_at)).total_seconds()
                        * 1000
                    ),
                )

    deadline_expired = (
        target.deadline_at is not None and _aware_datetime(target.deadline_at) <= now
    )
    if target.network_attempts >= target.max_task_executions or deadline_expired:
        attempt = await _create_target_delivery_attempt(
            session,
            target=target,
            item=item,
            task_id=task_id,
            now=now,
        )
        error = ScraperBoundaryError(
            ScraperErrorCode.RETRY_EXHAUSTED,
            "Comparison-job retry budget or item deadline is exhausted",
            retryable=False,
        )
        target.status = "terminal_failure"
        _set_terminal_target_contract(
            target,
            reason=error.code.value,
            raw_available=target.raw_size_bytes > 0,
        )
        target.error_category = error.code.value
        target.error_detail = str(error)
        target.owner_task_id = None
        target.lease_expires_at = None
        target.finished_at = now
        attempt.status = "terminal_failure"
        attempt.error_category = error.code.value
        attempt.error_detail = str(error)
        attempt.finished_at = now
        await session.commit()
        return CollectionClaim(
            action="target_terminal",
            run_id=run.id,
            run_item_id=item.id,
            catalog_item_id=catalog_item.id,
            product_url=catalog_item.product_url,
            oe_norm=catalog_item.oe_norm,
            scrape_target_id=target.id,
            scrape_attempt_id=attempt.id,
            delivery_no=attempt.delivery_no,
            terminal_error=error,
        )

    try:
        scrape_input = ScrapeInput.build(
            target.original_url,
            target.query,
            adapter_version=target.adapter_version,
        )
    except ScraperBoundaryError as exc:
        attempt = await _create_target_delivery_attempt(
            session,
            target=target,
            item=item,
            task_id=task_id,
            now=now,
        )
        target.status = "terminal_failure"
        _set_terminal_target_contract(
            target,
            reason=exc.code.value,
            raw_available=target.raw_size_bytes > 0,
        )
        target.error_category = exc.code.value
        target.error_detail = str(exc)[:4000]
        target.finished_at = now
        target.owner_task_id = None
        target.lease_expires_at = None
        attempt.status = "terminal_failure"
        attempt.error_category = exc.code.value
        attempt.error_detail = str(exc)[:4000]
        attempt.finished_at = now
        await session.commit()
        return CollectionClaim(
            action="target_terminal",
            run_id=run.id,
            run_item_id=item.id,
            catalog_item_id=catalog_item.id,
            product_url=catalog_item.product_url,
            oe_norm=catalog_item.oe_norm,
            scrape_target_id=target.id,
            scrape_attempt_id=attempt.id,
            delivery_no=attempt.delivery_no,
            terminal_error=exc,
        )

    attempt = await _create_target_delivery_attempt(
        session,
        target=target,
        item=item,
        task_id=task_id,
        now=now,
        advance_fence=True,
    )
    settings = get_settings()
    target.status = "collecting"
    target.execution_status = "RUNNING"
    target.acquisition_status = "NOT_STARTED"
    target.parse_status = "NOT_STARTED"
    target.evidence_status = "NONE"
    target.downstream_eligibility = "UNKNOWN"
    target.operator_action = "NO_RECOMMENDATION"
    target.reason_codes = []
    target.owner_task_id = task_id
    target.lease_expires_at = now + timedelta(
        seconds=max(1, settings.pricing_collection_lease_seconds)
    )
    target.network_attempts += 1
    execution_no = target.network_attempts
    target.first_started_at = target.first_started_at or now
    target.error_category = None
    target.error_detail = None
    attempt.network_attempted = True
    item.status = "collecting"
    item.task_id = task_id or item.task_id
    item.attempts += 1
    item.started_at = item.started_at or now
    item.error = None
    item.checkpoint = {
        "stage": "collecting",
        "scrape_target_id": str(target.id),
        "delivery_no": attempt.delivery_no,
        "execution_no": execution_no,
        "at": now.isoformat(),
    }
    await session.commit()
    return CollectionClaim(
        action="target_collect",
        run_id=run.id,
        run_item_id=item.id,
        catalog_item_id=catalog_item.id,
        product_url=catalog_item.product_url,
        oe_norm=catalog_item.oe_norm,
        scrape_target_id=target.id,
        scrape_attempt_id=attempt.id,
        delivery_no=attempt.delivery_no,
        fencing_token=attempt.fencing_token,
        execution_no=execution_no,
        task_id=task_id,
        scrape_input=scrape_input,
    )


async def _create_target_delivery_attempt(
    session,
    *,
    target: ScrapeTarget,
    item: PricingRunItem,
    task_id: str | None,
    now: datetime,
    advance_fence: bool = False,
) -> ScrapeAttempt:
    target.delivery_count += 1
    if advance_fence:
        target.fencing_token += 1
    attempt_fencing_token = max(1, target.fencing_token)
    attempt = ScrapeAttempt(
        scrape_target_id=target.id,
        pricing_run_item_id=item.id,
        task_id=task_id,
        delivery_no=target.delivery_count,
        fencing_token=attempt_fencing_token,
        network_attempted=False,
        status="running",
        started_at=now,
    )
    session.add(attempt)
    await session.flush()
    return attempt


async def _persist_target_success(
    claim: CollectionClaim,
    trace: ScrapeExecutionTrace,
    measurement: AttemptMeasurement,
    output: ScrapeOutput,
) -> bool:
    completed_requests = trace.drain_completed_requests()
    try:
        async with async_session_factory() as session:
            target = await session.scalar(
                select(ScrapeTarget)
                .where(ScrapeTarget.id == claim.scrape_target_id)
                .with_for_update()
            )
            attempt = await session.get(ScrapeAttempt, claim.scrape_attempt_id)
            if target is None or attempt is None:
                raise PricingItemNotFoundError("Scrape target attempt disappeared")
            if not _target_claim_is_current(target, attempt, claim):
                _mark_stale_target_attempt(
                    attempt,
                    measurement,
                    "Target success rejected by execution fence",
                )
                await session.commit()
                pricing_event(
                    "scrape_stale_execution_rejected",
                    item_kind="comparison_job",
                    pricing_run_id=str(claim.run_id),
                    scrape_target_id=str(claim.scrape_target_id),
                    delivery_no=claim.delivery_no,
                    execution_no=claim.execution_no,
                )
                return False
            await persist_http_traces(
                session,
                completed_requests,
                execution_no=claim.delivery_no,
                scrape_target_id=target.id,
            )
            raw_bytes = await retained_raw_evidence_bytes(
                session,
                scrape_target_id=target.id,
            )
            if raw_bytes <= 0:
                raise ScraperBoundaryError(
                    ScraperErrorCode.EVIDENCE_PERSISTENCE,
                    "Structured scraper output has no retained raw HTTP evidence",
                    retryable=False,
                )
            now = datetime.now(UTC)
            target.status = "succeeded"
            target.execution_status = "SUCCEEDED"
            target.acquisition_status = "SUCCEEDED"
            target.parse_status = "SUCCEEDED"
            target.evidence_status = "STRUCTURED_AVAILABLE"
            target.downstream_eligibility = "UNKNOWN"
            target.operator_action = "NO_RECOMMENDATION"
            target.reason_codes = []
            target.winning_attempt_id = attempt.id
            target.payload = output.payload
            target.content_sha256 = output.content_sha256
            target.raw_size_bytes = raw_bytes
            target.structured_size_bytes = output.structured_size_bytes
            target.metadata_size_bytes = output.metadata_size_bytes
            target.structured_completeness = Decimal(
                str(output.structured_completeness)
            )
            target.error_category = None
            target.error_detail = None
            target.owner_task_id = None
            target.lease_expires_at = None
            target.finished_at = now
            attempt.status = "succeeded"
            attempt.wall_time_ms = measurement.wall_time_ms
            attempt.cpu_time_ms = measurement.cpu_time_ms
            attempt.memory_peak_bytes = measurement.memory_peak_bytes
            attempt.raw_size_bytes = raw_bytes
            attempt.structured_size_bytes = output.structured_size_bytes
            attempt.metadata_size_bytes = output.metadata_size_bytes
            attempt.structured_completeness = Decimal(
                str(output.structured_completeness)
            )
            attempt.finished_at = now
            await session.commit()
            coverage = await _target_evidence_coverage(
                target.id,
                execution_no=claim.delivery_no,
            )
            pricing_event(
                "scrape_items_terminal",
                status="success",
                item_kind="comparison_job",
                pricing_run_id=str(claim.run_id),
                scrape_target_id=str(target.id),
                delivery_no=claim.delivery_no,
                evidence_coverage=str(coverage),
                structured_completeness=str(output.structured_completeness),
            )
            return True
    except Exception:
        trace.restore_completed_requests(completed_requests)
        raise


async def _persist_target_failure(
    claim: CollectionClaim,
    trace: ScrapeExecutionTrace,
    measurement: AttemptMeasurement,
    error: ScraperBoundaryError,
) -> bool:
    completed_requests = trace.drain_completed_requests()
    try:
        async with async_session_factory() as session:
            target = await session.scalar(
                select(ScrapeTarget)
                .where(ScrapeTarget.id == claim.scrape_target_id)
                .with_for_update()
            )
            attempt = await session.get(ScrapeAttempt, claim.scrape_attempt_id)
            item = await session.get(PricingRunItem, claim.run_item_id)
            if target is None or attempt is None or item is None:
                return False
            if not _target_claim_is_current(target, attempt, claim):
                _mark_stale_target_attempt(
                    attempt,
                    measurement,
                    "Target failure rejected by execution fence",
                )
                await session.commit()
                pricing_event(
                    "scrape_stale_execution_rejected",
                    item_kind="comparison_job",
                    pricing_run_id=str(claim.run_id),
                    scrape_target_id=str(claim.scrape_target_id),
                    delivery_no=claim.delivery_no,
                    execution_no=claim.execution_no,
                )
                return False
            await persist_http_traces(
                session,
                completed_requests,
                execution_no=claim.delivery_no,
                scrape_target_id=target.id,
            )
            raw_bytes = await retained_raw_evidence_bytes(
                session,
                scrape_target_id=target.id,
            )
            now = datetime.now(UTC)
            target.status = (
                "retryable_failure" if error.retryable else "terminal_failure"
            )
            raw_parse_failure = raw_bytes > 0 and error.code in {
                ScraperErrorCode.PARSE_CONTRACT,
                ScraperErrorCode.SERIALIZATION,
            }
            target.execution_status = (
                "RETRY_WAIT" if error.retryable else "TERMINAL_FAILED"
            )
            target.acquisition_status = (
                "BLOCKED"
                if error.code == ScraperErrorCode.SOURCE_ACCESS_BLOCKED
                else ("SUCCEEDED" if raw_parse_failure else "FAILED")
            )
            target.parse_status = "FAILED" if raw_parse_failure else "NOT_STARTED"
            target.evidence_status = "RAW_AVAILABLE" if raw_bytes > 0 else "NONE"
            target.downstream_eligibility = (
                "UNKNOWN" if error.retryable else "INELIGIBLE"
            )
            target.operator_action = (
                "REPLAY_REQUIRED" if raw_parse_failure else "NO_RECOMMENDATION"
            )
            target.reason_codes = [error.code.value]
            target.error_category = error.code.value
            target.error_detail = str(error)[:4000]
            target.raw_size_bytes = raw_bytes
            target.owner_task_id = None
            target.lease_expires_at = None
            target.finished_at = None if error.retryable else now
            attempt.status = (
                "retryable_failure" if error.retryable else "terminal_failure"
            )
            attempt.error_category = error.code.value
            attempt.error_detail = str(error)[:4000]
            attempt.wall_time_ms = measurement.wall_time_ms
            attempt.cpu_time_ms = measurement.cpu_time_ms
            attempt.memory_peak_bytes = measurement.memory_peak_bytes
            attempt.raw_size_bytes = raw_bytes
            attempt.finished_at = now
            item.error = f"{error.code.value}: {error}"[:4000]
            item.checkpoint = {
                "stage": ("retry_wait" if error.retryable else "terminal_failure"),
                "scrape_target_id": str(target.id),
                "delivery_no": claim.delivery_no,
                "error_category": error.code.value,
                "at": now.isoformat(),
            }
            await session.commit()
            pricing_event(
                (
                    "scrape_task_retry_wait"
                    if error.retryable
                    else "scrape_items_terminal"
                ),
                status="retry_wait" if error.retryable else "failed",
                item_kind="comparison_job",
                pricing_run_id=str(claim.run_id),
                scrape_target_id=str(target.id),
                delivery_no=claim.delivery_no,
                error_category=error.code.value,
            )
            return True
    except Exception:
        trace.restore_completed_requests(completed_requests)
        raise


def _target_claim_is_current(
    target: ScrapeTarget,
    attempt: ScrapeAttempt,
    claim: CollectionClaim,
) -> bool:
    explicit_fence_matches = claim.fencing_token == 0 or (
        getattr(target, "fencing_token", None) == claim.fencing_token
        and getattr(attempt, "fencing_token", None) == claim.fencing_token
    )
    return bool(
        claim.scrape_attempt_id is not None
        and attempt.id == claim.scrape_attempt_id
        and target.status == "collecting"
        and target.owner_task_id == claim.task_id
        and target.network_attempts == claim.execution_no
        and explicit_fence_matches
        and attempt.status == "running"
        and attempt.delivery_no == claim.delivery_no
        and attempt.task_id == claim.task_id
    )


def _target_lease_is_active(target: ScrapeTarget, now: datetime) -> bool:
    return bool(
        target.status == "collecting"
        and target.lease_expires_at is not None
        and _aware_datetime(target.lease_expires_at) > _aware_datetime(now)
    )


def _target_delivery_is_busy(
    target: ScrapeTarget,
    now: datetime,
    *,
    is_redelivery: bool,
) -> bool:
    return _target_lease_is_active(target, now) and not is_redelivery


def _mark_stale_target_attempt(
    attempt: ScrapeAttempt,
    measurement: AttemptMeasurement,
    detail: str,
) -> None:
    if attempt.status != "running":
        return
    attempt.status = "worker_lost"
    attempt.error_category = "stale_execution"
    attempt.error_detail = detail
    attempt.wall_time_ms = measurement.wall_time_ms
    attempt.cpu_time_ms = measurement.cpu_time_ms
    attempt.memory_peak_bytes = measurement.memory_peak_bytes
    attempt.finished_at = datetime.now(UTC)


def _set_terminal_target_contract(
    target: ScrapeTarget,
    *,
    reason: str,
    raw_available: bool,
    parse_failed: bool = False,
) -> None:
    """Keep legacy target state and the v2 multi-axis contract consistent."""

    target.execution_status = "TERMINAL_FAILED"
    target.acquisition_status = (
        "SUCCEEDED" if raw_available and parse_failed else "FAILED"
    )
    target.parse_status = "FAILED" if parse_failed else "NOT_STARTED"
    target.evidence_status = "RAW_AVAILABLE" if raw_available else "NONE"
    target.downstream_eligibility = "INELIGIBLE"
    target.operator_action = "REPLAY_REQUIRED" if parse_failed else "NO_RECOMMENDATION"
    target.reason_codes = [reason]


async def _refresh_target_attempt_measurement(
    claim: CollectionClaim,
    measurement: AttemptMeasurement,
) -> None:
    """Persist full worker occupancy after evidence fan-out or failure handling."""

    if claim.scrape_attempt_id is None:
        return
    async with async_session_factory() as session:
        attempt = await session.get(ScrapeAttempt, claim.scrape_attempt_id)
        if attempt is None:
            return
        attempt.wall_time_ms = measurement.wall_time_ms
        attempt.cpu_time_ms = measurement.cpu_time_ms
        attempt.memory_peak_bytes = max(
            attempt.memory_peak_bytes,
            measurement.memory_peak_bytes,
        )
        if attempt.status != "running":
            attempt.finished_at = datetime.now(UTC)
        await session.commit()


async def _materialize_target_evidence(scrape_target_id: UUID) -> None:
    """Fan one immutable target output into item-scoped Metis evidence."""

    async with async_session_factory() as session:
        target = await session.scalar(
            select(ScrapeTarget)
            .where(ScrapeTarget.id == scrape_target_id)
            .with_for_update()
        )
        if target is None or target.payload is None or target.status != "succeeded":
            raise PricingItemNotFoundError(
                f"Succeeded scrape target {scrape_target_id} is unavailable"
            )
        output = _verified_target_output(target)
        raw_manifest = await _verified_raw_evidence_manifest(session, target.id)
        raw_manifest_sha256 = canonical_sha256(raw_manifest)
        run = await session.get(PricingRun, target.pricing_run_id)
        if run is None:
            raise PricingItemNotFoundError("Pricing run disappeared")
        rows = list(
            (
                await session.execute(
                    select(PricingRunItem, CatalogItem)
                    .join(
                        CatalogItem,
                        CatalogItem.id == PricingRunItem.catalog_item_id,
                    )
                    .where(PricingRunItem.scrape_target_id == target.id)
                    .order_by(PricingRunItem.created_at, PricingRunItem.id)
                )
            ).all()
        )
        owned_sellers = set(
            (
                await session.scalars(
                    select(MarketplaceStore.external_id)
                    .join(
                        WorkspaceStore,
                        WorkspaceStore.store_id == MarketplaceStore.id,
                    )
                    .where(
                        WorkspaceStore.workspace_id == run.workspace_id,
                        WorkspaceStore.kind == StoreKind.owned,
                    )
                )
            ).all()
        )
        brand_tiers, brand_confidence = await _load_brand_rules(
            session,
            run.workspace_id,
        )
        offers = output.comparison_payload.get("offers")
        if not isinstance(offers, list):
            raise ScraperBoundaryError(
                ScraperErrorCode.SERIALIZATION,
                "Stored target offers are not a list",
                retryable=False,
            )
        observed_at = target.finished_at or datetime.now(UTC)
        materialized = 0
        for run_item, catalog_item in rows:
            if run_item.status in {
                "calculated",
                "manual_review",
                "failed",
                "cancelled",
            }:
                continue
            existing_capture = await session.scalar(
                select(RawMarketCapture).where(
                    RawMarketCapture.pricing_run_item_id == run_item.id,
                    RawMarketCapture.content_sha256 == target.content_sha256,
                )
            )
            if existing_capture is None:
                capture = RawMarketCapture(
                    pricing_run_item_id=run_item.id,
                    scrape_target_id=target.id,
                    source=target.source_type,
                    capture_kind="parser_output_ref",
                    payload={
                        "schema_version": "metis-scrape-target-ref-v2",
                        "scrape_target_id": str(target.id),
                        "canonical_output_sha256": target.content_sha256,
                        "raw_manifest_sha256": raw_manifest_sha256,
                        "raw_evidence": raw_manifest,
                        "adapter_version": target.adapter_version,
                        "parser_name": target.parser_name,
                        "parser_config_hash": target.parser_config_hash,
                        "output_schema_version": target.output_schema_version,
                        "source_policy_decision_id": target.source_policy_decision_id,
                        "source_policy_version": target.source_policy_version,
                        "source_lane": target.source_lane,
                    },
                    content_sha256=target.content_sha256 or output.content_sha256,
                    parser_version=target.adapter_version,
                    raw_size_bytes=target.raw_size_bytes,
                    structured_size_bytes=target.structured_size_bytes,
                    metadata_size_bytes=target.metadata_size_bytes,
                    structured_completeness=target.structured_completeness,
                    captured_at=observed_at,
                )
                session.add(capture)
                await session.flush()
                await _persist_payload_observations(
                    session,
                    run=run,
                    run_item=run_item,
                    catalog_item=catalog_item,
                    capture=capture,
                    offers=offers,
                    owned_sellers=owned_sellers,
                    brand_tiers=brand_tiers,
                    brand_confidence=brand_confidence,
                    observed_at=observed_at,
                    source_type=target.source_type,
                )
                materialized += 1
            run_item.status = "classified"
            run_item.error = None
            run_item.checkpoint = {
                "stage": "classified",
                "scrape_target_id": str(target.id),
                "content_sha256": target.content_sha256,
                "offers": len(offers),
                "at": datetime.now(UTC).isoformat(),
            }
        target.evidence_status = "INGESTED"
        target.downstream_eligibility = "UNKNOWN"
        target.operator_action = "NO_RECOMMENDATION"
        await session.commit()
        pricing_event(
            "scrape_target_materialized",
            pricing_run_id=str(run.id),
            scrape_target_id=str(target.id),
            dependent_items=len(rows),
            newly_materialized_items=materialized,
            offers=len(offers),
        )


async def _verified_raw_evidence_manifest(
    session,
    scrape_target_id: UUID,
) -> list[dict[str, Any]]:
    """Return a hash-verified, ordered HTTP evidence manifest for Metis lineage."""

    await load_replay_cache(session, scrape_target_id=scrape_target_id)
    rows = list(
        (
            await session.execute(
                select(ScrapeHttpRequest, ScrapeEvidenceBlob)
                .join(
                    ScrapeEvidenceBlob,
                    ScrapeEvidenceBlob.id == ScrapeHttpRequest.evidence_blob_id,
                )
                .where(
                    ScrapeHttpRequest.scrape_target_id == scrape_target_id,
                    ScrapeHttpRequest.outcome.in_(("success", "replayed")),
                )
                .order_by(
                    ScrapeHttpRequest.execution_no,
                    ScrapeHttpRequest.sequence_no,
                    ScrapeHttpRequest.id,
                )
            )
        ).all()
    )
    if not rows:
        raise ScraperBoundaryError(
            ScraperErrorCode.EVIDENCE_PERSISTENCE,
            "Metis evidence ingestion requires retained raw HTTP captures",
            retryable=False,
        )
    return [
        {
            "logical_request_id": str(request.id),
            "request_key": request.request_key,
            "request_kind": request.request_kind,
            "execution_no": request.execution_no,
            "sequence_no": request.sequence_no,
            "evidence_blob_id": str(blob.id),
            "raw_content_sha256": blob.content_sha256,
            "raw_size_bytes": blob.raw_size_bytes,
            "stored_size_bytes": blob.stored_size_bytes,
        }
        for request, blob in rows
    ]


async def _persist_payload_observations(
    session,
    *,
    run: PricingRun,
    run_item: PricingRunItem,
    catalog_item: CatalogItem,
    capture: RawMarketCapture,
    offers: list[Any],
    owned_sellers: set[str],
    brand_tiers: dict[str, ProductTier],
    brand_confidence: dict[str, Decimal],
    observed_at: datetime,
    source_type: str,
) -> None:
    for raw_offer in offers:
        if not isinstance(raw_offer, Mapping):
            continue
        try:
            price = Decimal(str(raw_offer.get("price"))).quantize(Decimal("0.01"))
            match_confidence = Decimal(str(raw_offer.get("match_score"))).quantize(
                Decimal("0.0001")
            )
        except Exception:
            continue
        if price <= 0 or not Decimal("0") <= match_confidence <= Decimal("1"):
            continue
        seller_id = str(raw_offer.get("seller_id") or "").strip()[:255]
        title = str(raw_offer.get("name") or "")
        brand = _optional_string(raw_offer.get("brand"))
        classification = classify_tier(
            brand=brand,
            title=title,
            description=None,
            brand_tiers=brand_tiers,
        )
        normalized_brand = normalize_brand(brand)
        if (
            normalized_brand in brand_confidence
            and "EXACT_BRAND_RULE" in classification.reasons
        ):
            classification = TierClassification(
                tier=classification.tier,
                confidence=brand_confidence[normalized_brand],
                is_used=classification.is_used,
                is_kemp=classification.is_kemp,
                exclusion_reason=classification.exclusion_reason,
                reasons=classification.reasons + ("WORKSPACE_BRAND_CONFIDENCE",),
                method_version=classification.method_version,
            )
        source_listing_id = _payload_source_listing_id(raw_offer, price)
        currency_raw = _optional_string(raw_offer.get("currency"))
        try:
            upstream_evidence = comparison_evidence_from_dict(
                raw_offer.get("comparison_evidence")
                if isinstance(raw_offer.get("comparison_evidence"), Mapping)
                else None
            )
        except ValueError:
            upstream_evidence = None
        comparison_evidence = bind_persisted_provenance(
            upstream_evidence,
            stable_seller_id=seller_id or None,
            source_type=source_type,
            source_record_id=source_listing_id,
            raw_evidence_sha256=capture.content_sha256,
            parser_contract_version=run.parser_version,
            currency_raw=currency_raw,
            currency_normalized=_currency_code(currency_raw),
            required_currency="UAH",
        )
        observation = MarketObservation(
            pricing_run_item_id=run_item.id,
            catalog_item_id=catalog_item.id,
            raw_capture_id=capture.id,
            source=source_type,
            source_listing_id=source_listing_id,
            seller_id=seller_id,
            seller_name=str(raw_offer.get("seller_name") or "Unknown seller")[:255],
            url=str(raw_offer.get("url") or ""),
            title=title,
            description=None,
            brand_raw=brand,
            matched_oe_norm=catalog_item.oe_norm,
            price=price,
            currency=_currency_code(currency_raw),
            currency_raw=currency_raw,
            currency_inferred=False,
            is_available=_availability(
                _optional_bool(raw_offer.get("is_available")),
                _optional_string(raw_offer.get("presence")),
            ),
            match_confidence=match_confidence,
            source_confidence=Decimal("1"),
            parser_version=run.parser_version,
            evidence_contract_version="comparison-evidence-v1",
            comparability_policy_id=comparison_evidence.policy_id,
            comparability_policy_hash=comparison_evidence.policy_hash,
            comparison_evidence=comparison_evidence_to_dict(comparison_evidence),
            seller_identity_verified=(comparison_evidence.seller_identity.verified),
            source_provenance_verified=comparison_evidence.provenance.verified,
            automatic_eligible=(
                comparison_evidence.hard_gate_result == HardGateResult.PASS
            ),
            observed_at=observed_at,
        )
        session.add(observation)
        await session.flush()
        session.add(
            ObservationTierClassification(
                market_observation_id=observation.id,
                tier=classification.tier.value,
                tier_confidence=classification.confidence,
                is_used=classification.is_used,
                is_kemp=classification.is_kemp,
                is_owned=seller_id in owned_sellers,
                is_dumping=False,
                exclusion_reason=classification.exclusion_reason,
                reason_codes=list(classification.reasons),
                method_version=classification.method_version,
            )
        )


async def _mark_target_group_classified(
    scrape_target_id: UUID,
    *,
    reason: str,
    error: Exception,
) -> None:
    async with async_session_factory() as session:
        target = await session.scalar(
            select(ScrapeTarget)
            .where(ScrapeTarget.id == scrape_target_id)
            .with_for_update()
        )
        if target is None:
            return
        now = datetime.now(UTC)
        if target.status != "succeeded":
            target.status = "terminal_failure"
            _set_terminal_target_contract(
                target,
                reason=reason[:50],
                raw_available=target.raw_size_bytes > 0,
                parse_failed=target.raw_size_bytes > 0,
            )
            target.error_category = reason[:50]
            target.error_detail = str(error)[:4000]
            target.owner_task_id = None
            target.lease_expires_at = None
            target.finished_at = target.finished_at or now
        items = list(
            (
                await session.scalars(
                    select(PricingRunItem).where(
                        PricingRunItem.scrape_target_id == target.id,
                        PricingRunItem.status.in_(
                            ("queued", "collecting", "collected", "classified")
                        ),
                    )
                )
            ).all()
        )
        for item in items:
            item.status = "classified"
            item.error = f"{reason}: {error}"[:4000]
            item.checkpoint = {
                "stage": "classified_without_evidence",
                "scrape_target_id": str(target.id),
                "reason": reason,
                "at": now.isoformat(),
            }
        await session.commit()


async def _target_evidence_coverage(
    scrape_target_id: UUID,
    *,
    execution_no: int | None = None,
) -> Decimal:
    async with async_session_factory() as session:
        return await evidence_coverage_ratio(
            session,
            scrape_target_id=scrape_target_id,
            execution_no=execution_no,
        )


async def _has_capture(run_item_id: UUID) -> bool:
    async with async_session_factory() as session:
        return (
            await session.scalar(
                select(func.count(RawMarketCapture.id)).where(
                    RawMarketCapture.pricing_run_item_id == run_item_id
                )
            )
            or 0
        ) > 0


async def _mark_classified(run_item_id: UUID, *, reason: str) -> None:
    async with async_session_factory() as session:
        item = await session.get(PricingRunItem, run_item_id)
        if item is None:
            raise PricingItemNotFoundError(str(run_item_id))
        if item.status in {"calculated", "manual_review", "failed", "cancelled"}:
            return
        item.status = "classified"
        item.checkpoint = {
            "stage": "classified",
            "reason": reason,
            "at": datetime.now(UTC).isoformat(),
        }
        await session.commit()


async def get_pricing_item_run_id(run_item_id: UUID) -> UUID | None:
    async with async_session_factory() as session:
        return await session.scalar(
            select(PricingRunItem.pricing_run_id).where(
                PricingRunItem.id == run_item_id
            )
        )


async def _run_id_for_statuses(
    run_item_id: UUID, statuses: tuple[str, ...]
) -> UUID | None:
    async with async_session_factory() as session:
        return await session.scalar(
            select(PricingRunItem.pricing_run_id).where(
                PricingRunItem.id == run_item_id,
                PricingRunItem.status.in_(statuses),
            )
        )


async def _persist_comparison(
    *,
    run_id: UUID,
    run_item_id: UUID,
    catalog_item_id: UUID,
    comparison: PriceComparison,
) -> None:
    payload = comparison.as_dict()
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    content_hash = hashlib.sha256(canonical.encode()).hexdigest()
    observed_at = datetime.now(UTC)
    async with async_session_factory() as session:
        existing = await session.scalar(
            select(RawMarketCapture).where(
                RawMarketCapture.pricing_run_item_id == run_item_id,
                RawMarketCapture.content_sha256 == content_hash,
            )
        )
        if existing is not None:
            return
        run = await session.get(PricingRun, run_id)
        item = await session.get(CatalogItem, catalog_item_id)
        run_item = await session.get(PricingRunItem, run_item_id)
        if run is None or item is None or run_item is None:
            raise PricingItemNotFoundError("Pricing run dependencies disappeared")
        capture = RawMarketCapture(
            pricing_run_item_id=run_item_id,
            source="prom",
            capture_kind="parser_output",
            payload=payload,
            content_sha256=content_hash,
            parser_version=run.parser_version,
            captured_at=observed_at,
        )
        session.add(capture)
        await session.flush()
        owned_sellers = set(
            (
                await session.scalars(
                    select(MarketplaceStore.external_id)
                    .join(
                        WorkspaceStore, WorkspaceStore.store_id == MarketplaceStore.id
                    )
                    .where(
                        WorkspaceStore.workspace_id == run.workspace_id,
                        WorkspaceStore.kind == StoreKind.owned,
                    )
                )
            ).all()
        )
        brand_tiers, brand_confidence = await _load_brand_rules(
            session, run.workspace_id
        )
        for offer in comparison.offers:
            product = offer.product
            if offer.price <= 0:
                continue
            source_listing_id = _source_listing_id(product.id, product.url, offer.price)
            seller_id = (
                str(product.seller_id).strip()[:255]
                if product.seller_id is not None
                else ""
            )
            classification = classify_tier(
                brand=product.brand,
                title=product.name or "",
                description=None,
                brand_tiers=brand_tiers,
            )
            normalized_brand = normalize_brand(product.brand)
            if (
                normalized_brand in brand_confidence
                and "EXACT_BRAND_RULE" in classification.reasons
            ):
                classification = TierClassification(
                    tier=classification.tier,
                    confidence=brand_confidence[normalized_brand],
                    is_used=classification.is_used,
                    is_kemp=classification.is_kemp,
                    exclusion_reason=classification.exclusion_reason,
                    reasons=classification.reasons + ("WORKSPACE_BRAND_CONFIDENCE",),
                    method_version=classification.method_version,
                )
            comparison_evidence = bind_persisted_provenance(
                offer.comparison_evidence,
                stable_seller_id=seller_id or None,
                source_type="prom",
                source_record_id=source_listing_id,
                raw_evidence_sha256=capture.content_sha256,
                parser_contract_version=run.parser_version,
                currency_raw=product.currency,
                currency_normalized=_currency_code(product.currency),
                required_currency="UAH",
            )
            observation = MarketObservation(
                pricing_run_item_id=run_item_id,
                catalog_item_id=catalog_item_id,
                raw_capture_id=capture.id,
                source="prom",
                source_listing_id=source_listing_id,
                seller_id=seller_id,
                seller_name=(product.seller_name or "Unknown seller")[:255],
                url=product.url or "",
                title=product.name or "",
                description=None,
                brand_raw=product.brand,
                matched_oe_norm=item.oe_norm,
                price=Decimal(str(offer.price)).quantize(Decimal("0.01")),
                currency=_currency_code(product.currency),
                currency_raw=product.currency,
                currency_inferred=False,
                is_available=_availability(product.is_available, product.presence),
                match_confidence=Decimal(str(offer.match.score)),
                source_confidence=Decimal("1"),
                parser_version=run.parser_version,
                evidence_contract_version="comparison-evidence-v1",
                comparability_policy_id=comparison_evidence.policy_id,
                comparability_policy_hash=comparison_evidence.policy_hash,
                comparison_evidence=comparison_evidence_to_dict(comparison_evidence),
                seller_identity_verified=(comparison_evidence.seller_identity.verified),
                source_provenance_verified=comparison_evidence.provenance.verified,
                automatic_eligible=(
                    comparison_evidence.hard_gate_result == HardGateResult.PASS
                ),
                observed_at=observed_at,
            )
            session.add(observation)
            await session.flush()
            is_owned = seller_id in owned_sellers
            session.add(
                ObservationTierClassification(
                    market_observation_id=observation.id,
                    tier=classification.tier.value,
                    tier_confidence=classification.confidence,
                    is_used=classification.is_used,
                    is_kemp=classification.is_kemp,
                    is_owned=is_owned,
                    # Dumping is determined against independent reference/normalized
                    # market cohorts later.  The customer's current price must not
                    # label an otherwise valid KEMP observation as dumping.
                    is_dumping=False,
                    exclusion_reason=classification.exclusion_reason,
                    reason_codes=list(classification.reasons),
                    method_version=classification.method_version,
                )
            )
        run_item.status = "classified"
        run_item.checkpoint = {
            "stage": "classified",
            "capture_id": str(capture.id),
            "offers": len(comparison.offers),
            "at": observed_at.isoformat(),
        }
        await session.commit()


async def _load_brand_rules(
    session, workspace_id: UUID
) -> tuple[dict[str, ProductTier], dict[str, Decimal]]:
    tiers = dict(DEFAULT_BRAND_TIERS)
    confidence: dict[str, Decimal] = {}
    records = list(
        (
            await session.scalars(
                select(BrandTierRule)
                .where(
                    BrandTierRule.is_active.is_(True),
                    or_(
                        BrandTierRule.workspace_id.is_(None),
                        BrandTierRule.workspace_id == workspace_id,
                    ),
                )
                .order_by(
                    BrandTierRule.workspace_id.asc().nullsfirst(),
                    BrandTierRule.updated_at,
                )
            )
        ).all()
    )
    for record in records:
        tiers[record.brand_normalized] = ProductTier(record.tier)
        confidence[record.brand_normalized] = record.confidence
    return tiers, confidence


async def claim_collection_finalization(run_id: UUID, *, task_id: str | None) -> bool:
    """Claim the single run-level calibration barrier once collection is done."""
    async with async_session_factory() as session:
        run = await session.scalar(
            select(PricingRun).where(PricingRun.id == run_id).with_for_update()
        )
        if run is None:
            raise PricingItemNotFoundError(str(run_id))
        if run.status in {"completed", "partial", "failed", "cancelled", "calculating"}:
            return False
        if run.status == "calibrating":
            return run.finalizer_task_id == task_id
        active = int(
            await session.scalar(
                select(func.count(PricingRunItem.id)).where(
                    PricingRunItem.pricing_run_id == run_id,
                    PricingRunItem.status.in_(("queued", "collecting", "collected")),
                )
            )
            or 0
        )
        if active:
            return False
        run.status = "calibrating"
        run.finalizer_task_id = task_id
        run.calibration_started_at = datetime.now(UTC)
        run.error = None
        await session.commit()
        return True


async def fail_collection_finalization(
    run_id: UUID, *, task_id: str | None, error: Exception
) -> None:
    """Fail undispatched items after the barrier exhausts its retries."""
    async with async_session_factory() as session:
        run = await session.scalar(
            select(PricingRun).where(PricingRun.id == run_id).with_for_update()
        )
        if (
            run is None
            or run.status != "calibrating"
            or run.finalizer_task_id != task_id
        ):
            return
        now = datetime.now(UTC)
        items = list(
            (
                await session.scalars(
                    select(PricingRunItem).where(
                        PricingRunItem.pricing_run_id == run_id,
                        PricingRunItem.status == "classified",
                    )
                )
            ).all()
        )
        for item in items:
            item.status = "failed"
            item.error = f"{type(error).__name__}: {error}"[:4000]
            item.finished_at = now
            item.checkpoint = {"stage": "barrier_failed", "at": now.isoformat()}
        run.status = "failed"
        run.finished_at = now
        run.error = f"{type(error).__name__}: {error}"[:4000]
        await session.commit()
    await finalize_pricing_run(run_id)


async def calibrate_run_and_prepare_calculations(run_id: UUID) -> list[UUID]:
    """Freeze pairs and both coefficient models before releasing calculations."""
    async with async_session_factory() as session:
        run = await session.get(PricingRun, run_id)
        if run is None:
            raise PricingItemNotFoundError(str(run_id))
        workspace_id = run.workspace_id
        policy = policy_from_dict(run.policy_config)
        settings = get_settings()
        require_activated_run_policy(
            policy,
            robust_v3_enabled=settings.pricing_v3_robust_dispersion_enabled,
            activation_artifact_verified=activation_artifact_verified(
                settings.pricing_v3_activation_artifact,
                settings.pricing_v3_activation_sha256,
            ),
        )
        pairs = await _derive_calibration_pairs(session, run_id, policy)
        _, dataset_hash = await persist_run_calibration_pairs(
            session,
            workspace_id=workspace_id,
            pricing_run_id=run_id,
            pairs=pairs,
        )
        selected_records = []
        if pairs:
            simple_records = await calibrate_tier_coefficients(
                session,
                workspace_id=workspace_id,
                pairs=pairs,
                model=CoefficientModel.SIMPLE_MEDIAN,
                min_category_pairs=policy.min_category_pairs,
                min_global_pairs=policy.min_global_pairs,
                min_effective_pairs=policy.min_effective_pairs,
                max_interval_ratio=policy.max_allowed_interval_width,
                pricing_run_id=run_id,
                policy_version=policy.version,
                selected=policy.coefficient_model == CoefficientModel.SIMPLE_MEDIAN,
            )
            shrinkage_records = await calibrate_tier_coefficients(
                session,
                workspace_id=workspace_id,
                pairs=pairs,
                model=CoefficientModel.SHRINKAGE,
                shrinkage_k=policy.shrinkage_k,
                min_category_pairs=policy.min_category_pairs,
                min_global_pairs=policy.min_global_pairs,
                min_effective_pairs=policy.min_effective_pairs,
                max_interval_ratio=policy.max_allowed_interval_width,
                pricing_run_id=run_id,
                policy_version=policy.version,
                selected=policy.coefficient_model == CoefficientModel.SHRINKAGE,
            )
            selected_records = (
                simple_records
                if policy.coefficient_model == CoefficientModel.SIMPLE_MEDIAN
                else shrinkage_records
            )
            for record in simple_records + shrinkage_records:
                pricing_event(
                    "coefficient_calibrated"
                    if record.validated
                    else "coefficient_unvalidated",
                    pricing_run_id=str(run_id),
                    category=record.category,
                    tier=record.tier,
                    model=record.model,
                    sample_size=record.sample_size,
                    effective_sample_size=str(record.effective_sample_size),
                )
        run = await session.get(PricingRun, run_id)
        if run is None:
            raise PricingItemNotFoundError(str(run_id))
        run.calibration_dataset_hash = dataset_hash
        run.coefficient_model = policy.coefficient_model.value
        run.coefficient_version = (
            selected_records[0].coefficient_version if selected_records else None
        )
        run.calibration_completed_at = datetime.now(UTC)
        await session.commit()

    async with async_session_factory() as session:
        run = await session.scalar(
            select(PricingRun).where(PricingRun.id == run_id).with_for_update()
        )
        if run is None:
            raise PricingItemNotFoundError(str(run_id))
        if run.cancel_requested:
            items = list(
                (
                    await session.scalars(
                        select(PricingRunItem).where(
                            PricingRunItem.pricing_run_id == run_id,
                            PricingRunItem.status == "classified",
                        )
                    )
                ).all()
            )
            now = datetime.now(UTC)
            for item in items:
                item.status = "cancelled"
                item.finished_at = now
            run.status = "cancelled"
            run.finished_at = now
            await session.commit()
            return []
        item_ids = list(
            (
                await session.scalars(
                    select(PricingRunItem.id)
                    .where(
                        PricingRunItem.pricing_run_id == run_id,
                        PricingRunItem.status == "classified",
                    )
                    .order_by(PricingRunItem.created_at, PricingRunItem.id)
                )
            ).all()
        )
        event_ids: list[UUID] = []
        for item_id in item_ids:
            event = await enqueue_dispatch(
                session,
                event_key=f"pricing-run:{run.id}:calculate:{item_id}:v1",
                aggregate_type="pricing_run_item",
                aggregate_id=item_id,
                workspace_id=run.workspace_id,
                task_name="marko.worker.calculate_pricing_item",
                task_args=[str(item_id)],
                queue="pricing-calculation",
            )
            event_ids.append(event.id)
        await session.commit()
        return event_ids


async def mark_run_calculating(run_id: UUID, *, task_id: str | None) -> None:
    async with async_session_factory() as session:
        run = await session.scalar(
            select(PricingRun).where(PricingRun.id == run_id).with_for_update()
        )
        if run is None:
            raise PricingItemNotFoundError(str(run_id))
        if run.status == "calibrating" and run.finalizer_task_id == task_id:
            run.status = "calculating"
            await session.commit()


async def _derive_calibration_pairs(
    session, run_id: UUID, policy
) -> list[CalibrationPair]:
    rows = list(
        (
            await session.execute(
                select(
                    CatalogItem,
                    MarketObservation,
                    ObservationTierClassification,
                )
                .join(PricingRunItem, PricingRunItem.catalog_item_id == CatalogItem.id)
                .join(
                    MarketObservation,
                    MarketObservation.pricing_run_item_id == PricingRunItem.id,
                )
                .join(
                    ObservationTierClassification,
                    ObservationTierClassification.market_observation_id
                    == MarketObservation.id,
                )
                .where(PricingRunItem.pricing_run_id == run_id)
                .order_by(
                    MarketObservation.id,
                    ObservationTierClassification.classified_at.desc(),
                    ObservationTierClassification.id.desc(),
                )
            )
        ).all()
    )
    latest: dict[
        UUID, tuple[CatalogItem, MarketObservation, ObservationTierClassification]
    ] = {}
    for item, observation, classification in rows:
        latest.setdefault(observation.id, (item, observation, classification))
    now = datetime.now(UTC)
    grouped: dict[
        tuple[str, str],
        list[tuple[CatalogItem, MarketObservation, ObservationTierClassification]],
    ] = {}
    for item, observation, classification in latest.values():
        age_hours = Decimal(
            str(max(0.0, (now - observation.observed_at).total_seconds()) / 3600)
        )
        tier = ProductTier(classification.tier)
        if (
            observation.price <= 0
            or observation.currency.upper() != policy.currency
            or observation.is_available is not True
            or age_hours > policy.max_age_hours
            or observation.match_confidence < policy.match_confidence_min
            or classification.tier_confidence < policy.tier_confidence_min
            or observation.source_confidence < policy.source_confidence_min
            or classification.is_used
            or classification.is_owned
            or tier == ProductTier.UNKNOWN
            or classification.exclusion_reason == "TIER_CONFLICT"
        ):
            continue
        grouped.setdefault((item.category, item.oe_norm.strip().upper()), []).append(
            (item, observation, classification)
        )

    result: list[CalibrationPair] = []
    for (category, oe_norm), observations in grouped.items():
        representatives: dict[
            tuple[ProductTier, str],
            tuple[CatalogItem, MarketObservation, ObservationTierClassification],
        ] = {}
        for row in observations:
            _, observation, classification = row
            tier = ProductTier(classification.tier)
            seller_key = (
                observation.seller_id.strip() or observation.seller_name.casefold()
            )
            key = (tier, seller_key)
            current = representatives.get(key)
            if current is None or (observation.price, observation.id) < (
                current[1].price,
                current[1].id,
            ):
                representatives[key] = row
        deduplicated = list(representatives.values())
        reference_rows = [
            row
            for row in deduplicated
            if ProductTier(row[2].tier) in {ProductTier.KEMP, ProductTier.BUDGET}
            and not row[2].is_dumping
        ]
        direct_kemp_rows = [
            row
            for row in reference_rows
            if ProductTier(row[2].tier) == ProductTier.KEMP
        ]
        if len(direct_kemp_rows) >= 3:
            direct_kemp_center = decimal_median(
                row[1].price for row in direct_kemp_rows
            )
            dumping_ids = {
                row[1].id
                for row in direct_kemp_rows
                if row[1].price < direct_kemp_center * policy.kemp_dumping_ratio
            }
            reference_rows = [
                row for row in reference_rows if row[1].id not in dumping_ids
            ]
        if not reference_rows:
            continue
        reference_price = decimal_median(row[1].price for row in reference_rows)
        reference_quality = decimal_median(
            _calibration_quality(row[1], row[2], now, policy) for row in reference_rows
        )
        tier_groups: dict[
            ProductTier,
            list[tuple[CatalogItem, MarketObservation, ObservationTierClassification]],
        ] = {}
        for row in deduplicated:
            tier = ProductTier(row[2].tier)
            if tier in {
                ProductTier.KEMP,
                ProductTier.BUDGET,
                ProductTier.USED,
                ProductTier.UNKNOWN,
            }:
                continue
            tier_groups.setdefault(tier, []).append(row)
        for tier, tier_rows in sorted(
            tier_groups.items(), key=lambda value: value[0].value
        ):
            tier_price = decimal_median(row[1].price for row in tier_rows)
            tier_quality = decimal_median(
                _calibration_quality(row[1], row[2], now, policy) for row in tier_rows
            )
            result.append(
                CalibrationPair(
                    oe_norm=oe_norm,
                    category=category,
                    tier=tier,
                    tier_price=tier_price,
                    reference_price=reference_price,
                    quality_weight=min(reference_quality, tier_quality),
                    tier_observation_ids=tuple(
                        sorted(str(row[1].id) for row in tier_rows)
                    ),
                    reference_observation_ids=tuple(
                        sorted(str(row[1].id) for row in reference_rows)
                    ),
                )
            )
    return result


def _calibration_quality(
    observation: MarketObservation,
    classification: ObservationTierClassification,
    now: datetime,
    policy,
) -> Decimal:
    age_hours = Decimal(
        str(max(0.0, (now - observation.observed_at).total_seconds()) / 3600)
    )
    freshness = Decimal(
        str(math.pow(2, -float(age_hours / policy.freshness_half_life_hours)))
    )
    return min(
        Decimal("1"),
        observation.match_confidence
        * classification.tier_confidence
        * observation.source_confidence
        * freshness,
    )


async def calculate_pricing_item(
    run_item_id: UUID, *, task_id: str | None = None
) -> UUID | None:
    run_id = await _claim_calculation(run_item_id, task_id=task_id)
    if run_id is None:
        terminal_run_id = await _run_id_for_statuses(
            run_item_id, ("calculated", "manual_review", "failed", "cancelled")
        )
        if terminal_run_id is not None:
            await finalize_pricing_run(terminal_run_id)
        return terminal_run_id
    await _calculate_and_persist(run_item_id)
    return run_id


async def _claim_calculation(run_item_id: UUID, *, task_id: str | None) -> UUID | None:
    async with async_session_factory() as session:
        item = await session.scalar(
            select(PricingRunItem)
            .where(PricingRunItem.id == run_item_id)
            .with_for_update(skip_locked=True)
        )
        if item is None:
            raise PricingItemNotFoundError(str(run_item_id))
        if item.status in {"calculated", "manual_review", "failed", "cancelled"}:
            return None
        if item.status == "calculating":
            return item.pricing_run_id if item.task_id == task_id else None
        if item.status != "classified":
            return None
        run = await session.get(PricingRun, item.pricing_run_id)
        if (
            run is None
            or run.status != "calculating"
            or run.calibration_completed_at is None
            or run.calibration_dataset_hash is None
        ):
            return None
        item.status = "calculating"
        item.task_id = task_id
        item.checkpoint = {
            "stage": "calculating",
            "at": datetime.now(UTC).isoformat(),
        }
        await session.commit()
        return item.pricing_run_id


async def _calculate_and_persist(run_item_id: UUID) -> None:
    async with async_session_factory() as session:
        existing = await session.scalar(
            select(PricingRecommendation).where(
                PricingRecommendation.pricing_run_item_id == run_item_id
            )
        )
        run_item = await session.get(PricingRunItem, run_item_id)
        if run_item is None:
            raise PricingItemNotFoundError(str(run_item_id))
        if existing is not None:
            if run_item.status not in {"calculated", "manual_review"}:
                run_item.status = (
                    "manual_review"
                    if existing.action
                    in {
                        RecommendationAction.MANUAL_REVIEW.value,
                        RecommendationAction.INSUFFICIENT_DATA.value,
                    }
                    else "calculated"
                )
                run_item.finished_at = datetime.now(UTC)
                await session.commit()
            await finalize_pricing_run(run_item.pricing_run_id)
            return
        run = await session.get(PricingRun, run_item.pricing_run_id)
        catalog_item = await session.get(CatalogItem, run_item.catalog_item_id)
        if run is None or catalog_item is None:
            raise PricingItemNotFoundError(
                "Pricing calculation dependencies are missing"
            )
        if run.cancel_requested:
            run_item.status = "cancelled"
            run_item.finished_at = datetime.now(UTC)
            await session.commit()
            await finalize_pricing_run(run.id)
            return

        rows = list(
            (
                await session.execute(
                    select(MarketObservation, ObservationTierClassification)
                    .join(
                        ObservationTierClassification,
                        ObservationTierClassification.market_observation_id
                        == MarketObservation.id,
                    )
                    .where(MarketObservation.pricing_run_item_id == run_item_id)
                    .order_by(
                        MarketObservation.id,
                        ObservationTierClassification.classified_at.desc(),
                        ObservationTierClassification.id.desc(),
                    )
                )
            ).all()
        )
        latest: dict[UUID, tuple[MarketObservation, ObservationTierClassification]] = {}
        for observation, classification in rows:
            latest.setdefault(observation.id, (observation, classification))
        now = datetime.now(UTC)
        offers = [
            _domain_offer(observation, classification, now)
            for observation, classification in latest.values()
        ]
        override = await get_latest_override(session, catalog_item.id)
        context = build_pricing_context(catalog_item, override)
        policy = policy_from_dict(run.policy_config)
        settings = get_settings()
        require_activated_run_policy(
            policy,
            robust_v3_enabled=settings.pricing_v3_robust_dispersion_enabled,
            activation_artifact_verified=activation_artifact_verified(
                settings.pricing_v3_activation_artifact,
                settings.pricing_v3_activation_sha256,
            ),
        )
        coefficients = await load_target_tier_coefficients(
            session,
            run=run,
            category=catalog_item.category,
            oe_norm=catalog_item.oe_norm,
            policy=policy,
        )
        result = recommend_price(context, offers, coefficients, policy=policy)
        comparability_activation_verified = bool(
            settings.pricing_comparability_v1_automatic_enabled
            and activation_artifact_verified(
                settings.pricing_comparability_activation_artifact,
                settings.pricing_comparability_activation_sha256,
            )
        )
        if result.automatic_eligible and not comparability_activation_verified:
            result = replace(
                result,
                action=RecommendationAction.MANUAL_REVIEW,
                recommended_price=None,
                action_gates_passed=False,
                automatic_eligible=False,
                confidence_grade="MANUAL",
                reasons=tuple(
                    dict.fromkeys(
                        result.reasons
                        + (
                            "COMPARABILITY_AUTOMATIC_ACTIVATION_BLOCKED",
                            "MANUAL_REVIEW_REQUIRED",
                        )
                    )
                ),
            )
        applied_versions = sorted(
            {
                coefficient.coefficient_version or coefficient.method_version
                for coefficient in coefficients.values()
            }
        )
        applied_coefficient_version = applied_versions[0] if applied_versions else None
        context_snapshot = {
            "sku": context.sku,
            "category": context.category,
            "currency": context.currency,
            "current_price": str(context.current_price),
            "stock_status": context.stock_status.value,
            "cost": str(context.cost) if context.cost is not None else None,
            "stock_qty": str(context.stock_qty)
            if context.stock_qty is not None
            else None,
            "stock_age_days": str(context.stock_age_days)
            if context.stock_age_days is not None
            else None,
            "expected_units_sold": str(context.expected_units_sold)
            if context.expected_units_sold is not None
            else None,
            "units_sold_30d": str(context.units_sold_30d)
            if context.units_sold_30d is not None
            else None,
            "units_sold_60d": str(context.units_sold_60d)
            if context.units_sold_60d is not None
            else None,
            "units_sold_90d": str(context.units_sold_90d)
            if context.units_sold_90d is not None
            else None,
            "days_since_last_sale": str(context.days_since_last_sale)
            if context.days_since_last_sale is not None
            else None,
            "historical_monthly_units": str(context.historical_monthly_units)
            if context.historical_monthly_units is not None
            else None,
            "views_30d": str(context.views_30d)
            if context.views_30d is not None
            else None,
            "conversion_rate_proxy": str(context.conversion_rate_proxy)
            if context.conversion_rate_proxy is not None
            else None,
            "liquidity_target": str(context.liquidity_target),
            "urgency": str(context.urgency),
            "manual_priority": str(context.manual_priority),
            "allow_below_cost": context.allow_below_cost,
            "below_cost_floor": str(context.below_cost_floor)
            if context.below_cost_floor is not None
            else None,
            "below_cost_authorization_id": context.below_cost_authorization_id,
            "below_cost_authorized_by": context.below_cost_authorized_by,
            "below_cost_authorized_at": (
                context.below_cost_authorized_at.isoformat()
                if context.below_cost_authorized_at
                else None
            ),
            "below_cost_reason": context.below_cost_reason,
            "below_cost_warning_confirmed": context.below_cost_warning_confirmed,
            "comparability_contract_version": "comparison-evidence-v1",
        }
        robust_diagnostic = cluster_diagnostic_to_dict(result.cluster_diagnostic)
        calculation_trace = {
            "replay_contract_version": "recommendation-replay-v3",
            "calculated_at": now.isoformat(),
            "catalog_snapshot_id": str(run.import_batch_id),
            "pricing_run_id": str(run.id),
            "fair_price_estimator": "median",
            "outlier_filter": result.outlier_method,
            "robust_dispersion": robust_dispersion_trace(
                selected_method=result.dispersion_method,
                pre_clean=result.pre_clean_dispersion_profile,
                post_clean=result.dispersion_profile,
                profile_version=policy.robust_dispersion_profile_version,
                correction_profile_version=(
                    policy.robust_scale_correction_profile_version
                ),
                finite_sample_correction=(policy.finite_sample_scale_correction),
            ),
            "robust_diagnostic": robust_diagnostic,
            "robust_policy_fingerprint": dict(result.robust_policy_fingerprint),
            "comparability": {
                "contract_version": "comparison-evidence-v1",
                "policy_id": result.comparability_policy_id,
                "policy_hash": result.comparability_policy_hash,
                "automatic_eligible": result.automatic_eligible,
                "verified_seller_count": result.verified_seller_count,
                "hard_gates": dict(result.hard_gate_results),
                "failed_hard_gates": list(result.failed_hard_gates),
                "unknown_hard_fields": list(result.unknown_hard_fields),
            },
            "confidence_aggregation": policy.confidence_aggregation.value,
            "factor_scores": {
                key: str(value) for key, value in result.factor_scores.items()
            },
            "hard_factor_floors": {
                key: str(value) for key, value in policy.factor_floors.items()
            },
            "action_gates_passed": result.action_gates_passed,
            "sensitivity": str(result.sensitivity)
            if result.sensitivity is not None
            else None,
            "winsorized_fair_price": str(result.winsorized_fair_price)
            if result.winsorized_fair_price is not None
            else None,
            "market_counts": {
                "raw": result.raw_competitor_count,
                "unique_sellers": result.unique_seller_count,
                "clean": result.clean_competitor_count,
                "effective": str(result.effective_competitor_count),
                "outliers": result.outlier_count,
            },
            "normalized_offers": [
                {
                    "observation_id": offer.observation_id,
                    "seller_id": offer.seller_id,
                    "seller_name": offer.seller_name,
                    "category": catalog_item.category,
                    "tier": offer.tier.value,
                    "raw_price": str(offer.raw_price),
                    "coefficient": str(offer.multiplier),
                    "multiplier": str(offer.multiplier),
                    "coefficient_model": (
                        offer.coefficient_model.value
                        if offer.coefficient_model is not None
                        else "reference"
                    ),
                    "coefficient_version": offer.coefficient_version,
                    "coefficient_sample_size": offer.coefficient_sample_size,
                    "coefficient_effective_sample_size": str(
                        offer.coefficient_effective_sample_size
                    ),
                    "coefficient_confidence": str(offer.coefficient_confidence),
                    "coefficient_dataset_hash": offer.coefficient_dataset_hash,
                    "normalized_price": str(offer.normalized_price),
                    "match_confidence": str(offer.match_confidence),
                    "tier_confidence": str(offer.tier_confidence),
                    "source_confidence": str(offer.source_confidence),
                    "age_hours": str(offer.age_hours),
                    "source": offer.source,
                    "listing_url": offer.listing_url,
                }
                for offer in result.evidence
            ],
            "tier_coefficients": [
                {
                    "category": coefficient.category,
                    "tier": coefficient.tier.value,
                    "multiplier": str(coefficient.multiplier),
                    "model": coefficient.model.value,
                    "method_version": coefficient.method_version,
                    "coefficient_version": coefficient.coefficient_version,
                    "dataset_hash": coefficient.dataset_hash,
                    "sample_size": coefficient.sample_size,
                    "effective_sample_size": str(coefficient.effective_sample_size),
                    "interval_low": str(coefficient.interval_low)
                    if coefficient.interval_low is not None
                    else None,
                    "interval_high": str(coefficient.interval_high)
                    if coefficient.interval_high is not None
                    else None,
                    "confidence": str(coefficient.confidence),
                    "validated": coefficient.validated,
                    "validation_reasons": list(coefficient.validation_reasons),
                    "excluded_oe_norm": coefficient.excluded_oe_norm,
                }
                for coefficient in sorted(
                    coefficients.values(), key=lambda value: value.tier.value
                )
            ],
            "excluded_observations": [
                {
                    "observation_id": excluded.observation_id,
                    "seller_id": excluded.seller_id,
                    "raw_price": str(excluded.raw_price)
                    if excluded.raw_price is not None
                    else None,
                    "tier": excluded.tier.value if excluded.tier else None,
                    "reason": excluded.reason,
                    "stage": excluded.stage,
                }
                for excluded in result.excluded
            ],
            "priority": {
                "raw_score": str(result.priority_score),
                "score_type": result.priority_score_type.value,
                "review_priority": str(result.review_priority),
                "inputs": dict(result.priority_inputs),
            },
            "policy_version": policy.version,
            "pricing_policy_hash": canonical_sha256(run.policy_config),
            "build_identity": settings.build_identity,
            "parser_version": run.parser_version,
            "classifier_version": run.classifier_version,
            "calibration_dataset_hash": run.calibration_dataset_hash,
            "coefficient_version": applied_coefficient_version,
            "price_tick": str(policy.price_tick),
            "price_tick_version": policy.price_tick_version,
        }
        fingerprint_payload = build_decision_fingerprint_payload(
            context_snapshot=context_snapshot,
            result=result,
            observations=[value[0] for value in latest.values()],
            policy_config=run.policy_config,
            coefficients=coefficients.values(),
            parser_version=run.parser_version,
            classifier_version=run.classifier_version,
            calibration_dataset_hash=run.calibration_dataset_hash,
            coefficient_version=applied_coefficient_version,
            build_identity=settings.build_identity,
            price_tick=policy.price_tick,
            price_tick_version=policy.price_tick_version,
        )
        decision_fingerprint = canonical_sha256(fingerprint_payload)
        calculation_trace["decision_fingerprint_payload"] = fingerprint_payload
        calculation_trace["decision_fingerprint"] = decision_fingerprint
        recommendation = PricingRecommendation(
            pricing_run_id=run.id,
            pricing_run_item_id=run_item.id,
            catalog_item_id=catalog_item.id,
            catalog_snapshot_id=run.import_batch_id,
            context_snapshot=context_snapshot,
            calculation_trace=calculation_trace,
            action=result.action.value,
            current_price=result.current_price,
            fair_price=result.fair_price,
            recommended_price=result.recommended_price,
            lower_bound=result.lower_bound,
            upper_bound=result.upper_bound,
            confidence=result.confidence,
            confidence_grade=result.confidence_grade,
            weakest_factor=result.weakest_factor,
            factor_scores={
                key: str(value) for key, value in result.factor_scores.items()
            },
            competitor_count=result.competitor_count,
            raw_competitor_count=result.raw_competitor_count,
            unique_seller_count=result.unique_seller_count,
            clean_competitor_count=result.clean_competitor_count,
            effective_competitor_count=result.effective_competitor_count,
            dispersion=result.dispersion,
            outlier_method=result.outlier_method,
            outlier_count=result.outlier_count,
            sensitivity=result.sensitivity,
            action_gates_passed=result.action_gates_passed,
            automatic_eligible=result.automatic_eligible,
            verified_seller_count=result.verified_seller_count,
            comparability_policy_id=result.comparability_policy_id,
            comparability_policy_hash=result.comparability_policy_hash,
            decision_fingerprint=decision_fingerprint,
            hard_gate_trace={
                "hard_gates": dict(result.hard_gate_results),
                "failed_hard_gates": list(result.failed_hard_gates),
                "unknown_hard_fields": list(result.unknown_hard_fields),
            },
            robust_diagnostic=robust_diagnostic,
            cost_floor=result.cost_floor,
            cost_basis_inventory_value=result.cost_basis_inventory_value,
            priority_score=result.priority_score,
            priority_score_type=result.priority_score_type.value,
            review_priority=result.review_priority,
            reason_codes=list(result.reasons),
            evidence_observation_ids=[
                offer.observation_id for offer in result.evidence
            ],
            excluded_observations=[
                {
                    "observation_id": excluded.observation_id,
                    "reason": excluded.reason,
                    "stage": excluded.stage,
                }
                for excluded in result.excluded
            ],
            policy_version=result.policy_version,
            parser_version=run.parser_version,
            classifier_version=run.classifier_version,
            coefficient_version=applied_coefficient_version,
            calibration_dataset_hash=run.calibration_dataset_hash,
            currency=context.currency,
            price_tick=policy.price_tick,
            price_tick_version=policy.price_tick_version,
        )
        session.add(recommendation)
        run_item.status = (
            "manual_review"
            if result.action
            in {
                RecommendationAction.MANUAL_REVIEW,
                RecommendationAction.INSUFFICIENT_DATA,
            }
            else "calculated"
        )
        run_item.finished_at = now
        run_item.checkpoint = {
            "stage": "calculated",
            "action": result.action.value,
            "confidence": str(result.confidence),
            "at": now.isoformat(),
        }
        await session.commit()
        event_name = {
            RecommendationAction.RAISE: "recommendation_raise",
            RecommendationAction.LOWER: "recommendation_lower",
            RecommendationAction.HOLD: "recommendation_hold",
            RecommendationAction.MANUAL_REVIEW: "recommendation_manual_review",
            RecommendationAction.INSUFFICIENT_DATA: "recommendation_manual_review",
        }[result.action]
        pricing_event(
            event_name,
            pricing_run_id=str(run.id),
            pricing_run_item_id=str(run_item.id),
            action=result.action.value,
            confidence=str(result.confidence),
            competitor_count=result.competitor_count,
            priority_score_type=result.priority_score_type.value,
        )
        pricing_event(
            "matching_candidates_total",
            classification=(
                "automatic_eligible" if result.automatic_eligible else "abstained"
            ),
            reason=(result.reasons[0] if result.reasons else "NONE"),
            value=result.raw_competitor_count,
        )
        pricing_event(
            "matching_automatic_eligible_total",
            policy_version=result.policy_version,
            value=int(result.automatic_eligible),
        )
        for field in result.unknown_hard_fields:
            pricing_event(
                "matching_missing_hard_field_total",
                field=field,
                category="auto_parts",
                value=1,
            )
        if result.action in {
            RecommendationAction.MANUAL_REVIEW,
            RecommendationAction.INSUFFICIENT_DATA,
        }:
            for reason in result.reasons:
                pricing_event(
                    "pricing_abstention_total",
                    reason=reason,
                    policy_version=result.policy_version,
                    value=1,
                )
        if result.cluster_diagnostic and result.cluster_diagnostic.flagged:
            pricing_event(
                "pricing_robust_cluster_flag_total",
                policy_version=result.policy_version,
                value=1,
            )
        if "ROBUST_BASELINE_ABSTENTION_NOT_RELAXABLE" in result.reasons:
            pricing_event(
                "pricing_unsafe_relaxation_blocked_total",
                baseline=policy.robust_baseline_policy_version,
                candidate=result.policy_version,
                value=1,
            )
    await finalize_pricing_run(run_item.pricing_run_id)


def _domain_offer(
    observation: MarketObservation,
    classification: ObservationTierClassification,
    now: datetime,
) -> CompetitorOffer:
    age_seconds = max(0.0, (now - observation.observed_at).total_seconds())
    return CompetitorOffer(
        observation_id=str(observation.id),
        seller_id=observation.seller_id,
        seller_name=observation.seller_name,
        price=observation.price,
        currency=observation.currency,
        currency_raw=observation.currency_raw,
        currency_inferred=observation.currency_inferred,
        currency_evidence=(
            f"market_observation:{observation.id}:currency_raw"
            if observation.currency_raw
            else None
        ),
        is_available=observation.is_available,
        age_hours=Decimal(str(age_seconds / 3600)),
        match_confidence=observation.match_confidence,
        tier=ProductTier(classification.tier),
        tier_confidence=classification.tier_confidence,
        source_confidence=observation.source_confidence,
        is_used=classification.is_used,
        is_kemp=classification.is_kemp,
        is_owned=classification.is_owned,
        is_dumping=classification.is_dumping,
        severe_conflict=classification.exclusion_reason == "TIER_CONFLICT",
        conflict_reason=classification.exclusion_reason,
        source=observation.source,
        listing_url=observation.url,
        comparison_evidence=comparison_evidence_from_dict(
            observation.comparison_evidence
        ),
    )


async def reset_pricing_item_for_retry(run_item_id: UUID, error: Exception) -> None:
    async with async_session_factory() as session:
        item = await session.get(PricingRunItem, run_item_id)
        if item is None or item.status in {
            "calculated",
            "manual_review",
            "failed",
            "cancelled",
        }:
            return
        item.status = "queued"
        item.error = f"{type(error).__name__}: {error}"[:4000]
        item.checkpoint = {
            "stage": "retry_queued",
            "attempts": item.attempts,
            "at": datetime.now(UTC).isoformat(),
        }
        await session.commit()
        pricing_event(
            "market_collection_retry",
            pricing_run_item_id=str(run_item_id),
            attempt=item.attempts,
            error_type=type(error).__name__,
        )


async def reset_pricing_calculation_for_retry(
    run_item_id: UUID, error: Exception
) -> None:
    async with async_session_factory() as session:
        item = await session.get(PricingRunItem, run_item_id)
        if item is None or item.status in {
            "calculated",
            "manual_review",
            "failed",
            "cancelled",
        }:
            return
        item.status = "classified"
        item.error = f"{type(error).__name__}: {error}"[:4000]
        item.checkpoint = {
            "stage": "calculation_retry_queued",
            "attempts": item.attempts,
            "at": datetime.now(UTC).isoformat(),
        }
        await session.commit()


async def fail_pricing_item(run_item_id: UUID, error: Exception) -> None:
    run_id: UUID | None = None
    async with async_session_factory() as session:
        item = await session.scalar(
            select(PricingRunItem)
            .where(PricingRunItem.id == run_item_id)
            .with_for_update()
        )
        if item is None or item.status in {"calculated", "manual_review", "cancelled"}:
            return
        run_id = item.pricing_run_id
        if item.scrape_target_id is not None and item.status in {
            "queued",
            "collecting",
            "collected",
        }:
            target = await session.scalar(
                select(ScrapeTarget)
                .where(ScrapeTarget.id == item.scrape_target_id)
                .with_for_update()
            )
            siblings = list(
                (
                    await session.scalars(
                        select(PricingRunItem).where(
                            PricingRunItem.scrape_target_id == item.scrape_target_id,
                            PricingRunItem.status.in_(
                                ("queued", "collecting", "collected")
                            ),
                        )
                    )
                ).all()
            )
            now = datetime.now(UTC)
            if target is not None and target.status != "succeeded":
                if target.status != "terminal_failure":
                    target.status = "terminal_failure"
                    _set_terminal_target_contract(
                        target,
                        reason=ScraperErrorCode.RETRY_EXHAUSTED.value,
                        raw_available=target.raw_size_bytes > 0,
                    )
                    target.error_category = ScraperErrorCode.RETRY_EXHAUSTED.value
                    target.error_detail = (f"{type(error).__name__}: {error}")[:4000]
                target.owner_task_id = None
                target.lease_expires_at = None
                target.finished_at = target.finished_at or now
                terminal_reason = (
                    target.error_category or ScraperErrorCode.RETRY_EXHAUSTED.value
                )
                terminal_detail = (
                    target.error_detail or f"{type(error).__name__}: {error}"
                )[:4000]
                for sibling in siblings:
                    sibling.status = "classified"
                    sibling.error = terminal_detail
                    sibling.checkpoint = {
                        "stage": "classified_without_evidence",
                        "reason": terminal_reason,
                        "at": now.isoformat(),
                    }
            else:
                for sibling in siblings:
                    sibling.status = "failed"
                    sibling.error = (
                        f"evidence_persistence: {type(error).__name__}: {error}"
                    )[:4000]
                    sibling.finished_at = now
                    sibling.checkpoint = {
                        "stage": "failed",
                        "reason": ScraperErrorCode.EVIDENCE_PERSISTENCE.value,
                        "at": now.isoformat(),
                    }
            await session.commit()
            pricing_event(
                "pricing_item_failed",
                pricing_run_id=str(run_id),
                pricing_run_item_id=str(run_item_id),
                scrape_target_id=str(item.scrape_target_id),
                error_type=type(error).__name__,
            )
            if run_id is not None:
                await finalize_pricing_run(run_id)
            return
        item.status = "failed"
        item.error = f"{type(error).__name__}: {error}"[:4000]
        item.finished_at = datetime.now(UTC)
        item.checkpoint = {"stage": "failed", "at": item.finished_at.isoformat()}
        await session.commit()
        pricing_event(
            "pricing_item_failed",
            pricing_run_id=str(run_id),
            pricing_run_item_id=str(run_item_id),
            error_type=type(error).__name__,
        )
    if run_id is not None:
        await finalize_pricing_run(run_id)


async def fail_pricing_run_dispatch(run_id: UUID, error: Exception) -> None:
    """Fail a run deterministically after orchestration dispatch is exhausted."""

    async with async_session_factory() as session:
        run = await session.scalar(
            select(PricingRun).where(PricingRun.id == run_id).with_for_update()
        )
        if run is None or run.status in {
            "completed",
            "partial",
            "failed",
            "cancelled",
        }:
            return
        now = datetime.now(UTC)
        detail = f"{type(error).__name__}: {error}"[:4000]
        targets = list(
            (
                await session.scalars(
                    select(ScrapeTarget).where(
                        ScrapeTarget.pricing_run_id == run_id,
                        ScrapeTarget.status.not_in(
                            ("succeeded", "terminal_failure", "cancelled")
                        ),
                    )
                )
            ).all()
        )
        target_ids = [target.id for target in targets]
        for target in targets:
            target.status = "terminal_failure"
            _set_terminal_target_contract(
                target,
                reason=ScraperErrorCode.RETRY_EXHAUSTED.value,
                raw_available=target.raw_size_bytes > 0,
            )
            target.error_category = ScraperErrorCode.RETRY_EXHAUSTED.value
            target.error_detail = detail
            target.owner_task_id = None
            target.lease_expires_at = None
            target.finished_at = now
        if target_ids:
            attempts = list(
                (
                    await session.scalars(
                        select(ScrapeAttempt).where(
                            ScrapeAttempt.scrape_target_id.in_(target_ids),
                            ScrapeAttempt.status == "running",
                        )
                    )
                ).all()
            )
            for attempt in attempts:
                attempt.status = "worker_lost"
                attempt.error_category = "dispatch_exhausted"
                attempt.error_detail = detail
                attempt.finished_at = now
                if attempt.wall_time_ms == 0:
                    attempt.wall_time_ms = max(
                        0,
                        round(
                            (now - _aware_datetime(attempt.started_at)).total_seconds()
                            * 1000
                        ),
                    )
        items = list(
            (
                await session.scalars(
                    select(PricingRunItem).where(
                        PricingRunItem.pricing_run_id == run_id,
                        PricingRunItem.status.not_in(
                            (
                                "calculated",
                                "manual_review",
                                "failed",
                                "cancelled",
                            )
                        ),
                    )
                )
            ).all()
        )
        for item in items:
            item.status = "failed"
            item.error = f"dispatch_exhausted: {detail}"[:4000]
            item.finished_at = now
            item.checkpoint = {
                "stage": "failed",
                "reason": "dispatch_exhausted",
                "at": now.isoformat(),
            }
        run.status = "failed"
        run.failed_items = run.total_items
        run.error = f"Pricing dispatch exhausted: {detail}"[:4000]
        run.finished_at = now
        await session.commit()
        pricing_event(
            "pricing_run_failed",
            pricing_run_id=str(run.id),
            status="failed",
            reason="dispatch_exhausted",
            failed=run.failed_items,
        )


async def finalize_pricing_run(run_id: UUID) -> None:
    async with async_session_factory() as session:
        run = await session.scalar(
            select(PricingRun).where(PricingRun.id == run_id).with_for_update()
        )
        if run is None:
            return
        counts = {
            status: int(count)
            for status, count in (
                await session.execute(
                    select(PricingRunItem.status, func.count(PricingRunItem.id))
                    .where(PricingRunItem.pricing_run_id == run_id)
                    .group_by(PricingRunItem.status)
                )
            ).all()
        }
        calculated = counts.get("calculated", 0)
        manual = counts.get("manual_review", 0)
        failed = counts.get("failed", 0)
        cancelled = counts.get("cancelled", 0)
        terminal = calculated + manual + failed + cancelled
        run.completed_items = calculated + manual
        run.failed_items = failed
        run.manual_review_items = manual
        if terminal >= run.total_items:
            if cancelled == run.total_items:
                run.status = "cancelled"
            elif calculated + manual == 0:
                run.status = "failed"
            elif failed or cancelled:
                run.status = "partial"
            else:
                run.status = "completed"
            run.finished_at = datetime.now(UTC)
            event_name = {
                "completed": "pricing_run_completed",
                "partial": "pricing_run_partial",
                "failed": "pricing_run_failed",
                "cancelled": "pricing_run_cancelled",
            }[run.status]
            pricing_event(
                event_name,
                pricing_run_id=str(run.id),
                status=run.status,
                calculated=calculated,
                manual_review=manual,
                failed=failed,
                cancelled=cancelled,
            )
        elif run.status not in {
            "failed",
            "cancelled",
            "classifying",
            "calibrating",
            "calculating",
        }:
            run.status = "running"
        await session.commit()


def _source_listing_id(product_id: int | None, url: str | None, price: float) -> str:
    if product_id is not None:
        return str(product_id)
    return hashlib.sha256(f"{url or ''}|{price}".encode()).hexdigest()


def _currency_code(value: str | None) -> str:
    normalized = (value or "").strip().casefold()
    if not normalized:
        return "UNK"
    if normalized in {"uah", "грн", "₴", "гривня", "гривень"}:
        return "UAH"
    return normalized.upper()[:3]


def _availability(explicit: bool | None, presence: str | None) -> bool | None:
    if explicit is not None:
        return explicit
    value = (presence or "").casefold()
    if value in {"available", "in_stock", "в наличии", "в наявності"}:
        return True
    if value in {"unavailable", "out_of_stock", "нет в наличии"}:
        return False
    return None


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _payload_source_listing_id(
    offer: Mapping[str, Any],
    price: Decimal,
) -> str:
    product_id = offer.get("product_id")
    if product_id is not None:
        return str(product_id)[:255]
    return hashlib.sha256(f"{offer.get('url') or ''}|{price}".encode()).hexdigest()


__all__ = [
    "PermanentCollectionError",
    "PricingItemNotFoundError",
    "calculate_pricing_item",
    "calibrate_run_and_prepare_calculations",
    "claim_collection_finalization",
    "fail_pricing_item",
    "fail_pricing_run_dispatch",
    "finalize_pricing_run",
    "get_pricing_item_run_id",
    "mark_run_calculating",
    "prepare_run_dispatch",
    "process_pricing_item",
    "fail_collection_finalization",
    "reset_pricing_calculation_for_retry",
    "reset_pricing_item_for_retry",
]
