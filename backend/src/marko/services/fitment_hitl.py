"""Persistence boundary for fitment-bound human pricing recommendations."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    CatalogItem,
    FitmentAnalysis,
    FitmentAuditEvent,
    FitmentCandidateAssessment,
    FitmentFeedbackEvent,
    FitmentMarketRecommendation,
    FitmentNotification,
    FitmentRecommendationReview,
    MarketObservation,
)
from metis.fitment import (
    FeedbackReason,
    HITL_MARKET_CONTRACT_VERSION,
    HITL_RECOMMENDATION_VERSION,
    PricingStrategy,
    RecommendationDecision,
    WeightedMarketOffer,
    build_robust_market_statistics,
    normalize_part_number,
    recommend_market_price,
)

from .fitment_intelligence import (
    FitmentIdempotencyConflict,
    FitmentIntelligenceError,
    FitmentNotFoundError,
)
from marko.services.market_price import effective_observation_price


HITL_FEEDBACK_LABEL_VERSION = "fitment-hitl-feedback-v1"


async def generate_fitment_recommendation(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    analysis_id: UUID,
    catalog_item_id: UUID,
    idempotency_key: str,
    strategy: PricingStrategy,
    approved_price_floor: Decimal | None,
    absolute_buffer: Decimal,
    percentage_buffer: Decimal,
    max_decrease_rate: Decimal,
    max_increase_rate: Decimal,
    deadband: Decimal,
    minimum_confidence: Decimal,
    price_tick: Decimal,
    custom_anchor: Decimal | None,
) -> FitmentMarketRecommendation:
    """Generate and persist one immutable advisory result.

    Only assessments already admitted by fitment and price-comparability gates
    enter the market distribution.  Raw cost is intentionally not accepted at
    this boundary; callers may provide only an approved derived floor.
    """

    key = _idempotency_key(idempotency_key)
    analysis = await session.get(FitmentAnalysis, analysis_id)
    if analysis is None or analysis.workspace_id != workspace_id:
        raise FitmentNotFoundError("fitment analysis not found")
    if analysis.catalog_item_id != catalog_item_id:
        raise FitmentNotFoundError("analysis does not belong to catalog item")
    if analysis.status != "completed":
        raise FitmentIntelligenceError("fitment analysis is not complete")
    item = await session.get(CatalogItem, analysis.catalog_item_id)
    if item is None or item.workspace_id != workspace_id:
        raise FitmentNotFoundError("catalog item not found")
    # Fitment recommendations are a price-bearing boundary too.  A legacy
    # analysis whose target was a supplier article must not produce a market
    # price for the catalog item: the authoritative target is the original
    # vehicle OE persisted by the catalog identity graph.
    identity_status = str(
        getattr(item, "identity_status", "UNRESOLVED") or "UNRESOLVED"
    ).strip().upper()
    if identity_status != "OE_CONFIRMED":
        raise FitmentIntelligenceError(
            "fitment recommendation requires a confirmed original OE"
        )
    catalog_oe = normalize_part_number(str(getattr(item, "oe_norm", "") or ""))
    target_oes = {
        normalized
        for raw in analysis.target_identity.get("oe_numbers", [])
        if (normalized := normalize_part_number(str(raw))) is not None
    }
    if catalog_oe is None or catalog_oe not in target_oes:
        raise FitmentIntelligenceError(
            "fitment recommendation target does not contain the catalog OE"
        )

    existing = await session.scalar(
        select(FitmentMarketRecommendation).where(
            FitmentMarketRecommendation.workspace_id == workspace_id,
            FitmentMarketRecommendation.idempotency_key == key,
        )
    )
    if existing is not None:
        if existing.analysis_id != analysis_id:
            raise FitmentIdempotencyConflict(
                "recommendation idempotency key belongs to another analysis"
            )
        return existing

    rows = list(
        (
            await session.execute(
                select(FitmentCandidateAssessment, MarketObservation)
                .join(
                    MarketObservation,
                    MarketObservation.id
                    == FitmentCandidateAssessment.market_observation_id,
                )
                .where(FitmentCandidateAssessment.analysis_id == analysis_id)
                .order_by(FitmentCandidateAssessment.id)
            )
        ).all()
    )
    market_offers: list[WeightedMarketOffer] = []
    snapshot_rows: list[dict[str, Any]] = []
    for assessment, observation in rows:
        trace = assessment.price_factor_trace or {}
        identity = assessment.candidate_identity or {}
        commercial = assessment.candidate_commercial_context or {}
        normalized_price = assessment.normalized_unit_price
        candidate_snapshot = {
            "assessment_id": str(assessment.id),
            "observation_id": str(observation.id),
            "seller_id": observation.seller_id,
            "sale_price": str(effective_observation_price(observation)),
            "reference_price": (
                str(observation.reference_price)
                if observation.reference_price is not None
                else None
            ),
            "normalized_unit_price": (
                str(normalized_price) if normalized_price is not None else None
            ),
            "price_unit_status": assessment.price_unit_status,
            "price_eligible": assessment.price_eligible,
            "price_reason_codes": list(assessment.price_reason_codes),
        }
        snapshot_rows.append(candidate_snapshot)
        if not assessment.price_eligible or normalized_price is None:
            continue
        article = str(identity.get("manufacturer_article") or "").strip()
        brand = str(identity.get("manufacturer_brand") or observation.brand_raw or "").strip()
        part_key = str(commercial.get("product_identity_key") or "").strip()
        if not part_key:
            part_key = f"{brand.casefold()}:{article.casefold()}"
        seller_group = str(commercial.get("seller_group_id") or "").strip()
        if not part_key or part_key == ":" or not seller_group:
            # A missing stable identity/group must not increase effective sample size.
            continue
        tier_factor = _decimal(trace.get("tier"), Decimal("0"))
        condition_factor = _decimal(trace.get("condition"), Decimal("0"))
        price_comparability = tier_factor * condition_factor
        market_offers.append(
            WeightedMarketOffer(
                offer_id=str(assessment.id),
                normalized_unit_price=Decimal(normalized_price),
                fitment_score=Decimal(assessment.compatibility_probability),
                price_comparability=_bounded(price_comparability),
                source_quality=_bounded(_decimal(trace.get("source_quality"))),
                availability_factor=_bounded(_decimal(trace.get("availability"))),
                freshness_factor=_bounded(_decimal(trace.get("freshness"))),
                seller_independence_factor=_bounded(
                    _decimal(trace.get("seller_independence"))
                ),
                unit_certainty=_bounded(Decimal(assessment.price_unit_certainty)),
                part_identity_key=part_key,
                seller_group_id=seller_group,
                preserve_if_outlier=bool(
                    assessment.authoritative_confirmation
                    and identity.get("manufacturer_article")
                    and identity.get("manufacturer_article")
                    == analysis.target_identity.get("manufacturer_article")
                ),
                metadata={
                    "seller_id": observation.seller_id,
                    "source_listing_id": observation.source_listing_id,
                },
            )
        )

    market = build_robust_market_statistics(market_offers)
    recommendation = recommend_market_price(
        current_price=Decimal(item.current_price),
        currency=item.currency,
        market=market,
        strategy=strategy,
        approved_price_floor=approved_price_floor,
        absolute_buffer=absolute_buffer,
        percentage_buffer=percentage_buffer,
        max_decrease_rate=max_decrease_rate,
        max_increase_rate=max_increase_rate,
        deadband=deadband,
        minimum_confidence=minimum_confidence,
        price_tick=price_tick,
        custom_anchor=custom_anchor,
    )
    config = {
        "strategy": strategy.value,
        "approved_price_floor": _json_safe(approved_price_floor),
        "absolute_buffer": str(absolute_buffer),
        "percentage_buffer": str(percentage_buffer),
        "max_decrease_rate": str(max_decrease_rate),
        "max_increase_rate": str(max_increase_rate),
        "deadband": str(deadband),
        "minimum_confidence": str(minimum_confidence),
        "price_tick": str(price_tick),
        "custom_anchor": _json_safe(custom_anchor),
        "raw_cost_transmitted": False,
    }
    input_fingerprint = _sha256(
        {
            "analysis_id": analysis_id,
            "analysis_request_sha256": analysis.request_sha256,
            "scoring_version": analysis.scoring_version,
            "catalog_price": item.current_price,
            "currency": item.currency,
            "candidates": snapshot_rows,
            "configuration": config,
            "recommendation_version": HITL_RECOMMENDATION_VERSION,
        }
    )
    same_snapshot = await session.scalar(
        select(FitmentMarketRecommendation).where(
            FitmentMarketRecommendation.analysis_id == analysis_id,
            FitmentMarketRecommendation.input_fingerprint == input_fingerprint,
        )
    )
    if same_snapshot is not None:
        return same_snapshot

    confidence = recommendation.confidence
    record = FitmentMarketRecommendation(
        id=uuid4(),
        workspace_id=workspace_id,
        analysis_id=analysis_id,
        catalog_item_id=item.id,
        created_by=actor_user_id,
        idempotency_key=key,
        input_fingerprint=input_fingerprint,
        action=recommendation.action.value,
        strategy=recommendation.strategy.value,
        current_price=recommendation.current_price,
        recommended_price=recommendation.recommended_price,
        recommended_range_min=recommendation.recommended_range_min,
        recommended_range_max=recommendation.recommended_range_max,
        absolute_change=recommendation.absolute_change,
        relative_change=recommendation.relative_change,
        market_anchor=recommendation.market_anchor,
        approved_price_floor=recommendation.price_floor,
        currency=recommendation.currency,
        confidence=confidence.value,
        confidence_factors={
            "fitment": str(confidence.fitment),
            "source": str(confidence.source),
            "freshness": str(confidence.freshness),
            "sample": str(confidence.sample),
            "diversity": str(confidence.diversity),
            "stability": str(confidence.stability),
            "completeness": str(confidence.completeness),
        },
        market_summary={
            "collected_offers": len(rows),
            "commercially_eligible_offers": market.eligible_offer_count,
            "included_offers": market.included_offer_count,
            "outlier_count": market.outlier_count,
            "unique_part_identities": market.unique_part_identities,
            "independent_seller_groups": market.independent_seller_groups,
            "effective_sample_size": str(market.effective_sample_size),
            "total_weight": str(market.total_weight),
        },
        price_statistics={
            "weighted_min": _json_safe(market.weighted_min),
            "weighted_q20": _json_safe(market.weighted_q20),
            "weighted_q25": _json_safe(market.weighted_q25),
            "weighted_q35": _json_safe(market.weighted_q35),
            "weighted_median": _json_safe(market.weighted_median),
            "weighted_q75": _json_safe(market.weighted_q75),
            "weighted_q80": _json_safe(market.weighted_q80),
            "weighted_max": _json_safe(market.weighted_max),
            "weighted_log_mad": _json_safe(market.weighted_log_mad),
            "log_price_iqr": _json_safe(market.log_price_iqr),
        },
        candidate_decisions=[_json_safe(value) for value in market.decisions],
        reason_codes=list(recommendation.reason_codes),
        warnings=list(recommendation.warnings),
        configuration_snapshot=config,
        contract_version=HITL_MARKET_CONTRACT_VERSION,
        recommendation_version=HITL_RECOMMENDATION_VERSION,
        automatic_price_change_allowed=False,
    )
    session.add(record)
    await session.flush()
    notification = FitmentNotification(
        workspace_id=workspace_id,
        recommendation_id=record.id,
        notification_type="price_review_recommended",
        group_key=f"fitment-review:{datetime.now(UTC).date().isoformat()}",
        payload={
            "notification_type": "price_review_recommended",
            "product_id": str(item.id),
            "current_price": str(record.current_price),
            "recommended_price": _json_safe(record.recommended_price),
            "recommended_range": [
                _json_safe(record.recommended_range_min),
                _json_safe(record.recommended_range_max),
            ],
            "confidence": str(record.confidence),
            "reason_summary": record.reason_codes[0] if record.reason_codes else None,
            "review_url": f"/fitment/recommendations/{record.id}",
        },
        status="pending",
    )
    session.add(notification)
    analysis.workflow_state = "NOTIFIED"
    session.add(
        _audit_event(
            workspace_id=workspace_id,
            event_type="fitment_market_recommendation_created",
            entity_type="fitment_market_recommendation",
            entity_id=str(record.id),
            actor_user_id=actor_user_id,
            payload={
                "analysis_id": str(analysis_id),
                "action": record.action,
                "confidence": str(record.confidence),
                "input_fingerprint": input_fingerprint,
                "automatic_price_change_allowed": False,
            },
        )
    )
    await session.commit()
    await session.refresh(record)
    return record


async def get_fitment_recommendation(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    catalog_item_id: UUID,
    recommendation_id: UUID | None = None,
) -> FitmentMarketRecommendation | None:
    filters = [
        FitmentMarketRecommendation.workspace_id == workspace_id,
        FitmentMarketRecommendation.catalog_item_id == catalog_item_id,
    ]
    if recommendation_id is not None:
        filters.append(FitmentMarketRecommendation.id == recommendation_id)
    return await session.scalar(
        select(FitmentMarketRecommendation)
        .where(*filters)
        .order_by(
            FitmentMarketRecommendation.created_at.desc(),
            FitmentMarketRecommendation.id.desc(),
        )
        .limit(1)
    )


async def review_fitment_recommendation(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    recommendation_id: UUID,
    idempotency_key: str,
    decision: RecommendationDecision,
    approved_price: Decimal | None,
    reason_code: FeedbackReason,
    comment: str | None,
    allow_below_floor: bool,
    below_floor_warning_confirmed: bool,
) -> FitmentRecommendationReview:
    key = _idempotency_key(idempotency_key)
    recommendation = await session.get(FitmentMarketRecommendation, recommendation_id)
    if recommendation is None or recommendation.workspace_id != workspace_id:
        raise FitmentNotFoundError("fitment recommendation not found")
    existing = await session.scalar(
        select(FitmentRecommendationReview).where(
            FitmentRecommendationReview.workspace_id == workspace_id,
            FitmentRecommendationReview.idempotency_key == key,
        )
    )
    if existing is not None:
        if (
            existing.recommendation_id != recommendation_id
            or existing.decision != decision.value
        ):
            raise FitmentIdempotencyConflict(
                "review idempotency key belongs to another decision"
            )
        return existing

    final_price = approved_price
    if decision == RecommendationDecision.ACCEPTED:
        final_price = recommendation.recommended_price
    if decision in {
        RecommendationDecision.ACCEPTED,
        RecommendationDecision.ACCEPTED_WITH_MODIFICATION,
    }:
        if final_price is None or final_price <= 0:
            raise FitmentIntelligenceError("accepted decision requires a positive price")
        floor = recommendation.approved_price_floor
        if floor is not None and final_price < floor:
            if not allow_below_floor or not below_floor_warning_confirmed:
                raise FitmentIntelligenceError(
                    "price below approved floor requires explicit warning confirmation"
                )
    elif approved_price is not None:
        raise FitmentIntelligenceError(
            "non-acceptance decision cannot contain approved_price"
        )

    snapshot = {
        "recommendation_id": str(recommendation.id),
        "analysis_id": str(recommendation.analysis_id),
        "input_fingerprint": recommendation.input_fingerprint,
        "system_action": recommendation.action,
        "system_recommended_price": _json_safe(recommendation.recommended_price),
        "approved_price": _json_safe(final_price),
        "confidence": str(recommendation.confidence),
        "automatic_marketplace_publication": False,
        "allow_below_floor": allow_below_floor,
        "below_floor_warning_confirmed": below_floor_warning_confirmed,
    }
    review = FitmentRecommendationReview(
        workspace_id=workspace_id,
        recommendation_id=recommendation.id,
        reviewer_id=actor_user_id,
        idempotency_key=key,
        decision=decision.value,
        approved_price=final_price,
        reason_code=reason_code.value,
        comment=comment.strip() if comment else None,
        recommendation_snapshot=snapshot,
    )
    session.add(review)
    await session.flush()
    feedback = FitmentFeedbackEvent(
        workspace_id=workspace_id,
        reviewer_id=actor_user_id,
        idempotency_key=_sha256({"review": review.id, "kind": "price_feedback"}),
        entity_type="fitment_market_recommendation",
        entity_id=str(recommendation.id),
        event_type="price_recommendation_decision",
        reason_code=reason_code.value,
        label_payload={
            "decision": decision.value,
            "system_action": recommendation.action,
            "system_price": _json_safe(recommendation.recommended_price),
            "human_price": _json_safe(final_price),
            "blind_online_learning_allowed": False,
        },
        status="active",
        label_version=HITL_FEEDBACK_LABEL_VERSION,
    )
    session.add(feedback)
    analysis = await session.get(FitmentAnalysis, recommendation.analysis_id)
    if analysis is not None:
        analysis.workflow_state = {
            RecommendationDecision.ACCEPTED: "ACCEPTED",
            RecommendationDecision.ACCEPTED_WITH_MODIFICATION: "ACCEPTED_WITH_MODIFICATION",
            RecommendationDecision.REJECTED: "REJECTED",
            RecommendationDecision.DEFERRED: "DEFERRED",
            RecommendationDecision.RESEARCH_REQUESTED: "RESEARCH_REQUESTED",
        }[decision]
    session.add(
        _audit_event(
            workspace_id=workspace_id,
            event_type="fitment_recommendation_reviewed",
            entity_type="fitment_market_recommendation",
            entity_id=str(recommendation.id),
            actor_user_id=actor_user_id,
            payload={
                "decision": decision.value,
                "approved_price": _json_safe(final_price),
                "reason_code": reason_code.value,
                "automatic_marketplace_publication": False,
            },
        )
    )
    await session.commit()
    await session.refresh(review)
    return review


async def list_fitment_notifications(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    notification_status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[FitmentNotification], int]:
    filters = [FitmentNotification.workspace_id == workspace_id]
    if notification_status is not None:
        if notification_status not in {"pending", "delivered", "read", "dismissed"}:
            raise FitmentIntelligenceError("invalid notification status")
        filters.append(FitmentNotification.status == notification_status)
    total = int(
        await session.scalar(select(func.count(FitmentNotification.id)).where(*filters))
        or 0
    )
    rows = list(
        (
            await session.scalars(
                select(FitmentNotification)
                .where(*filters)
                .order_by(
                    FitmentNotification.created_at.desc(),
                    FitmentNotification.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return rows, total


async def mark_fitment_notification_read(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor_user_id: UUID,
    notification_id: UUID,
) -> FitmentNotification:
    notification = await session.get(FitmentNotification, notification_id)
    if notification is None or notification.workspace_id != workspace_id:
        raise FitmentNotFoundError("fitment notification not found")
    if notification.status == "read":
        return notification
    if notification.status == "dismissed":
        raise FitmentIntelligenceError("dismissed notification cannot become read")
    notification.status = "read"
    session.add(
        _audit_event(
            workspace_id=workspace_id,
            event_type="fitment_notification_read",
            entity_type="fitment_notification",
            entity_id=str(notification.id),
            actor_user_id=actor_user_id,
            payload={"recommendation_id": str(notification.recommendation_id)},
        )
    )
    await session.commit()
    await session.refresh(notification)
    return notification


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (ValueError, TypeError):
        return default
    return parsed if parsed.is_finite() else default


def _bounded(value: Decimal) -> Decimal:
    return max(Decimal("0"), min(value, Decimal("1")))


def _idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 64:
        raise FitmentIntelligenceError("idempotency_key must contain 1-64 characters")
    return normalized


def _audit_event(
    *,
    workspace_id: UUID,
    event_type: str,
    entity_type: str,
    entity_id: str,
    actor_user_id: UUID | None,
    payload: Mapping[str, Any],
) -> FitmentAuditEvent:
    safe_payload = _json_safe(payload)
    return FitmentAuditEvent(
        workspace_id=workspace_id,
        event_key=_sha256(
            {
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "actor_user_id": actor_user_id,
                "payload": safe_payload,
            }
        ),
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        payload=safe_payload,
    )


def _json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return value


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_safe(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "HITL_FEEDBACK_LABEL_VERSION",
    "generate_fitment_recommendation",
    "get_fitment_recommendation",
    "list_fitment_notifications",
    "mark_fitment_notification_read",
    "review_fitment_recommendation",
]
