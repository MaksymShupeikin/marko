"""Competitor evidence for one product in the owned-store catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    CatalogItem,
    MarketObservation,
    ObservationTierClassification,
    PricingRecommendation,
    PricingRun,
)
from marko.services.catalog_discovery import (
    CatalogDiscoveredOffer,
    CatalogDiscoverySnapshot,
    latest_catalog_discovery,
)
from marko.services.owned_catalog import (
    OwnedCatalogProduct,
    canonical_catalog_sku,
    normalize_catalog_code,
)
from marko.services.pricing_runs import get_recommendation_evidence


@dataclass(frozen=True)
class CatalogCompetitorOffer:
    observation_id: UUID
    seller_id: str
    seller_name: str
    title: str
    url: str
    price: Decimal
    currency: str
    is_available: bool | None
    normalized_price: Decimal | None
    tier: str
    match_confidence: Decimal
    observed_at: datetime


@dataclass(frozen=True)
class CatalogCompetitorComparison:
    recommendation_id: UUID | None
    compared_at: datetime | None
    current_price: Decimal | None
    fair_price: Decimal | None
    recommended_price: Decimal | None
    currency: str | None
    reason_codes: tuple[str, ...]
    items: tuple[CatalogCompetitorOffer, ...]
    discovery_run_id: UUID | None = None
    discovered_at: datetime | None = None
    discovery_query: str | None = None
    discovery_status: str | None = None
    prom_reported_total: int | None = None
    discovered_total: int = 0
    discovery_retrieved_count: int = 0
    discovery_persisted_count: int = 0
    owned_excluded_count: int = 0
    discovery_rejected_count: int = 0
    comparable_count: int = 0
    review_count: int = 0
    skipped_count: int = 0
    selection_histogram: Mapping[str, int] = field(default_factory=dict)
    search_pages_fetched: int = 0
    search_page_limit: int = 0
    unfetched_count: int = 0
    coverage_ratio: Decimal | None = None
    coverage_reason: str | None = None
    selection_method_version: str | None = None
    selection_config_sha256: str | None = None
    brand_rules_dataset_id: str | None = None
    discovery_items: tuple[CatalogDiscoveredOffer, ...] = ()


@dataclass(frozen=True)
class CatalogRecommendationSummary:
    recommended_price: Decimal | None
    currency: str
    action: str
    computed_at: datetime


async def list_catalog_competitors(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    sku: str | None,
    oe: str | None,
    brand: str | None,
) -> CatalogCompetitorComparison:
    """Return only offers that entered the latest price comparison.

    Owned-store observations, reference-only KEMP observations, and rejected
    candidates are intentionally excluded. The owned catalog itself remains
    the source product, never a substitute for competitor evidence.
    """

    discovery = await latest_catalog_discovery(
        session,
        workspace_id=workspace_id,
        sku=sku,
        oe=oe,
        brand=brand,
    )
    match = await _latest_matching_recommendation(
        session,
        workspace_id=workspace_id,
        sku=sku,
        oe=oe,
        brand=brand,
    )
    if match is None:
        return empty_catalog_competitor_comparison(discovery=discovery)

    recommendation, _ = match
    rows = await get_recommendation_evidence(
        session,
        workspace_id=workspace_id,
        recommendation_id=recommendation.id,
    )
    return build_catalog_competitor_comparison(
        recommendation,
        rows,
        discovery=discovery,
    )


async def list_catalog_recommendation_summaries(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    products: tuple[OwnedCatalogProduct, ...],
) -> dict[str, CatalogRecommendationSummary]:
    """Return the latest recommendation matching each visible catalog product."""

    codes = tuple(
        sorted(
            {
                code
                for product in products
                for raw_value in (product.sku, product.oe)
                if (code := normalize_catalog_code(raw_value))
            }
        )
    )
    if not codes:
        return {}

    recommendation_rank = func.row_number().over(
        partition_by=PricingRecommendation.catalog_item_id,
        order_by=(
            PricingRecommendation.computed_at.desc(),
            PricingRecommendation.id.desc(),
        ),
    )
    latest_recommendations = (
        select(
            PricingRecommendation.id.label("recommendation_id"),
            recommendation_rank.label("recommendation_rank"),
        )
        .join(PricingRun, PricingRun.id == PricingRecommendation.pricing_run_id)
        .where(PricingRun.workspace_id == workspace_id)
        .subquery()
    )
    normalized_sku_column = _normalized_identifier_column(CatalogItem.sku)
    rows = list(
        (
            await session.execute(
                select(PricingRecommendation, CatalogItem)
                .select_from(PricingRecommendation)
                .join(
                    latest_recommendations,
                    latest_recommendations.c.recommendation_id
                    == PricingRecommendation.id,
                )
                .join(
                    CatalogItem,
                    CatalogItem.id == PricingRecommendation.catalog_item_id,
                )
                .where(
                    latest_recommendations.c.recommendation_rank == 1,
                    CatalogItem.workspace_id == workspace_id,
                    or_(
                        CatalogItem.oe_norm.in_(codes),
                        CatalogItem.mpn_norm.in_(codes),
                        normalized_sku_column.in_(codes),
                    ),
                )
            )
        ).all()
    )
    return build_catalog_recommendation_summaries(products, rows)


def build_catalog_recommendation_summaries(
    products: tuple[OwnedCatalogProduct, ...],
    rows: list[tuple[PricingRecommendation, CatalogItem]],
) -> dict[str, CatalogRecommendationSummary]:
    summaries: dict[str, CatalogRecommendationSummary] = {}
    for product in products:
        matches = [
            (
                _catalog_item_match_score(
                    item,
                    sku=product.sku,
                    oe=product.oe,
                    brand=product.brand,
                ),
                recommendation,
            )
            for recommendation, item in rows
        ]
        matches = [match for match in matches if match[0] > 0]
        if not matches:
            continue
        _, recommendation = max(
            matches,
            key=lambda match: (
                match[0],
                match[1].computed_at,
                str(match[1].id),
            ),
        )
        summaries[product.id] = CatalogRecommendationSummary(
            recommended_price=recommendation.recommended_price,
            currency=recommendation.currency,
            action=recommendation.action,
            computed_at=recommendation.computed_at,
        )
    return summaries


def empty_catalog_competitor_comparison(
    *,
    discovery: CatalogDiscoverySnapshot | None = None,
) -> CatalogCompetitorComparison:
    return CatalogCompetitorComparison(
        recommendation_id=None,
        compared_at=None,
        current_price=None,
        fair_price=None,
        recommended_price=None,
        currency=None,
        reason_codes=(),
        items=(),
        **_discovery_fields(discovery),
    )


def build_catalog_competitor_comparison(
    recommendation: PricingRecommendation,
    rows: list[tuple[MarketObservation, ObservationTierClassification]],
    *,
    discovery: CatalogDiscoverySnapshot | None = None,
) -> CatalogCompetitorComparison:
    """Build the catalog panel from the recommendation's actual evidence set."""

    rows_by_id = {
        str(observation.id): (observation, tier) for observation, tier in rows
    }
    normalized_by_id = _normalized_prices(recommendation.calculation_trace)
    offers: list[CatalogCompetitorOffer] = []

    for raw_observation_id in recommendation.evidence_observation_ids:
        pair = rows_by_id.get(str(raw_observation_id))
        if pair is None:
            continue
        observation, classification = pair
        if classification.is_owned:
            continue
        if str(classification.cohort_role).upper() != "TARGET_MARKET":
            continue
        offers.append(
            CatalogCompetitorOffer(
                observation_id=observation.id,
                seller_id=observation.seller_id,
                seller_name=observation.seller_name,
                title=observation.title,
                url=observation.url,
                price=observation.price,
                currency=observation.currency,
                is_available=observation.is_available,
                normalized_price=normalized_by_id.get(str(observation.id)),
                tier=classification.tier,
                match_confidence=observation.match_confidence,
                observed_at=observation.observed_at,
            )
        )

    return CatalogCompetitorComparison(
        recommendation_id=recommendation.id,
        compared_at=recommendation.computed_at,
        current_price=recommendation.current_price,
        fair_price=recommendation.fair_price,
        recommended_price=recommendation.recommended_price,
        currency=recommendation.currency,
        reason_codes=tuple(recommendation.reason_codes),
        items=tuple(offers),
        **_discovery_fields(discovery),
    )


def _discovery_fields(
    discovery: CatalogDiscoverySnapshot | None,
) -> dict[str, Any]:
    if discovery is None:
        return {
            "discovery_run_id": None,
            "discovered_at": None,
            "discovery_query": None,
            "discovery_status": None,
            "prom_reported_total": None,
            "discovered_total": 0,
            "discovery_retrieved_count": 0,
            "discovery_persisted_count": 0,
            "owned_excluded_count": 0,
            "discovery_rejected_count": 0,
            "comparable_count": 0,
            "review_count": 0,
            "skipped_count": 0,
            "selection_histogram": {},
            "search_pages_fetched": 0,
            "search_page_limit": 0,
            "unfetched_count": 0,
            "coverage_ratio": None,
            "coverage_reason": None,
            "selection_method_version": None,
            "selection_config_sha256": None,
            "brand_rules_dataset_id": None,
            "discovery_items": (),
        }
    return {
        "discovery_run_id": discovery.run_id,
        "discovered_at": discovery.collected_at,
        "discovery_query": discovery.query,
        "discovery_status": discovery.status,
        "prom_reported_total": discovery.prom_reported_total,
        "discovered_total": len(discovery.items),
        "discovery_retrieved_count": discovery.retrieved_count,
        "discovery_persisted_count": discovery.persisted_count,
        "owned_excluded_count": discovery.owned_excluded_count,
        "discovery_rejected_count": discovery.rejected_count,
        "comparable_count": discovery.comparable_count,
        "review_count": discovery.review_count,
        "skipped_count": discovery.skipped_count,
        "selection_histogram": dict(discovery.selection_histogram),
        "search_pages_fetched": discovery.search_pages_fetched,
        "search_page_limit": discovery.search_page_limit,
        "unfetched_count": discovery.unfetched_count,
        "coverage_ratio": discovery.coverage_ratio,
        "coverage_reason": discovery.coverage_reason,
        "selection_method_version": discovery.selection_method_version,
        "selection_config_sha256": discovery.selection_config_sha256,
        "brand_rules_dataset_id": discovery.brand_rules_dataset_id,
        "discovery_items": discovery.items,
    }


async def _latest_matching_recommendation(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    sku: str | None,
    oe: str | None,
    brand: str | None,
) -> tuple[PricingRecommendation, CatalogItem] | None:
    sku_code = normalize_catalog_code(sku)
    oe_code = normalize_catalog_code(oe)
    codes = {value for value in (sku_code, oe_code) if value}
    if not codes:
        return None

    conditions = []
    normalized_sku_column = _normalized_identifier_column(CatalogItem.sku)
    for code in codes:
        conditions.extend(
            (
                CatalogItem.oe_norm == code,
                CatalogItem.mpn_norm == code,
                normalized_sku_column == code,
            )
        )

    rows = list(
        (
            await session.execute(
                select(PricingRecommendation, CatalogItem)
                .join(
                    CatalogItem, CatalogItem.id == PricingRecommendation.catalog_item_id
                )
                .join(PricingRun, PricingRun.id == PricingRecommendation.pricing_run_id)
                .where(
                    PricingRun.workspace_id == workspace_id,
                    or_(*conditions),
                )
                .order_by(PricingRecommendation.computed_at.desc())
                .limit(100)
            )
        ).all()
    )
    if not rows:
        return None

    return max(
        rows,
        key=lambda row: (
            _catalog_item_match_score(
                row[1],
                sku=sku,
                oe=oe,
                brand=brand,
            ),
            row[0].computed_at,
        ),
    )


def _catalog_item_match_score(
    item: CatalogItem,
    *,
    sku: str | None,
    oe: str | None,
    brand: str | None,
) -> int:
    target_sku = canonical_catalog_sku(sku, brand)
    target_oe = normalize_catalog_code(oe)
    item_sku = canonical_catalog_sku(item.sku, item.brand)
    item_oe = normalize_catalog_code(item.oe_norm)
    item_mpn = normalize_catalog_code(item.mpn_norm)

    score = 0
    if target_oe and item_oe == target_oe:
        score += 16
    if target_oe and item_mpn == target_oe:
        score += 12
    if target_sku and item_sku == target_sku:
        score += 10
    if target_sku and item_oe == target_sku:
        score += 8
    if target_sku and item_mpn == target_sku:
        score += 6
    if normalize_catalog_code(brand) and normalize_catalog_code(
        item.brand
    ) == normalize_catalog_code(brand):
        score += 1
    return score


def _normalized_identifier_column(column: Any) -> Any:
    expression = func.upper(column)
    for character in (" ", "-", ".", "/", "_"):
        expression = func.replace(expression, character, "")
    return expression


def _normalized_prices(trace: Any) -> dict[str, Decimal]:
    if not isinstance(trace, dict):
        return {}
    raw_offers = trace.get("normalized_offers")
    if not isinstance(raw_offers, list):
        return {}
    result: dict[str, Decimal] = {}
    for item in raw_offers:
        if not isinstance(item, dict):
            continue
        observation_id = item.get("observation_id")
        value = item.get("normalized_price")
        if observation_id is None or value is None:
            continue
        try:
            result[str(observation_id)] = Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
    return result


__all__ = [
    "CatalogCompetitorComparison",
    "CatalogCompetitorOffer",
    "CatalogRecommendationSummary",
    "build_catalog_competitor_comparison",
    "build_catalog_recommendation_summaries",
    "empty_catalog_competitor_comparison",
    "list_catalog_competitors",
    "list_catalog_recommendation_summaries",
]
