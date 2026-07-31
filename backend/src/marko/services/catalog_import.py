"""Idempotent, observable store-catalog import around the frozen Prom gateway."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from uuid import UUID, uuid4

from sqlalchemy import func, select

from marko.core.config import get_settings
from marko.infrastructure.db.models import (
    Listing,
    MarketplaceStore,
    PriceObservation,
    StoreSyncProductSnapshot,
    StoreSyncTaskExecution,
    SyncRun,
    SyncStatus,
)
from marko.infrastructure.db.session import async_session_factory
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.gateway import PromGateway
from metis.pricing.observability import pricing_event
from marko.services.collection_guard import DistributedCollectionGuard
from marko.services.parser_models import Product
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
    ScraperBoundaryError,
    ScraperErrorCode,
    classify_scraper_exception,
)
from marko.services.scraper_outbox import enqueue_dispatch
from marko.services.source_access import require_live_prom_marketplace_collection

import marko.repositories.listings as listings_repo


_BATCH_SIZE = 25
_PRICE_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


class CatalogImportError(RuntimeError):
    pass


class RetryableCatalogImportError(CatalogImportError):
    pass


class TerminalCatalogImportError(CatalogImportError):
    pass


class StaleCatalogImportClaim(CatalogImportError):
    """A superseded worker tried to persist after another execution took over."""


@dataclass(frozen=True)
class StoreSyncClaim:
    sync_run_id: UUID
    execution_id: UUID
    execution_no: int
    store_id: UUID
    store_url: str
    max_task_executions: int
    deadline_at: datetime
    task_id: str | None
    fencing_token: int = 0
    start_page: int = 1
    page_budget: int = 100
    total_page_limit: int = 1000
    failed_executions_before: int = 0


@dataclass(frozen=True)
class StoreSyncTaskResult:
    persisted_products: int
    continuation_dispatch_id: UUID | None = None


@dataclass(frozen=True)
class StoreSyncChunkResult:
    persisted_products: int
    catalog_pages_fetched: int


@dataclass(frozen=True)
class ProductPersistenceStats:
    extracted: int
    persisted: int
    duplicates: int
    database_writes: int
    completeness_sum: Decimal


def parse_product_price(product: Product) -> Decimal | None:
    # Discounted price is the active payable price. ``price``/``priceOriginal``
    # may be the crossed-out reference price in Prom payloads.
    raw = product.discounted_price or product.price or product.price_original
    if raw is None:
        return None
    normalized = str(raw).replace("\u00a0", "").replace(" ", "").replace(",", ".")
    match = _PRICE_NUMBER_RE.search(normalized)
    if match is None:
        return None
    try:
        parsed = Decimal(match.group()).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return parsed if parsed > 0 else None


async def import_store_catalog(
    sync_run_id: UUID,
    *,
    task_id: str | None = None,
    is_redelivery: bool = False,
    redelivery_reason: str | None = None,
) -> StoreSyncTaskResult:
    """Execute one bounded task attempt for one ``store_sync`` logical item."""

    claim = await _claim_execution(
        sync_run_id,
        task_id=task_id,
        is_redelivery=is_redelivery,
        redelivery_reason=redelivery_reason,
    )
    if claim is None:
        return StoreSyncTaskResult(
            persisted_products=await _persisted_product_count(sync_run_id)
        )

    settings = get_settings()
    probe = AttemptResourceProbe()
    trace: ScrapeExecutionTrace | None = None
    try:
        async with async_session_factory() as session:
            replay_cache = (
                await load_replay_cache(session, sync_run_id=sync_run_id)
                if settings.scrape_raw_evidence_replay_enabled
                else {}
            )
        trace = ScrapeExecutionTrace(
            item_kind="store_sync",
            execution_no=claim.execution_no,
            replay_cache=replay_cache,
            guard=DistributedCollectionGuard(settings, namespace="prom"),
            live_request_gate=require_live_prom_marketplace_collection,
        )
        chunk = await _run_import(claim, trace)
        measurement = probe.finish()
        if _chunk_reached_page_budget(claim, chunk.catalog_pages_fetched):
            next_page = claim.start_page + chunk.catalog_pages_fetched
            if next_page > claim.total_page_limit:
                raise ScraperBoundaryError(
                    ScraperErrorCode.INVALID_INPUT,
                    "Store catalog reached the configured total page limit "
                    f"({claim.total_page_limit}) before an end page was observed",
                    retryable=False,
                )
            dispatch_id = await _finish_chunk(
                claim,
                chunk,
                measurement,
                next_page=next_page,
            )
            return StoreSyncTaskResult(
                persisted_products=chunk.persisted_products,
                continuation_dispatch_id=dispatch_id,
            )
        persisted = await _finish_success(
            claim,
            chunk.persisted_products,
            measurement,
        )
        if not persisted:
            return StoreSyncTaskResult(
                persisted_products=await _persisted_product_count(sync_run_id)
            )
        return StoreSyncTaskResult(persisted_products=chunk.persisted_products)
    except StaleCatalogImportClaim:
        return StoreSyncTaskResult(
            persisted_products=await _persisted_product_count(sync_run_id)
        )
    except Exception as exc:
        failure: Exception = exc
        measurement = probe.finish()
        if trace is not None:
            try:
                await _flush_trace_only(claim, trace)
            except StaleCatalogImportClaim:
                return StoreSyncTaskResult(
                    persisted_products=await _persisted_product_count(sync_run_id)
                )
            except Exception as trace_exc:
                failure = ScraperBoundaryError(
                    ScraperErrorCode.EVIDENCE_PERSISTENCE,
                    "Could not persist store-sync HTTP evidence: "
                    f"{type(trace_exc).__name__}: {trace_exc}",
                    retryable=True,
                )
        boundary = _catalog_boundary(failure)
        exhausted = (
            claim.failed_executions_before + 1 >= claim.max_task_executions
            or datetime.now(UTC) >= claim.deadline_at
        )
        if exhausted and boundary.retryable:
            boundary = ScraperBoundaryError(
                ScraperErrorCode.RETRY_EXHAUSTED,
                f"Store-sync retry budget exhausted: {boundary}",
                retryable=False,
            )
        try:
            persisted = await _finish_failure(claim, boundary, measurement)
        except StaleCatalogImportClaim:
            return StoreSyncTaskResult(
                persisted_products=await _persisted_product_count(sync_run_id)
            )
        except Exception as state_exc:
            raise RetryableCatalogImportError(
                "Could not persist store-sync terminal/retry state: "
                f"{type(state_exc).__name__}: {state_exc}"
            ) from state_exc
        if not persisted:
            return StoreSyncTaskResult(
                persisted_products=await _persisted_product_count(sync_run_id)
            )
        if boundary.retryable:
            raise RetryableCatalogImportError(str(boundary)) from failure
        raise TerminalCatalogImportError(str(boundary)) from failure
    finally:
        try:
            await _refresh_store_execution_measurement(
                claim,
                probe.finish(),
            )
        except Exception as measurement_error:
            pricing_event(
                "scrape_measurement_persistence_failed",
                item_kind="store_sync",
                sync_run_id=str(claim.sync_run_id),
                execution_no=claim.execution_no,
                error_type=type(measurement_error).__name__,
            )
        if trace is not None:
            trace.close()


async def _claim_execution(
    sync_run_id: UUID,
    *,
    task_id: str | None,
    is_redelivery: bool,
    redelivery_reason: str | None,
) -> StoreSyncClaim | None:
    async with async_session_factory() as session:
        sync_run = await session.scalar(
            select(SyncRun).where(SyncRun.id == sync_run_id).with_for_update()
        )
        if sync_run is None:
            raise TerminalCatalogImportError(f"Sync run {sync_run_id} does not exist")
        if sync_run.store_id is None:
            raise TerminalCatalogImportError(f"Sync run {sync_run_id} has no store")
        if sync_run.scrape_state == "succeeded":
            return None
        if sync_run.scrape_state in {"failed", "cancelled"}:
            raise TerminalCatalogImportError(
                f"Sync run {sync_run_id} is already {sync_run.scrape_state}"
            )
        now = datetime.now(UTC)
        settings = get_settings()
        deadline = sync_run.scrape_deadline_at
        if deadline is None:
            deadline = now + timedelta(
                seconds=max(1, settings.store_sync_item_deadline_seconds)
            )
            sync_run.scrape_deadline_at = deadline
        failed_executions_before = int(
            await session.scalar(
                select(func.count(StoreSyncTaskExecution.id)).where(
                    StoreSyncTaskExecution.sync_run_id == sync_run.id,
                    StoreSyncTaskExecution.outcome.in_(
                        ("retryable_failure", "worker_lost")
                    ),
                )
            )
            or 0
        )
        lease_active = (
            sync_run.scrape_state == "running"
            and sync_run.scrape_lease_expires_at is not None
            and _aware(sync_run.scrape_lease_expires_at) > now
        )
        if lease_active and not is_redelivery:
            await session.commit()
            return None
        if (
            now >= deadline
            or failed_executions_before >= sync_run.scrape_max_task_executions
        ):
            sync_run.status = SyncStatus.failed
            sync_run.scrape_state = "failed"
            sync_run.error = "Store-sync retry budget exhausted before execution"
            sync_run.finished_at = now
            await session.commit()
            raise TerminalCatalogImportError(sync_run.error)
        store = await session.get(MarketplaceStore, sync_run.store_id)
        if store is None:
            raise TerminalCatalogImportError(
                f"Store {sync_run.store_id} does not exist"
            )

        start_page = _checkpoint_next_page(
            sync_run.scrape_checkpoint,
            fallback=sync_run.scrape_catalog_pages + 1,
        )
        total_page_limit = (
            settings.store_sync_scraper_max_pages
            if settings.store_sync_scraper_max_pages > 0
            else settings.store_sync_scraper_total_page_limit
        )
        if start_page > total_page_limit:
            sync_run.status = SyncStatus.failed
            sync_run.scrape_state = "failed"
            sync_run.error = (
                "Store-sync total page limit was reached before completion"
            )
            sync_run.finished_at = now
            await session.commit()
            raise TerminalCatalogImportError(sync_run.error)
        page_budget = min(
            settings.store_sync_scraper_pages_per_task,
            total_page_limit - start_page + 1,
        )
        execution_no = sync_run.scrape_task_executions + 1
        redelivered = is_redelivery
        expired_owner = sync_run.scrape_state == "running" and (
            sync_run.scrape_lease_expires_at is None
            or _aware(sync_run.scrape_lease_expires_at) <= now
        )
        if redelivered or expired_owner:
            previous_running = list(
                (
                    await session.scalars(
                        select(StoreSyncTaskExecution).where(
                            StoreSyncTaskExecution.sync_run_id == sync_run.id,
                            StoreSyncTaskExecution.outcome == "running",
                        )
                    )
                ).all()
            )
            for previous in previous_running:
                previous.outcome = "worker_lost"
                previous.error_category = "worker_lost"
                previous.error_detail = (
                    "Broker redelivered an execution that never reached "
                    "a terminal task outcome"
                )
                previous.finished_at = now
        sync_run.scrape_fencing_token += 1
        fencing_token = sync_run.scrape_fencing_token
        execution = StoreSyncTaskExecution(
            sync_run_id=sync_run.id,
            task_id=task_id,
            execution_no=execution_no,
            fencing_token=fencing_token,
            is_redelivery=redelivered,
            redelivery_reason=(
                redelivery_reason
                or (
                    "bounded_continuation"
                    if start_page > 1 and not redelivered
                    else None
                )
            ),
            outcome="running",
            started_at=now,
        )
        session.add(execution)
        sync_run.status = SyncStatus.running
        sync_run.scrape_state = "running"
        sync_run.scrape_owner_task_id = task_id
        sync_run.scrape_lease_expires_at = now + timedelta(
            seconds=max(1, settings.store_sync_lease_seconds)
        )
        sync_run.scrape_task_executions = execution_no
        if redelivered:
            sync_run.scrape_task_redeliveries += 1
        sync_run.started_at = sync_run.started_at or now
        sync_run.task_id = task_id or sync_run.task_id
        sync_run.error = None
        sync_run.scrape_checkpoint = {
            "stage": "running",
            "item_kind": "store_sync",
            "execution_no": execution_no,
            "start_page": start_page,
            "page_budget": page_budget,
            "next_page": start_page,
            "replay_entries": 0,
            "at": now.isoformat(),
        }
        await session.flush()
        execution_id = execution.id
        await session.commit()
        pricing_event(
            "scrape_task_execution_started",
            item_kind="store_sync",
            sync_run_id=str(sync_run.id),
            execution_no=execution_no,
            redelivery=redelivered,
        )
        return StoreSyncClaim(
            sync_run_id=sync_run.id,
            execution_id=execution_id,
            execution_no=execution_no,
            fencing_token=fencing_token,
            store_id=store.id,
            store_url=store.canonical_url,
            max_task_executions=sync_run.scrape_max_task_executions,
            deadline_at=deadline,
            task_id=task_id,
            start_page=start_page,
            page_budget=page_budget,
            total_page_limit=total_page_limit,
            failed_executions_before=failed_executions_before,
        )


async def _run_import(
    claim: StoreSyncClaim,
    trace: ScrapeExecutionTrace,
) -> StoreSyncChunkResult:
    settings = get_settings()
    config = ScrapeConfig(
        delay=settings.pricing_scraper_request_delay_seconds,
        delay_jitter=settings.pricing_scraper_request_jitter_seconds,
        timeout=settings.store_sync_scraper_http_timeout_seconds,
        max_attempts=max(1, settings.store_sync_scraper_http_max_attempts),
        max_pages=claim.page_budget,
        start_page=claim.start_page,
    )
    batch: list[Product] = []
    catalog_pages_fetched = 0
    with scrape_execution(trace):
        try:
            for product in PromGateway(config).scrape(claim.store_url, strict=True):
                batch.append(product)
                if len(batch) >= _BATCH_SIZE:
                    catalog_pages_fetched += await _persist_progress(
                        claim,
                        trace,
                        batch,
                    )
                    batch = []
        except Exception:
            if batch:
                await _persist_progress(claim, trace, batch)
            raise
        catalog_pages_fetched += await _persist_progress(claim, trace, batch)

    imported = await _persisted_product_count(claim.sync_run_id)
    if imported == 0:
        raise ScraperBoundaryError(
            ScraperErrorCode.PARSE_CONTRACT,
            "Prom returned no valid products for this store",
            retryable=False,
        )
    return StoreSyncChunkResult(
        persisted_products=imported,
        catalog_pages_fetched=catalog_pages_fetched,
    )


async def _persist_progress(
    claim: StoreSyncClaim,
    trace: ScrapeExecutionTrace,
    products: list[Product],
) -> int:
    completed_requests = trace.drain_completed_requests()
    if not products and not completed_requests:
        return 0
    try:
        async with async_session_factory() as session:
            sync_run = await session.scalar(
                select(SyncRun).where(SyncRun.id == claim.sync_run_id).with_for_update()
            )
            if sync_run is None:
                raise TerminalCatalogImportError(str(claim.sync_run_id))
            execution = await session.scalar(
                select(StoreSyncTaskExecution)
                .where(StoreSyncTaskExecution.id == claim.execution_id)
                .with_for_update()
            )
            if not _store_claim_is_current(sync_run, execution, claim):
                await _mark_stale_store_execution(
                    session,
                    execution,
                    "Store-sync checkpoint rejected by execution fence",
                )
                raise StaleCatalogImportClaim(str(claim.sync_run_id))
            product_stats = await _persist_batch(
                session,
                sync_run_id=claim.sync_run_id,
                store_id=claim.store_id,
                products=products,
            )
            trace_stats = await persist_http_traces(
                session,
                completed_requests,
                execution_no=claim.execution_no,
                sync_run_id=claim.sync_run_id,
            )
            old_persisted = sync_run.scrape_products_persisted
            new_persisted = old_persisted + product_stats.persisted
            sync_run.scrape_products_extracted += product_stats.extracted
            sync_run.scrape_products_persisted = new_persisted
            sync_run.scrape_duplicate_products += product_stats.duplicates
            sync_run.scrape_catalog_pages += trace_stats.catalog_pages
            sync_run.scrape_database_writes += (
                product_stats.database_writes + trace_stats.database_writes + 1
            )
            sync_run.scrape_structured_completeness = _merge_structured_completeness(
                current=sync_run.scrape_structured_completeness,
                current_count=old_persisted,
                added_sum=product_stats.completeness_sum,
                added_count=product_stats.persisted,
            )
            sync_run.progress_current = sync_run.scrape_products_persisted
            sync_run.scrape_checkpoint = {
                "stage": "checkpointed",
                "execution_no": claim.execution_no,
                "start_page": claim.start_page,
                "page_budget": claim.page_budget,
                "next_page": sync_run.scrape_catalog_pages + 1,
                "products_persisted": sync_run.scrape_products_persisted,
                "logical_requests": trace_stats.logical_requests,
                "physical_attempts": trace_stats.physical_attempts,
                "last_request_sequence": (
                    completed_requests[-1].sequence_no if completed_requests else None
                ),
                "at": datetime.now(UTC).isoformat(),
            }
            sync_run.scrape_lease_expires_at = datetime.now(UTC) + timedelta(
                seconds=max(1, get_settings().store_sync_lease_seconds)
            )
            await session.commit()
            return trace_stats.catalog_pages
    except Exception:
        trace.restore_completed_requests(completed_requests)
        raise


async def _flush_trace_only(
    claim: StoreSyncClaim,
    trace: ScrapeExecutionTrace,
) -> None:
    completed_requests = trace.drain_completed_requests()
    if not completed_requests:
        return
    try:
        async with async_session_factory() as session:
            sync_run = await session.scalar(
                select(SyncRun).where(SyncRun.id == claim.sync_run_id).with_for_update()
            )
            if sync_run is None:
                return
            execution = await session.scalar(
                select(StoreSyncTaskExecution)
                .where(StoreSyncTaskExecution.id == claim.execution_id)
                .with_for_update()
            )
            if not _store_claim_is_current(sync_run, execution, claim):
                await _mark_stale_store_execution(
                    session,
                    execution,
                    "Store-sync trace rejected by execution fence",
                )
                raise StaleCatalogImportClaim(str(claim.sync_run_id))
            stats = await persist_http_traces(
                session,
                completed_requests,
                execution_no=claim.execution_no,
                sync_run_id=claim.sync_run_id,
            )
            sync_run.scrape_catalog_pages += stats.catalog_pages
            sync_run.scrape_database_writes += stats.database_writes + 1
            sync_run.scrape_checkpoint = {
                "stage": "attempt_trace_persisted",
                "execution_no": claim.execution_no,
                "start_page": claim.start_page,
                "page_budget": claim.page_budget,
                "next_page": sync_run.scrape_catalog_pages + 1,
                "logical_requests": stats.logical_requests,
                "physical_attempts": stats.physical_attempts,
                "at": datetime.now(UTC).isoformat(),
            }
            await session.commit()
    except Exception:
        trace.restore_completed_requests(completed_requests)
        raise


async def _persist_batch(
    session,
    *,
    sync_run_id: UUID,
    store_id: UUID,
    products: list[Product],
) -> ProductPersistenceStats:
    extracted = len(products)
    valid_products = [
        product
        for product in products
        if product.id is not None and product.name and product.url
    ]
    if not valid_products:
        return ProductPersistenceStats(
            extracted=extracted,
            persisted=0,
            duplicates=0,
            database_writes=0,
            completeness_sum=Decimal("0"),
        )

    external_ids = [str(product.id) for product in valid_products]
    existing_listings = await listings_repo.get_listings_by_external_ids(
        session,
        store_id,
        external_ids,
    )
    existing = {listing.external_id: listing for listing in existing_listings}
    existing_snapshot_external_ids = set(
        (
            await session.scalars(
                select(StoreSyncProductSnapshot.external_id).where(
                    StoreSyncProductSnapshot.sync_run_id == sync_run_id,
                    StoreSyncProductSnapshot.external_id.in_(external_ids),
                )
            )
        ).all()
    )
    now = datetime.now(UTC)
    persisted = 0
    duplicates = 0
    writes = 0
    completeness_sum = Decimal("0")

    for product in valid_products:
        external_id = str(product.id)
        listing = existing.get(external_id)
        if external_id in existing_snapshot_external_ids:
            duplicates += 1
            continue

        price = parse_product_price(product)
        currency, currency_raw, currency_inferred = _currency_evidence(product.currency)
        payload = product.as_dict()
        canonical_payload = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        completeness = _product_completeness(product).quantize(Decimal("0.000001"))
        if listing is None:
            listing = Listing(
                id=uuid4(),
                store_id=store_id,
                external_id=external_id,
                name=product.name or external_id,
                url=product.url or "",
            )
            await listings_repo.add_listing(session, listing)
            existing[external_id] = listing
            writes += 1
        else:
            writes += 1

        listing.name = product.name or listing.name
        listing.url = product.url or listing.url
        listing.sku = product.sku
        listing.model_id = product.model_id
        listing.brand = product.brand
        listing.currency = currency
        listing.current_price = price
        listing.is_available = product.is_available
        listing.raw_data = payload
        listing.last_seen_at = now

        session.add(
            StoreSyncProductSnapshot(
                sync_run_id=sync_run_id,
                listing_id=listing.id,
                external_id=external_id,
                payload=payload,
                content_sha256=hashlib.sha256(canonical_payload).hexdigest(),
                structured_size_bytes=len(canonical_payload),
                structured_completeness=completeness,
            )
        )
        existing_snapshot_external_ids.add(external_id)
        persisted += 1
        completeness_sum += completeness
        writes += 1

        if price is not None:
            await listings_repo.add_price_observation(
                session,
                PriceObservation(
                    listing_id=listing.id,
                    sync_run_id=sync_run_id,
                    price=price,
                    currency=currency,
                    currency_raw=currency_raw,
                    currency_inferred=currency_inferred,
                    is_available=product.is_available,
                    observed_at=now,
                ),
            )
            writes += 1

    await session.flush()
    return ProductPersistenceStats(
        extracted=extracted,
        persisted=persisted,
        duplicates=duplicates,
        database_writes=writes,
        completeness_sum=completeness_sum,
    )


async def _finish_success(
    claim: StoreSyncClaim,
    imported: int,
    measurement: AttemptMeasurement,
) -> bool:
    async with async_session_factory() as session:
        sync_run = await session.scalar(
            select(SyncRun).where(SyncRun.id == claim.sync_run_id).with_for_update()
        )
        execution = await session.get(StoreSyncTaskExecution, claim.execution_id)
        store = await session.get(MarketplaceStore, claim.store_id)
        if sync_run is None or execution is None or store is None:
            raise TerminalCatalogImportError("Store-sync dependencies disappeared")
        if not _store_claim_is_current(sync_run, execution, claim):
            await _mark_stale_store_execution(
                session,
                execution,
                "Store-sync success rejected by execution fence",
            )
            return False
        now = datetime.now(UTC)
        coverage = await evidence_coverage_ratio(
            session,
            sync_run_id=claim.sync_run_id,
            execution_no=claim.execution_no,
        )
        raw_bytes = await retained_raw_evidence_bytes(
            session,
            sync_run_id=claim.sync_run_id,
        )
        store.last_synced_at = now
        sync_run.status = SyncStatus.completed
        sync_run.scrape_state = "succeeded"
        sync_run.scrape_owner_task_id = None
        sync_run.scrape_lease_expires_at = None
        sync_run.progress_current = imported
        sync_run.progress_total = imported
        sync_run.scrape_products_persisted = imported
        sync_run.scrape_evidence_coverage = coverage
        sync_run.scrape_raw_evidence_bytes = raw_bytes
        sync_run.finished_at = now
        sync_run.scrape_checkpoint = {
            "stage": "succeeded",
            "execution_no": claim.execution_no,
            "products_persisted": imported,
            "evidence_coverage": str(coverage),
            "at": now.isoformat(),
        }
        execution.outcome = "succeeded"
        execution.wall_time_ms = measurement.wall_time_ms
        execution.cpu_time_ms = measurement.cpu_time_ms
        execution.memory_peak_bytes = measurement.memory_peak_bytes
        execution.finished_at = now
        await session.commit()
        pricing_event(
            "scrape_items_terminal",
            status="success",
            item_kind="store_sync",
            sync_run_id=str(claim.sync_run_id),
            execution_no=claim.execution_no,
            evidence_coverage=str(coverage),
        )
        return True


async def _finish_chunk(
    claim: StoreSyncClaim,
    chunk: StoreSyncChunkResult,
    measurement: AttemptMeasurement,
    *,
    next_page: int,
) -> UUID | None:
    """Commit a visible partial result and enqueue the next bounded page chunk."""

    async with async_session_factory() as session:
        sync_run = await session.scalar(
            select(SyncRun).where(SyncRun.id == claim.sync_run_id).with_for_update()
        )
        execution = await session.get(StoreSyncTaskExecution, claim.execution_id)
        if sync_run is None or execution is None:
            raise TerminalCatalogImportError("Store-sync dependencies disappeared")
        if not _store_claim_is_current(sync_run, execution, claim):
            await _mark_stale_store_execution(
                session,
                execution,
                "Store-sync chunk completion rejected by execution fence",
            )
            return None

        now = datetime.now(UTC)
        sync_run.status = SyncStatus.queued
        sync_run.scrape_state = "queued"
        sync_run.scrape_owner_task_id = None
        sync_run.scrape_lease_expires_at = None
        sync_run.progress_current = chunk.persisted_products
        sync_run.progress_total = None
        sync_run.scrape_products_persisted = chunk.persisted_products
        sync_run.scrape_evidence_coverage = await evidence_coverage_ratio(
            session,
            sync_run_id=claim.sync_run_id,
            execution_no=claim.execution_no,
        )
        sync_run.scrape_raw_evidence_bytes = await retained_raw_evidence_bytes(
            session,
            sync_run_id=claim.sync_run_id,
        )
        sync_run.scrape_checkpoint = {
            "stage": "chunk_succeeded",
            "execution_no": claim.execution_no,
            "start_page": claim.start_page,
            "pages_fetched": chunk.catalog_pages_fetched,
            "next_page": next_page,
            "products_persisted": chunk.persisted_products,
            "at": now.isoformat(),
        }
        execution.outcome = "succeeded"
        execution.wall_time_ms = measurement.wall_time_ms
        execution.cpu_time_ms = measurement.cpu_time_ms
        execution.memory_peak_bytes = measurement.memory_peak_bytes
        execution.finished_at = now
        dispatch = await enqueue_dispatch(
            session,
            event_key=f"store-sync:{sync_run.id}:page:{next_page}:v1",
            aggregate_type="sync_run",
            aggregate_id=sync_run.id,
            workspace_id=sync_run.workspace_id,
            task_name="marko.worker.import_store_catalog",
            task_args=[str(sync_run.id)],
            queue="store-sync",
            max_attempts=20,
        )
        sync_run.task_id = dispatch.task_id
        await session.commit()
        pricing_event(
            "scrape_chunk_completed",
            item_kind="store_sync",
            sync_run_id=str(sync_run.id),
            execution_no=claim.execution_no,
            start_page=claim.start_page,
            pages_fetched=chunk.catalog_pages_fetched,
            next_page=next_page,
            products_persisted=chunk.persisted_products,
        )
        return dispatch.id


async def _finish_failure(
    claim: StoreSyncClaim,
    error: ScraperBoundaryError,
    measurement: AttemptMeasurement,
) -> bool:
    async with async_session_factory() as session:
        sync_run = await session.scalar(
            select(SyncRun).where(SyncRun.id == claim.sync_run_id).with_for_update()
        )
        execution = await session.get(StoreSyncTaskExecution, claim.execution_id)
        if sync_run is None or execution is None:
            return False
        if not _store_claim_is_current(sync_run, execution, claim):
            await _mark_stale_store_execution(
                session,
                execution,
                "Store-sync failure rejected by execution fence",
            )
            return False
        now = datetime.now(UTC)
        terminal = not error.retryable
        sync_run.scrape_state = "failed" if terminal else "retry_wait"
        sync_run.scrape_owner_task_id = None
        sync_run.scrape_lease_expires_at = None
        sync_run.status = SyncStatus.failed if terminal else SyncStatus.running
        sync_run.error = f"{error.code.value}: {error}"[:4000]
        sync_run.finished_at = now if terminal else None
        sync_run.scrape_checkpoint = {
            "stage": "terminal_failure" if terminal else "retry_wait",
            "execution_no": claim.execution_no,
            "start_page": claim.start_page,
            "next_page": sync_run.scrape_catalog_pages + 1,
            "error_category": error.code.value,
            "at": now.isoformat(),
        }
        execution.outcome = "terminal_failure" if terminal else "retryable_failure"
        execution.error_category = error.code.value
        execution.error_detail = str(error)[:4000]
        execution.wall_time_ms = measurement.wall_time_ms
        execution.cpu_time_ms = measurement.cpu_time_ms
        execution.memory_peak_bytes = measurement.memory_peak_bytes
        execution.finished_at = now
        sync_run.scrape_evidence_coverage = await evidence_coverage_ratio(
            session,
            sync_run_id=claim.sync_run_id,
            execution_no=claim.execution_no,
        )
        sync_run.scrape_raw_evidence_bytes = await retained_raw_evidence_bytes(
            session,
            sync_run_id=claim.sync_run_id,
        )
        await session.commit()
        pricing_event(
            "scrape_items_terminal" if terminal else "scrape_task_retry_wait",
            status="failed" if terminal else "retry_wait",
            item_kind="store_sync",
            sync_run_id=str(claim.sync_run_id),
            execution_no=claim.execution_no,
            error_category=error.code.value,
        )
        return True


async def _persisted_product_count(sync_run_id: UUID) -> int:
    async with async_session_factory() as session:
        return int(
            await session.scalar(
                select(func.count(StoreSyncProductSnapshot.id)).where(
                    StoreSyncProductSnapshot.sync_run_id == sync_run_id
                )
            )
            or 0
        )


async def fail_store_sync_task(
    sync_run_id: UUID,
    *,
    task_id: str | None,
    error: Exception,
) -> None:
    """Force a terminal state after Celery can no longer redeliver the task."""

    async with async_session_factory() as session:
        sync_run = await session.scalar(
            select(SyncRun).where(SyncRun.id == sync_run_id).with_for_update()
        )
        if sync_run is None or sync_run.scrape_state in {
            "succeeded",
            "failed",
            "cancelled",
        }:
            return
        # Never let an obsolete task fail a newer fenced execution.
        if (
            sync_run.scrape_owner_task_id is not None
            and sync_run.scrape_owner_task_id != task_id
        ):
            return
        now = datetime.now(UTC)
        detail = f"{type(error).__name__}: {error}"[:4000]
        sync_run.status = SyncStatus.failed
        sync_run.scrape_state = "failed"
        sync_run.scrape_owner_task_id = None
        sync_run.scrape_lease_expires_at = None
        sync_run.error = f"task_retry_exhausted: {detail}"[:4000]
        sync_run.finished_at = now
        sync_run.scrape_checkpoint = {
            "stage": "terminal_failure",
            "reason": "task_retry_exhausted",
            "at": now.isoformat(),
        }
        running = list(
            (
                await session.scalars(
                    select(StoreSyncTaskExecution).where(
                        StoreSyncTaskExecution.sync_run_id == sync_run_id,
                        StoreSyncTaskExecution.outcome == "running",
                    )
                )
            ).all()
        )
        for execution in running:
            execution.outcome = "terminal_failure"
            execution.error_category = ScraperErrorCode.RETRY_EXHAUSTED.value
            execution.error_detail = detail
            execution.finished_at = now
            if execution.wall_time_ms == 0:
                execution.wall_time_ms = max(
                    0,
                    round((now - _aware(execution.started_at)).total_seconds() * 1000),
                )
        await session.commit()
        pricing_event(
            "scrape_items_terminal",
            status="failed",
            item_kind="store_sync",
            sync_run_id=str(sync_run_id),
            error_category=ScraperErrorCode.RETRY_EXHAUSTED.value,
        )


def _store_claim_is_current(
    sync_run: SyncRun,
    execution: StoreSyncTaskExecution | None,
    claim: StoreSyncClaim,
) -> bool:
    explicit_fence_matches = claim.fencing_token == 0 or (
        getattr(execution, "fencing_token", None) == claim.fencing_token
        and getattr(sync_run, "scrape_fencing_token", None) == claim.fencing_token
    )
    return bool(
        execution is not None
        and execution.id == claim.execution_id
        and execution.execution_no == claim.execution_no
        and explicit_fence_matches
        and execution.outcome == "running"
        and sync_run.scrape_state == "running"
        and sync_run.scrape_task_executions == claim.execution_no
        and sync_run.scrape_owner_task_id == claim.task_id
    )


async def _mark_stale_store_execution(
    session,
    execution: StoreSyncTaskExecution | None,
    detail: str,
) -> None:
    if execution is not None and execution.outcome == "running":
        execution.outcome = "worker_lost"
        execution.error_category = "stale_execution"
        execution.error_detail = detail
        execution.finished_at = datetime.now(UTC)
    await session.commit()


async def _refresh_store_execution_measurement(
    claim: StoreSyncClaim,
    measurement: AttemptMeasurement,
) -> None:
    """Persist full worker occupancy after state/evidence finalization."""

    async with async_session_factory() as session:
        execution = await session.get(
            StoreSyncTaskExecution,
            claim.execution_id,
        )
        if execution is None:
            return
        execution.wall_time_ms = measurement.wall_time_ms
        execution.cpu_time_ms = measurement.cpu_time_ms
        execution.memory_peak_bytes = max(
            execution.memory_peak_bytes,
            measurement.memory_peak_bytes,
        )
        if execution.outcome != "running":
            execution.finished_at = datetime.now(UTC)
        await session.commit()


def _checkpoint_next_page(
    checkpoint: dict[str, object] | None,
    *,
    fallback: int,
) -> int:
    value = (checkpoint or {}).get("next_page")
    try:
        parsed = int(value) if value is not None else fallback
    except (TypeError, ValueError):
        parsed = fallback
    return max(1, fallback, parsed)


def _chunk_reached_page_budget(
    claim: StoreSyncClaim,
    catalog_pages_fetched: int,
) -> bool:
    return (
        claim.page_budget > 0
        and catalog_pages_fetched >= claim.page_budget
    )


def _catalog_boundary(exc: Exception) -> ScraperBoundaryError:
    if isinstance(exc, ScraperBoundaryError):
        return exc
    if isinstance(exc, TerminalCatalogImportError):
        return ScraperBoundaryError(
            ScraperErrorCode.INVALID_INPUT,
            str(exc),
            retryable=False,
        )
    return classify_scraper_exception(exc)


def _product_completeness(product: Product) -> Decimal:
    checks = (
        product.id is not None,
        bool(product.name),
        bool(product.url and product.url.startswith(("https://", "http://"))),
        parse_product_price(product) is not None,
        bool(product.currency),
        bool(product.seller_id or product.seller_name),
    )
    return Decimal(sum(checks)) / Decimal(len(checks))


def _merge_structured_completeness(
    *,
    current: Decimal | None,
    current_count: int,
    added_sum: Decimal,
    added_count: int,
) -> Decimal | None:
    """Merge completeness only for newly persisted immutable snapshots."""

    if current_count < 0 or added_count < 0:
        raise ValueError("completeness counts must be non-negative")
    total_count = current_count + added_count
    if total_count == 0:
        return current
    total = (current or Decimal("0")) * Decimal(current_count) + added_sum
    return (total / Decimal(total_count)).quantize(Decimal("0.000001"))


def _currency_code(value: str | None) -> str:
    raw = (value or "UAH").strip().casefold()
    if raw in {"uah", "грн", "₴", "гривня", "гривень"}:
        return "UAH"
    normalized = raw.upper()
    return normalized[:3] or "UAH"


def _currency_evidence(value: str | None) -> tuple[str, str | None, bool]:
    raw = value.strip() if value is not None else ""
    currency_raw = raw or None
    return _currency_code(currency_raw), currency_raw, currency_raw is None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def structured_product_size(product: Product) -> int:
    """Deterministic structured-output byte estimate used by storage metrics."""

    return len(
        json.dumps(
            product.as_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    )


__all__ = [
    "CatalogImportError",
    "RetryableCatalogImportError",
    "StaleCatalogImportClaim",
    "TerminalCatalogImportError",
    "fail_store_sync_task",
    "import_store_catalog",
    "parse_product_price",
    "structured_product_size",
]
