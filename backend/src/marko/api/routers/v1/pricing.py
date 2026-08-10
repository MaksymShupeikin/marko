"""Authenticated pricing engine, run, calibration, and audit endpoints."""

from __future__ import annotations

from dataclasses import asdict, fields
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.api.dependencies import CurrentUser, WorkspaceAdmin, get_session
from marko.services.auth import AuthContext
from marko.core.config import get_settings
from marko.core.ai_model_identity import is_immutable_model_snapshot
from marko.infrastructure.db.models import (
    CatalogItem,
    MarketObservation,
    OfferProcessingOutcome,
)
from marko.services.catalog_costs import get_latest_cost_record
from marko.services.catalog_data_evidence import catalog_data_evidence
from marko.api.schemas.pricing import (
    AiEvidenceExtractionResponse,
    AiEvidenceFieldResponse,
    AiEvidenceSpendEstimateResponse,
    AiEvidenceStatusResponse,
    AiEvidenceUsageResponse,
    CalibrationRequest,
    CatalogItemOverrideRequest,
    CatalogItemOverrideResponse,
    ComparabilityFeedbackRequest,
    ComparabilityRunReportResponse,
    ComparabilityReviewRequest,
    ComparabilityReviewResponse,
    ComparabilityStatusResponse,
    PricingEvaluateRequest,
    PricingEvaluateResponse,
    PricingRunCreateRequest,
    PricingRunPageResponse,
    PricingRunPreviewRequest,
    PricingRunPreviewResponse,
    PricingRunResponse,
    PricingRunScopeEstimateResponse,
    PricingRunScopeExclusionResponse,
    ScraperMetricsResponse,
    ObservationTierOverrideRequest,
    ObservationTierOverrideResponse,
    RecommendationDecisionRequest,
    RecommendationDecisionResponse,
    RecommendationEvidenceResponse,
    RecommendationActionCountsResponse,
    RecommendationPageResponse,
    RecommendationReplayResponse,
    RecommendationResponse,
    TierCoefficientResponse,
    TierCoefficientPageResponse,
)
from metis.pricing import (
    CalibrationPair,
    CoefficientModel,
    cluster_diagnostic_to_dict,
    comparison_evidence_to_dict,
    dispersion_profile_to_dict,
    recommend_price,
)
from marko.services.pricing_runs import (
    CatalogItemNotFoundError,
    OperatorRunStart,
    ACTOR_TYPE_USER,
    PRICING_RUN_START_PERMISSION,
    IssuedPreviewContract,
    PreviewActor,
    PricingRunActiveScopeConflictError,
    PricingRunError,
    PricingRunIdempotencyConflictError,
    PricingRunNotFoundError,
    PricingRunScope,
    PricingRunScopeConflictError,
    PricingRunStartContractError,
    PricingTaskDispatchError,
    RecommendationNotFoundError,
    IDENTITY_BLOCKED_RECOMMENDATION_ACTION,
    add_catalog_item_override,
    add_recommendation_decision,
    calibrate_tier_coefficients,
    cancel_pricing_run,
    create_pricing_run,
    get_pricing_run,
    get_recommendation,
    get_recommendation_evidence,
    list_pricing_runs,
    list_recommendations,
    list_tier_coefficients,
    policy_from_dict,
    preview_pricing_run_for_operator,
    recommendation_price_identity_allowed,
    override_observation_tier,
)
from marko.services.cost_privacy import privacy_safe_mapping
from marko.services.market_collection import _validated_listing_url
from marko.services.market_price import effective_observation_price
from marko.services.llm_comparability import (
    ComparabilityReviewNotFound,
    ComparabilityReviewUnavailable,
    add_comparability_feedback,
    load_effective_review_map,
    request_observation_comparability_review,
)
from marko.services.comparability_reporting import build_comparability_run_report
from marko.services.recommendation_replay import (
    RecommendationReplayUnavailable,
    replay_recommendation,
)
from marko.services.recommendation_export import (
    RecommendationExportError,
    _export_identity_fields,
    export_recommendations,
)
from marko.worker.celery_app import celery_app
from marko.services.scraper_metrics import (
    AiEvidenceExtractionView,
    ai_evidence_spend_estimate,
    ai_evidence_telemetry_snapshot,
    assert_publishable,
    get_pricing_run_scraper_metrics,
    render_prometheus,
)
from marko.services.ai_cost_policy import (
    AiCostPolicyError,
    ESTIMATE_DISCLAIMER,
    resolve_rate_card,
)

router = APIRouter()


@router.get(
    "/comparability/status",
    response_model=ComparabilityStatusResponse,
)
async def get_llm_comparability_status(
    _current: CurrentUser,
) -> ComparabilityStatusResponse:
    settings = get_settings()
    return ComparabilityStatusResponse(
        mode=settings.pricing_llm_comparability_mode,
        provider=settings.pricing_llm_provider,
        model=settings.pricing_llm_model,
        reasoning_effort=settings.pricing_llm_reasoning_effort,
        rate_card_version=settings.pricing_llm_rate_version,
        configured=bool(
            settings.pricing_llm_comparability_mode != "off"
            and settings.pricing_llm_api_key.get_secret_value().strip()
            and settings.pricing_llm_model.strip()
        ),
        automatic_price_publication=False,
    )


#: Contract defaults for the extractor settings owned by another agent.  Read
#: through ``getattr`` so this read surface degrades to "off and unconfigured"
#: instead of failing to import while those settings are still landing.
_AI_EVIDENCE_DEFAULTS: dict[str, str] = {
    "pricing_ai_evidence_mode": "off",
    "pricing_ai_evidence_provider": "openai_responses",
    "pricing_ai_evidence_model": "gpt-5.6-luna",
    "pricing_ai_evidence_reasoning_effort": "medium",
}


class _AiEvidenceStorageUnavailable(RuntimeError):
    """The extraction table is not provisioned in this deployment yet."""


def _ai_evidence_config(settings: Any) -> dict[str, Any]:
    """Public configuration only.  The API key is read for a boolean and dropped."""

    values = {
        name: str(getattr(settings, name, default) or default).strip() or default
        for name, default in _AI_EVIDENCE_DEFAULTS.items()
    }
    key_text = ""
    for name in ("pricing_ai_evidence_api_key", "pricing_llm_api_key"):
        secret = getattr(settings, name, None)
        if secret is None:
            continue
        getter = getattr(secret, "get_secret_value", None)
        key_text = str(getter() if callable(getter) else secret).strip()
        if key_text:
            break
    mode = values["pricing_ai_evidence_mode"]
    if mode not in {"off", "shadow"}:
        mode = "off"
    if mode != "off" and not is_immutable_model_snapshot(
        values["pricing_ai_evidence_model"]
    ):
        mode = "off"
    return {
        "mode": mode,
        "provider": values["pricing_ai_evidence_provider"],
        "model": values["pricing_ai_evidence_model"],
        "reasoning_effort": values["pricing_ai_evidence_reasoning_effort"],
        "configured": bool(
            mode != "off" and key_text and values["pricing_ai_evidence_model"]
        ),
        "shadow_only": True,
    }


def _ai_evidence_rate_card(model_id: str | None):
    """Resolve an exact model snapshot; an unknown explicit model has no price."""

    try:
        return resolve_rate_card(model_id=model_id) if model_id else resolve_rate_card()
    except AiCostPolicyError:
        return None


def _ai_evidence_spend_response(
    view: AiEvidenceExtractionView,
) -> AiEvidenceSpendEstimateResponse:
    if view.persisted_spend_estimate is not None:
        try:
            return AiEvidenceSpendEstimateResponse.model_validate(
                {"available": True, **view.persisted_spend_estimate}
            )
        except (TypeError, ValueError):
            # A malformed historical estimate must not break evidence reads;
            # recompute from the separately persisted token counters instead.
            pass
    # ``provider_model`` is provider-controlled metadata.  Only the immutable
    # deployment model id may select a rate card or cross the public boundary.
    estimated_model = view.model_id
    card = _ai_evidence_rate_card(estimated_model)
    if card is None:
        return AiEvidenceSpendEstimateResponse(
            available=False,
            reason="rate_card_unavailable",
        )
    estimate = ai_evidence_spend_estimate(view.usage, card=card)
    return AiEvidenceSpendEstimateResponse.model_validate(estimate)


def _ai_evidence_response(
    view: AiEvidenceExtractionView,
) -> AiEvidenceExtractionResponse:
    """Serialize one extraction: evidence yes, hidden reasoning never.

    The payload is built from the scrubbed projection rather than from the row,
    so a provider field that nobody anticipated cannot ride along into the
    response by being copied verbatim.
    """

    payload = assert_publishable(view.as_public_dict())
    return AiEvidenceExtractionResponse(
        extraction_id=payload["extraction_id"],
        market_observation_id=payload["market_observation_id"],
        status=payload["status"],
        shadow_only=payload["shadow_only"],
        provider=payload["provider"],
        model_id=payload["model_id"],
        reasoning_effort=payload["reasoning_effort"],
        prompt_version=payload["prompt_version"],
        schema_version=payload["schema_version"],
        extractor_version=payload["extractor_version"],
        latency_ms=payload["latency_ms"],
        usage=(
            AiEvidenceUsageResponse.model_validate(payload["usage"])
            if payload["usage"]
            else None
        ),
        usage_error=payload["usage_error"],
        verification_result=payload["verification_result"],
        verification_reasons=payload["verification_reasons"],
        fields=[
            AiEvidenceFieldResponse.model_validate(item) for item in payload["fields"]
        ],
        error_code=payload["error_code"],
        created_at=payload["created_at"],
        spend_estimate=_ai_evidence_spend_response(view),
    )


async def _observation_belongs_to_workspace(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    observation_id: UUID,
) -> bool:
    """Workspace ownership travels through the catalog item, as elsewhere."""

    found = await session.scalar(
        select(func.count(MarketObservation.id))
        .join(CatalogItem, CatalogItem.id == MarketObservation.catalog_item_id)
        .where(
            MarketObservation.id == observation_id,
            CatalogItem.workspace_id == workspace_id,
        )
    )
    return bool(found)


async def _load_observation_ai_evidence(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    observation_id: UUID,
) -> list[Any]:
    """Load extraction rows scoped to one workspace and one observation."""

    from marko.infrastructure.db import models as db_models

    model = getattr(db_models, "AiEvidenceExtraction", None)
    if model is None:
        raise _AiEvidenceStorageUnavailable(
            "ai_evidence_extractions is not provisioned"
        )
    statement = select(model).where(model.market_observation_id == observation_id)
    workspace_column = getattr(model, "workspace_id", None)
    if workspace_column is None:
        raise _AiEvidenceStorageUnavailable(
            "ai_evidence_extractions has no workspace column to isolate on"
        )
    statement = statement.where(workspace_column == workspace_id)
    created_at = getattr(model, "created_at", None)
    if created_at is not None:
        statement = statement.order_by(created_at.asc())
    return list((await session.scalars(statement)).all())


@router.get("/ai-evidence/status", response_model=AiEvidenceStatusResponse)
async def get_ai_evidence_status(_current: CurrentUser) -> AiEvidenceStatusResponse:
    """Extractor configuration and counters.  No secret ever crosses this line."""

    config = _ai_evidence_config(get_settings())
    card = _ai_evidence_rate_card(config["model"])
    rate_available = card is not None
    return AiEvidenceStatusResponse(
        mode=config["mode"],
        provider=config["provider"],
        model=config["model"],
        reasoning_effort=config["reasoning_effort"],
        configured=config["configured"],
        shadow_only=config["shadow_only"],
        rate_card_available=rate_available,
        rate_card_reason=None if rate_available else "rate_card_unavailable",
        rate_version=card.rate_version if card is not None else None,
        rates_effective_date=card.effective_date if card is not None else None,
        rates_per_million=card.rates_per_million() if card is not None else {},
        estimate_disclaimer=ESTIMATE_DISCLAIMER,
        telemetry=ai_evidence_telemetry_snapshot(
            card=card,
            model_id=None if card is not None else config["model"],
        ),
    )


@router.get(
    "/observations/{observation_id}/ai-evidence",
    response_model=list[AiEvidenceExtractionResponse],
)
async def get_observation_ai_evidence(
    observation_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AiEvidenceExtractionResponse]:
    """Return persisted extraction evidence for one observation in this workspace."""

    if not await _observation_belongs_to_workspace(
        session,
        workspace_id=current.workspace_id,
        observation_id=observation_id,
    ):
        raise HTTPException(status_code=404, detail="Observation not found")
    try:
        rows = await _load_observation_ai_evidence(
            session,
            workspace_id=current.workspace_id,
            observation_id=observation_id,
        )
    except _AiEvidenceStorageUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="AI evidence storage is not available",
        ) from exc
    views = [AiEvidenceExtractionView.from_row(row) for row in rows]
    for view in views:
        if view.workspace_id is not None and view.workspace_id != current.workspace_id:
            # Defense in depth: a row that escaped the scoped query is treated
            # as a missing resource, never as content to serialize.
            raise HTTPException(status_code=404, detail="Observation not found")
        if (
            view.market_observation_id is not None
            and view.market_observation_id != observation_id
        ):
            raise HTTPException(status_code=404, detail="Observation not found")
    return [_ai_evidence_response(view) for view in views]


@router.post("/evaluate", response_model=PricingEvaluateResponse)
async def evaluate_price(
    payload: PricingEvaluateRequest,
    _current: CurrentUser,
) -> PricingEvaluateResponse:
    """Deterministic, side-effect-free evaluation useful for preview and QA."""
    try:
        policy = policy_from_dict(payload.policy)
    except PricingRunError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    coefficients = {
        (coefficient.category, coefficient.tier): coefficient.to_domain()
        for coefficient in payload.coefficients
    }
    result = recommend_price(
        payload.context.to_domain(),
        [offer.to_domain() for offer in payload.offers],
        coefficients,
        policy=policy,
    )
    return PricingEvaluateResponse(
        sku=result.sku,
        action=result.action.value,
        current_price=result.current_price,
        fair_price=result.fair_price,
        recommended_price=result.recommended_price,
        lower_bound=result.lower_bound,
        upper_bound=result.upper_bound,
        confidence=result.confidence,
        confidence_grade=result.confidence_grade,
        weakest_factor=result.weakest_factor,
        factor_scores=dict(result.factor_scores),
        competitor_count=result.competitor_count,
        raw_competitor_count=result.raw_competitor_count,
        unique_seller_count=result.unique_seller_count,
        clean_competitor_count=result.clean_competitor_count,
        target_market_count=result.target_market_count,
        kemp_reference_count=result.kemp_reference_count,
        owned_store_count=result.owned_store_count,
        rejected_count=result.rejected_count,
        effective_competitor_count=result.effective_competitor_count,
        dispersion=result.dispersion,
        dispersion_method=result.dispersion_method.value,
        dispersion_profile=dispersion_profile_to_dict(result.dispersion_profile),
        outlier_method=result.outlier_method,
        outlier_count=result.outlier_count,
        sensitivity=result.sensitivity,
        action_gates_passed=result.action_gates_passed,
        automatic_eligible=result.automatic_eligible,
        verified_seller_count=result.verified_seller_count,
        comparability_policy_id=result.comparability_policy_id,
        comparability_policy_hash=result.comparability_policy_hash,
        hard_gate_results=dict(result.hard_gate_results),
        failed_hard_gates=list(result.failed_hard_gates),
        unknown_hard_fields=list(result.unknown_hard_fields),
        robust_diagnostic=cluster_diagnostic_to_dict(result.cluster_diagnostic),
        robust_policy_fingerprint=dict(result.robust_policy_fingerprint),
        priority_score=result.priority_score,
        priority_score_type=result.priority_score_type.value,
        review_priority=result.review_priority,
        absolute_recommended_change=result.absolute_recommended_change,
        percentage_recommended_change=result.percentage_recommended_change,
        reasons=list(result.reasons),
        evidence=[_normalized_offer_payload(item) for item in result.evidence],
        kemp_reference_evidence=[
            _normalized_offer_payload(item) for item in result.kemp_reference_evidence
        ],
        excluded=[asdict(item) for item in result.excluded],
        policy_version=result.policy_version,
    )


def _normalized_offer_payload(item: object) -> dict[str, object]:
    """Serialize an immutable offer without deepcopying MappingProxyType evidence."""

    payload = {
        field.name: getattr(item, field.name)
        for field in fields(item)
        if field.name != "comparison_evidence"
    }
    payload["comparison_evidence"] = comparison_evidence_to_dict(
        getattr(item, "comparison_evidence")
    )
    return payload


def _preview_response(
    scope: PricingRunScope, contract: IssuedPreviewContract
) -> PricingRunPreviewResponse:
    return PricingRunPreviewResponse(
        scope_contract_version=scope.contract_version,
        import_batch_id=scope.import_batch_id,
        scope_mode=scope.scope_mode,
        policy_version=scope.policy_version,
        catalog_snapshot_hash=scope.catalog_snapshot_hash,
        scope_hash=scope.scope_hash,
        policy_snapshot_hash=scope.policy_hash,
        requires_full_catalog_confirmation=scope.requires_full_catalog_confirmation,
        estimate=PricingRunScopeEstimateResponse.model_validate(scope.estimate),
        exclusions=[
            PricingRunScopeExclusionResponse.model_validate(exclusion)
            for exclusion in scope.exclusions
        ],
        exclusions_truncated=scope.exclusions_truncated,
        scope_manifest=scope.manifest,
        preview_contract_version=contract.contract_version,
        preview_token=contract.token,
        preview_expires_at=contract.expires_at,
        preview_request_hash=contract.request_hash,
    )


def _preview_actor(current: AuthContext) -> PreviewActor:
    """Актор с ролью и правами на момент обращения — их и запоминает контракт."""

    return PreviewActor(
        actor_id=str(current.user.id),
        actor_type=ACTOR_TYPE_USER,
        workspace_role=current.workspace_role.value,
        permissions=(PRICING_RUN_START_PERMISSION,),
    )


@router.post("/runs/preview", response_model=PricingRunPreviewResponse)
async def preview_pricing_run_scope(
    payload: PricingRunPreviewRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PricingRunPreviewResponse:
    """Показать замороженную область прогона и выдать контракт на её запуск.

    Прогон здесь не создаётся.  Единственная запись — строка контракта: без неё
    старт нечем закрыть, потому что «ожидаемый хеш» сервер публикует сам и
    клиент лишь возвращает его обратно.
    """

    try:
        scope, contract = await preview_pricing_run_for_operator(
            session,
            workspace_id=current.workspace_id,
            import_batch_id=payload.import_batch_id,
            actor=_preview_actor(current),
            scope_mode=payload.scope_mode,
            catalog_item_ids=payload.catalog_item_ids,
            policy_config=payload.policy,
            confirm_full_catalog=payload.scope_mode == "FULL_CATALOG",
        )
    except PricingRunError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return _preview_response(scope, contract)


@router.post(
    "/runs", response_model=PricingRunResponse, status_code=status.HTTP_202_ACCEPTED
)
async def start_pricing_run(
    request: Request,
    payload: PricingRunCreateRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PricingRunResponse:
    try:
        # Старт оператора идёт только через типизированный контракт предпросмотра:
        # его нельзя собрать «без полей», и системным повтором он притвориться
        # не может.
        start = OperatorRunStart(
            idempotency_key=payload.idempotency_key,
            preview_token=payload.preview_token,
            actor=_preview_actor(current),
            confirm_full_catalog=payload.confirm_full_catalog,
        )
        run = await create_pricing_run(
            session,
            workspace_id=current.workspace_id,
            import_batch_id=payload.import_batch_id,
            celery_app=celery_app,
            start=start,
            policy_config=payload.policy,
            correlation_id=getattr(request.state, "correlation_id", None),
            scope_mode=payload.scope_mode,
            catalog_item_ids=payload.catalog_item_ids,
        )
    except PricingTaskDispatchError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (
        PricingRunScopeConflictError,
        PricingRunIdempotencyConflictError,
        PricingRunActiveScopeConflictError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PricingRunStartContractError as exc:
        # Отсутствующий, чужой, просроченный или не тот контракт — это отказ в
        # праве стартовать, а не «неверно заполненная форма».
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PricingRunError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PricingRunResponse.model_validate(run)


@router.get("/runs", response_model=PricingRunPageResponse)
async def get_pricing_runs(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PricingRunPageResponse:
    runs, total = await list_pricing_runs(
        session, workspace_id=current.workspace_id, limit=limit, offset=offset
    )
    return PricingRunPageResponse(
        items=[PricingRunResponse.model_validate(run) for run in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}", response_model=PricingRunResponse)
async def get_pricing_run_details(
    run_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PricingRunResponse:
    try:
        run = await get_pricing_run(
            session, workspace_id=current.workspace_id, run_id=run_id
        )
    except PricingRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Pricing run not found") from exc
    return PricingRunResponse.model_validate(run)


@router.get(
    "/runs/{run_id}/comparability-report",
    response_model=ComparabilityRunReportResponse,
)
async def get_pricing_run_comparability_report(
    run_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ComparabilityRunReportResponse:
    """Return coverage, safety, reliability and labelled accuracy separately."""

    try:
        run = await get_pricing_run(
            session,
            workspace_id=current.workspace_id,
            run_id=run_id,
        )
    except PricingRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Pricing run not found") from exc
    report = await build_comparability_run_report(session, run=run)
    return ComparabilityRunReportResponse.model_validate(report)


@router.get(
    "/runs/{run_id}/collection-metrics",
    response_model=ScraperMetricsResponse,
)
async def get_pricing_run_collection_metrics(
    run_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    arrival_rate_items_per_second: Annotated[float, Query(ge=0)] = 0.0,
    parallel_efficiency: Annotated[float, Query(gt=0, le=1)] = 1.0,
    database_write_capacity_per_second: Annotated[
        float | None,
        Query(gt=0),
    ] = None,
    queue_capacity_items_per_second: Annotated[
        float | None,
        Query(gt=0),
    ] = None,
) -> ScraperMetricsResponse:
    try:
        snapshot = await get_pricing_run_scraper_metrics(
            session,
            workspace_id=current.workspace_id,
            run_id=run_id,
            arrival_rate_items_per_second=arrival_rate_items_per_second,
            parallel_efficiency=parallel_efficiency,
            database_write_capacity_per_second=(database_write_capacity_per_second),
            queue_capacity_items_per_second=queue_capacity_items_per_second,
        )
    except PricingRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Pricing run not found") from exc
    return ScraperMetricsResponse.model_validate(snapshot)


@router.get(
    "/runs/{run_id}/collection-metrics/prometheus",
    response_class=PlainTextResponse,
)
async def get_pricing_run_collection_metrics_prometheus(
    run_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlainTextResponse:
    try:
        snapshot = await get_pricing_run_scraper_metrics(
            session,
            workspace_id=current.workspace_id,
            run_id=run_id,
        )
    except PricingRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Pricing run not found") from exc
    return PlainTextResponse(
        render_prometheus(snapshot),
        media_type="text/plain; version=0.0.4",
    )


@router.post("/runs/{run_id}/cancel", response_model=PricingRunResponse)
async def request_run_cancellation(
    run_id: UUID,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PricingRunResponse:
    try:
        run = await cancel_pricing_run(
            session, workspace_id=current.workspace_id, run_id=run_id
        )
    except PricingRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Pricing run not found") from exc
    return PricingRunResponse.model_validate(run)


@router.post(
    "/coefficients/calibrate",
    response_model=list[TierCoefficientResponse],
    status_code=status.HTTP_201_CREATED,
)
async def calibrate_coefficients(
    payload: CalibrationRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[TierCoefficientResponse]:
    pairs = [
        CalibrationPair(
            oe_norm=pair.oe_norm,
            category=pair.category,
            tier=pair.tier,
            tier_price=pair.tier_price,
            reference_price=pair.reference_price,
            quality_weight=pair.quality_weight,
            tier_observation_ids=pair.tier_observation_ids,
            reference_observation_ids=pair.reference_observation_ids,
        )
        for pair in payload.pairs
    ]
    records = await calibrate_tier_coefficients(
        session,
        workspace_id=current.workspace_id,
        pairs=pairs,
        model=payload.model,
        shrinkage_k=payload.shrinkage_k,
        min_category_pairs=payload.min_category_pairs,
        min_global_pairs=payload.min_global_pairs,
        min_effective_pairs=payload.min_effective_pairs,
        max_interval_ratio=payload.max_interval_ratio,
    )
    return [TierCoefficientResponse.model_validate(record) for record in records]


@router.get("/coefficients", response_model=TierCoefficientPageResponse)
async def get_coefficients(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    pricing_run_id: UUID | None = None,
    category: str | None = None,
    model: Literal["simple_median", "shrinkage"] | None = None,
    validated: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TierCoefficientPageResponse:
    records, total = await list_tier_coefficients(
        session,
        workspace_id=current.workspace_id,
        pricing_run_id=pricing_run_id,
        category=category,
        model=CoefficientModel(model) if model else None,
        validated=validated,
        limit=limit,
        offset=offset,
    )
    return TierCoefficientPageResponse(
        items=[TierCoefficientResponse.model_validate(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/catalog-items/{catalog_item_id}/overrides",
    response_model=CatalogItemOverrideResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_catalog_override(
    catalog_item_id: UUID,
    payload: CatalogItemOverrideRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogItemOverrideResponse:
    try:
        override = await add_catalog_item_override(
            session,
            workspace_id=current.workspace_id,
            user_id=current.user.id,
            catalog_item_id=catalog_item_id,
            values=payload.model_dump(exclude_unset=True),
        )
    except CatalogItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Catalog item not found") from exc
    except PricingRunError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response_data = {
        name: getattr(override, name)
        for name in CatalogItemOverrideResponse.model_fields
        if name not in {"cost_configured", "cost_privacy_mode"}
    }
    cost_record = await get_latest_cost_record(
        session,
        workspace_id=current.workspace_id,
        catalog_item_id=catalog_item_id,
    )
    response_data.update(
        cost_configured=cost_record is not None and cost_record.action == "SET",
        cost_privacy_mode=get_settings().cost_privacy_mode,
    )
    return CatalogItemOverrideResponse.model_validate(response_data)


@router.get("/recommendations", response_model=RecommendationPageResponse)
async def get_recommendations(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    run_id: UUID | None = None,
    action: Literal["RAISE", "HOLD", "LOWER", "MANUAL_REVIEW", "INSUFFICIENT_DATA"]
    | None = None,
    confidence_grade: str | None = None,
    category: str | None = None,
    queue: Literal["raise", "clearance", "review", "hold", "all"] = "all",
    priority_score_type: str | None = None,
    confidence_min: Annotated[Decimal | None, Query(ge=0, le=1)] = None,
    confidence_max: Annotated[Decimal | None, Query(ge=0, le=1)] = None,
    sort: Literal[
        "ABSOLUTE_RECOMMENDED_CHANGE",
        "PERCENT_RECOMMENDED_CHANGE",
        "EXPECTED_GROSS_UPLIFT",
        "CLEARANCE_CAPITAL_LOCK",
        "REVIEW_PRIORITY",
        "NEWEST",
    ] = "ABSOLUTE_RECOMMENDED_CHANGE",
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RecommendationPageResponse:
    if (
        confidence_min is not None
        and confidence_max is not None
        and confidence_min > confidence_max
    ):
        raise HTTPException(
            status_code=422, detail="confidence_min cannot exceed confidence_max"
        )
    try:
        rows, total, resolved_run_id, action_counts = await list_recommendations(
            session,
            workspace_id=current.workspace_id,
            run_id=run_id,
            action=action,
            confidence_grade=confidence_grade,
            category=category,
            queue=queue,
            priority_score_type=priority_score_type,
            confidence_min=confidence_min,
            confidence_max=confidence_max,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except PricingRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Pricing run not found") from exc
    return RecommendationPageResponse(
        items=[
            _recommendation_response(recommendation, item)
            for recommendation, item in rows
        ],
        total=total,
        run_id=resolved_run_id,
        limit=limit,
        offset=offset,
        action_counts=RecommendationActionCountsResponse.model_validate(action_counts),
    )


@router.get("/recommendations/export")
async def download_recommendations(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    format: Literal["csv", "xlsx"] = "xlsx",
    run_id: UUID | None = None,
    action: Literal["RAISE", "HOLD", "LOWER", "MANUAL_REVIEW", "INSUFFICIENT_DATA"]
    | None = None,
    confidence_grade: str | None = None,
    category: str | None = None,
    queue: Literal["raise", "clearance", "review", "hold", "all"] = "all",
    priority_score_type: str | None = None,
    confidence_min: Annotated[Decimal | None, Query(ge=0, le=1)] = None,
    confidence_max: Annotated[Decimal | None, Query(ge=0, le=1)] = None,
    sort: Literal[
        "ABSOLUTE_RECOMMENDED_CHANGE",
        "PERCENT_RECOMMENDED_CHANGE",
        "EXPECTED_GROSS_UPLIFT",
        "CLEARANCE_CAPITAL_LOCK",
        "REVIEW_PRIORITY",
        "NEWEST",
    ] = "ABSOLUTE_RECOMMENDED_CHANGE",
) -> Response:
    if (
        confidence_min is not None
        and confidence_max is not None
        and confidence_min > confidence_max
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_CONFIDENCE_RANGE",
                "message": "confidence_min cannot exceed confidence_max",
            },
        )
    try:
        export = await export_recommendations(
            session,
            workspace_id=current.workspace_id,
            export_format=format,
            run_id=run_id,
            action=action,
            confidence_grade=confidence_grade,
            category=category,
            queue=queue,
            priority_score_type=priority_score_type,
            confidence_min=confidence_min,
            confidence_max=confidence_max,
            sort=sort,
        )
    except PricingRunNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "PRICING_RUN_NOT_FOUND",
                "message": "Pricing run not found",
            },
        ) from exc
    except RecommendationExportError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return Response(
        content=export.content,
        media_type=export.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{export.filename}"',
            "X-Export-Row-Count": str(export.row_count),
        },
    )


@router.get(
    "/recommendations/{recommendation_id}", response_model=RecommendationResponse
)
async def get_recommendation_details(
    recommendation_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RecommendationResponse:
    try:
        recommendation, item = await get_recommendation(
            session,
            workspace_id=current.workspace_id,
            recommendation_id=recommendation_id,
        )
    except RecommendationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Recommendation not found") from exc
    return _recommendation_response(recommendation, item)


@router.get(
    "/recommendations/{recommendation_id}/evidence",
    response_model=list[RecommendationEvidenceResponse],
)
async def get_recommendation_market_evidence(
    recommendation_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[RecommendationEvidenceResponse]:
    try:
        recommendation, _ = await get_recommendation(
            session,
            workspace_id=current.workspace_id,
            recommendation_id=recommendation_id,
        )
        rows = await get_recommendation_evidence(
            session,
            workspace_id=current.workspace_id,
            recommendation_id=recommendation_id,
        )
    except RecommendationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Recommendation not found") from exc
    effective_reviews = await load_effective_review_map(
        session,
        [observation.id for observation, _ in rows],
    )
    llm_trace = recommendation.calculation_trace.get("llm_comparability")
    llm_review_required = bool(
        isinstance(llm_trace, dict) and llm_trace.get("required")
    )
    normalized_by_id = {
        str(value.get("observation_id")): value
        for value in recommendation.calculation_trace.get("normalized_offers", [])
        if isinstance(value, dict) and value.get("observation_id")
    }
    normalized_by_id.update(
        {
            str(value.get("observation_id")): value
            for value in recommendation.calculation_trace.get(
                "kemp_reference_offers", []
            )
            if isinstance(value, dict) and value.get("observation_id")
        }
    )
    excluded_by_id = {
        str(value.get("observation_id")): value
        for value in recommendation.calculation_trace.get("excluded_observations", [])
        if isinstance(value, dict) and value.get("observation_id")
    }
    run_item_ids = {observation.pricing_run_item_id for observation, _ in rows}
    outcome_counts_by_item: dict[UUID, dict[str, int]] = {
        run_item_id: {} for run_item_id in run_item_ids
    }
    if run_item_ids:
        outcome_rows = list(
            (
                await session.execute(
                    select(
                        OfferProcessingOutcome.pricing_run_item_id,
                        OfferProcessingOutcome.outcome_code,
                        func.count(OfferProcessingOutcome.id),
                    )
                    .where(OfferProcessingOutcome.pricing_run_item_id.in_(run_item_ids))
                    .group_by(
                        OfferProcessingOutcome.pricing_run_item_id,
                        OfferProcessingOutcome.outcome_code,
                    )
                )
            ).all()
        )
        for run_item_id, outcome_code, count in outcome_rows:
            outcome_counts_by_item[run_item_id][outcome_code] = int(count)
    response: list[RecommendationEvidenceResponse] = []
    for observation, classification in rows:
        semantic_review = effective_reviews.get(observation.id)
        normalized = normalized_by_id.get(str(observation.id), {})
        excluded = excluded_by_id.get(str(observation.id), {})
        cohort_role = str(
            normalized.get("cohort_role")
            or excluded.get("cohort_role")
            or classification.cohort_role
        )
        multiplier_raw = normalized.get("multiplier", normalized.get("coefficient"))
        normalized_price_raw = normalized.get("normalized_price")
        coefficient_confidence_raw = normalized.get("coefficient_confidence")
        age_hours_raw = normalized.get("age_hours")
        if age_hours_raw is None:
            observed_age_seconds = (
                recommendation.computed_at - observation.observed_at
            ).total_seconds()
            age_hours = (
                Decimal(str(observed_age_seconds / 3600))
                if observed_age_seconds >= 0
                else None
            )
        else:
            age_hours = Decimal(str(age_hours_raw))
        safe_url, validation_absence_reason = _validated_listing_url(observation.url)
        url_absence_reason = (
            validation_absence_reason
            if validation_absence_reason == "INVALID_URL_PROTOCOL"
            else observation.url_absence_reason or validation_absence_reason
        )
        response.append(
            RecommendationEvidenceResponse(
                observation_id=observation.id,
                seller_id=observation.seller_id,
                seller_name=observation.seller_name,
                title=observation.title,
                description=observation.description,
                description_available=observation.description_available,
                condition_raw=observation.condition_raw,
                condition_state=observation.condition_state,
                condition_reason_codes=observation.condition_reason_codes,
                cross_candidates=observation.cross_candidates,
                brand=observation.brand_raw,
                search_oe_norm=observation.search_oe_norm,
                extracted_oe_norms=observation.extracted_oe_norms,
                verified_matched_oe_norm=observation.verified_matched_oe_norm,
                comparison_identity_key=observation.comparison_identity_key,
                oe_verification_status=observation.oe_verification_status,
                oe_evidence_summary=_safe_oe_evidence_summary(observation.oe_evidence),
                oe_extractor_version=observation.oe_extractor_version,
                oe_reenriched_at=observation.oe_reenriched_at,
                oe_reenrichment_error_code=(observation.oe_reenrichment_error_code),
                url=safe_url,
                url_absence_reason=url_absence_reason,
                price=effective_observation_price(observation),
                currency=observation.currency,
                currency_raw=observation.currency_raw,
                currency_inferred=observation.currency_inferred,
                is_available=observation.is_available,
                match_confidence=observation.match_confidence,
                source_confidence=observation.source_confidence,
                source_confidence_factors=observation.source_confidence_factors,
                source_confidence_method_version=(
                    observation.source_confidence_method_version
                ),
                age_hours=age_hours,
                tier=classification.tier,
                tier_confidence=classification.tier_confidence,
                is_used=classification.is_used,
                is_kemp=classification.is_kemp,
                is_owned=classification.is_owned,
                is_dumping=classification.is_dumping,
                cohort_role=cohort_role,
                target_effect=(
                    "IN_TARGET_MEDIAN"
                    if cohort_role == "TARGET_MARKET"
                    else "NOT_IN_TARGET_MEDIAN"
                ),
                exclusion_reason=classification.exclusion_reason,
                normalized_price=(
                    Decimal(str(normalized_price_raw))
                    if normalized_price_raw is not None
                    else None
                ),
                multiplier=(
                    Decimal(str(multiplier_raw)) if multiplier_raw is not None else None
                ),
                coefficient_model=(
                    str(normalized.get("coefficient_model"))
                    if normalized.get("coefficient_model") is not None
                    else None
                ),
                coefficient_version=(
                    str(normalized.get("coefficient_version"))
                    if normalized.get("coefficient_version") is not None
                    else None
                ),
                coefficient_confidence=(
                    Decimal(str(coefficient_confidence_raw))
                    if coefficient_confidence_raw is not None
                    else None
                ),
                observed_at=observation.observed_at,
                automatic_eligible=observation.automatic_eligible,
                comparability_hard_gate_result=(
                    observation.comparability_hard_gate_result
                ),
                calibration_exclusion_codes=(observation.calibration_exclusion_codes),
                offer_outcome_counts=outcome_counts_by_item.get(
                    observation.pricing_run_item_id,
                    {},
                ),
                comparability_policy_id=observation.comparability_policy_id,
                comparability_policy_hash=observation.comparability_policy_hash,
                comparison_evidence=observation.comparison_evidence,
                candidate_snapshot=observation.candidate_snapshot,
                llm_review_required=llm_review_required,
                llm_pricing_eligible=bool(
                    semantic_review is not None and semantic_review.comparable
                ),
                llm_review=(
                    ComparabilityReviewResponse.model_validate(
                        semantic_review.as_dict()
                    )
                    if semantic_review is not None
                    else None
                ),
            )
        )
    return response


@router.post(
    "/observations/{observation_id}/comparability-reviews",
    response_model=ComparabilityReviewResponse,
)
async def review_market_observation_comparability(
    observation_id: UUID,
    payload: ComparabilityReviewRequest,
    current: WorkspaceAdmin,
) -> ComparabilityReviewResponse:
    """Run or retrieve the immutable semantic review for one candidate."""

    try:
        review = await request_observation_comparability_review(
            observation_id,
            workspace_id=current.workspace_id,
            force=payload.force,
        )
    except ComparabilityReviewNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "COMPARABILITY_OBSERVATION_NOT_FOUND",
                "message": "Market observation not found",
            },
        ) from exc
    except ComparabilityReviewUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "LLM_COMPARABILITY_DISABLED",
                "message": str(exc),
            },
        ) from exc
    return ComparabilityReviewResponse.model_validate(review.as_dict())


@router.post(
    "/comparability-reviews/{review_id}/feedback",
    response_model=ComparabilityReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_comparability_feedback(
    review_id: UUID,
    payload: ComparabilityFeedbackRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ComparabilityReviewResponse:
    """Append a customer confirmation/correction as labelled evidence."""

    try:
        review = await add_comparability_feedback(
            session,
            workspace_id=current.workspace_id,
            user_id=current.user.id,
            review_id=review_id,
            decision=payload.decision,
            corrected_verdict=payload.corrected_verdict,
            corrected_match_level=payload.corrected_match_level,
            corrected_identity_verdict=payload.corrected_identity_verdict,
            corrected_identity_match_level=payload.corrected_identity_match_level,
            corrected_pricing_admission=payload.corrected_pricing_admission,
            confidence=payload.confidence,
            reason=payload.reason,
            evidence_corrections=[
                item.model_dump(mode="json") for item in payload.evidence_corrections
            ],
        )
    except ComparabilityReviewNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "COMPARABILITY_REVIEW_NOT_FOUND",
                "message": "Comparability review not found",
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_COMPARABILITY_FEEDBACK",
                "message": str(exc),
            },
        ) from exc
    return ComparabilityReviewResponse.model_validate(review.as_dict())


@router.get(
    "/recommendations/{recommendation_id}/replay",
    response_model=RecommendationReplayResponse,
)
async def replay_persisted_recommendation(
    recommendation_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RecommendationReplayResponse:
    try:
        replay = await replay_recommendation(
            session,
            workspace_id=current.workspace_id,
            recommendation_id=recommendation_id,
        )
    except RecommendationNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Recommendation not found",
        ) from exc
    except RecommendationReplayUnavailable as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RECOMMENDATION_REPLAY_UNAVAILABLE",
                "message": str(exc),
            },
        ) from exc
    return RecommendationReplayResponse(
        recommendation_id=replay.recommendation_id,
        replay_contract_version=replay.replay_contract_version,
        calculated_at=replay.calculated_at,
        exact_match=replay.exact_match,
        mismatches=privacy_safe_mapping(replay.mismatches),
        replayed=privacy_safe_mapping(replay.replayed),
    )


@router.post(
    "/observations/{observation_id}/tier-overrides",
    response_model=ObservationTierOverrideResponse,
    status_code=status.HTTP_201_CREATED,
)
async def override_market_observation_tier(
    observation_id: UUID,
    payload: ObservationTierOverrideRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ObservationTierOverrideResponse:
    try:
        record = await override_observation_tier(
            session,
            workspace_id=current.workspace_id,
            user_id=current.user.id,
            observation_id=observation_id,
            tier=payload.tier,
            reason=payload.reason,
        )
    except RecommendationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Observation not found") from exc
    except PricingRunError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ObservationTierOverrideResponse.model_validate(record)


@router.post(
    "/recommendations/{recommendation_id}/decisions",
    response_model=RecommendationDecisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def decide_recommendation(
    recommendation_id: UUID,
    payload: RecommendationDecisionRequest,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RecommendationDecisionResponse:
    try:
        decision = await add_recommendation_decision(
            session,
            workspace_id=current.workspace_id,
            recommendation_id=recommendation_id,
            user_id=current.user.id,
            decision=payload.decision,
            new_price=payload.new_price,
            allow_below_cost=payload.allow_below_cost,
            warning_confirmed=payload.warning_confirmed,
            reason=payload.reason,
        )
    except RecommendationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Recommendation not found") from exc
    except PricingRunError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response_data = {
        name: getattr(decision, name)
        for name in RecommendationDecisionResponse.model_fields
        if name != "context_snapshot"
    }
    response_data["context_snapshot"] = privacy_safe_mapping(decision.context_snapshot)
    return RecommendationDecisionResponse.model_validate(response_data)


def _safe_oe_evidence_summary(
    evidence: Any,
) -> list[dict[str, Any]]:
    """Expose trace identifiers and normalized facts, never retained raw content."""

    if not isinstance(evidence, list):
        return []
    result: list[dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "evidence_ref": item.get("evidence_ref"),
                "source_kind": item.get("source_kind"),
                "normalized_value": item.get("normalized_value"),
                "confidence": item.get("confidence"),
                "raw_capture_id": item.get("raw_capture_id"),
                "extractor_version": item.get("extractor_version"),
            }
        )
    return result


def _recommendation_response(recommendation, item) -> RecommendationResponse:
    robust_trace = recommendation.calculation_trace.get("robust_dispersion", {})
    if not isinstance(robust_trace, dict):
        robust_trace = {}
    identity = _export_identity_fields(item)
    identity_blocked = not recommendation_price_identity_allowed(
        item, recommendation.action
    )
    response_action = (
        "MANUAL_REVIEW" if identity_blocked else recommendation.action
    )
    response_reason_codes = list(recommendation.reason_codes or [])
    if identity_blocked and IDENTITY_BLOCKED_RECOMMENDATION_ACTION not in response_reason_codes:
        response_reason_codes.append(IDENTITY_BLOCKED_RECOMMENDATION_ACTION)
    # ``PricingRecommendation`` is append-only.  Do not mutate the historical
    # row just because a later identity reparse proved it was MPN_ONLY; instead
    # downgrade the read boundary and remove every derived market-price field.
    response_fair_price = None if identity_blocked else recommendation.fair_price
    response_recommended_price = (
        None if identity_blocked else recommendation.recommended_price
    )
    response_lower_bound = None if identity_blocked else recommendation.lower_bound
    response_upper_bound = None if identity_blocked else recommendation.upper_bound
    response_absolute_change = (
        None
        if identity_blocked
        else recommendation.absolute_recommended_change
    )
    response_percentage_change = (
        None
        if identity_blocked
        else recommendation.percentage_recommended_change
    )
    return RecommendationResponse(
        id=recommendation.id,
        pricing_run_id=recommendation.pricing_run_id,
        catalog_snapshot_id=recommendation.catalog_snapshot_id,
        catalog_item_id=item.id,
        sku=item.sku,
        oe_norm=identity["oe"],
        mpn_norm=identity["mpn"] or None,
        search_identity=identity["search_identity"] or None,
        identity_status=identity["identity_status"],
        catalog_data_evidence=catalog_data_evidence(item).as_dict(),
        name=item.name,
        category=item.category,
        stock_status=recommendation.context_snapshot.get(
            "stock_status", item.stock_status
        ),
        context_snapshot=privacy_safe_mapping(recommendation.context_snapshot),
        calculation_trace=privacy_safe_mapping(recommendation.calculation_trace),
        action=response_action,
        current_price=recommendation.current_price,
        fair_price=response_fair_price,
        recommended_price=response_recommended_price,
        lower_bound=response_lower_bound,
        upper_bound=response_upper_bound,
        confidence=recommendation.confidence,
        confidence_grade=recommendation.confidence_grade,
        weakest_factor=recommendation.weakest_factor,
        factor_scores=recommendation.factor_scores,
        competitor_count=recommendation.competitor_count,
        raw_competitor_count=recommendation.raw_competitor_count,
        unique_seller_count=recommendation.unique_seller_count,
        clean_competitor_count=recommendation.clean_competitor_count,
        target_market_count=recommendation.target_market_count,
        kemp_reference_count=recommendation.kemp_reference_count,
        owned_store_count=recommendation.owned_store_count,
        rejected_count=recommendation.rejected_count,
        effective_competitor_count=recommendation.effective_competitor_count,
        dispersion=recommendation.dispersion,
        dispersion_method=str(robust_trace.get("selected_method", "legacy_mad")),
        dispersion_profile=(
            robust_trace.get("post_clean")
            if isinstance(robust_trace.get("post_clean"), dict)
            else None
        ),
        outlier_method=recommendation.outlier_method,
        outlier_count=recommendation.outlier_count,
        sensitivity=recommendation.sensitivity,
        action_gates_passed=(
            False if identity_blocked else recommendation.action_gates_passed
        ),
        automatic_eligible=(
            False if identity_blocked else recommendation.automatic_eligible
        ),
        verified_seller_count=recommendation.verified_seller_count,
        comparability_policy_id=recommendation.comparability_policy_id,
        comparability_policy_hash=recommendation.comparability_policy_hash,
        decision_fingerprint=recommendation.decision_fingerprint,
        hard_gate_trace=recommendation.hard_gate_trace,
        robust_diagnostic=recommendation.robust_diagnostic,
        priority_score=recommendation.priority_score,
        priority_score_type=recommendation.priority_score_type,
        review_priority=recommendation.review_priority,
        absolute_recommended_change=response_absolute_change,
        percentage_recommended_change=response_percentage_change,
        reason_codes=response_reason_codes,
        evidence_observation_ids=recommendation.evidence_observation_ids,
        kemp_reference_observation_ids=(recommendation.kemp_reference_observation_ids),
        excluded_observations=recommendation.excluded_observations,
        policy_version=recommendation.policy_version,
        parser_version=recommendation.parser_version,
        classifier_version=recommendation.classifier_version,
        coefficient_version=recommendation.coefficient_version,
        calibration_dataset_hash=recommendation.calibration_dataset_hash,
        currency=recommendation.currency,
        price_tick=recommendation.price_tick,
        price_tick_version=recommendation.price_tick_version,
        computed_at=recommendation.computed_at,
    )
