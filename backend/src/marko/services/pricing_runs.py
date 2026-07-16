"""Persistence and orchestration services for pricing runs."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
import json
from typing import Any, Mapping
from uuid import UUID

from celery import Celery
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.core.config import get_settings
from marko.infrastructure.db.models import (
    CatalogImportBatch,
    CatalogItem,
    CatalogItemOverride,
    MarketObservation,
    ObservationTierClassification,
    PricingRecommendation,
    PricingRun,
    PricingRunItem,
    RecommendationDecision,
    ScrapeTarget,
    TierCalibrationPairRecord,
    TierCoefficientRecord,
)
from marko.pricing import (
    CalibrationPair,
    CoefficientModel,
    PricingPolicy,
    ProductPricingContext,
    ProductTier,
    StockStatus,
    TierCoefficient,
    calibration_dataset_hash,
    fit_shrinkage_coefficients,
    fit_simple_coefficients,
)
from marko.pricing.tiering import TIER_METHOD_VERSION
from marko.pricing.observability import pricing_event
from marko.services.scraper_contract import (
    PROM_ADAPTER_VERSION,
    ScrapeInput,
    ScraperBoundaryError,
    fallback_input_hash,
)

PARSER_ADAPTER_VERSION = PROM_ADAPTER_VERSION
ACTIVE_RUN_STATUSES = (
    "queued",
    "running",
    "collecting",
    "classifying",
    "calibrating",
    "calculating",
)
TERMINAL_RUN_ITEM_STATUSES = ("calculated", "manual_review", "failed", "cancelled")
CATALOG_OVERRIDE_SNAPSHOT_FIELDS = (
    "stock_status",
    "cost",
    "stock_qty",
    "stock_age_days",
    "expected_units_sold",
    "units_sold_30d",
    "units_sold_60d",
    "units_sold_90d",
    "days_since_last_sale",
    "historical_monthly_units",
    "views_30d",
    "conversion_rate_proxy",
    "manual_priority",
    "liquidity_target",
    "urgency",
    "allow_below_cost",
    "below_cost_floor",
    "below_cost_warning_confirmed",
)


class PricingRunError(RuntimeError):
    pass


class PricingRunNotFoundError(LookupError):
    pass


class RecommendationNotFoundError(LookupError):
    pass


class CatalogItemNotFoundError(LookupError):
    pass


class PricingTaskDispatchError(PricingRunError):
    pass


def _validate_decision_price(
    *,
    new_price: Decimal | None,
    cost: Decimal | None,
    stock_status: str | None,
    approved_floor: Decimal | None,
    allow_below_cost: bool,
    warning_confirmed: bool,
) -> bool:
    """Validate the API-side below-cost boundary and return whether it applies."""
    is_below_cost = new_price is not None and cost is not None and new_price < cost
    if not is_below_cost:
        return False
    if not allow_below_cost:
        raise PricingRunError("Below-cost price requires explicit allow_below_cost")
    if not warning_confirmed:
        raise PricingRunError("Below-cost warning must be explicitly confirmed")
    if stock_status != "dead_stock":
        raise PricingRunError("Below-cost pricing is allowed only for dead_stock")
    if approved_floor is None:
        raise PricingRunError("Below-cost decision requires an approved floor")
    if new_price < approved_floor:
        raise PricingRunError("Decision price is below the approved below-cost floor")
    return True


def policy_to_dict(policy: PricingPolicy) -> dict[str, Any]:
    return _json_safe(asdict(policy))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def policy_from_dict(config: Mapping[str, Any] | None) -> PricingPolicy:
    defaults = PricingPolicy()
    if not config:
        return defaults
    allowed = {field.name for field in fields(PricingPolicy)}
    unknown = set(config) - allowed
    if unknown:
        raise PricingRunError(
            "Unknown pricing policy fields: " + ", ".join(sorted(unknown))
        )
    converted: dict[str, Any] = {}
    for name, raw in config.items():
        default = getattr(defaults, name)
        try:
            if isinstance(default, Decimal):
                value = Decimal(str(raw))
                if not value.is_finite():
                    raise ValueError
            elif isinstance(default, Enum):
                value = type(default)(str(raw))
            elif isinstance(default, Mapping):
                if not isinstance(raw, Mapping):
                    raise ValueError
                value = {
                    **default,
                    **{str(key): Decimal(str(item)) for key, item in raw.items()},
                }
            elif isinstance(default, bool):
                if not isinstance(raw, bool):
                    raise ValueError
                value = raw
            elif isinstance(default, int):
                if isinstance(raw, bool):
                    raise ValueError
                value = int(raw)
            elif isinstance(default, str):
                value = str(raw)
            else:
                value = raw
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise PricingRunError(f"Invalid policy value for {name}") from exc
        converted[name] = value
    try:
        policy = PricingPolicy(**converted)
        _validate_policy(policy)
    except ValueError as exc:
        raise PricingRunError(str(exc)) from exc
    return policy


def _validate_policy(policy: PricingPolicy) -> None:
    # PricingPolicy.__post_init__ is the canonical validation boundary.
    if not policy.version.strip():
        raise PricingRunError("pricing policy version is required")


async def create_pricing_run(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
    celery_app: Celery,
    policy_config: Mapping[str, Any] | None = None,
) -> PricingRun:
    batch = await session.scalar(
        select(CatalogImportBatch).where(
            CatalogImportBatch.id == import_batch_id,
            CatalogImportBatch.workspace_id == workspace_id,
        )
    )
    if batch is None:
        raise PricingRunError("Catalog import not found")
    if batch.status not in {"completed", "partial"} or batch.imported_rows < 1:
        raise PricingRunError("Catalog import has no valid rows")
    active = await session.scalar(
        select(PricingRun)
        .where(
            PricingRun.workspace_id == workspace_id,
            PricingRun.import_batch_id == import_batch_id,
            PricingRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        .order_by(PricingRun.created_at.desc())
        .limit(1)
    )
    if active is not None:
        return active

    policy = policy_from_dict(policy_config)
    catalog_items = list(
        (
            await session.scalars(
                select(CatalogItem)
                .where(
                    CatalogItem.workspace_id == workspace_id,
                    CatalogItem.import_batch_id == import_batch_id,
                    CatalogItem.is_available.is_not(False),
                )
                .order_by(CatalogItem.source_row)
            )
        ).all()
    )
    if not catalog_items:
        raise PricingRunError("Catalog import has no available rows")

    run = PricingRun(
        workspace_id=workspace_id,
        import_batch_id=import_batch_id,
        status="queued",
        policy_version=policy.version,
        policy_config=policy_to_dict(policy),
        parser_version=PARSER_ADAPTER_VERSION,
        classifier_version=TIER_METHOD_VERSION,
        coefficient_model=policy.coefficient_model.value,
        total_items=len(catalog_items),
    )
    session.add(run)
    await session.flush()

    targets_by_hash: dict[str, ScrapeTarget] = {}
    target_hash_by_item: dict[UUID, str] = {}
    settings = get_settings()
    for catalog_item in catalog_items:
        raw_url = (catalog_item.product_url or "").strip() or None
        raw_query = catalog_item.oe_norm
        try:
            scrape_input = ScrapeInput.build(
                raw_url,
                raw_query,
                adapter_version=PARSER_ADAPTER_VERSION,
            )
        except ScraperBoundaryError:
            input_hash = fallback_input_hash(
                raw_url,
                raw_query,
                adapter_version=PARSER_ADAPTER_VERSION,
            )
            canonical_url = None
            product_key = None
            normalized_query = " ".join(raw_query.strip().upper().split())
            metadata_payload = {
                "adapter_version": PARSER_ADAPTER_VERSION,
                "product_url": raw_url,
                "query": normalized_query,
                "input_hash": input_hash,
            }
        else:
            input_hash = scrape_input.input_hash
            canonical_url = scrape_input.canonical_url
            product_key = scrape_input.product_key
            normalized_query = scrape_input.query
            metadata_payload = scrape_input.as_dict()
        target = targets_by_hash.get(input_hash)
        if target is None:
            target = ScrapeTarget(
                pricing_run_id=run.id,
                source="prom",
                original_url=raw_url,
                canonical_url=canonical_url,
                product_key=product_key,
                query=normalized_query,
                input_hash=input_hash,
                adapter_version=PARSER_ADAPTER_VERSION,
                status="queued",
                max_task_executions=max(
                    1,
                    settings.pricing_collection_max_task_executions,
                ),
                deadline_at=datetime.now(UTC)
                + timedelta(
                    seconds=max(
                        1,
                        settings.pricing_collection_item_deadline_seconds,
                    )
                ),
                metadata_size_bytes=len(
                    json.dumps(
                        metadata_payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode()
                ),
            )
            targets_by_hash[input_hash] = target
        target_hash_by_item[catalog_item.id] = input_hash
    session.add_all(list(targets_by_hash.values()))
    await session.flush()

    session.add_all(
        [
            PricingRunItem(
                pricing_run_id=run.id,
                catalog_item_id=catalog_item.id,
                scrape_target_id=targets_by_hash[
                    target_hash_by_item[catalog_item.id]
                ].id,
                status="queued",
                idempotency_key=f"{run.id}:{catalog_item.id}",
            )
            for catalog_item in catalog_items
        ]
    )
    await session.commit()
    await session.refresh(run)

    try:
        await asyncio.to_thread(
            celery_app.send_task,
            "marko.worker.start_pricing_run",
            args=[str(run.id)],
        )
    except Exception as exc:
        run.status = "failed"
        run.error = f"Could not enqueue pricing run: {exc}"[:4000]
        run.finished_at = datetime.now(UTC)
        await session.commit()
        raise PricingTaskDispatchError(run.error) from exc
    pricing_event(
        "pricing_run_started",
        pricing_run_id=str(run.id),
        workspace_id=str(workspace_id),
        items=run.total_items,
        unique_inputs=len(targets_by_hash),
        unique_urls=len(
            {
                target.canonical_url
                for target in targets_by_hash.values()
                if target.canonical_url
            }
        ),
        duplicates=max(0, run.total_items - len(targets_by_hash)),
        policy_version=run.policy_version,
    )
    return run


async def get_pricing_run(
    session: AsyncSession, *, workspace_id: UUID, run_id: UUID
) -> PricingRun:
    run = await session.scalar(
        select(PricingRun).where(
            PricingRun.id == run_id,
            PricingRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise PricingRunNotFoundError(str(run_id))
    return run


async def list_pricing_runs(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    limit: int,
    offset: int,
) -> tuple[list[PricingRun], int]:
    where = PricingRun.workspace_id == workspace_id
    total = int(
        await session.scalar(select(func.count(PricingRun.id)).where(where)) or 0
    )
    runs = list(
        (
            await session.scalars(
                select(PricingRun)
                .where(where)
                .order_by(PricingRun.created_at.desc(), PricingRun.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return runs, total


async def cancel_pricing_run(
    session: AsyncSession, *, workspace_id: UUID, run_id: UUID
) -> PricingRun:
    run = await get_pricing_run(session, workspace_id=workspace_id, run_id=run_id)
    if run.status in {"completed", "partial", "failed", "cancelled"}:
        return run
    run.cancel_requested = True
    await session.commit()
    return run


async def get_latest_override(
    session: AsyncSession, catalog_item_id: UUID
) -> CatalogItemOverride | None:
    return await session.scalar(
        select(CatalogItemOverride)
        .where(CatalogItemOverride.catalog_item_id == catalog_item_id)
        .order_by(CatalogItemOverride.created_at.desc(), CatalogItemOverride.id.desc())
        .limit(1)
    )


def _merge_catalog_override_snapshot(
    values: Mapping[str, Any], previous: CatalogItemOverride | None
) -> dict[str, Any]:
    snapshot = {
        field: (
            values[field]
            if field in values
            else getattr(
                previous,
                field,
                False
                if field in {"allow_below_cost", "below_cost_warning_confirmed"}
                else None,
            )
        )
        for field in CATALOG_OVERRIDE_SNAPSHOT_FIELDS
    }
    if not snapshot["allow_below_cost"]:
        snapshot["below_cost_floor"] = None
        snapshot["below_cost_warning_confirmed"] = False
    return snapshot


async def add_catalog_item_override(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    catalog_item_id: UUID,
    values: Mapping[str, Any],
) -> CatalogItemOverride:
    item = await session.scalar(
        select(CatalogItem).where(
            CatalogItem.id == catalog_item_id,
            CatalogItem.workspace_id == workspace_id,
        )
    )
    if item is None:
        raise CatalogItemNotFoundError(str(catalog_item_id))
    allowed = {
        "stock_status",
        "cost",
        "stock_qty",
        "stock_age_days",
        "expected_units_sold",
        "units_sold_30d",
        "units_sold_60d",
        "units_sold_90d",
        "days_since_last_sale",
        "historical_monthly_units",
        "views_30d",
        "conversion_rate_proxy",
        "manual_priority",
        "liquidity_target",
        "urgency",
        "allow_below_cost",
        "below_cost_floor",
        "below_cost_warning_confirmed",
        "reason",
    }
    if set(values) - allowed:
        raise PricingRunError("Unknown catalog override fields")
    reason = str(values.get("reason", "")).strip()
    if not reason:
        raise PricingRunError("Override reason is required")
    previous = await get_latest_override(session, catalog_item_id)
    snapshot = _merge_catalog_override_snapshot(values, previous)
    allow_below_cost = bool(snapshot["allow_below_cost"])
    below_floor = snapshot["below_cost_floor"]
    if allow_below_cost and below_floor is None:
        raise PricingRunError("below_cost_floor is required for below-cost override")
    if allow_below_cost and not snapshot["below_cost_warning_confirmed"]:
        raise PricingRunError("below-cost warning confirmation is required")
    if allow_below_cost and snapshot["stock_status"] != "dead_stock":
        raise PricingRunError("Below-cost pricing is allowed only for dead_stock")
    override = CatalogItemOverride(
        catalog_item_id=catalog_item_id,
        user_id=user_id,
        **snapshot,
        reason=reason,
    )
    session.add(override)
    await session.commit()
    await session.refresh(override)
    return override


def build_pricing_context(
    item: CatalogItem, override: CatalogItemOverride | None
) -> ProductPricingContext:
    def latest(name: str, fallback: Any) -> Any:
        if override is None:
            return fallback
        value = getattr(override, name)
        return fallback if value is None else value

    status_raw = latest("stock_status", item.stock_status)
    try:
        stock_status = StockStatus(status_raw)
    except ValueError:
        stock_status = StockStatus.UNKNOWN
    return ProductPricingContext(
        sku=item.sku,
        category=item.category,
        current_price=item.current_price,
        currency=item.currency,
        stock_status=stock_status,
        cost=latest("cost", item.cost),
        stock_qty=latest("stock_qty", item.stock_qty),
        stock_age_days=latest("stock_age_days", item.stock_age_days),
        expected_units_sold=latest("expected_units_sold", item.expected_units_sold),
        units_sold_30d=latest("units_sold_30d", item.units_sold_30d),
        units_sold_60d=latest("units_sold_60d", item.units_sold_60d),
        units_sold_90d=latest("units_sold_90d", item.units_sold_90d),
        days_since_last_sale=latest("days_since_last_sale", item.days_since_last_sale),
        historical_monthly_units=latest(
            "historical_monthly_units", item.historical_monthly_units
        ),
        views_30d=latest("views_30d", item.views_30d),
        conversion_rate_proxy=latest(
            "conversion_rate_proxy", item.conversion_rate_proxy
        ),
        liquidity_target=latest("liquidity_target", Decimal("0")),
        urgency=latest("urgency", Decimal("1")),
        manual_priority=latest("manual_priority", item.manual_priority),
        allow_below_cost=override.allow_below_cost if override else False,
        below_cost_floor=override.below_cost_floor if override else None,
        below_cost_authorization_id=(str(override.id) if override else None),
        below_cost_authorized_by=(
            str(override.user_id) if override and override.user_id else None
        ),
        below_cost_authorized_at=(override.created_at if override else None),
        below_cost_reason=(override.reason if override else None),
        below_cost_warning_confirmed=(
            override.below_cost_warning_confirmed if override else False
        ),
    )


def _coefficient_to_domain(record: TierCoefficientRecord) -> TierCoefficient:
    return TierCoefficient(
        category=record.category,
        tier=ProductTier(record.tier),
        multiplier=record.multiplier,
        model=CoefficientModel(record.model),
        method_version=record.method_version,
        coefficient_version=record.coefficient_version,
        sample_size=record.sample_size,
        effective_sample_size=record.effective_sample_size,
        confidence=record.confidence,
        validated=record.validated,
        log_effect=record.log_effect,
        global_log_effect=record.global_log_effect,
        shrinkage_weight=record.shrinkage_weight,
        interval_low=record.interval_low,
        interval_high=record.interval_high,
        dataset_hash=record.dataset_hash,
        validation_reasons=tuple(record.validation_reasons),
    )


async def load_tier_coefficients(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    category: str,
    pricing_run_id: UUID | None = None,
) -> dict[tuple[str, ProductTier], TierCoefficient]:
    conditions = [
        TierCoefficientRecord.workspace_id == workspace_id,
        TierCoefficientRecord.category == category,
    ]
    if pricing_run_id is None:
        conditions.extend(
            [
                TierCoefficientRecord.pricing_run_id.is_(None),
                TierCoefficientRecord.validated.is_(True),
            ]
        )
    else:
        conditions.extend(
            [
                TierCoefficientRecord.pricing_run_id == pricing_run_id,
                TierCoefficientRecord.is_selected.is_(True),
            ]
        )
    records = list(
        (
            await session.scalars(
                select(TierCoefficientRecord)
                .where(*conditions)
                .order_by(TierCoefficientRecord.computed_at.desc())
            )
        ).all()
    )
    result: dict[tuple[str, ProductTier], TierCoefficient] = {}
    for record in records:
        coefficient = _coefficient_to_domain(record)
        key = (record.category, coefficient.tier)
        if key in result:
            continue
        result[key] = coefficient
    return result


async def persist_run_calibration_pairs(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    pricing_run_id: UUID,
    pairs: list[CalibrationPair],
) -> tuple[list[TierCalibrationPairRecord], str]:
    dataset_hash = calibration_dataset_hash(pairs)
    existing = list(
        (
            await session.scalars(
                select(TierCalibrationPairRecord).where(
                    TierCalibrationPairRecord.pricing_run_id == pricing_run_id
                )
            )
        ).all()
    )
    if existing:
        hashes = {record.dataset_hash for record in existing}
        if hashes != {dataset_hash}:
            raise PricingRunError("Run calibration dataset changed after freezing")
        return existing, dataset_hash
    records = [
        TierCalibrationPairRecord(
            workspace_id=workspace_id,
            pricing_run_id=pricing_run_id,
            oe_norm=pair.oe_norm.strip().upper(),
            category=pair.category.strip(),
            tier=pair.tier.value,
            tier_price=pair.tier_price,
            reference_price=pair.reference_price,
            quality_weight=pair.quality_weight,
            tier_observation_ids=list(pair.tier_observation_ids),
            reference_observation_ids=list(pair.reference_observation_ids),
            dataset_hash=dataset_hash,
        )
        for pair in pairs
    ]
    session.add_all(records)
    await session.flush()
    return records, dataset_hash


async def load_run_calibration_pairs(
    session: AsyncSession, *, pricing_run_id: UUID
) -> list[CalibrationPair]:
    records = list(
        (
            await session.scalars(
                select(TierCalibrationPairRecord)
                .where(TierCalibrationPairRecord.pricing_run_id == pricing_run_id)
                .order_by(
                    TierCalibrationPairRecord.category,
                    TierCalibrationPairRecord.tier,
                    TierCalibrationPairRecord.oe_norm,
                )
            )
        ).all()
    )
    return [
        CalibrationPair(
            oe_norm=record.oe_norm,
            category=record.category,
            tier=ProductTier(record.tier),
            tier_price=record.tier_price,
            reference_price=record.reference_price,
            quality_weight=record.quality_weight,
            tier_observation_ids=tuple(record.tier_observation_ids),
            reference_observation_ids=tuple(record.reference_observation_ids),
        )
        for record in records
    ]


async def calibrate_tier_coefficients(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    pairs: list[CalibrationPair],
    model: CoefficientModel,
    shrinkage_k: Decimal = Decimal("10"),
    min_category_pairs: int = 8,
    min_global_pairs: int = 20,
    min_effective_pairs: Decimal | None = None,
    max_interval_ratio: Decimal = Decimal("3"),
    pricing_run_id: UUID | None = None,
    policy_version: str = "pricing-v2",
    selected: bool = False,
) -> list[TierCoefficientRecord]:
    dataset_hash = calibration_dataset_hash(pairs)
    scope = f":run-{pricing_run_id}" if pricing_run_id else ""
    method_version = f"tier-{model.value}-v2{scope}"
    if model == CoefficientModel.SIMPLE_MEDIAN:
        coefficients = fit_simple_coefficients(
            pairs,
            min_pairs=min_category_pairs,
            min_effective_pairs=min_effective_pairs,
            max_interval_ratio=max_interval_ratio,
            method_version=method_version,
        )
    else:
        coefficients = fit_shrinkage_coefficients(
            pairs,
            shrinkage_k=shrinkage_k,
            min_category_pairs=min_category_pairs,
            min_global_pairs=min_global_pairs,
            min_effective_pairs=min_effective_pairs,
            max_interval_ratio=max_interval_ratio,
            method_version=method_version,
        )
    coefficient_versions = {
        coefficient.coefficient_version for coefficient in coefficients.values()
    }
    existing = list(
        (
            await session.scalars(
                select(TierCoefficientRecord).where(
                    TierCoefficientRecord.workspace_id == workspace_id,
                    TierCoefficientRecord.pricing_run_id == pricing_run_id,
                    TierCoefficientRecord.method_version == method_version,
                    TierCoefficientRecord.coefficient_version.in_(coefficient_versions),
                )
            )
        ).all()
    )
    if existing:
        return existing
    records = [
        TierCoefficientRecord(
            workspace_id=workspace_id,
            pricing_run_id=pricing_run_id,
            category=coefficient.category,
            tier=coefficient.tier.value,
            model=coefficient.model.value,
            multiplier=coefficient.multiplier,
            log_effect=coefficient.log_effect,
            global_log_effect=coefficient.global_log_effect,
            shrinkage_weight=coefficient.shrinkage_weight,
            sample_size=coefficient.sample_size,
            effective_sample_size=coefficient.effective_sample_size,
            confidence=coefficient.confidence,
            interval_low=coefficient.interval_low,
            interval_high=coefficient.interval_high,
            validated=coefficient.validated,
            dataset_hash=dataset_hash,
            method_version=coefficient.method_version,
            coefficient_version=coefficient.coefficient_version,
            policy_version=policy_version,
            validation_reasons=list(coefficient.validation_reasons),
            is_selected=selected,
        )
        for coefficient in coefficients.values()
    ]
    session.add_all(records)
    await session.commit()
    return records


async def load_target_tier_coefficients(
    session: AsyncSession,
    *,
    run: PricingRun,
    category: str,
    oe_norm: str,
    policy: PricingPolicy,
) -> dict[tuple[str, ProductTier], TierCoefficient]:
    frozen = await load_tier_coefficients(
        session,
        workspace_id=run.workspace_id,
        category=category,
        pricing_run_id=run.id,
    )
    if not policy.require_target_leakage_protection:
        return frozen
    pairs = await load_run_calibration_pairs(session, pricing_run_id=run.id)
    normalized_target = oe_norm.strip().upper()
    if not any(pair.oe_norm.strip().upper() == normalized_target for pair in pairs):
        return frozen
    method_version = f"tier-{policy.coefficient_model.value}-v2:loo-run-{run.id}"
    if policy.coefficient_model == CoefficientModel.SIMPLE_MEDIAN:
        fitted = fit_simple_coefficients(
            pairs,
            min_pairs=policy.min_category_pairs,
            min_effective_pairs=policy.min_effective_pairs,
            max_interval_ratio=policy.max_allowed_interval_width,
            method_version=method_version,
            exclude_oe_norm=normalized_target,
        )
    else:
        fitted = fit_shrinkage_coefficients(
            pairs,
            shrinkage_k=policy.shrinkage_k,
            min_category_pairs=policy.min_category_pairs,
            min_global_pairs=policy.min_global_pairs,
            min_effective_pairs=policy.min_effective_pairs,
            max_interval_ratio=policy.max_allowed_interval_width,
            method_version=method_version,
            exclude_oe_norm=normalized_target,
        )
    return {key: value for key, value in fitted.items() if key[0] == category}


async def list_tier_coefficients(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    pricing_run_id: UUID | None,
    category: str | None,
    model: CoefficientModel | None,
    validated: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[TierCoefficientRecord], int]:
    conditions = [TierCoefficientRecord.workspace_id == workspace_id]
    if pricing_run_id is not None:
        conditions.append(TierCoefficientRecord.pricing_run_id == pricing_run_id)
    if category:
        conditions.append(TierCoefficientRecord.category == category)
    if model is not None:
        conditions.append(TierCoefficientRecord.model == model.value)
    if validated is not None:
        conditions.append(TierCoefficientRecord.validated.is_(validated))
    total = int(
        await session.scalar(
            select(func.count(TierCoefficientRecord.id)).where(*conditions)
        )
        or 0
    )
    records = list(
        (
            await session.scalars(
                select(TierCoefficientRecord)
                .where(*conditions)
                .order_by(
                    TierCoefficientRecord.computed_at.desc(),
                    TierCoefficientRecord.category,
                    TierCoefficientRecord.tier,
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return records, total


async def list_recommendations(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    run_id: UUID | None,
    action: str | None,
    confidence_grade: str | None,
    category: str | None,
    queue: str,
    priority_score_type: str | None,
    confidence_min: Decimal | None,
    confidence_max: Decimal | None,
    sort: str,
    limit: int,
    offset: int,
) -> tuple[list[tuple[PricingRecommendation, CatalogItem]], int, UUID | None]:
    if run_id is None:
        run_id = await session.scalar(
            select(PricingRun.id)
            .where(PricingRun.workspace_id == workspace_id)
            .order_by(PricingRun.created_at.desc())
            .limit(1)
        )
        if run_id is None:
            return [], 0, None
    else:
        await get_pricing_run(session, workspace_id=workspace_id, run_id=run_id)
    conditions = [PricingRecommendation.pricing_run_id == run_id]
    if action:
        conditions.append(PricingRecommendation.action == action)
    if confidence_grade:
        conditions.append(PricingRecommendation.confidence_grade == confidence_grade)
    if category:
        conditions.append(CatalogItem.category == category)
    if priority_score_type:
        conditions.append(
            PricingRecommendation.priority_score_type == priority_score_type
        )
    if confidence_min is not None:
        conditions.append(PricingRecommendation.confidence >= confidence_min)
    if confidence_max is not None:
        conditions.append(PricingRecommendation.confidence <= confidence_max)
    if queue == "raise":
        conditions.append(PricingRecommendation.action == "RAISE")
    elif queue == "clearance":
        conditions.extend(
            [
                PricingRecommendation.priority_score_type == "clearance_priority",
                PricingRecommendation.action.in_(("LOWER", "HOLD")),
            ]
        )
    elif queue == "review":
        conditions.append(
            PricingRecommendation.action.in_(("MANUAL_REVIEW", "INSUFFICIENT_DATA"))
        )
    elif queue == "hold":
        conditions.append(PricingRecommendation.action == "HOLD")
    count_statement = (
        select(func.count(PricingRecommendation.id))
        .join(CatalogItem, CatalogItem.id == PricingRecommendation.catalog_item_id)
        .where(*conditions)
    )
    total = int(await session.scalar(count_statement) or 0)
    if sort == "review_priority" or queue == "review":
        order = [PricingRecommendation.review_priority.desc()]
    elif sort == "newest" or queue == "hold":
        order = [PricingRecommendation.computed_at.desc()]
    elif queue == "all":
        score_type_group = case(
            (PricingRecommendation.action == "RAISE", 1),
            (PricingRecommendation.priority_score_type == "clearance_priority", 2),
            (
                PricingRecommendation.action.in_(
                    ("MANUAL_REVIEW", "INSUFFICIENT_DATA")
                ),
                3,
            ),
            else_=4,
        )
        order = [score_type_group, PricingRecommendation.priority_score.desc()]
    else:
        order = [PricingRecommendation.priority_score.desc()]
    rows = list(
        (
            await session.execute(
                select(PricingRecommendation, CatalogItem)
                .join(
                    CatalogItem, CatalogItem.id == PricingRecommendation.catalog_item_id
                )
                .where(*conditions)
                .order_by(*order, PricingRecommendation.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return [(row[0], row[1]) for row in rows], total, run_id


async def get_recommendation(
    session: AsyncSession, *, workspace_id: UUID, recommendation_id: UUID
) -> tuple[PricingRecommendation, CatalogItem]:
    row = (
        await session.execute(
            select(PricingRecommendation, CatalogItem)
            .join(CatalogItem, CatalogItem.id == PricingRecommendation.catalog_item_id)
            .join(PricingRun, PricingRun.id == PricingRecommendation.pricing_run_id)
            .where(
                PricingRecommendation.id == recommendation_id,
                PricingRun.workspace_id == workspace_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise RecommendationNotFoundError(str(recommendation_id))
    return row[0], row[1]


async def get_recommendation_evidence(
    session: AsyncSession, *, workspace_id: UUID, recommendation_id: UUID
) -> list[tuple[MarketObservation, ObservationTierClassification]]:
    recommendation, _ = await get_recommendation(
        session, workspace_id=workspace_id, recommendation_id=recommendation_id
    )
    evidence_ids = [UUID(value) for value in recommendation.evidence_observation_ids]
    if not evidence_ids:
        return []
    rows = list(
        (
            await session.execute(
                select(MarketObservation, ObservationTierClassification)
                .join(
                    ObservationTierClassification,
                    ObservationTierClassification.market_observation_id
                    == MarketObservation.id,
                )
                .where(
                    MarketObservation.pricing_run_item_id
                    == recommendation.pricing_run_item_id,
                    MarketObservation.id.in_(evidence_ids),
                )
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
    return list(latest.values())


async def override_observation_tier(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    observation_id: UUID,
    tier: ProductTier,
    reason: str,
) -> ObservationTierClassification:
    observation = await session.scalar(
        select(MarketObservation)
        .join(
            PricingRunItem, PricingRunItem.id == MarketObservation.pricing_run_item_id
        )
        .join(PricingRun, PricingRun.id == PricingRunItem.pricing_run_id)
        .where(
            MarketObservation.id == observation_id,
            PricingRun.workspace_id == workspace_id,
        )
    )
    if observation is None:
        raise RecommendationNotFoundError(str(observation_id))
    current = await session.scalar(
        select(ObservationTierClassification)
        .where(ObservationTierClassification.market_observation_id == observation_id)
        .order_by(
            ObservationTierClassification.classified_at.desc(),
            ObservationTierClassification.id.desc(),
        )
        .limit(1)
    )
    if not reason.strip():
        raise PricingRunError("Tier override reason is required")
    record = ObservationTierClassification(
        market_observation_id=observation_id,
        tier=tier.value,
        tier_confidence=Decimal("1"),
        is_used=tier == ProductTier.USED,
        is_kemp=tier == ProductTier.KEMP,
        is_owned=current.is_owned if current else False,
        is_dumping=(current.is_dumping if current else False)
        if tier == ProductTier.KEMP
        else False,
        exclusion_reason="USED_OR_REFURBISHED" if tier == ProductTier.USED else None,
        reason_codes=["MANUAL_OVERRIDE", reason.strip()],
        method_version="manual-tier-override-v1",
        override_user_id=user_id,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def add_recommendation_decision(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    recommendation_id: UUID,
    user_id: UUID,
    decision: str,
    new_price: Decimal | None,
    allow_below_cost: bool,
    warning_confirmed: bool,
    reason: str,
) -> RecommendationDecision:
    recommendation, item = await get_recommendation(
        session, workspace_id=workspace_id, recommendation_id=recommendation_id
    )
    if decision not in {"accepted", "rejected", "overridden"}:
        raise PricingRunError("Unknown recommendation decision")
    if decision == "overridden" and (new_price is None or new_price <= 0):
        raise PricingRunError("Override requires a positive new_price")
    if decision == "accepted":
        new_price = recommendation.recommended_price
    elif decision == "rejected":
        new_price = None
        allow_below_cost = False
        warning_confirmed = False
    if not reason.strip():
        raise PricingRunError("Decision reason is required")
    latest_override = await get_latest_override(session, item.id)
    cost = (
        latest_override.cost
        if latest_override and latest_override.cost is not None
        else item.cost
    )
    approved_floor_raw = recommendation.context_snapshot.get("below_cost_floor")
    approved_floor = (
        Decimal(str(approved_floor_raw)) if approved_floor_raw is not None else None
    )
    is_below_cost = _validate_decision_price(
        new_price=new_price,
        cost=cost,
        stock_status=recommendation.context_snapshot.get("stock_status"),
        approved_floor=approved_floor,
        allow_below_cost=allow_below_cost,
        warning_confirmed=warning_confirmed,
    )
    decided_at = datetime.now(UTC)
    record = RecommendationDecision(
        recommendation_id=recommendation_id,
        user_id=user_id,
        decision=decision,
        old_price=recommendation.current_price,
        new_price=new_price,
        cost_snapshot=cost,
        recommended_price_snapshot=recommendation.recommended_price,
        approved_floor=approved_floor,
        allow_below_cost=allow_below_cost,
        reason=reason.strip(),
        warning_confirmed=is_below_cost and warning_confirmed,
        warning_confirmed_at=decided_at
        if is_below_cost and warning_confirmed
        else None,
        context_snapshot=recommendation.context_snapshot,
        policy_version=recommendation.policy_version,
        decided_at=decided_at,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    if is_below_cost:
        pricing_event(
            "below_cost_decision",
            recommendation_id=str(recommendation_id),
            user_id=str(user_id),
            decision=decision,
            new_price=str(new_price),
            approved_floor=str(approved_floor),
        )
    return record


__all__ = [
    "CatalogItemNotFoundError",
    "PARSER_ADAPTER_VERSION",
    "PricingRunError",
    "PricingRunNotFoundError",
    "PricingTaskDispatchError",
    "RecommendationNotFoundError",
    "add_catalog_item_override",
    "add_recommendation_decision",
    "build_pricing_context",
    "calibrate_tier_coefficients",
    "cancel_pricing_run",
    "create_pricing_run",
    "get_latest_override",
    "get_pricing_run",
    "get_recommendation",
    "get_recommendation_evidence",
    "list_tier_coefficients",
    "list_pricing_runs",
    "list_recommendations",
    "load_run_calibration_pairs",
    "load_target_tier_coefficients",
    "load_tier_coefficients",
    "persist_run_calibration_pairs",
    "policy_from_dict",
    "policy_to_dict",
    "override_observation_tier",
]
