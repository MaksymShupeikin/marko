"""Incremental catalog monitoring and the user-facing price attention read model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
from typing import Any
from uuid import UUID

from celery import Celery
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    AttentionItem,
    CatalogImportBatch,
    CatalogItem,
    CatalogProduct,
    PriceAssessment,
    PricingRecommendation,
    PricingRun,
    SyncRun,
)
from marko.core.config import get_settings
from marko.infrastructure.db.session import async_session_factory
from marko.services.pricing_runs import (
    CONFIRMATION_SOURCE_AUTOMATED_MONITORING,
    TrustedRunStart,
    create_pricing_run,
)
from marko.services.unified_catalog import SOURCE_PROM_STORE


ATTENTION_STATUSES = (
    "OVERPRICED",
    "UNDERPRICED",
    "IN_MARKET",
    "REVIEW_REQUIRED",
    "NO_DATA",
    "PROCESSING",
)


@dataclass(frozen=True)
class AttentionSummary:
    total: int
    overpriced: int
    underpriced: int
    in_market: int
    review_required: int
    no_data: int
    processing: int
    updated_at: datetime | None


@dataclass(frozen=True)
class AttentionRow:
    product_id: UUID
    recommendation_id: UUID | None
    name: str
    sku: str | None
    oe: str | None
    brand: str | None
    source_kind: str
    source_id: UUID
    status: str
    severity: int
    our_price: Decimal | None
    market_low: Decimal | None
    market_high: Decimal | None
    suggested_price: Decimal | None
    currency: str
    difference_percent: Decimal | None
    confidence: Decimal
    evidence_count: int
    reason_codes: tuple[str, ...]
    market_checked_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True)
class AttentionPage:
    items: tuple[AttentionRow, ...]
    total: int
    limit: int
    offset: int


async def start_store_monitoring_run(sync_run_id: UUID, celery_app: Celery) -> UUID | None:
    """Materialise the latest store view and start one idempotent pricing run."""

    if not get_settings().attention_monitoring_enabled:
        return None
    async with async_session_factory() as session:
        sync_run = await session.get(SyncRun, sync_run_id)
        if sync_run is None:
            return None
        sync_status = getattr(sync_run.status, "value", sync_run.status)
        if (
            sync_status != "completed"
            or sync_run.workspace_id is None
            or sync_run.store_id is None
        ):
            return None
        batch = await _materialize_store_batch(session, sync_run=sync_run)
        if batch is None:
            await session.commit()
            return None
        await _mark_batch_attention_processing(
            session,
            workspace_id=sync_run.workspace_id,
            import_batch_id=batch.id,
        )
        run = await create_pricing_run(
            session,
            workspace_id=sync_run.workspace_id,
            import_batch_id=batch.id,
            celery_app=celery_app,
            start=TrustedRunStart(
                confirmation_source=CONFIRMATION_SOURCE_AUTOMATED_MONITORING,
                reason="automatic market monitoring after owned-store sync",
                idempotency_key=f"attention-store-sync:{sync_run.id}",
                full_catalog_confirmed=True,
            ),
        )
        await session.commit()
        return run.id


async def start_import_monitoring_run(
    session: AsyncSession,
    *,
    batch: CatalogImportBatch,
    celery_app: Celery,
) -> UUID | None:
    """Start the same monitoring pipeline for an imported XLSX snapshot."""

    if not get_settings().attention_monitoring_enabled:
        return None
    if batch.status not in {"completed", "partial"} or batch.imported_rows <= 0:
        return None
    await _mark_batch_attention_processing(
        session,
        workspace_id=batch.workspace_id,
        import_batch_id=batch.id,
    )
    run = await create_pricing_run(
        session,
        workspace_id=batch.workspace_id,
        import_batch_id=batch.id,
        celery_app=celery_app,
        start=TrustedRunStart(
            confirmation_source=CONFIRMATION_SOURCE_AUTOMATED_MONITORING,
            reason="automatic market monitoring after XLSX import",
            idempotency_key=f"attention-xlsx-import:{batch.id}",
            full_catalog_confirmed=True,
        ),
    )
    await session.commit()
    return run.id


async def mark_run_attention_processing(session: AsyncSession, run_id: UUID) -> int:
    """Show every product in an active run as actively being checked."""

    run = await session.get(PricingRun, run_id)
    if run is None:
        return 0
    return await _mark_batch_attention_processing(
        session,
        workspace_id=run.workspace_id,
        import_batch_id=run.import_batch_id,
    )


async def _mark_batch_attention_processing(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
) -> int:
    """Mark the batch before its pricing dispatch can race to completion."""

    products = list(
        (
            await session.scalars(
                select(CatalogProduct)
                .join(CatalogItem, CatalogItem.id == CatalogProduct.catalog_item_id)
                .where(
                    CatalogProduct.workspace_id == workspace_id,
                    CatalogItem.import_batch_id == import_batch_id,
                )
            )
        ).all()
    )
    if not products:
        return 0
    attention_by_product = {
        item.product_id: item
        for item in (
            await session.scalars(
                select(AttentionItem).where(
                    AttentionItem.product_id.in_([product.id for product in products])
                )
            )
        ).all()
    }
    for product in products:
        attention = attention_by_product.get(product.id)
        if attention is None:
            attention = AttentionItem(
                workspace_id=product.workspace_id,
                product_id=product.id,
            )
            session.add(attention)
            attention_by_product[product.id] = attention
        attention.status = "PROCESSING"
        attention.severity = 0
        attention.review_state = "OPEN"
    return len(products)


async def mark_source_monitoring_failed(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    source_kind: str,
    source_id: UUID,
) -> int:
    """Turn a failed automatic start into visible work instead of endless loading."""

    product_ids = list(
        (
            await session.scalars(
                select(CatalogProduct.id).where(
                    CatalogProduct.workspace_id == workspace_id,
                    CatalogProduct.source_kind == source_kind,
                    CatalogProduct.source_id == source_id,
                )
            )
        ).all()
    )
    if not product_ids:
        return 0
    items = list(
        (
            await session.scalars(
                select(AttentionItem).where(
                    AttentionItem.product_id.in_(product_ids),
                    AttentionItem.review_state == "OPEN",
                    AttentionItem.status == "PROCESSING",
                )
            )
        ).all()
    )
    for item in items:
        item.status = "REVIEW_REQUIRED"
        item.severity = 60
    return len(items)


async def _materialize_store_batch(
    session: AsyncSession,
    *,
    sync_run: SyncRun,
) -> CatalogImportBatch | None:
    fingerprint = hashlib.sha256(
        f"attention-store-sync:{sync_run.id}".encode()
    ).hexdigest()
    existing = await session.scalar(
        select(CatalogImportBatch).where(
            CatalogImportBatch.workspace_id == sync_run.workspace_id,
            CatalogImportBatch.request_fingerprint == fingerprint,
        )
    )
    if existing is not None:
        return existing

    products = list(
        (
            await session.scalars(
                select(CatalogProduct)
                .where(
                    CatalogProduct.workspace_id == sync_run.workspace_id,
                    CatalogProduct.source_kind == SOURCE_PROM_STORE,
                    CatalogProduct.source_id == sync_run.store_id,
                    CatalogProduct.current_price.is_not(None),
                    CatalogProduct.is_available.is_not(False),
                )
                .order_by(CatalogProduct.source_product_id)
            )
        ).all()
    )
    if not products:
        return None

    now = datetime.now(UTC)
    batch = CatalogImportBatch(
        workspace_id=sync_run.workspace_id,
        filename=f"prom-store-{sync_run.store_id}-{sync_run.id}.snapshot",
        content_sha256=fingerprint,
        request_fingerprint=fingerprint,
        content_size=0,
        status="completed",
        column_mapping={"source": "PROM_STORE", "sync_run_id": str(sync_run.id)},
        total_rows=len(products),
        imported_rows=len(products),
        rejected_rows=0,
        error_log=[],
        characteristics_report={"source": "PROM_STORE"},
        started_at=now,
        finished_at=now,
    )
    session.add(batch)
    await session.flush()

    seen_skus: set[str] = set()
    items: list[CatalogItem] = []
    for source_row, product in enumerate(products, start=2):
        part_numbers_raw = list(
            dict.fromkeys(
                value
                for value in (product.oe_raw, product.mpn_raw)
                if value and value.strip()
            )
        )
        part_numbers_norm = list(
            dict.fromkeys(
                value
                for value in (product.oe_norm, product.mpn_norm)
                if value and value.strip()
            )
        )
        base_sku = (product.sku or f"PROM-{product.source_product_id}")[:220]
        sku = base_sku
        if sku in seen_skus:
            sku = f"{base_sku}-{product.source_product_id}"[:255]
        seen_skus.add(sku)
        item = CatalogItem(
            workspace_id=sync_run.workspace_id,
            import_batch_id=batch.id,
            store_id=sync_run.store_id,
            source_row=source_row,
            sku=sku,
            oe_raw=product.oe_raw or product.oe_norm or "",
            oe_norm=product.oe_norm or "",
            mpn_raw=product.mpn_raw or "",
            mpn_norm=product.mpn_norm or "",
            name=product.name,
            category=(product.category or "Автотовары")[:255],
            brand=product.brand,
            description=product.description,
            product_url=product.product_url,
            current_price=product.current_price,
            currency=product.currency,
            is_available=product.is_available,
            stock_status="unknown",
            stock_qty=None,
            stock_age_days=None,
            expected_units_sold=None,
            units_sold_30d=None,
            units_sold_60d=None,
            units_sold_90d=None,
            days_since_last_sale=None,
            historical_monthly_units=None,
            views_30d=None,
            conversion_rate_proxy=None,
            cost=None,
            manual_priority=Decimal("1"),
            raw_row=product.raw_data or {},
            part_numbers_raw=part_numbers_raw,
            part_numbers_norm=part_numbers_norm,
            applicability_brands=[],
            applicability_models=[],
            characteristics_raw=_target_characteristics(product.raw_data),
            identity_status="UNRESOLVED",
            identity_reason=product.identity_reason,
        )
        session.add(item)
        items.append(item)
    await session.flush()
    for product, item in zip(products, items, strict=True):
        product.catalog_item_id = item.id
    await session.flush()
    return batch


def _target_characteristics(raw_data: dict[str, Any] | None) -> dict[str, Any]:
    """Preserve quality/fitment evidence needed by comparability review."""

    payload = raw_data or {}
    raw_characteristics = payload.get("characteristics")
    if isinstance(raw_characteristics, dict):
        result = dict(raw_characteristics)
    else:
        result: dict[str, Any] = {}
        if isinstance(raw_characteristics, list):
            for row in raw_characteristics:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name") or row.get("title") or "").strip()
                value = row.get("value")
                if name and value not in (None, ""):
                    result[name] = value
    for key in (
        "condition",
        "package_quantity",
        "side",
        "position",
        "fitment",
        "vehicle_generation",
        "year_from",
        "year_to",
        "engine",
        "body_variant",
    ):
        value = payload.get(key)
        if value not in (None, ""):
            result.setdefault(key, value)
    return result


async def project_attention_for_run(session: AsyncSession, run_id: UUID) -> int:
    """Project immutable pricing output into the mutable daily-work queue."""

    run = await session.get(PricingRun, run_id)
    if run is None:
        return 0
    products = list(
        (
            await session.scalars(
                select(CatalogProduct)
                .join(CatalogItem, CatalogItem.id == CatalogProduct.catalog_item_id)
                .where(
                    CatalogProduct.workspace_id == run.workspace_id,
                    CatalogItem.import_batch_id == run.import_batch_id,
                )
            )
        ).all()
    )
    if not products:
        return 0
    product_by_item = {
        product.catalog_item_id: product
        for product in products
        if product.catalog_item_id is not None
    }
    recommendations = list(
        (
            await session.scalars(
                select(PricingRecommendation).where(
                    PricingRecommendation.pricing_run_id == run_id,
                    PricingRecommendation.catalog_item_id.in_(product_by_item),
                )
            )
        ).all()
    )
    recommendation_by_item = {
        recommendation.catalog_item_id: recommendation
        for recommendation in recommendations
    }
    attention_by_product = {
        item.product_id: item
        for item in (
            await session.scalars(
                select(AttentionItem).where(
                    AttentionItem.product_id.in_([product.id for product in products])
                )
            )
        ).all()
    }
    projected = 0
    for product in products:
        recommendation = recommendation_by_item.get(product.catalog_item_id)
        evaluation_key = f"pricing-run:{run_id}:{product.id}"
        assessment = await session.scalar(
            select(PriceAssessment).where(
                PriceAssessment.evaluation_key == evaluation_key
            )
        )
        if assessment is None:
            values = _assessment_values(product, recommendation)
            assessment = PriceAssessment(
                product_id=product.id,
                recommendation_id=(recommendation.id if recommendation else None),
                evaluation_key=evaluation_key,
                **values,
            )
            session.add(assessment)
            await session.flush()
        attention = attention_by_product.get(product.id)
        if attention is None:
            attention = AttentionItem(
                workspace_id=product.workspace_id,
                product_id=product.id,
            )
            session.add(attention)
            attention_by_product[product.id] = attention
        attention.latest_assessment_id = assessment.id
        attention.status = assessment.status
        attention.severity = _severity(
            assessment.status,
            assessment.difference_percent,
        )
        attention.review_state = "OPEN"
        projected += 1
    return projected


async def mark_run_attention_failed(session: AsyncSession, run_id: UUID) -> int:
    """Expose a terminal failed/cancelled run without erasing older evidence."""

    run = await session.get(PricingRun, run_id)
    if run is None:
        return 0
    product_ids = list(
        (
            await session.scalars(
                select(CatalogProduct.id)
                .join(CatalogItem, CatalogItem.id == CatalogProduct.catalog_item_id)
                .where(
                    CatalogProduct.workspace_id == run.workspace_id,
                    CatalogItem.import_batch_id == run.import_batch_id,
                )
            )
        ).all()
    )
    if not product_ids:
        return 0
    items = list(
        (
            await session.scalars(
                select(AttentionItem).where(
                    AttentionItem.product_id.in_(product_ids),
                    AttentionItem.review_state == "OPEN",
                )
            )
        ).all()
    )
    for item in items:
        item.status = "REVIEW_REQUIRED"
        item.severity = 60
    return len(items)


def _assessment_values(
    product: CatalogProduct,
    recommendation: PricingRecommendation | None,
) -> dict[str, Any]:
    if recommendation is None:
        return {
            "status": "NO_DATA",
            "our_price": product.current_price,
            "market_low": None,
            "market_high": None,
            "suggested_price": None,
            "difference_percent": None,
            "confidence": Decimal("0"),
            "evidence_count": 0,
            "reason_codes": ["PRICING_RESULT_NOT_PRODUCED"],
            "market_checked_at": None,
        }
    trace = recommendation.calculation_trace or {}
    trace = trace if isinstance(trace, dict) else {}
    advisory = trace.get("advisory_decision")
    advisory = advisory if isinstance(advisory, dict) else {}
    advisory_status = str(advisory.get("status") or "")
    # Comparability-gated rail already computed RAISE/LOWER. Incomplete
    # evidence only has an operator hint: keep REVIEW_REQUIRED, never
    # promote the hint into UNDERPRICED/OVERPRICED.
    inherit_advisory_action = (
        advisory_status != "INCOMPLETE_EVIDENCE_REVIEW_REQUIRED"
    )
    action = str(
        (advisory.get("action") if inherit_advisory_action else None)
        or recommendation.action
    )
    suggested = recommendation.recommended_price or _decimal(
        advisory.get("recommended_price")
    )
    market_prices = [
        price
        for offer in trace.get("normalized_offers", [])
        if isinstance(offer, dict)
        and offer.get("cohort_role") == "TARGET_MARKET"
        and (price := _decimal(offer.get("normalized_price"))) is not None
    ]
    market_low = (
        min(market_prices)
        if market_prices
        else recommendation.lower_bound
        or _decimal(advisory.get("target_band_low"))
    )
    market_high = (
        max(market_prices)
        if market_prices
        else recommendation.upper_bound
        or _decimal(advisory.get("target_band_high"))
    )
    status = {
        "RAISE": "UNDERPRICED",
        "LOWER": "OVERPRICED",
        "HOLD": "IN_MARKET",
    }.get(action)
    if status is None:
        if advisory_status == "INCOMPLETE_EVIDENCE_REVIEW_REQUIRED":
            status = "REVIEW_REQUIRED"
        elif recommendation.verified_seller_count == 0:
            status = "NO_DATA"
        else:
            status = "REVIEW_REQUIRED"
    difference = None
    if product.current_price is not None and suggested not in (None, Decimal("0")):
        difference = ((product.current_price - suggested) / suggested) * Decimal("100")
    reasons = list(recommendation.reason_codes or [])
    if advisory:
        reasons.append("ADVISORY_REQUIRES_REVIEW")
    return {
        "status": status,
        "our_price": product.current_price,
        "market_low": market_low,
        "market_high": market_high,
        "suggested_price": suggested,
        "difference_percent": difference,
        "confidence": recommendation.confidence,
        "evidence_count": recommendation.verified_seller_count,
        "reason_codes": list(dict.fromkeys(reasons)),
        "market_checked_at": recommendation.computed_at,
    }


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _severity(status: str, difference: Decimal | None) -> int:
    if status == "REVIEW_REQUIRED":
        return 60
    if status == "NO_DATA":
        return 30
    if status in {"IN_MARKET", "PROCESSING"}:
        return 0
    if difference is None:
        return 50
    return min(100, max(1, int(abs(difference))))


async def get_attention_summary(
    session: AsyncSession,
    *,
    workspace_id: UUID,
) -> AttentionSummary:
    counts = {
        status: int(count)
        for status, count in (
            await session.execute(
                select(AttentionItem.status, func.count(AttentionItem.id))
                .where(
                    AttentionItem.workspace_id == workspace_id,
                    AttentionItem.review_state == "OPEN",
                )
                .group_by(AttentionItem.status)
            )
        ).all()
    }
    updated_at = await session.scalar(
        select(func.max(AttentionItem.updated_at)).where(
            AttentionItem.workspace_id == workspace_id
        )
    )
    return AttentionSummary(
        total=sum(counts.values()),
        overpriced=counts.get("OVERPRICED", 0),
        underpriced=counts.get("UNDERPRICED", 0),
        in_market=counts.get("IN_MARKET", 0),
        review_required=counts.get("REVIEW_REQUIRED", 0),
        no_data=counts.get("NO_DATA", 0),
        processing=counts.get("PROCESSING", 0),
        updated_at=updated_at,
    )


async def list_attention_items(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    status: str | None = None,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> AttentionPage:
    conditions = [
        AttentionItem.workspace_id == workspace_id,
        AttentionItem.review_state == "OPEN",
    ]
    if status:
        if status not in ATTENTION_STATUSES:
            raise ValueError(f"unknown attention status: {status}")
        conditions.append(AttentionItem.status == status)
    if normalized := (query or "").strip():
        pattern = f"%{normalized}%"
        conditions.append(
            or_(
                CatalogProduct.name.ilike(pattern),
                CatalogProduct.sku.ilike(pattern),
                CatalogProduct.oe_norm.ilike(pattern),
            )
        )
    total = int(
        await session.scalar(
            select(func.count(AttentionItem.id))
            .join(CatalogProduct, CatalogProduct.id == AttentionItem.product_id)
            .where(*conditions)
        )
        or 0
    )
    rows = (
        await session.execute(
            select(AttentionItem, CatalogProduct, PriceAssessment)
            .join(CatalogProduct, CatalogProduct.id == AttentionItem.product_id)
            .outerjoin(
                PriceAssessment,
                PriceAssessment.id == AttentionItem.latest_assessment_id,
            )
            .where(*conditions)
            .order_by(
                AttentionItem.severity.desc(),
                AttentionItem.updated_at.desc(),
                CatalogProduct.name,
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return AttentionPage(
        items=tuple(_attention_row(item, product, assessment) for item, product, assessment in rows),
        total=total,
        limit=limit,
        offset=offset,
    )


def _attention_row(
    item: AttentionItem,
    product: CatalogProduct,
    assessment: PriceAssessment | None,
) -> AttentionRow:
    return AttentionRow(
        product_id=product.id,
        recommendation_id=(assessment.recommendation_id if assessment else None),
        name=product.name,
        sku=product.sku,
        oe=product.oe_norm,
        brand=product.brand,
        source_kind=product.source_kind,
        source_id=product.source_id,
        status=item.status,
        severity=item.severity,
        our_price=(assessment.our_price if assessment else product.current_price),
        market_low=(assessment.market_low if assessment else None),
        market_high=(assessment.market_high if assessment else None),
        suggested_price=(assessment.suggested_price if assessment else None),
        currency=product.currency,
        difference_percent=(assessment.difference_percent if assessment else None),
        confidence=(assessment.confidence if assessment else Decimal("0")),
        evidence_count=(assessment.evidence_count if assessment else 0),
        reason_codes=tuple(assessment.reason_codes or ()) if assessment else (),
        market_checked_at=(assessment.market_checked_at if assessment else None),
        updated_at=item.updated_at,
    )


__all__ = [
    "ATTENTION_STATUSES",
    "AttentionPage",
    "AttentionRow",
    "AttentionSummary",
    "get_attention_summary",
    "list_attention_items",
    "mark_run_attention_processing",
    "mark_run_attention_failed",
    "mark_source_monitoring_failed",
    "project_attention_for_run",
    "start_import_monitoring_run",
    "start_store_monitoring_run",
]
