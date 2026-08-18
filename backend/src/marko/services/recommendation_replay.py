"""Network-free verification of persisted pricing recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    MarketObservation,
    ObservationTierClassification,
    PricingDiscoveryDecision,
    PricingRecommendation,
    PricingRunItem,
)
from marko.services.cost_privacy import privacy_safe_mapping
from marko.services.decision_fingerprint import (
    DECISION_FINGERPRINT_V1,
    build_decision_fingerprint_payload,
    canonical_sha256,
)
from marko.services.llm_comparability import effective_review_from_snapshot
from marko.services.market_collection import (
    _domain_offer,
    _semantic_review_required_for_observation,
    apply_comparability_activation_gate,
    resolve_bound_execution_item,
)
from marko.services.no_oe_pricing import (
    NO_OE_REPLAY_CONTRACT_V1,
    _five_percent_below,
)
from marko.services.pricing_runs import (
    PricingRunSnapshotError,
    customer_identity_available,
    customer_identity_query,
    get_pricing_run,
    get_recommendation,
    load_run_execution_policy,
    load_target_tier_coefficients,
)
from metis.pricing import (
    PricingResult,
    ProductPricingContext,
    StockStatus,
    cluster_diagnostic_to_dict,
    dispersion_profile_to_dict,
    recommend_price,
    robust_dispersion_trace,
)
from metis.pricing.observability import pricing_event

REPLAY_CONTRACT_V1 = "recommendation-replay-v1"
REPLAY_CONTRACT_V2 = "recommendation-replay-v2"
REPLAY_CONTRACT_V3 = "recommendation-replay-v3"
REPLAY_CONTRACT_V4 = "recommendation-replay-v4"
REPLAY_CONTRACT_V5 = "recommendation-replay-v5"
REPLAY_CONTRACT_V6 = "recommendation-replay-v6"
REPLAY_CONTRACT_VERSION = REPLAY_CONTRACT_V6
SUPPORTED_REPLAY_CONTRACTS = frozenset(
    {
        REPLAY_CONTRACT_V1,
        REPLAY_CONTRACT_V2,
        REPLAY_CONTRACT_V3,
        REPLAY_CONTRACT_V4,
        REPLAY_CONTRACT_V5,
        REPLAY_CONTRACT_V6,
    }
)


class RecommendationReplayUnavailable(RuntimeError):
    """The stored recommendation predates the replay input contract."""


@dataclass(frozen=True)
class RecommendationReplay:
    recommendation_id: UUID
    replay_contract_version: str
    calculated_at: datetime
    exact_match: bool
    mismatches: dict[str, dict[str, Any]]
    replayed: dict[str, Any]


async def replay_recommendation(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    recommendation_id: UUID,
) -> RecommendationReplay:
    recommendation, item = await get_recommendation(
        session,
        workspace_id=workspace_id,
        recommendation_id=recommendation_id,
    )
    trace = recommendation.calculation_trace
    replay_contract_version = str(trace.get("replay_contract_version", ""))
    # Развилка стоит ДО машинерии OE-дорожки намеренно: рекомендация без OE не
    # имеет подтверждённого OE по определению, и общая проверка личности ниже
    # объявила бы её неповторимой раньше, чем дело дошло бы до расчёта.
    if replay_contract_version == NO_OE_REPLAY_CONTRACT_V1:
        return await _replay_no_oe(
            session,
            recommendation=recommendation,
            trace=trace,
        )
    if replay_contract_version not in SUPPORTED_REPLAY_CONTRACTS:
        raise RecommendationReplayUnavailable(
            "Recommendation has no supported replay contract"
        )
    calculated_at = _required_datetime(trace.get("calculated_at"))
    run = await get_pricing_run(
        session,
        workspace_id=workspace_id,
        run_id=recommendation.pricing_run_id,
    )
    run_item = await session.scalar(
        select(PricingRunItem).where(
            PricingRunItem.id == recommendation.pricing_run_item_id,
            PricingRunItem.pricing_run_id == run.id,
            PricingRunItem.catalog_item_id == item.id,
        )
    )
    if run_item is None:
        raise RecommendationReplayUnavailable(
            "Recommendation run-item snapshot is missing"
        )
    # Повтор обязан подбирать коэффициенты по той же позиции, по которой их
    # подбирал расчёт, то есть по ЗАМОРОЖЕННОЙ. ``item`` — живая строка
    # каталога: она нужна только чтобы предъявить владельца и убедиться, что
    # позиция ещё существует, и её категория/OE могли измениться после старта.
    # Читать их отсюда значило бы «повторять» по другому товару и объявлять
    # расхождение дефектом расчёта.
    try:
        frozen_item = resolve_bound_execution_item(run, run_item, item)
    except PricingRunSnapshotError as exc:
        raise RecommendationReplayUnavailable(
            f"Recommendation run-item snapshot is not usable: {exc}"
        ) from exc
    # A legacy recommendation may have been written before the pricing-run
    # identity boundary existed.  Never let replay turn its stored MPN/private
    # KEMP code into a fresh pricing result: replay is a calculation verifier,
    # not an identity migration path.  The row must be re-enriched and started
    # again only after a confirmed vehicle OE is persisted.
    if not customer_identity_available(frozen_item):
        raise RecommendationReplayUnavailable(
            "Recommendation replay requires a confirmed vehicle OE; "
            "MPN-only or unresolved identity cannot be replayed"
        )

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
                    MarketObservation.pricing_run_item_id == run_item.id,
                    ObservationTierClassification.classified_at <= calculated_at,
                )
                .order_by(
                    MarketObservation.id,
                    ObservationTierClassification.classified_at.desc(),
                    ObservationTierClassification.id.desc(),
                )
            )
        ).all()
    )
    latest: dict[
        UUID,
        tuple[MarketObservation, ObservationTierClassification],
    ] = {}
    for observation, classification in rows:
        latest.setdefault(observation.id, (observation, classification))

    context = context_from_snapshot(recommendation.context_snapshot)
    # Повтор рекомендации обязан читать политику ТОЛЬКО из снимка прогона:
    # иначе изменённый файл развёртывания молча переопределяет историю, и
    # «повтор» перестаёт быть повтором.
    policy = load_run_execution_policy(run)
    coefficients = await load_target_tier_coefficients(
        session,
        run=run,
        category=frozen_item.category,
        oe_norm=customer_identity_query(frozen_item),
        policy=policy,
        comparison_identity_keys={
            observation.comparison_identity_key
            for observation, _classification in latest.values()
            if observation.comparison_identity_key
        },
    )
    llm_trace = trace.get("llm_comparability")
    llm_required = bool(isinstance(llm_trace, Mapping) and llm_trace.get("required"))
    raw_required_observation_ids = (
        llm_trace.get("required_observation_ids")
        if isinstance(llm_trace, Mapping)
        else None
    )
    if raw_required_observation_ids is None:
        # Traces written before per-observation authority existed must replay
        # under their original global-only contract.
        required_observation_ids = frozenset()
    elif not isinstance(raw_required_observation_ids, list) or not all(
        isinstance(value, str) for value in raw_required_observation_ids
    ):
        raise RecommendationReplayUnavailable(
            "Stored LLM comparability required-observation snapshot is invalid"
        )
    else:
        required_observation_ids = frozenset(raw_required_observation_ids)
    review_snapshots = (
        llm_trace.get("reviews", ()) if isinstance(llm_trace, Mapping) else ()
    )
    effective_reviews = {}
    if isinstance(review_snapshots, list):
        try:
            effective_reviews = {
                review.market_observation_id: review
                for raw in review_snapshots
                if isinstance(raw, Mapping)
                for review in (effective_review_from_snapshot(raw),)
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise RecommendationReplayUnavailable(
                "Stored LLM comparability review snapshot is invalid"
            ) from exc
    result = recommend_price(
        context,
        [
            _domain_offer(
                observation,
                classification,
                calculated_at,
                semantic_review=effective_reviews.get(observation.id),
                semantic_review_required=(
                    _semantic_review_required_for_observation(
                        observation,
                        global_required=llm_required,
                        traced_required_observation_ids=required_observation_ids,
                    )
                ),
            )
            for observation, classification in latest.values()
        ],
        coefficients,
        policy=policy,
        legacy_replay="comparability" not in trace,
    )
    comparability_trace = trace.get("comparability", {})
    if isinstance(comparability_trace, Mapping):
        stored_activation_verified = comparability_trace.get("activation_verified")
    else:
        stored_activation_verified = None
    if stored_activation_verified is None:
        # Pre-field traces can still be replayed: the emitted gate reason is
        # immutable evidence that the release gate was closed at calculation.
        stored_activation_verified = (
            "COMPARABILITY_AUTOMATIC_ACTIVATION_BLOCKED"
            not in recommendation.reason_codes
        )
    result = apply_comparability_activation_gate(
        result,
        activation_verified=bool(stored_activation_verified),
    )
    mismatches = compare_replayed_result(
        recommendation,
        result,
        replay_contract_version=replay_contract_version,
    )
    fingerprint_payload = build_decision_fingerprint_payload(
        context_snapshot=privacy_safe_mapping(recommendation.context_snapshot),
        result=result,
        observations=[value[0] for value in latest.values()],
        policy_config=run.policy_config,
        coefficients=coefficients.values(),
        parser_version=run.parser_version,
        classifier_version=run.classifier_version,
        calibration_dataset_hash=run.calibration_dataset_hash,
        coefficient_version=recommendation.coefficient_version,
        build_identity=str(trace.get("build_identity", "NOT_AVAILABLE")),
        price_tick=policy.price_tick,
        price_tick_version=policy.price_tick_version,
        fingerprint_version=str(
            trace.get("decision_fingerprint_version", DECISION_FINGERPRINT_V1)
        ),
        comparability_reviews=[
            review.as_dict()
            for review in sorted(
                effective_reviews.values(),
                key=lambda value: str(value.market_observation_id),
            )
        ],
    )
    replayed_fingerprint = canonical_sha256(fingerprint_payload)
    if (
        replay_contract_version
        in {
            REPLAY_CONTRACT_V3,
            REPLAY_CONTRACT_V4,
            REPLAY_CONTRACT_V5,
            REPLAY_CONTRACT_V6,
        }
        and recommendation.decision_fingerprint
        and recommendation.decision_fingerprint != replayed_fingerprint
    ):
        mismatches["decision_fingerprint"] = {
            "expected": recommendation.decision_fingerprint,
            "actual": replayed_fingerprint,
        }
    replayed_summary = _replayed_summary(result)
    replayed_summary["decision_fingerprint"] = replayed_fingerprint
    pricing_event(
        "replay_exact_match_total",
        policy_version=result.policy_version,
        exact_match=not mismatches,
        value=1,
    )
    return RecommendationReplay(
        recommendation_id=recommendation.id,
        replay_contract_version=replay_contract_version,
        calculated_at=calculated_at,
        exact_match=not mismatches,
        mismatches=mismatches,
        replayed=replayed_summary,
    )


async def _replay_no_oe(
    session: AsyncSession,
    *,
    recommendation: PricingRecommendation,
    trace: Mapping[str, Any],
) -> RecommendationReplay:
    """Пересчитать рекомендацию дорожки без OE из её же допущенных предложений.

    Считать здесь нечего, кроме минимума одобренных человеком цен и минус пяти
    процентов, — и именно поэтому повтор осмыслен: он показывает, что цена
    выведена из решений оператора, которые лежат в базе и не менялись, а не из
    промежуточного состояния воркера.
    """

    calculated_at = _required_datetime(trace.get("calculated_at"))
    stored_threshold = trace.get("min_independent_sellers")
    if (
        not isinstance(stored_threshold, int)
        or isinstance(stored_threshold, bool)
        or stored_threshold < 1
    ):
        raise RecommendationReplayUnavailable(
            "Recommendation trace is missing the independent-seller threshold "
            "it was calculated under"
        )
    snapshot = recommendation.context_snapshot
    review_snapshot_hash = str(
        (snapshot if isinstance(snapshot, Mapping) else {}).get(
            "review_snapshot_hash", ""
        )
    )
    if not review_snapshot_hash:
        raise RecommendationReplayUnavailable(
            "Recommendation context snapshot is missing the review snapshot hash"
        )

    # Порядок здесь несущий, а не косметический: при двух допущенных
    # предложениях одного продавца ``setdefault`` оставляет ПЕРВОЕ, и другой
    # порядок дал бы другую справедливую цену.  Повторяем выборку расчёта
    # дословно — те же сортировка, схлопывание по предложению и по продавцу.
    decisions = list(
        (
            await session.scalars(
                select(PricingDiscoveryDecision)
                .where(
                    PricingDiscoveryDecision.pricing_run_item_id
                    == recommendation.pricing_run_item_id,
                    PricingDiscoveryDecision.created_at <= calculated_at,
                )
                .order_by(
                    PricingDiscoveryDecision.created_at,
                    PricingDiscoveryDecision.id,
                )
            )
        ).all()
    )
    latest = {decision.catalog_discovery_offer_id: decision for decision in decisions}
    approved = [
        decision for decision in latest.values() if decision.decision == "APPROVE"
    ]
    by_seller: dict[str, PricingDiscoveryDecision] = {}
    for value in approved:
        by_seller.setdefault(value.seller_id, value)

    enough = len(by_seller) >= stored_threshold
    fair_price = min((value.price for value in by_seller.values()), default=None)
    recommended_price = (
        _five_percent_below(fair_price) if enough and fair_price else None
    )
    reason_codes = [
        "NO_OE_HUMAN_APPROVED_OFFERS",
        "AUTOMATIC_ELIGIBILITY_FORCED_FALSE",
        "NO_GLOBAL_IDENTITY_CREATED",
    ]
    if not enough:
        reason_codes.append("INSUFFICIENT_INDEPENDENT_SELLERS")
    replayed_fingerprint = canonical_sha256(
        {
            "run_item_id": str(recommendation.pricing_run_item_id),
            "review_snapshot_hash": review_snapshot_hash,
            "decision_ids": [str(value.id) for value in by_seller.values()],
        }
    )

    stored_hashes = trace.get("offer_hashes")
    expected: dict[str, Any] = {
        "action": recommendation.action,
        "fair_price": _quantize(recommendation.fair_price, "0.01"),
        "recommended_price": _quantize(recommendation.recommended_price, "0.01"),
        "competitor_count": recommendation.competitor_count,
        "raw_competitor_count": recommendation.raw_competitor_count,
        "unique_seller_count": recommendation.unique_seller_count,
        "reason_codes": list(recommendation.reason_codes),
        "offer_hashes": list(stored_hashes) if isinstance(stored_hashes, list) else [],
        "decision_fingerprint": recommendation.decision_fingerprint,
    }
    actual: dict[str, Any] = {
        "action": "MANUAL_REVIEW" if enough else "INSUFFICIENT_DATA",
        "fair_price": _quantize(fair_price, "0.01"),
        "recommended_price": _quantize(recommended_price, "0.01"),
        "competitor_count": len(by_seller),
        "raw_competitor_count": len(latest),
        "unique_seller_count": len(by_seller),
        "reason_codes": reason_codes,
        "offer_hashes": [value.offer_sha256 for value in by_seller.values()],
        "decision_fingerprint": replayed_fingerprint,
    }
    mismatches = {
        field: {
            "stored": _json_value(expected[field]),
            "replayed": _json_value(actual[field]),
        }
        for field in expected
        if expected[field] != actual[field]
    }
    replayed_summary = {
        **{field: _json_value(value) for field, value in actual.items()},
        "method": str(trace.get("method", "")),
        "min_independent_sellers": stored_threshold,
    }
    pricing_event(
        "replay_exact_match_total",
        policy_version=recommendation.policy_version,
        exact_match=not mismatches,
        value=1,
    )
    return RecommendationReplay(
        recommendation_id=recommendation.id,
        replay_contract_version=NO_OE_REPLAY_CONTRACT_V1,
        calculated_at=calculated_at,
        exact_match=not mismatches,
        mismatches=mismatches,
        replayed=replayed_summary,
    )


def context_from_snapshot(snapshot: Mapping[str, Any]) -> ProductPricingContext:
    return ProductPricingContext(
        sku=_required_string(snapshot, "sku"),
        category=_required_string(snapshot, "category"),
        current_price=_required_decimal(snapshot, "current_price"),
        currency=_required_string(snapshot, "currency"),
        stock_status=StockStatus(
            str(snapshot.get("stock_status", StockStatus.UNKNOWN.value))
        ),
        # Legacy snapshots may contain raw cost data.  The V1 privacy mode is
        # intentionally undecided, so replay must not materialize it back into
        # the active pricing context.  The pricing engine is market-evidence
        # based and does not need either value for current recommendations.
        cost=None,
        stock_qty=_optional_decimal(snapshot.get("stock_qty")),
        stock_age_days=_optional_decimal(snapshot.get("stock_age_days")),
        expected_units_sold=_optional_decimal(snapshot.get("expected_units_sold")),
        units_sold_30d=_optional_decimal(snapshot.get("units_sold_30d")),
        units_sold_60d=_optional_decimal(snapshot.get("units_sold_60d")),
        units_sold_90d=_optional_decimal(snapshot.get("units_sold_90d")),
        days_since_last_sale=_optional_decimal(snapshot.get("days_since_last_sale")),
        historical_monthly_units=_optional_decimal(
            snapshot.get("historical_monthly_units")
        ),
        views_30d=_optional_decimal(snapshot.get("views_30d")),
        conversion_rate_proxy=_optional_decimal(snapshot.get("conversion_rate_proxy")),
        liquidity_target=_decimal_or_default(
            snapshot.get("liquidity_target"), Decimal("0")
        ),
        # Missing legacy urgency must resolve to the domain/API default.  A
        # default of one silently turns an absent signal into maximum urgency
        # and can change the replayed priority score.
        urgency=_decimal_or_default(snapshot.get("urgency"), Decimal("0")),
        manual_priority=_decimal_or_default(
            snapshot.get("manual_priority"), Decimal("1")
        ),
        allow_below_cost=bool(snapshot.get("allow_below_cost", False)),
        below_cost_floor=None,
        below_cost_authorization_id=_optional_string(
            snapshot.get("below_cost_authorization_id")
        ),
        below_cost_authorized_by=_optional_string(
            snapshot.get("below_cost_authorized_by")
        ),
        below_cost_authorized_at=_optional_datetime(
            snapshot.get("below_cost_authorized_at")
        ),
        below_cost_reason=_optional_string(snapshot.get("below_cost_reason")),
        below_cost_warning_confirmed=bool(
            snapshot.get("below_cost_warning_confirmed", False)
        ),
    )


def compare_replayed_result(
    stored: PricingRecommendation,
    replayed: PricingResult,
    *,
    replay_contract_version: str | None = None,
) -> dict[str, dict[str, Any]]:
    trace = getattr(stored, "calculation_trace", {})
    if not isinstance(trace, Mapping):
        trace = {}
    contract = replay_contract_version or str(
        trace.get("replay_contract_version", REPLAY_CONTRACT_V1)
    )
    expected: dict[str, Any] = {
        "action": stored.action,
        "current_price": _quantize(stored.current_price, "0.01"),
        "fair_price": _quantize(stored.fair_price, "0.01"),
        "recommended_price": _quantize(stored.recommended_price, "0.01"),
        "lower_bound": _quantize(stored.lower_bound, "0.01"),
        "upper_bound": _quantize(stored.upper_bound, "0.01"),
        "confidence": _quantize(stored.confidence, "0.0001"),
        "confidence_grade": stored.confidence_grade,
        "weakest_factor": stored.weakest_factor,
        "competitor_count": stored.competitor_count,
        "raw_competitor_count": stored.raw_competitor_count,
        "unique_seller_count": stored.unique_seller_count,
        "clean_competitor_count": stored.clean_competitor_count,
        "effective_competitor_count": _quantize(
            stored.effective_competitor_count, "0.0001"
        ),
        "dispersion": _quantize(stored.dispersion, "0.00000001"),
        "outlier_method": stored.outlier_method,
        "outlier_count": stored.outlier_count,
        "sensitivity": _quantize(stored.sensitivity, "0.00000001"),
        "action_gates_passed": stored.action_gates_passed,
        "cost_floor": _quantize(stored.cost_floor, "0.01"),
        "priority_score": _quantize(stored.priority_score, "0.000001"),
        "priority_score_type": stored.priority_score_type,
        "review_priority": _quantize(stored.review_priority, "0.000001"),
        "reason_codes": list(stored.reason_codes),
        "evidence_observation_ids": list(stored.evidence_observation_ids),
        "policy_version": stored.policy_version,
    }
    actual: dict[str, Any] = {
        "action": replayed.action.value,
        "current_price": _quantize(replayed.current_price, "0.01"),
        "fair_price": _quantize(replayed.fair_price, "0.01"),
        "recommended_price": _quantize(replayed.recommended_price, "0.01"),
        "lower_bound": _quantize(replayed.lower_bound, "0.01"),
        "upper_bound": _quantize(replayed.upper_bound, "0.01"),
        "confidence": _quantize(replayed.confidence, "0.0001"),
        "confidence_grade": replayed.confidence_grade,
        "weakest_factor": replayed.weakest_factor,
        "competitor_count": replayed.competitor_count,
        "raw_competitor_count": replayed.raw_competitor_count,
        "unique_seller_count": replayed.unique_seller_count,
        "clean_competitor_count": replayed.clean_competitor_count,
        "effective_competitor_count": _quantize(
            replayed.effective_competitor_count, "0.0001"
        ),
        "dispersion": _quantize(replayed.dispersion, "0.00000001"),
        "outlier_method": replayed.outlier_method,
        "outlier_count": replayed.outlier_count,
        "sensitivity": _quantize(replayed.sensitivity, "0.00000001"),
        "action_gates_passed": replayed.action_gates_passed,
        "cost_floor": _quantize(replayed.cost_floor, "0.01"),
        "priority_score": _quantize(replayed.priority_score, "0.000001"),
        "priority_score_type": replayed.priority_score_type.value,
        "review_priority": _quantize(replayed.review_priority, "0.000001"),
        "reason_codes": list(replayed.reasons),
        "evidence_observation_ids": [
            offer.observation_id for offer in replayed.evidence
        ],
        "policy_version": replayed.policy_version,
    }
    if contract in {
        REPLAY_CONTRACT_V2,
        REPLAY_CONTRACT_V3,
        REPLAY_CONTRACT_V4,
        REPLAY_CONTRACT_V5,
        REPLAY_CONTRACT_V6,
    }:
        stored_robust = trace.get("robust_dispersion", {})
        if not isinstance(stored_robust, Mapping):
            stored_robust = {}
        replayed_robust = robust_dispersion_trace(
            selected_method=replayed.dispersion_method,
            pre_clean=replayed.pre_clean_dispersion_profile,
            post_clean=replayed.dispersion_profile,
            profile_version=replayed.robust_dispersion_profile_version,
            correction_profile_version=(
                replayed.robust_scale_correction_profile_version
            ),
            finite_sample_correction=replayed.finite_sample_scale_correction,
        )
        expected.update(
            {
                "dispersion_method": stored_robust.get("selected_method"),
                "pre_clean_dispersion_profile": stored_robust.get("pre_clean"),
                "dispersion_profile": stored_robust.get("post_clean"),
                "profile_version": stored_robust.get("profile_version"),
                "correction_profile_version": stored_robust.get(
                    "correction_profile_version"
                ),
                "finite_sample_correction": stored_robust.get(
                    "finite_sample_correction"
                ),
                "robust_constants": stored_robust.get("constants"),
            }
        )
        actual.update(
            {
                "dispersion_method": replayed_robust["selected_method"],
                "pre_clean_dispersion_profile": replayed_robust["pre_clean"],
                "dispersion_profile": replayed_robust["post_clean"],
                "profile_version": replayed_robust["profile_version"],
                "correction_profile_version": replayed_robust[
                    "correction_profile_version"
                ],
                "finite_sample_correction": replayed_robust["finite_sample_correction"],
                "robust_constants": replayed_robust["constants"],
            }
        )
    if contract in {
        REPLAY_CONTRACT_V3,
        REPLAY_CONTRACT_V4,
        REPLAY_CONTRACT_V5,
        REPLAY_CONTRACT_V6,
    }:
        stored_comparability = trace.get("comparability", {})
        if not isinstance(stored_comparability, Mapping):
            stored_comparability = {}
        expected.update(
            {
                "automatic_eligible": stored_comparability.get("automatic_eligible"),
                "verified_seller_count": stored_comparability.get(
                    "verified_seller_count"
                ),
                "comparability_policy_id": stored_comparability.get("policy_id"),
                "comparability_policy_hash": stored_comparability.get("policy_hash"),
                "hard_gate_results": stored_comparability.get("hard_gates"),
                "failed_hard_gates": stored_comparability.get("failed_hard_gates"),
                "unknown_hard_fields": stored_comparability.get("unknown_hard_fields"),
                "robust_diagnostic": trace.get("robust_diagnostic"),
                "robust_policy_fingerprint": trace.get("robust_policy_fingerprint"),
            }
        )
        actual.update(
            {
                "automatic_eligible": replayed.automatic_eligible,
                "verified_seller_count": replayed.verified_seller_count,
                "comparability_policy_id": replayed.comparability_policy_id,
                "comparability_policy_hash": replayed.comparability_policy_hash,
                "hard_gate_results": dict(replayed.hard_gate_results),
                "failed_hard_gates": list(replayed.failed_hard_gates),
                "unknown_hard_fields": list(replayed.unknown_hard_fields),
                "robust_diagnostic": cluster_diagnostic_to_dict(
                    replayed.cluster_diagnostic
                ),
                "robust_policy_fingerprint": dict(replayed.robust_policy_fingerprint),
            }
        )
    return {
        field: {
            "stored": _json_value(expected[field]),
            "replayed": _json_value(actual[field]),
        }
        for field in expected
        if expected[field] != actual[field]
    }


def _replayed_summary(result: PricingResult) -> dict[str, Any]:
    return {
        "action": result.action.value,
        "current_price": str(result.current_price),
        "fair_price": _string_or_none(result.fair_price),
        "recommended_price": _string_or_none(result.recommended_price),
        "lower_bound": _string_or_none(result.lower_bound),
        "upper_bound": _string_or_none(result.upper_bound),
        "confidence": str(result.confidence),
        "confidence_grade": result.confidence_grade,
        "weakest_factor": result.weakest_factor,
        "competitor_count": result.competitor_count,
        "raw_competitor_count": result.raw_competitor_count,
        "unique_seller_count": result.unique_seller_count,
        "clean_competitor_count": result.clean_competitor_count,
        "effective_competitor_count": str(result.effective_competitor_count),
        "dispersion": _string_or_none(result.dispersion),
        "dispersion_method": result.dispersion_method.value,
        "dispersion_profile": dispersion_profile_to_dict(result.dispersion_profile),
        "reason_codes": list(result.reasons),
        "evidence_observation_ids": [offer.observation_id for offer in result.evidence],
        "policy_version": result.policy_version,
        "automatic_eligible": result.automatic_eligible,
        "verified_seller_count": result.verified_seller_count,
        "comparability_policy_id": result.comparability_policy_id,
        "comparability_policy_hash": result.comparability_policy_hash,
        "hard_gate_results": dict(result.hard_gate_results),
        "failed_hard_gates": list(result.failed_hard_gates),
        "unknown_hard_fields": list(result.unknown_hard_fields),
    }


def _required_string(snapshot: Mapping[str, Any], key: str) -> str:
    value = snapshot.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RecommendationReplayUnavailable(
            f"Recommendation context snapshot is missing {key}"
        )
    return value


def _required_decimal(snapshot: Mapping[str, Any], key: str) -> Decimal:
    value = _optional_decimal(snapshot.get(key))
    if value is None:
        raise RecommendationReplayUnavailable(
            f"Recommendation context snapshot is missing {key}"
        )
    return value


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _decimal_or_default(value: Any, default: Decimal) -> Decimal:
    parsed = _optional_decimal(value)
    return default if parsed is None else parsed


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _required_datetime(value: Any) -> datetime:
    parsed = _optional_datetime(value)
    if parsed is None:
        raise RecommendationReplayUnavailable(
            "Recommendation trace is missing calculated_at"
        )
    return parsed


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _quantize(value: Decimal | None, quantum: str) -> Decimal | None:
    return value.quantize(Decimal(quantum)) if value is not None else None


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def _string_or_none(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


__all__ = [
    "REPLAY_CONTRACT_VERSION",
    "REPLAY_CONTRACT_V1",
    "REPLAY_CONTRACT_V2",
    "REPLAY_CONTRACT_V3",
    "REPLAY_CONTRACT_V4",
    "REPLAY_CONTRACT_V5",
    "REPLAY_CONTRACT_V6",
    "RecommendationReplay",
    "RecommendationReplayUnavailable",
    "compare_replayed_result",
    "context_from_snapshot",
    "replay_recommendation",
]
