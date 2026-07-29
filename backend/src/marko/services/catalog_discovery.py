"""Persisted, discovery-only Prom search for owned catalog cards.

This boundary makes live parser output visible in the product UI without
misrepresenting search hits as verified pricing evidence.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID
import zlib

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.core.config import Settings, get_settings
from marko.infrastructure.db.models import (
    CatalogDiscoveryCapture,
    CatalogDiscoveryOffer,
    CatalogDiscoveryRun,
    CrossLink,
    MarketplaceStore,
    ScrapeEvidenceBlob,
    StoreKind,
    WorkspaceStore,
)
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.exceptions import is_canonical_pagination_redirect
from marko.parsers.prom.parser import parse_search
from marko.services.offer_processing import (
    AcceptedCandidate,
    RejectedOffer,
    assess_candidate_source,
    process_offer_candidate,
)
from marko.services.owned_catalog import normalize_catalog_code
from marko.services.pricing_runs import load_tier_coefficients
from marko.services.scrape_runtime import (
    LogicalRequestTrace,
    ScrapeExecutionTrace,
    scrape_execution,
)
from marko.services.scraper_contract import (
    FrozenPromScraperAdapter,
    QueryInput,
    ScrapeOutput,
)
from marko.services.source_access import require_live_prom_marketplace_collection
from metis.pricing import (
    CandidateItem,
    CandidateSelectionConfig,
    CandidateStatus,
    ProductTier,
    ReferenceItem,
    build_category_domain_context,
    check_candidate,
    load_approved_brand_rules,
    load_candidate_selection_config,
    normalize_candidate_oem,
    verdict_histogram,
)


CATALOG_DISCOVERY_CONTRACT_VERSION = "catalog-discovery-v1"


class CatalogDiscoveryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class CatalogDiscoveredOffer:
    discovery_offer_id: UUID
    source_listing_id: str
    seller_id: str
    seller_name: str
    title: str
    url: str
    sku: str | None
    brand: str | None
    sale_price: Decimal
    reference_price: Decimal | None
    currency: str
    measure_unit: str | None
    is_available: bool | None
    title_contains_query: bool
    identity_status: str
    source_confidence: Decimal
    reason_codes: tuple[str, ...]
    selection_status: str
    selection_reason: str
    passed_gates: tuple[str, ...]
    selection_flags: tuple[str, ...]
    selection_details: Mapping[str, object]
    predicted_tier: str
    tier_confidence: Decimal


@dataclass(frozen=True)
class CatalogDiscoverySnapshot:
    run_id: UUID
    collected_at: datetime
    query: str
    status: str
    prom_reported_total: int | None
    retrieved_count: int
    persisted_count: int
    owned_excluded_count: int
    rejected_count: int
    pricing_evidence_count: int
    reference_only_count: int
    rejected_candidate_count: int
    selection_histogram: Mapping[str, int]
    search_pages_fetched: int
    search_page_limit: int
    unfetched_count: int
    coverage_ratio: Decimal | None
    coverage_reason: str | None
    selection_method_version: str | None
    selection_config_sha256: str | None
    brand_rules_dataset_id: str | None
    items: tuple[CatalogDiscoveredOffer, ...]


@dataclass(frozen=True)
class _LiveDiscoveryResult:
    output: ScrapeOutput
    requests: tuple[LogicalRequestTrace, ...]
    parser_outcome: str
    prom_reported_total: int | None


@dataclass(frozen=True)
class _SelectionRuntime:
    config: CandidateSelectionConfig
    reference: ReferenceItem
    owned_seller_ids: frozenset[str]
    confirmed_cross_oems: frozenset[str]
    brand_tiers: Mapping[str, ProductTier]
    brand_rules_dataset_id: str
    brand_rules_sha256: str | None
    # Validated ``(category, tier)`` multipliers. Empty until calibration has
    # run, which keeps every off-level candidate out of the price basis.
    calibrated_premiums: Mapping[tuple[str, ProductTier], Decimal]


def catalog_product_key(
    *,
    sku: str | None,
    oe: str | None,
    brand: str | None,
) -> str:
    normalized_sku = normalize_catalog_code(sku)
    normalized_oe = normalize_catalog_code(oe)
    normalized_brand = normalize_catalog_code(brand)
    if not normalized_sku and not normalized_oe:
        raise CatalogDiscoveryError(
            "CATALOG_DISCOVERY_IDENTIFIER_REQUIRED",
            "Для поиска нужен OE/OEM или артикул товара.",
        )
    payload = json.dumps(
        {
            "sku": normalized_sku,
            "oe": normalized_oe,
            "brand": normalized_brand,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def catalog_discovery_query(*, sku: str | None, oe: str | None) -> str:
    query = normalize_catalog_code(oe) or normalize_catalog_code(sku)
    if not query:
        raise CatalogDiscoveryError(
            "CATALOG_DISCOVERY_IDENTIFIER_REQUIRED",
            "Для поиска нужен OE/OEM или артикул товара.",
        )
    return query


async def collect_catalog_discovery(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    sku: str | None,
    oe: str | None,
    brand: str | None,
    title: str | None = None,
    current_price: Decimal | None = None,
    currency: str | None = None,
    category: str | None = None,
    settings: Settings | None = None,
) -> CatalogDiscoverySnapshot:
    """Run one bounded live search and persist raw evidence plus every outcome."""

    resolved_settings = settings or get_settings()
    require_live_prom_marketplace_collection(resolved_settings)
    query = catalog_discovery_query(sku=sku, oe=oe)
    product_key = catalog_product_key(sku=sku, oe=oe, brand=brand)
    selection_config = load_candidate_selection_config(
        resolve_backend_path(resolved_settings.pricing_candidate_selection_path)
    )
    brand_rules = load_approved_brand_rules(
        optional_backend_path(resolved_settings.pricing_brand_tiers_path)
    )
    dynamic_owned_seller_ids = await _owned_seller_ids(session, workspace_id)
    effective_owned_seller_ids = frozenset(dynamic_owned_seller_ids) | (
        selection_config.own_seller_ids
    )
    confirmed_cross_oems = await _confirmed_cross_oems(
        session,
        workspace_id=workspace_id,
        reference_oem=query,
    )
    reference = ReferenceItem(
        oem=query,
        title=(title or "").strip() or query,
        price=current_price,
        brand=(brand or "").strip() or None,
        category=(category or "").strip() or None,
    )
    selection_runtime = _SelectionRuntime(
        config=selection_config,
        reference=reference,
        owned_seller_ids=effective_owned_seller_ids,
        confirmed_cross_oems=confirmed_cross_oems,
        brand_tiers=brand_rules.tiers,
        brand_rules_dataset_id=brand_rules.dataset_id,
        brand_rules_sha256=brand_rules.source_sha256,
        calibrated_premiums=await _validated_tier_premiums(
            session,
            workspace_id=workspace_id,
            category=reference.category,
        ),
    )
    search_page_limit = resolved_settings.catalog_discovery_max_search_pages
    run = CatalogDiscoveryRun(
        workspace_id=workspace_id,
        product_key=product_key,
        query=query,
        sku=(sku or "").strip() or None,
        oe_norm=normalize_catalog_code(oe) or None,
        brand=(brand or "").strip() or None,
        reference_title=reference.title,
        reference_price=reference.price,
        reference_currency=(currency or "").strip().upper()[:3] or None,
        reference_category=reference.category,
        search_page_limit=search_page_limit,
        selection_method_version=selection_config.method_version,
        selection_config_sha256=selection_config.source_sha256,
        brand_rules_dataset_id=brand_rules.dataset_id,
        brand_rules_sha256=brand_rules.source_sha256,
        status="running",
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    # Read the identifier out while the instance is still loaded: the rollback
    # in the failure path expires every attribute, and touching ``run.id``
    # afterwards triggers a lazy refresh outside the async context, which
    # raises MissingGreenlet and loses the real error along with the row's
    # "failed" status.
    run_id = run.id

    try:
        live = await asyncio.to_thread(
            _collect_live,
            query,
            resolved_settings,
            search_page_limit=search_page_limit,
        )
        await _persist_live_result(
            session,
            run=run,
            live=live,
            selection=selection_runtime,
        )
    except Exception as exc:
        await session.rollback()
        failed = await session.get(CatalogDiscoveryRun, run_id)
        if failed is not None:
            failed.status = "failed"
            failed.error_code = str(getattr(exc, "code", type(exc).__name__))[:100]
            failed.error_detail = str(exc)[:2000]
            failed.completed_at = datetime.now(UTC)
            await session.commit()
        if isinstance(exc, CatalogDiscoveryError):
            raise
        raise CatalogDiscoveryError(
            "CATALOG_DISCOVERY_FAILED",
            f"Не удалось собрать объявления Prom: {type(exc).__name__}: {exc}",
        ) from exc

    snapshot = await get_catalog_discovery_run(
        session,
        workspace_id=workspace_id,
        run_id=run_id,
    )
    if snapshot is None:
        raise CatalogDiscoveryError(
            "CATALOG_DISCOVERY_PERSISTENCE_FAILED",
            "Сбор завершился, но сохранённый snapshot не найден.",
        )
    return snapshot


async def latest_catalog_discovery(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    sku: str | None,
    oe: str | None,
    brand: str | None,
) -> CatalogDiscoverySnapshot | None:
    try:
        product_key = catalog_product_key(sku=sku, oe=oe, brand=brand)
    except CatalogDiscoveryError:
        return None
    run = await session.scalar(
        select(CatalogDiscoveryRun)
        .where(
            CatalogDiscoveryRun.workspace_id == workspace_id,
            CatalogDiscoveryRun.product_key == product_key,
            CatalogDiscoveryRun.status == "completed",
        )
        .order_by(
            CatalogDiscoveryRun.completed_at.desc(),
            CatalogDiscoveryRun.id.desc(),
        )
        .limit(1)
    )
    if run is None:
        return None
    return await _snapshot_for_run(session, run)


async def get_catalog_discovery_run(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    run_id: UUID,
) -> CatalogDiscoverySnapshot | None:
    run = await session.scalar(
        select(CatalogDiscoveryRun).where(
            CatalogDiscoveryRun.id == run_id,
            CatalogDiscoveryRun.workspace_id == workspace_id,
        )
    )
    if run is None or run.status != "completed":
        return None
    return await _snapshot_for_run(session, run)


def usable_search_requests(
    requests: tuple[LogicalRequestTrace, ...],
) -> tuple[LogicalRequestTrace, ...]:
    """Return the requests that carry evidence, rejecting genuine failures.

    Prom answers a page past the end of its own reported total with a 3xx to
    the canonical search URL. The gateway stops there deliberately, so that
    trailing probe is an end-of-pagination marker rather than an unfinished
    required request; failing the whole run on it discarded every page already
    fetched. Any other unfinished request is still fatal, and a run in which
    nothing succeeded has no evidence at all.
    """

    usable = tuple(
        request
        for request in requests
        if request.outcome in {"success", "replayed"}
        and request.raw_body is not None
        and request.response_status_code is not None
    )
    usable_ids = {id(request) for request in usable}
    tolerated = tuple(
        request
        for request in requests
        if id(request) not in usable_ids
        and request.error_category == "upstream_3xx"
        and is_canonical_pagination_redirect(
            status_code=request.response_status_code,
            request_url=request.prepared_url,
            redirect_location=request.response_redirect_location,
            page_num=request.sequence_no,
        )
        and request.raw_body is not None
        and request.content_sha256 is not None
    )
    if not usable or len(usable) + len(tolerated) != len(requests):
        raise CatalogDiscoveryError(
            "CATALOG_DISCOVERY_HTTP_INCOMPLETE",
            "Не все обязательные поисковые запросы завершились успешно.",
        )
    return usable


def _collect_live(
    query: str,
    settings: Settings,
    *,
    search_page_limit: int,
) -> _LiveDiscoveryResult:
    scrape_input = QueryInput.build(query, language="ua")
    trace = ScrapeExecutionTrace(
        item_kind=CATALOG_DISCOVERY_CONTRACT_VERSION,
        execution_no=1,
        live_request_gate=lambda: require_live_prom_marketplace_collection(settings),
    )
    config = ScrapeConfig(
        delay=settings.pricing_scraper_request_delay_seconds,
        delay_jitter=settings.pricing_scraper_request_jitter_seconds,
        timeout=settings.pricing_scraper_http_timeout_seconds,
        max_attempts=max(1, settings.pricing_scraper_http_max_attempts),
        max_search_pages=search_page_limit,
        max_sellers=max(1, settings.pricing_scraper_max_sellers),
    )
    try:
        with scrape_execution(trace):
            output = FrozenPromScraperAdapter(config).extract(scrape_input)
        requests = tuple(trace.drain_completed_requests())
    finally:
        trace.close()
    if not requests:
        raise CatalogDiscoveryError(
            "CATALOG_DISCOVERY_RAW_CAPTURE_MISSING",
            "Парсер вернул результат без HTTP trace.",
        )
    usable = usable_search_requests(requests)
    output_payload = output.comparison_payload
    parser_outcome = str(output_payload.get("acquisition_outcome") or "UNKNOWN")
    totals: list[int] = []
    for request in usable:
        assert request.raw_body is not None
        encoding = request.response_encoding or "utf-8"
        page = parse_search(
            request.raw_body.decode(encoding, errors="replace"),
            "ua",
        )
        if page.total is not None:
            totals.append(page.total)
    return _LiveDiscoveryResult(
        output=output,
        requests=requests,
        parser_outcome=parser_outcome,
        prom_reported_total=max(totals) if totals else None,
    )


async def _persist_live_result(
    session: AsyncSession,
    *,
    run: CatalogDiscoveryRun,
    live: _LiveDiscoveryResult,
    selection: _SelectionRuntime,
) -> None:
    # ``CatalogDiscoveryRun.request_count`` is exposed to the API as
    # ``search_pages_fetched`` and therefore keeps its original meaning:
    # successfully fetched result pages. Terminal pagination probes are still
    # persisted below as captures and counted by HTTP telemetry, but must not
    # turn a canonical upstream gap into a false SEARCH_PAGE_HARD_CAP.
    successful_request_count = len(usable_search_requests(live.requests))

    for request in live.requests:
        assert request.raw_body is not None
        content_sha256 = hashlib.sha256(request.raw_body).hexdigest()
        if request.content_sha256 != content_sha256:
            raise CatalogDiscoveryError(
                "CATALOG_DISCOVERY_RAW_HASH_MISMATCH",
                "SHA-256 сырого ответа не совпадает с HTTP trace.",
            )
        blob = await session.scalar(
            select(ScrapeEvidenceBlob).where(
                ScrapeEvidenceBlob.content_sha256 == content_sha256
            )
        )
        if blob is None:
            compressed = zlib.compress(request.raw_body, level=9)
            blob = ScrapeEvidenceBlob(
                content_sha256=content_sha256,
                content_zlib=compressed,
                raw_size_bytes=len(request.raw_body),
                stored_size_bytes=len(compressed),
                content_type=request.response_content_type,
                encoding=request.response_encoding,
            )
            session.add(blob)
            await session.flush()
        session.add(
            CatalogDiscoveryCapture(
                discovery_run_id=run.id,
                evidence_blob_id=blob.id,
                sequence_no=request.sequence_no,
                request_kind=request.request_kind,
                prepared_url=request.prepared_url,
                status_code=request.response_status_code or 0,
                attempts_total=len(request.attempts),
                latency_ms=request.latency_ms,
                raw_size_bytes=len(request.raw_body),
                content_sha256=content_sha256,
            )
        )

    accepted_by_listing: dict[str, tuple[AcceptedCandidate, Decimal]] = {}
    rejected_count = 0
    for index, raw_offer in enumerate(live.output.candidate_records):
        processed = process_offer_candidate(raw_offer, fallback_index=index)
        if isinstance(processed, RejectedOffer):
            rejected_count += 1
            continue
        assessment = assess_candidate_source(
            processed,
            raw_capture_verified=True,
            parser_contract_verified=True,
        )
        accepted_by_listing.setdefault(
            processed.source_listing_id,
            (processed, assessment.value),
        )

    # The majority vote needs the whole result set, so the category context is
    # derived once here and passed in; check_candidate stays per-candidate pure.
    category_context = build_category_domain_context(
        [
            _category_path(candidate.product)
            for candidate, _confidence in accepted_by_listing.values()
        ],
        selection.config.category_domain,
    )

    owned_excluded_count = 0
    verdicts = []
    for candidate, source_confidence in accepted_by_listing.values():
        product = candidate.product
        seller_id = str(product.get("seller_id") or "").strip()
        is_owned = bool(seller_id and seller_id in selection.owned_seller_ids)
        if is_owned:
            owned_excluded_count += 1
        title = str(product.get("name") or "").strip()
        sku = str(product.get("sku") or "").strip() or None
        title_contains_query = run.query in normalize_catalog_code(title)
        sku_contains_query = run.query in normalize_catalog_code(sku)
        identity_status = (
            "QUERY_TOKEN_PRESENT"
            if title_contains_query or sku_contains_query
            else "SEARCH_RESULT_UNVERIFIED"
        )
        reason_codes = ["DISCOVERY_ONLY_NOT_PRICING_EVIDENCE"]
        if identity_status == "QUERY_TOKEN_PRESENT":
            reason_codes.append("QUERY_TOKEN_PRESENT_REQUIRES_VERIFICATION")
        else:
            reason_codes.append("QUERY_TOKEN_NOT_PRESENT")
        if is_owned:
            reason_codes.append("OWNED_SELLER_EXCLUDED")
        verdict = check_candidate(
            selection.reference,
            CandidateItem(
                seller_id=seller_id,
                seller_name=str(product.get("seller_name") or "Неизвестный продавец"),
                title=title,
                description=(
                    str(product.get("description")).strip()
                    if product.get("description")
                    else None
                ),
                article_field=sku,
                brand=str(product.get("brand") or "").strip() or None,
                price=candidate.price,
                condition=(
                    str(product.get("condition")).strip()
                    if product.get("condition")
                    else None
                ),
                category_id=_category_id(product),
                category_path=_category_path(product),
            ),
            selection.config,
            owned_seller_ids=selection.owned_seller_ids,
            confirmed_cross_oems=selection.confirmed_cross_oems,
            brand_tiers=selection.brand_tiers,
            category_context=category_context,
            calibrated_premiums=selection.calibrated_premiums,
        )
        verdicts.append(verdict)
        reason_codes.extend(
            (
                f"CANDIDATE_SELECTION_{verdict.status.value}",
                verdict.reason,
            )
        )
        session.add(
            CatalogDiscoveryOffer(
                discovery_run_id=run.id,
                raw_offer_index=candidate.raw_offer_index,
                source_listing_id=candidate.source_listing_id,
                seller_id=seller_id,
                seller_name=str(product.get("seller_name") or "Неизвестный продавец")[
                    :255
                ],
                title=title or "Без названия",
                url=str(product.get("url") or "").strip(),
                sku=sku,
                brand=str(product.get("brand") or "").strip() or None,
                sale_price=candidate.price,
                reference_price=candidate.reference_price,
                currency=str(product.get("currency") or "UAH").strip().upper()[:3],
                measure_unit=(
                    str(product.get("measure_unit") or "").strip()[:80] or None
                ),
                is_available=(
                    product.get("is_available")
                    if isinstance(product.get("is_available"), bool)
                    else None
                ),
                is_owned=is_owned,
                title_contains_query=title_contains_query,
                identity_status=identity_status,
                source_confidence=source_confidence,
                reason_codes=list(dict.fromkeys(reason_codes)),
                selection_status=verdict.status.value,
                selection_reason=verdict.reason,
                passed_gates=list(verdict.passed_gates),
                selection_flags=list(verdict.flags),
                selection_details=dict(verdict.details),
                predicted_tier=verdict.predicted_tier.value,
                tier_confidence=verdict.tier_confidence,
                raw_snapshot=dict(product),
            )
        )

    histogram = verdict_histogram(verdicts)
    reported_total = live.prom_reported_total
    retrieved_count = len(live.output.candidate_records)
    unfetched_count, coverage_ratio, coverage_reason = _coverage_summary(
        reported_total=reported_total,
        retrieved_count=retrieved_count,
        request_count=successful_request_count,
        search_page_limit=run.search_page_limit,
    )

    run.status = "completed"
    run.parser_outcome = live.parser_outcome
    run.prom_reported_total = reported_total
    run.request_count = successful_request_count
    run.retrieved_count = retrieved_count
    run.persisted_count = len(accepted_by_listing)
    run.rejected_count = rejected_count
    run.owned_excluded_count = owned_excluded_count
    run.pricing_evidence_count = sum(
        verdict.status is CandidateStatus.PRICING_EVIDENCE for verdict in verdicts
    )
    run.reference_only_count = sum(
        verdict.status is CandidateStatus.REFERENCE_ONLY for verdict in verdicts
    )
    run.rejected_candidate_count = sum(
        verdict.status is CandidateStatus.REJECTED for verdict in verdicts
    )
    run.selection_histogram = histogram
    run.unfetched_count = unfetched_count
    run.coverage_ratio = coverage_ratio
    run.coverage_reason = coverage_reason
    run.completed_at = datetime.now(UTC)
    await session.commit()


def _coverage_summary(
    *,
    reported_total: int | None,
    retrieved_count: int,
    request_count: int,
    search_page_limit: int,
) -> tuple[int, Decimal | None, str]:
    unfetched_count = max(0, (reported_total or retrieved_count) - retrieved_count)
    coverage_ratio = (
        (Decimal(retrieved_count) / Decimal(reported_total)).quantize(
            Decimal("0.000001")
        )
        if reported_total is not None and reported_total > 0
        else None
    )
    if reported_total is None:
        reason = "PROM_TOTAL_UNKNOWN"
    elif unfetched_count and request_count >= search_page_limit:
        reason = "SEARCH_PAGE_HARD_CAP"
    elif unfetched_count:
        reason = "UPSTREAM_RESULT_GAP"
    else:
        reason = "FULL_REPORTED_RESULT_SET"
    return unfetched_count, coverage_ratio, reason


async def _owned_seller_ids(
    session: AsyncSession,
    workspace_id: UUID,
) -> set[str]:
    return {
        str(value).strip()
        for value in (
            await session.scalars(
                select(MarketplaceStore.external_id)
                .join(WorkspaceStore, WorkspaceStore.store_id == MarketplaceStore.id)
                .where(
                    WorkspaceStore.workspace_id == workspace_id,
                    WorkspaceStore.kind == StoreKind.owned,
                )
            )
        ).all()
        if str(value).strip()
    }


async def _validated_tier_premiums(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    category: str | None,
) -> Mapping[tuple[str, ProductTier], Decimal]:
    """Read the validated baseline coefficients for the reference category.

    Only validated ones are returned, and the key is normalized the same way
    the gate normalizes it, so a category that differs by case or padding does
    not silently look uncalibrated.
    """

    normalized = (category or "").strip()
    if not normalized:
        return {}
    coefficients = await load_tier_coefficients(
        session,
        workspace_id=workspace_id,
        category=normalized,
    )
    return {
        (key[0].strip().casefold(), key[1]): coefficient.multiplier
        for key, coefficient in coefficients.items()
        if coefficient.validated
    }


async def _confirmed_cross_oems(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    reference_oem: str,
) -> frozenset[str]:
    normalized_reference = normalize_candidate_oem(reference_oem)
    if not normalized_reference:
        return frozenset()
    rows = list(
        (
            await session.execute(
                select(CrossLink.our_oem_norm, CrossLink.extracted_oem_norm).where(
                    CrossLink.workspace_id == workspace_id,
                    CrossLink.validation_status == "CONFIRMED",
                    or_(
                        CrossLink.our_oem_norm == normalized_reference,
                        CrossLink.extracted_oem_norm == normalized_reference,
                    ),
                )
            )
        ).all()
    )
    equivalents: set[str] = set()
    for our_oem, extracted_oem in rows:
        for value in (our_oem, extracted_oem):
            normalized = normalize_candidate_oem(value)
            if normalized and normalized != normalized_reference:
                equivalents.add(normalized)
    return frozenset(equivalents)


def _category_id(product: Mapping[str, Any]) -> int | None:
    """Read Prom's leaf category id, tolerating absent or non-numeric values."""

    value = product.get("category_id")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _category_path(product: Mapping[str, Any]) -> tuple[int, ...]:
    """Read Prom's root-to-leaf category ancestry as integers.

    Retained snapshots predating the field, and any element that is not a
    plain integer, yield an empty path so the gate fails open instead of
    inventing a domain.
    """

    raw = product.get("category_ids")
    if not isinstance(raw, (list, tuple)):
        return ()
    path: list[int] = []
    for element in raw:
        if isinstance(element, bool) or not isinstance(element, (int, str)):
            return ()
        try:
            path.append(int(element))
        except (TypeError, ValueError):
            return ()
    return tuple(path)


def resolve_backend_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_file():
        return path
    if not path.is_absolute():
        backend_root = Path(__file__).resolve().parents[3]
        candidate = backend_root / path
        if candidate.is_file():
            return candidate
    return path


def optional_backend_path(raw_path: str) -> Path | None:
    if not raw_path.strip():
        return None
    return resolve_backend_path(raw_path)


async def _snapshot_for_run(
    session: AsyncSession,
    run: CatalogDiscoveryRun,
) -> CatalogDiscoverySnapshot:
    offers = list(
        (
            await session.scalars(
                select(CatalogDiscoveryOffer)
                .where(
                    CatalogDiscoveryOffer.discovery_run_id == run.id,
                    CatalogDiscoveryOffer.is_owned.is_(False),
                )
                .order_by(
                    case(
                        (
                            CatalogDiscoveryOffer.selection_status
                            == "PRICING_EVIDENCE",
                            0,
                        ),
                        (
                            CatalogDiscoveryOffer.selection_status == "REFERENCE_ONLY",
                            1,
                        ),
                        else_=2,
                    ),
                    CatalogDiscoveryOffer.title_contains_query.desc(),
                    CatalogDiscoveryOffer.is_available.desc().nullslast(),
                    CatalogDiscoveryOffer.sale_price,
                    CatalogDiscoveryOffer.raw_offer_index,
                )
            )
        ).all()
    )
    return CatalogDiscoverySnapshot(
        run_id=run.id,
        collected_at=run.completed_at or run.created_at,
        query=run.query,
        status=run.status,
        prom_reported_total=run.prom_reported_total,
        retrieved_count=run.retrieved_count,
        persisted_count=run.persisted_count,
        owned_excluded_count=run.owned_excluded_count,
        rejected_count=run.rejected_count,
        pricing_evidence_count=run.pricing_evidence_count,
        reference_only_count=run.reference_only_count,
        rejected_candidate_count=run.rejected_candidate_count,
        selection_histogram=dict(run.selection_histogram or {}),
        search_pages_fetched=run.request_count,
        search_page_limit=run.search_page_limit,
        unfetched_count=run.unfetched_count,
        coverage_ratio=run.coverage_ratio,
        coverage_reason=run.coverage_reason,
        selection_method_version=run.selection_method_version,
        selection_config_sha256=run.selection_config_sha256,
        brand_rules_dataset_id=run.brand_rules_dataset_id,
        items=tuple(
            CatalogDiscoveredOffer(
                discovery_offer_id=offer.id,
                source_listing_id=offer.source_listing_id,
                seller_id=offer.seller_id,
                seller_name=offer.seller_name,
                title=offer.title,
                url=offer.url,
                sku=offer.sku,
                brand=offer.brand,
                sale_price=offer.sale_price,
                reference_price=offer.reference_price,
                currency=offer.currency,
                measure_unit=offer.measure_unit,
                is_available=offer.is_available,
                title_contains_query=offer.title_contains_query,
                identity_status=offer.identity_status,
                source_confidence=offer.source_confidence,
                reason_codes=tuple(offer.reason_codes),
                selection_status=offer.selection_status,
                selection_reason=offer.selection_reason,
                passed_gates=tuple(offer.passed_gates),
                selection_flags=tuple(offer.selection_flags),
                selection_details=dict(offer.selection_details),
                predicted_tier=offer.predicted_tier,
                tier_confidence=offer.tier_confidence,
            )
            for offer in offers
        ),
    )


__all__ = [
    "CATALOG_DISCOVERY_CONTRACT_VERSION",
    "CatalogDiscoveredOffer",
    "CatalogDiscoveryError",
    "CatalogDiscoverySnapshot",
    "catalog_discovery_query",
    "catalog_product_key",
    "collect_catalog_discovery",
    "get_catalog_discovery_run",
    "latest_catalog_discovery",
    "optional_backend_path",
    "resolve_backend_path",
    "usable_search_requests",
]
