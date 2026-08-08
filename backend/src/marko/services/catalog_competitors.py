"""Competitor evidence for one product in the owned-store catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    CatalogItem,
    CatalogProduct,
    MarketObservation,
    ObservationTierClassification,
    PricingRecommendation,
    PricingRun,
    PricingRunItem,
)
from marko.services.catalog_discovery import (
    CatalogDiscoveredOffer,
    CatalogDiscoverySnapshot,
    latest_catalog_discovery,
)
from marko.services.catalog_identity_safety import is_internal_catalog_code
from marko.services.owned_catalog import (
    OwnedCatalogProduct,
    canonical_catalog_sku,
    normalize_catalog_code,
)
from marko.services.offer_identity import persisted_identity_fields_consistent
from marko.services.market_price import effective_observation_price
from marko.services.pricing_runs import get_recommendation_evidence
from marko.services.semantic_candidate_gate import semantic_gate_snapshot_is_current


# A recommendation is meaningful only for a catalog identity that was
# resolved by the importer/reparser.  Legacy rows keep ``oe_norm`` populated
# even when that value is a private seller code; allowing those rows into the
# lookup can attach another product's recommendation to the visible catalog
# card.  Keep this allow-list next to the lookup code so a new identity state
# cannot silently become price-bearing.
_MATCHABLE_CATALOG_IDENTITY_STATUSES = frozenset({"OE_CONFIRMED", "MPN_ONLY"})
# A recommendation is a price-bearing artifact.  An MPN-only row may remain
# visible in discovery/manual lookup, but it cannot select or surface a stored
# pricing recommendation until the identity reparser promotes it to a public
# vehicle OE namespace.  Keeping this stricter than the discovery allow-list
# prevents legacy recommendations from being attached to a private KEMP code.
_RECOMMENDATION_CATALOG_IDENTITY_STATUSES = frozenset({"OE_CONFIRMED"})


def _public_lookup_code(value: str | None) -> str:
    """Normalize a lookup key while excluding private KEMP join codes."""

    normalized = normalize_catalog_code(value)
    if not normalized or is_internal_catalog_code(normalized):
        return ""
    return normalized


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
    automatic_eligible: bool = False
    hard_gate_result: str = "MANUAL_REVIEW"
    oe_verification_status: str = "UNKNOWN"
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CatalogCompetitorComparison:
    recommendation_id: UUID | None
    compared_at: datetime | None
    current_price: Decimal | None
    fair_price: Decimal | None
    confidence_grade: str | None
    dispersion: Decimal | None
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
    pricing_evidence_count: int = 0
    reference_only_count: int = 0
    rejected_candidate_count: int = 0
    selection_histogram: Mapping[str, int] = field(default_factory=dict)
    search_pages_fetched: int = 0
    search_page_limit: int = 0
    unfetched_count: int = 0
    coverage_ratio: Decimal | None = None
    coverage_reason: str | None = None
    selection_method_version: str | None = None
    selection_config_sha256: str | None = None
    brand_rules_dataset_id: str | None = None
    # Everything the run produced, rejected candidates included, for the
    # diagnostic view.
    discovery_items: tuple[CatalogDiscoveredOffer, ...] = ()
    # The two customer-facing lists.  They are built here rather than in the
    # client so that "counts towards the price" is decided once, on the server,
    # next to the gate chain that decided it.
    pricing_evidence: tuple[CatalogDiscoveredOffer, ...] = ()
    reference_only: tuple[CatalogDiscoveredOffer, ...] = ()
    # Offers already retained by the automatic run but not used by a finished
    # recommendation.  Keeping these separate prevents the UI from claiming
    # that a fuzzy search hit affected the price while still making collection
    # progress and rejection reasons visible immediately.
    candidate_items: tuple[CatalogCompetitorOffer, ...] = ()
    collection_status: str | None = None


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
    product_id: UUID | None = None,
    sku: str | None,
    oe: str | None,
    brand: str | None,
    mpn: str | None = None,
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
        mpn=mpn,
        brand=brand,
    )
    candidate_items, collection_status = await _latest_observed_candidates(
        session,
        workspace_id=workspace_id,
        product_id=product_id,
        sku=sku,
        oe=oe,
    )
    match = await _latest_matching_recommendation(
        session,
        workspace_id=workspace_id,
        product_id=product_id,
        sku=sku,
        oe=oe,
        mpn=mpn,
        brand=brand,
    )
    if match is None:
        return empty_catalog_competitor_comparison(
            discovery=discovery,
            candidate_items=candidate_items,
            collection_status=collection_status,
        )

    recommendation, _ = match
    rows = await get_recommendation_evidence(
        session,
        workspace_id=workspace_id,
        recommendation_id=recommendation.id,
    )
    comparison = build_catalog_competitor_comparison(
        recommendation,
        rows,
        discovery=discovery,
    )
    evidence_ids = {item.observation_id for item in comparison.items}
    return replace(
        comparison,
        candidate_items=tuple(
            item for item in candidate_items if item.observation_id not in evidence_ids
        ),
        collection_status=collection_status,
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
                for raw_value in (
                    product.oe,
                    getattr(product, "mpn", None),
                    product.sku,
                )
                if (code := _public_lookup_code(raw_value))
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
                    CatalogItem.identity_status.in_(_RECOMMENDATION_CATALOG_IDENTITY_STATUSES),
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
        selected = _select_unique_best_recommendation(
            rows,
            sku=product.sku,
            oe=product.oe,
            mpn=getattr(product, "mpn", None),
            brand=product.brand,
        )
        if selected is None:
            continue
        recommendation, _item = selected
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
    candidate_items: tuple[CatalogCompetitorOffer, ...] = (),
    collection_status: str | None = None,
) -> CatalogCompetitorComparison:
    return CatalogCompetitorComparison(
        recommendation_id=None,
        compared_at=None,
        current_price=None,
        fair_price=None,
        confidence_grade=None,
        dispersion=None,
        recommended_price=None,
        currency=None,
        reason_codes=(),
        items=(),
        candidate_items=candidate_items,
        collection_status=collection_status,
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
        if (
            classification.is_owned
            or getattr(classification, "is_kemp", False)
            or getattr(classification, "is_used", False)
            or getattr(classification, "is_dumping", False)
            or getattr(classification, "exclusion_reason", None)
        ):
            continue
        if str(classification.cohort_role).upper() != "TARGET_MARKET":
            continue
        # ``evidence_observation_ids`` is an output of the calculation, not an
        # authority by itself.  A stale recommendation or a hand-built replay
        # can carry an old id after its observation was demoted.  Re-apply the
        # persisted admission contract at the API presentation boundary so the
        # catalog panel cannot show a false price-bearing competitor.
        if (
            getattr(observation, "automatic_eligible", False) is not True
            or getattr(observation, "comparability_hard_gate_result", "")
            != "PASS"
            or getattr(observation, "oe_verification_status", "")
            not in {"VERIFIED_EXACT", "VERIFIED_CROSS"}
            or getattr(observation, "seller_identity_verified", False) is not True
            or getattr(observation, "source_provenance_verified", False) is not True
            or not persisted_identity_fields_consistent(observation)
            or not semantic_gate_snapshot_is_current(
                getattr(observation, "candidate_snapshot", None),
                expected_source_listing_id=getattr(
                    observation, "source_listing_id", None
                ),
                expected_raw_capture_id=getattr(observation, "raw_capture_id", None),
                expected_identity_key=getattr(
                    observation, "comparison_identity_key", None
                ),
                require_identity_namespace=(
                    getattr(observation, "catalog_item_id", None) is not None
                ),
            )
        ):
            continue
        offers.append(
            CatalogCompetitorOffer(
                observation_id=observation.id,
                seller_id=observation.seller_id,
                seller_name=observation.seller_name,
                title=observation.title,
                url=observation.url,
                price=effective_observation_price(observation),
                currency=observation.currency,
                is_available=observation.is_available,
                normalized_price=normalized_by_id.get(str(observation.id)),
                tier=classification.tier,
                match_confidence=observation.match_confidence,
                observed_at=observation.observed_at,
                automatic_eligible=bool(
                    getattr(observation, "automatic_eligible", False)
                ),
                hard_gate_result=str(
                    getattr(
                        observation,
                        "comparability_hard_gate_result",
                        "MANUAL_REVIEW",
                    )
                ),
                oe_verification_status=str(
                    getattr(observation, "oe_verification_status", "UNKNOWN")
                ),
                reason_codes=_observation_reason_codes(observation),
            )
        )

    return CatalogCompetitorComparison(
        recommendation_id=recommendation.id,
        compared_at=recommendation.computed_at,
        current_price=recommendation.current_price,
        fair_price=recommendation.fair_price,
        confidence_grade=recommendation.confidence_grade,
        dispersion=recommendation.dispersion,
        recommended_price=recommendation.recommended_price,
        currency=recommendation.currency,
        reason_codes=tuple(recommendation.reason_codes),
        items=tuple(offers),
        **_discovery_fields(discovery),
    )


async def _latest_observed_candidates(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    product_id: UUID | None,
    sku: str | None,
    oe: str | None,
) -> tuple[tuple[CatalogCompetitorOffer, ...], str | None]:
    """Return retained automatic-run candidates before recommendation finality."""

    run_item_query = (
        select(PricingRunItem)
        .join(PricingRun, PricingRun.id == PricingRunItem.pricing_run_id)
        .join(CatalogItem, CatalogItem.id == PricingRunItem.catalog_item_id)
        .where(PricingRun.workspace_id == workspace_id)
        .order_by(PricingRun.created_at.desc(), PricingRunItem.created_at.desc())
        .limit(1)
    )
    if product_id is not None:
        product = await session.scalar(
            select(CatalogProduct).where(
                CatalogProduct.id == product_id,
                CatalogProduct.workspace_id == workspace_id,
            )
        )
        if product is None or product.catalog_item_id is None:
            return (), None
        run_item_query = run_item_query.where(
            PricingRunItem.catalog_item_id == product.catalog_item_id
        )
    else:
        codes = {
            value
            for raw in (sku, oe)
            if (value := normalize_catalog_code(raw))
        }
        if not codes:
            return (), None
        normalized_sku_column = _normalized_identifier_column(CatalogItem.sku)
        run_item_query = run_item_query.where(
            or_(
                CatalogItem.oe_norm.in_(codes),
                CatalogItem.mpn_norm.in_(codes),
                normalized_sku_column.in_(codes),
            )
        )

    run_item = await session.scalar(run_item_query)
    if run_item is None:
        return (), None
    rows = list(
        (
            await session.execute(
                select(MarketObservation, ObservationTierClassification)
                .join(
                    ObservationTierClassification,
                    ObservationTierClassification.market_observation_id
                    == MarketObservation.id,
                )
                .where(MarketObservation.pricing_run_item_id == run_item.id)
                .order_by(
                    MarketObservation.id,
                    ObservationTierClassification.classified_at.desc(),
                    ObservationTierClassification.id.desc(),
                )
            )
        ).all()
    )
    latest_by_observation: dict[
        UUID, tuple[MarketObservation, ObservationTierClassification]
    ] = {}
    for observation, classification in rows:
        latest_by_observation.setdefault(
            observation.id,
            (observation, classification),
        )
    offers = [
        CatalogCompetitorOffer(
            observation_id=observation.id,
            seller_id=observation.seller_id,
            seller_name=observation.seller_name,
            title=observation.title,
            url=observation.url,
            price=observation.price,
            currency=observation.currency,
            is_available=observation.is_available,
            normalized_price=None,
            tier=classification.tier,
            match_confidence=observation.match_confidence,
            observed_at=observation.observed_at,
            automatic_eligible=observation.automatic_eligible,
            hard_gate_result=observation.comparability_hard_gate_result,
            oe_verification_status=observation.oe_verification_status,
            reason_codes=_observation_reason_codes(observation),
        )
        for observation, classification in latest_by_observation.values()
        if not classification.is_owned
    ]
    offers.sort(key=lambda item: (item.price, item.seller_name.casefold()))
    return tuple(offers), run_item.status


def _observation_reason_codes(observation: MarketObservation) -> tuple[str, ...]:
    evidence = getattr(observation, "comparison_evidence", None)
    if not isinstance(evidence, Mapping):
        return ()
    values = evidence.get("reason_codes")
    if not isinstance(values, list):
        return ()
    return tuple(str(value) for value in values if str(value).strip())


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
            "pricing_evidence_count": 0,
            "reference_only_count": 0,
            "rejected_candidate_count": 0,
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
            "pricing_evidence": (),
            "reference_only": (),
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
        # ``CatalogDiscoverySnapshot`` is a retrieval-only surface.  Do not
        # trust a hand-built/legacy snapshot that still carries the old
        # PRICING_EVIDENCE label; only recommendation evidence in ``items``
        # can affect a fair price.
        "pricing_evidence_count": 0,
        "reference_only_count": sum(
            item.selection_status != "REJECTED" for item in discovery.items
        ),
        "rejected_candidate_count": discovery.rejected_candidate_count,
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
        "pricing_evidence": (),
        "reference_only": tuple(
            item
            for item in discovery.items
            if item.selection_status != "REJECTED"
        ),
    }


async def _latest_matching_recommendation(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    product_id: UUID | None = None,
    sku: str | None,
    oe: str | None,
    brand: str | None,
    mpn: str | None = None,
) -> tuple[PricingRecommendation, CatalogItem] | None:
    if product_id is not None:
        direct = (
            await session.execute(
                select(PricingRecommendation, CatalogItem)
                .join(
                    CatalogItem,
                    CatalogItem.id == PricingRecommendation.catalog_item_id,
                )
                .join(
                    PricingRun,
                    PricingRun.id == PricingRecommendation.pricing_run_id,
                )
                .join(
                    CatalogProduct,
                    CatalogProduct.catalog_item_id == CatalogItem.id,
                )
                .where(
                    CatalogProduct.id == product_id,
                    CatalogProduct.workspace_id == workspace_id,
                    PricingRun.workspace_id == workspace_id,
                )
                .order_by(PricingRecommendation.computed_at.desc())
                .limit(1)
            )
        ).one_or_none()
        if direct is not None:
            return direct

    sku_code = _public_lookup_code(sku)
    oe_code = _public_lookup_code(oe)
    mpn_code = _public_lookup_code(mpn)
    codes = {value for value in (sku_code, oe_code, mpn_code) if value}
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
                    CatalogItem.identity_status.in_(_RECOMMENDATION_CATALOG_IDENTITY_STATUSES),
                    or_(*conditions),
                )
                .order_by(PricingRecommendation.computed_at.desc())
                .limit(100)
            )
        ).all()
    )
    if not rows:
        return None

    return _select_unique_best_recommendation(
        rows,
        sku=sku,
        oe=oe,
        mpn=mpn,
        brand=brand,
    )


def _select_unique_best_recommendation(
    rows: list[tuple[Any, CatalogItem]] | tuple[tuple[Any, CatalogItem], ...],
    *,
    sku: str | None,
    oe: str | None,
    brand: str | None,
    mpn: str | None = None,
) -> tuple[Any, CatalogItem] | None:
    """Choose a recommendation only when the catalog identity is unique.

    Normalized OE values can intentionally occur on more than one imported
    row (for example a collision, variant or duplicate listing). Selecting the
    newest row on a score tie silently attaches another product's price to the
    requested card. Precision wins: an unresolved tie returns no
    recommendation and leaves the operator with the manual/discovery path.
    """

    # This helper is a price-bearing selection boundary, not the broader
    # discovery matcher.  Keep MPN_ONLY rows available to explicit manual
    # lookup through ``_catalog_item_match_score`` but never let one select a
    # persisted recommendation by itself.
    recommendation_rows = [
        (recommendation, item)
        for recommendation, item in rows
        if str(getattr(item, "identity_status", "UNRESOLVED") or "UNRESOLVED")
        .strip()
        .upper()
        in _RECOMMENDATION_CATALOG_IDENTITY_STATUSES
    ]
    scored = [
        (
            _catalog_item_match_score(
                item,
                sku=sku,
                oe=oe,
                mpn=mpn,
                brand=brand,
            ),
            recommendation,
            item,
        )
        for recommendation, item in recommendation_rows
    ]
    scored = [entry for entry in scored if entry[0] > 0]
    if not scored:
        return None
    best_score = max(entry[0] for entry in scored)
    best = [entry for entry in scored if entry[0] == best_score]
    item_keys = {
        str(getattr(item, "id", id(item)))
        for _score, _recommendation, item in best
    }
    if len(item_keys) > 1:
        return None
    _score, recommendation, item = max(
        best,
        key=lambda entry: (
            getattr(entry[1], "computed_at", None),
            str(getattr(entry[1], "id", "")),
        ),
    )
    return recommendation, item


def _catalog_item_match_score(
    item: CatalogItem,
    *,
    sku: str | None,
    oe: str | None,
    brand: str | None,
    mpn: str | None = None,
) -> int:
    identity_status = str(
        getattr(item, "identity_status", "UNRESOLVED") or "UNRESOLVED"
    ).strip().upper()
    if identity_status not in _MATCHABLE_CATALOG_IDENTITY_STATUSES:
        return 0

    target_sku = _public_lookup_code(canonical_catalog_sku(sku, brand))
    target_oe = _public_lookup_code(oe)
    target_mpn = _public_lookup_code(mpn)
    item_sku = _public_lookup_code(canonical_catalog_sku(item.sku, item.brand))
    # ``oe_norm`` is not an OE in the MPN_ONLY namespace.  It may contain the
    # seller's private KEMP code, so it must never be used as a cross-field
    # match or as a fallback for the visible product card.
    item_oe = (
        _public_lookup_code(item.oe_norm)
        if identity_status == "OE_CONFIRMED"
        else ""
    )
    item_mpn = _public_lookup_code(item.mpn_norm)

    score = 0
    if target_oe and identity_status == "OE_CONFIRMED" and item_oe == target_oe:
        score += 16
    if target_mpn and item_mpn == target_mpn:
        score += 14
    if target_mpn and item_oe == target_mpn:
        score += 10
    if target_sku and item_sku == target_sku:
        score += 10
    if target_sku and item_oe == target_sku:
        score += 8
    if target_sku and item_mpn == target_sku:
        score += 6
    # Brand is a tie-breaker only.  It must never create a positive match on
    # its own when the requested identity is absent or belongs to another
    # namespace.
    if score and normalize_catalog_code(brand) and normalize_catalog_code(
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
