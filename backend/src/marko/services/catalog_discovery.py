"""Persisted, discovery-only Prom search for owned catalog cards.

This boundary makes live parser output visible in the product UI without
misrepresenting search hits as verified pricing evidence.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
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
    CatalogItem,
    CatalogIdentityLink,
    MarketplaceStore,
    ScrapeEvidenceBlob,
    StoreKind,
    WorkspaceStore,
)
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.exceptions import is_self_describing_pagination_redirect
from marko.parsers.prom.parser import parse_search
from marko.services.scrape_coverage import coverage_summary as _coverage_summary
from marko.services.offer_processing import (
    AcceptedCandidate,
    RejectedOffer,
    assess_candidate_source,
    process_offer_candidate,
)
from marko.services.catalog_identity_safety import (
    catalog_identity_pair_has_safe_shape,
    confirmed_catalog_identity_conditions,
    is_internal_catalog_code,
)
from marko.services.owned_catalog import canonical_catalog_sku, normalize_catalog_code
from marko.services.pricing_runs import (
    customer_identity_query_from_fields,
    load_tier_coefficients,
)


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
from marko.services.semantic_candidate_gate import (
    SEMANTIC_PRICING_GATE_VERSION,
    apply_semantic_pricing_gate,
)
from metis.pricing.raise_policy import (
    RaisePolicyConfigError,
    RaiseStrategy,
    load_raise_policy,
)
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


# Only identities that have been resolved by the importer/reparser may
# participate in private-code resolution.  ``oe_norm`` is intentionally
# populated on some MPN_ONLY legacy rows with a private KEMP shelf code; an
# UNRESOLVED row must never be allowed to influence the consensus query merely
# because that code happens to match the probe.
_MATCHABLE_CATALOG_IDENTITY_STATUSES = ("OE_CONFIRMED", "MPN_ONLY")


CATALOG_DISCOVERY_CONTRACT_VERSION = "catalog-discovery-v1"
_SHORT_NUMERIC_IDENTITY_MAX_DIGITS = 6
_IDENTIFIER_LABEL_RE = re.compile(
    r"(?:\b(?:oe|oem|art|article|артикул|арт)\b|"
    r"\bpart\s+(?:no|number)\b|"
    r"\bкод\s+(?:запчасти|запчастини|виробника|производителя)\b|[#№])",
    re.IGNORECASE,
)
_IDENTIFIER_BOUNDARY_CHARS = r"A-Za-zА-Яа-яЇїІіЄєҐґ0-9"


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
    # Candidate-native namespaces are exposed for operator verification.  They
    # are read from the immutable raw snapshot, never reconstructed from our
    # search query, so the UI cannot confuse intent with extracted evidence.
    mpn: str | None = None
    oe_raw: str | None = None
    part_numbers: tuple[str, ...] = ()


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
    # True when the deployment's pricing strategy targets the cheapest
    # comparable offer regardless of level, which retires the two tier gates.
    tier_agnostic: bool


def tier_agnostic_pricing(settings: Settings) -> bool:
    """Read the tier-agnostic decision from the deployment's pricing strategy.

    The strategy file is the single source of truth: the owner's choice lives in
    ``raise_policy.yaml`` because it is a pricing decision, and re-declaring it
    in the comparability config would let the collector and the pricing engine
    classify the same offer differently.

    An unreadable strategy stops the run instead of defaulting.  Both fallbacks
    are wrong in a way that is hard to notice later: assuming tier-agnostic
    would admit unconverted cross-level prices, and assuming the opposite would
    quietly file thousands of comparable offers as ``REFERENCE_ONLY`` and look
    like poor market coverage rather than a broken config.
    """

    configured = settings.pricing_raise_policy_path.strip()
    if not configured:
        return False
    try:
        policy = load_raise_policy(resolve_backend_path(configured))
    except RaisePolicyConfigError as exc:
        raise CatalogDiscoveryError(
            "CATALOG_DISCOVERY_RAISE_POLICY_INVALID",
            f"Стратегия цен не читается, сбор остановлен: {exc}",
        ) from exc
    return policy.strategy is RaiseStrategy.BUDGET_FLOOR and policy.tier_agnostic


def catalog_product_key(
    *,
    sku: str | None,
    oe: str | None,
    brand: str | None,
    mpn: str | None = None,
) -> str:
    normalized_sku = normalize_catalog_code(sku)
    normalized_oe = normalize_catalog_code(oe)
    normalized_mpn = normalize_catalog_code(mpn)
    normalized_brand = normalize_catalog_code(brand)
    if not normalized_sku and not normalized_oe and not normalized_mpn:
        raise CatalogDiscoveryError(
            "CATALOG_DISCOVERY_IDENTIFIER_REQUIRED",
            "Для поиска нужен OE/OEM, MPN или артикул товара.",
        )
    payload = json.dumps(
        {
            "sku": normalized_sku,
            "oe": normalized_oe,
            "mpn": normalized_mpn,
            "brand": normalized_brand,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def catalog_discovery_query(
    *,
    sku: str | None,
    oe: str | None,
    mpn: str | None = None,
) -> str:
    """Pick the identifier to search the marketplace with.

    WP-2 makes the empty-``oe`` branch the common case rather than the odd one:
    a position whose article belongs to a component supplier now closes as
    ``MPN_ONLY`` with no ``oe_norm`` at all, where before the article was
    written into ``oe`` and searched as though it were one.  Falling back to the
    article is right — an MPN finds the same supplier part on the market — but
    it must be a stated choice, because the two searches answer different
    questions and only the OE branch can find the vehicle maker's own part.
    Which branch ran is recoverable from the offer's ``identity_status``
    downstream; it is deliberately not encoded in the query string, which stays
    a plain search term.
    """

    query = (
        normalize_catalog_code(oe)
        or normalize_catalog_code(mpn)
        or normalize_catalog_code(sku)
    )
    if not query:
        raise CatalogDiscoveryError(
            "CATALOG_DISCOVERY_IDENTIFIER_REQUIRED",
            "Для поиска нужен OE/OEM, MPN или артикул товара.",
        )
    return query


def catalog_discovery_search_context(
    *,
    title: str | None,
    brand: str | None,
    category: str | None,
) -> str | None:
    """Build bounded retrieval context without changing the identity query.

    Prom reuses short numeric manufacturer numbers across unrelated domains.
    The exact number remains the only identity key; this context is merely an
    additive second retrieval pass used by ``PromGateway`` for ambiguous
    4--6-digit queries.  Keep it deterministic and bounded so it is safe to
    freeze in the query input hash and never becomes an unbounded title search.
    """

    parts = tuple(
        value.strip()
        for value in (title, brand, category)
        if isinstance(value, str) and value.strip()
    )
    if not parts:
        return None
    return " ".join(parts)[:255]


def _catalog_identity_query_from_rows(rows: list[CatalogItem]) -> str | None:
    """Return one consensus query from matching imported catalog rows.

    Duplicate rows are expected in the customer's export.  A disagreement is
    not expected, and must not be resolved by whichever row the database
    happens to return first: that would make the discovery target
    nondeterministic and could search a different part.
    """

    queries = {
        query
        for item in rows
        if (
            query := customer_identity_query_from_fields(
                identity_status=item.identity_status,
                oe_norm=item.oe_norm,
                mpn_norm=item.mpn_norm,
                part_numbers_norm=tuple(item.part_numbers_norm or ()),
            )
        )
    }
    return next(iter(queries)) if len(queries) == 1 else None


async def _resolve_private_catalog_discovery_query(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    sku: str | None,
    oe: str | None,
    brand: str | None,
    requested_query: str,
    mpn: str | None = None,
) -> str:
    """Resolve a private KEMP input to a public MPN/characteristic number.

    The live catalog UI often knows only the seller's private SKU (for
    example ``776414``).  Searching that value on Prom is both noisy and
    semantically wrong.  When the imported customer catalog contains the
    same private key, use its frozen identity classification instead.  This
    path is deliberately limited to private probes; an operator-supplied
    public OE keeps the ordinary direct-search behavior.
    """

    normalized_mpn = normalize_catalog_code(mpn)
    # An explicitly supplied *public* manufacturer number is already the
    # retrieval key.  A private KEMP shelf code can also arrive in this field
    # after a loose XLS mapping, however; it must take the same resolver path
    # as a private SKU/OE and may never be sent to Prom as public identity.
    if normalized_mpn and not is_internal_catalog_code(normalized_mpn):
        return requested_query

    probes = tuple(
        dict.fromkeys(
            value
            for value in (
                normalize_catalog_code(oe),
                normalized_mpn,
                canonical_catalog_sku(sku, brand),
                normalize_catalog_code(sku),
            )
            if value
        )
    )
    if not any(is_internal_catalog_code(value) for value in probes):
        return requested_query

    raw_sku = (sku or "").strip()
    raw_oe = (oe or "").strip()
    predicates = [
        CatalogItem.oe_norm.in_(probes),
        CatalogItem.mpn_norm.in_(probes),
    ]
    if raw_sku:
        predicates.append(CatalogItem.sku == raw_sku)
    if raw_oe:
        predicates.append(CatalogItem.oe_raw == raw_oe)
    rows = list(
        (
            await session.scalars(
                select(CatalogItem)
                .where(
                    CatalogItem.workspace_id == workspace_id,
                    CatalogItem.identity_status.in_(
                        _MATCHABLE_CATALOG_IDENTITY_STATUSES
                    ),
                    or_(*predicates),
                )
                .order_by(CatalogItem.source_row, CatalogItem.id)
                .limit(64)
            )
        ).all()
    )
    resolved = _catalog_identity_query_from_rows(rows)
    if resolved:
        return resolved
    if not rows:
        detail = "для приватного кода не найдена строка импортированного каталога"
        code = "CATALOG_DISCOVERY_IDENTITY_UNRESOLVED"
    else:
        detail = "строки импортированного каталога дают неоднозначный публичный номер"
        code = "CATALOG_DISCOVERY_IDENTITY_AMBIGUOUS"
    raise CatalogDiscoveryError(
        code,
        f"Нельзя безопасно искать {requested_query}: {detail}.",
    )


async def collect_catalog_discovery(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    sku: str | None,
    oe: str | None,
    brand: str | None,
    mpn: str | None = None,
    title: str | None = None,
    current_price: Decimal | None = None,
    currency: str | None = None,
    category: str | None = None,
    settings: Settings | None = None,
) -> CatalogDiscoverySnapshot:
    """Run one bounded live search and persist raw evidence plus every outcome."""

    resolved_settings = settings or get_settings()
    require_live_prom_marketplace_collection(resolved_settings)
    requested_query = catalog_discovery_query(sku=sku, oe=oe, mpn=mpn)
    query = await _resolve_private_catalog_discovery_query(
        session,
        workspace_id=workspace_id,
        sku=sku,
        oe=oe,
        mpn=mpn,
        brand=brand,
        requested_query=requested_query,
    )
    product_key = catalog_product_key(sku=sku, oe=oe, mpn=mpn, brand=brand)
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
        tier_agnostic=tier_agnostic_pricing(resolved_settings),
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
            excluded_seller_ids=effective_owned_seller_ids,
            search_context=catalog_discovery_search_context(
                title=title,
                brand=brand,
                category=category,
            ),
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
    mpn: str | None = None,
) -> CatalogDiscoverySnapshot | None:
    try:
        product_key = catalog_product_key(sku=sku, oe=oe, mpn=mpn, brand=brand)
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
    """Return the search pages that carry evidence, rejecting genuine failures.

    Prom answers a page past the end of its own reported total with a 3xx to
    the canonical search URL. The gateway stops there deliberately, so that
    trailing probe is an end-of-pagination marker rather than an unfinished
    required request; failing the whole run on it discarded every page already
    fetched. Any other unfinished search page is still fatal, and a run in
    which nothing succeeded has no evidence at all.

    Competitor product cards are deliberately not judged here. The gateway
    degrades a broken card and keeps its listing, so one 404 must not discard
    a whole run — the more so now that the detail budget is unbounded and a
    run fetches every non-owned row. Excluding them also keeps the returned
    count meaning what its consumers read it as: search pages fetched, the
    number ``_coverage_summary`` compares against the page cap.
    """

    pages = tuple(
        request for request in requests if request.request_kind == "search_page"
    )
    usable = tuple(
        request
        for request in pages
        if request.outcome in {"success", "replayed"}
        and request.raw_body is not None
        and request.response_status_code is not None
    )
    usable_ids = {id(request) for request in usable}
    tolerated = tuple(
        request
        for request in pages
        if id(request) not in usable_ids
        and is_self_describing_pagination_redirect(
            status_code=request.response_status_code,
            request_url=request.prepared_url,
            redirect_location=request.response_redirect_location,
        )
        and request.raw_body is not None
        and request.content_sha256 is not None
    )
    if not usable or len(usable) + len(tolerated) != len(pages):
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
    excluded_seller_ids: frozenset[str] = frozenset(),
    search_context: str | None = None,
) -> _LiveDiscoveryResult:
    scrape_input = QueryInput.build(
        query,
        language="ua",
        search_context=search_context,
    )
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
        max_oe_page_pages=max(1, settings.pricing_scraper_max_oe_page_pages),
        max_sellers=max(1, settings.pricing_scraper_max_sellers),
        max_detail_cards=max(0, settings.pricing_scraper_max_detail_cards),
    )
    try:
        with scrape_execution(trace):
            output = FrozenPromScraperAdapter(
                config,
                excluded_seller_ids=excluded_seller_ids,
            ).extract(scrape_input)
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
    rejected_histogram: dict[str, int] = {}
    for index, raw_offer in enumerate(live.output.candidate_records):
        processed = process_offer_candidate(raw_offer, fallback_index=index)
        if isinstance(processed, RejectedOffer):
            rejected_count += 1
            key = f"INPUT_{processed.outcome_code.value}:REJECTED"
            rejected_histogram[key] = rejected_histogram.get(key, 0) + 1
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
        title_contains_query = _title_carries_query(title, run.query)
        # Structured SKU, MPN, labelled part numbers and native OE are identity
        # namespaces.  Do not
        # collapse them to ``sku or mpn``: a seller can expose a different
        # internal SKU alongside the exact manufacturer number we searched.
        # Every namespace uses exact normalized equality; substring matching
        # would make 123456 appear in the unrelated 1234567 listing.
        structured_identity_field = _structured_identity_field(product, run.query)
        identity_status = (
            "QUERY_TOKEN_PRESENT"
            if title_contains_query or structured_identity_field is not None
            else "SEARCH_RESULT_UNVERIFIED"
        )
        reason_codes = ["DISCOVERY_ONLY_NOT_PRICING_EVIDENCE"]
        if structured_identity_field is not None:
            reason_codes.append(f"STRUCTURED_{structured_identity_field}_MATCH")
        if title_contains_query:
            reason_codes.append("QUERY_TOKEN_PRESENT_REQUIRES_VERIFICATION")
        if identity_status != "QUERY_TOKEN_PRESENT":
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
                article_fields=_candidate_article_fields(product),
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
            tier_agnostic=selection.tier_agnostic,
        )
        verdict = apply_semantic_pricing_gate(
            verdict,
            reference=selection.reference,
            candidate={
                **dict(product),
                "title": title,
                "description": (
                    str(product.get("description")).strip()
                    if product.get("description")
                    else None
                ),
                "brand": str(product.get("brand") or "").strip() or None,
                "category": product.get("category")
                or product.get("category_name")
                or product.get("category_title")
                or "",
            },
            # Discovery may expose a candidate for operator review, but it is
            # not the persisted market-observation path.  Require the same
            # commercial fields here as the pricing boundary so a future
            # caller cannot mistake a bare search hit for a unit-normalized
            # price observation.
            require_pricing_completeness=True,
        )
        # A catalog discovery run is deliberately a retrieval/diagnostic
        # surface.  Even a candidate that passes the deterministic gates is
        # not yet a pricing observation: it has no frozen observation row,
        # seller/provenance admission, or recommendation membership.  Keep
        # the original semantic gate in ``selection_details`` for audit, but
        # fail closed at the discovery boundary.
        verdict = _discovery_only_verdict(verdict)
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
    # Rejected payloads have no safe price/listing row to persist, but their
    # outcome must remain visible in the run accounting.  Otherwise malformed
    # offers silently disappear and the operator cannot distinguish a clean
    # market from parser/data loss.
    for key, count in rejected_histogram.items():
        histogram[key] = count
    histogram = dict(sorted(histogram.items()))
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


def _title_carries_query(title: str | None, query: str) -> bool:
    """Return true only for an identifier-shaped title occurrence.

    Prom search retrieval is intentionally broad, but the discovery flag is
    shown as evidence to an operator. It must not claim an OE when the query
    is merely a suffix/prefix of a longer article. Short all-numeric values are
    accepted in a title only with an explicit identifier label; structured SKU
    equality is handled by the caller.
    """

    # A KEMP shelf code is a private join key, never public identity evidence.
    # Keep this helper fail-closed even if a caller bypasses the resolver and
    # passes the original catalog code as the active query.
    if not title or not query or is_internal_catalog_code(query):
        return False
    pieces = r"[\s./_-]*".join(re.escape(character) for character in query)
    pattern = re.compile(
        rf"(?<![{_IDENTIFIER_BOUNDARY_CHARS}]){pieces}"
        rf"(?![{_IDENTIFIER_BOUNDARY_CHARS}])",
        re.IGNORECASE,
    )
    for match in pattern.finditer(title):
        if query.isdigit() and len(query) <= _SHORT_NUMERIC_IDENTITY_MAX_DIGITS:
            prefix = title[max(0, match.start() - 48) : match.start()]
            if _IDENTIFIER_LABEL_RE.search(prefix):
                return True
            continue
        return True
    return False


def _candidate_article_fields(
    product: Mapping[str, Any],
) -> tuple[tuple[str, str], ...]:
    """Return all candidate-native identifier namespaces in stable order.

    The listing parser deliberately keeps ``sku``, ``mpn``, labelled part
    numbers and ``oe_raw`` separate. Passing all namespaces to candidate
    selection prevents a valid MPN
    from being hidden by an unrelated seller SKU while retaining provenance
    in the gate details.
    """

    fields: list[tuple[str, str]] = []
    for label, key in (
        ("SKU", "sku"),
        ("MPN", "mpn"),
        ("OE", "oe_raw"),
    ):
        value = str(product.get(key) or "").strip()
        if value:
            fields.append((label, value))
    part_numbers = product.get("part_numbers")
    if isinstance(part_numbers, (list, tuple)):
        fields.extend(
            ("PART_NUMBER", value)
            for item in part_numbers
            if (value := str(item or "").strip())
        )
    return tuple(fields)


def _structured_identity_field(
    product: Mapping[str, Any],
    query: str,
) -> str | None:
    """Return the exact native namespace matching the active query."""

    # The discovery UI must not turn a private supplier code into a claimed
    # public OE/MPN match.  The resolver normally replaces it with a public
    # mapped number; this guard protects direct/helper callers as well.
    if is_internal_catalog_code(query):
        return None
    for label, value in _candidate_article_fields(product):
        if (
            not is_internal_catalog_code(value)
            and normalize_candidate_oem(value) == query
        ):
            return label
    return None


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
    """Numbers a confirmed link says name the same part as ``reference_oem``.

    Only the current long-lived catalog identity graph is global authority.
    ``cross_links`` are immutable evidence owned by one pricing run; promoting
    them into every later discovery would turn a single historical seller claim
    into permanent workspace knowledge without current-policy revalidation.
    """

    normalized_reference = normalize_candidate_oem(reference_oem)
    if not normalized_reference:
        return frozenset()
    rows = list(
        (
            await session.execute(
                select(
                    CatalogIdentityLink.our_oem_norm,
                    CatalogIdentityLink.extracted_oem_norm,
                ).where(
                    *confirmed_catalog_identity_conditions(workspace_id),
                    or_(
                        CatalogIdentityLink.our_oem_norm == normalized_reference,
                        CatalogIdentityLink.extracted_oem_norm == normalized_reference,
                    ),
                )
            )
        ).all()
    )
    rows = [
        (our_oem, extracted_oem)
        for our_oem, extracted_oem in rows
        if catalog_identity_pair_has_safe_shape(our_oem, extracted_oem)
    ]
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
    effective_items = tuple(_effective_discovery_offer(offer) for offer in offers)
    effective_histogram: dict[str, int] = {}
    for item in effective_items:
        histogram_key = f"{item.selection_reason} ({item.selection_status})"
        effective_histogram[histogram_key] = (
            effective_histogram.get(histogram_key, 0) + 1
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
        # Do not trust historical run counters at the read boundary.  A run
        # may have been persisted before the active semantic gate existed;
        # its offers are still useful for discovery, but cannot be presented as
        # current pricing evidence.
        pricing_evidence_count=sum(
            item.selection_status == "PRICING_EVIDENCE"
            for item in effective_items
        ),
        reference_only_count=sum(
            item.selection_status == "REFERENCE_ONLY" for item in effective_items
        ),
        rejected_candidate_count=sum(
            item.selection_status == "REJECTED" for item in effective_items
        ),
        selection_histogram=dict(sorted(effective_histogram.items())),
        search_pages_fetched=run.request_count,
        search_page_limit=run.search_page_limit,
        unfetched_count=run.unfetched_count,
        coverage_ratio=run.coverage_ratio,
        coverage_reason=run.coverage_reason,
        selection_method_version=run.selection_method_version,
        selection_config_sha256=run.selection_config_sha256,
        brand_rules_dataset_id=run.brand_rules_dataset_id,
        items=effective_items,
    )


def _has_current_semantic_admission(offer: CatalogDiscoveryOffer) -> bool:
    """Return whether a persisted discovery offer has active gate proof.

    ``selection_status`` and run counters predate the semantic gate and cannot
    authorize a price on their own.  This read-side check prevents historical
    rows from silently becoming pricing evidence after a safety upgrade.  New
    runs persist the gate under ``selection_details``; old rows fail closed and
    remain available as operator-visible discovery results.
    """

    if offer.selection_status != "PRICING_EVIDENCE":
        return False
    details = offer.selection_details
    gate = details.get("semantic_gate") if isinstance(details, Mapping) else None
    if not isinstance(gate, Mapping):
        return False
    return (
        str(gate.get("status") or "").strip() == "PRICING_EVIDENCE"
        and str(gate.get("reason") or "").strip() == "OK"
        and str(gate.get("gate_version") or "").strip()
        == SEMANTIC_PRICING_GATE_VERSION
    )


def _discovery_only_verdict(verdict: Any) -> Any:
    """Prevent a discovery candidate from becoming price evidence.

    ``CandidateStatus.PRICING_EVIDENCE`` is meaningful inside the pure
    candidate-selection algorithm.  A persisted catalog discovery row is a
    different boundary and must never be consumed as a market observation.
    Preserve the pure verdict and semantic proof in the details for replay,
    while exposing ``REFERENCE_ONLY`` to every discovery/API consumer.
    """

    if verdict.status is not CandidateStatus.PRICING_EVIDENCE:
        return verdict
    details = dict(verdict.details or {})
    details["discovery_admission"] = {
        "status": "REFERENCE_ONLY",
        "reason": "DISCOVERY_ONLY_NOT_PRICING_EVIDENCE",
        "original_status": "PRICING_EVIDENCE",
        "original_reason": verdict.reason,
    }
    return replace(
        verdict,
        status=CandidateStatus.REFERENCE_ONLY,
        reason="DISCOVERY_ONLY_NOT_PRICING_EVIDENCE",
        flags=tuple(
            dict.fromkeys(
                (*verdict.flags, "DISCOVERY_ONLY_NOT_PRICING_EVIDENCE")
            )
        ),
        details=MappingProxyType(details),
    )


def _effective_discovery_offer(offer: CatalogDiscoveryOffer) -> CatalogDiscoveredOffer:
    """Materialize one offer with a current, fail-closed read status."""

    selection_status = offer.selection_status
    selection_reason = offer.selection_reason
    reason_codes = tuple(offer.reason_codes)
    selection_flags = tuple(offer.selection_flags)
    selection_details = dict(offer.selection_details or {})
    if offer.selection_status == "PRICING_EVIDENCE":
        stale = not _has_current_semantic_admission(offer)
        selection_status = "REFERENCE_ONLY"
        selection_reason = (
            "SEMANTIC_GATE_STALE"
            if stale
            else "DISCOVERY_ONLY_NOT_PRICING_EVIDENCE"
        )
        reason_codes = tuple(
            dict.fromkeys(
                (
                    *reason_codes,
                    *(("SEMANTIC_GATE_STALE",) if stale else ()),
                    "DISCOVERY_ONLY_NOT_PRICING_EVIDENCE",
                )
            )
        )
        selection_flags = tuple(
            dict.fromkeys(
                (
                    *selection_flags,
                    *(("SEMANTIC_GATE_STALE",) if stale else ()),
                    "DISCOVERY_ONLY_NOT_PRICING_EVIDENCE",
                )
            )
        )
        selection_details["runtime_admission"] = {
            "status": "REFERENCE_ONLY",
            "reason": selection_reason,
            "original_selection_status": offer.selection_status,
            "original_selection_reason": offer.selection_reason,
            "required_gate_version": SEMANTIC_PRICING_GATE_VERSION,
            "discovery_only": True,
        }
    return CatalogDiscoveredOffer(
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
        reason_codes=reason_codes,
        selection_status=selection_status,
        selection_reason=selection_reason,
        passed_gates=tuple(offer.passed_gates),
        selection_flags=selection_flags,
        selection_details=selection_details,
        predicted_tier=offer.predicted_tier,
        tier_confidence=offer.tier_confidence,
        mpn=_raw_snapshot_text(getattr(offer, "raw_snapshot", None), "mpn"),
        oe_raw=_raw_snapshot_text(getattr(offer, "raw_snapshot", None), "oe_raw"),
        part_numbers=_raw_snapshot_part_numbers(
            getattr(offer, "raw_snapshot", None)
        ),
    )


def _raw_snapshot_text(snapshot: Mapping[str, Any] | None, key: str) -> str | None:
    """Read one candidate-native identifier without inventing a value."""

    if not isinstance(snapshot, Mapping):
        return None
    value = snapshot.get(key)
    text = str(value or "").strip()
    return text or None


def _raw_snapshot_part_numbers(
    snapshot: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    """Read parser-extracted labelled codes without treating the query as data."""

    if not isinstance(snapshot, Mapping):
        return ()
    raw = snapshot.get("part_numbers")
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(
        value
        for item in raw
        if (value := str(item or "").strip())
    )


__all__ = [
    "CATALOG_DISCOVERY_CONTRACT_VERSION",
    "CatalogDiscoveredOffer",
    "CatalogDiscoveryError",
    "CatalogDiscoverySnapshot",
    "catalog_discovery_query",
    "catalog_discovery_search_context",
    "catalog_product_key",
    "collect_catalog_discovery",
    "get_catalog_discovery_run",
    "latest_catalog_discovery",
    "optional_backend_path",
    "resolve_backend_path",
    "usable_search_requests",
]
