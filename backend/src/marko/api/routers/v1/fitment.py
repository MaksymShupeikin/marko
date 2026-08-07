"""Workspace-scoped API for evidence-first fitment intelligence."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from marko.api.dependencies import CurrentUser, WorkspaceAdmin, get_session
from marko.api.schemas.fitment import (
    CrossReferencePageResponse,
    CrossReferenceRequest,
    CrossReferenceResponse,
    FitmentAnalysisResponse,
    FitmentAnalyzeRequest,
    FitmentCandidatePageResponse,
    FitmentCandidateResponse,
    FitmentNotificationPageResponse,
    FitmentNotificationResponse,
    FitmentRecommendationCreateRequest,
    FitmentRecommendationResponse,
    FitmentRecommendationReviewRequest,
    FitmentRecommendationReviewResponse,
    FitmentReviewRequest,
    FitmentReviewResponse,
    FitmentSourceRequest,
    FitmentSourceCapabilityResponse,
    FitmentSourceReliabilityResponse,
    FitmentSourceResponse,
    SellerRelationRequest,
    SellerRelationResponse,
    SellerResolutionRequest,
    SellerResolutionResponse,
    SourceDocumentRequest,
    SourceDocumentResponse,
    SourceRouteResponse,
)
from marko.services.fitment_intelligence import (
    AnalysisSpec,
    CandidateAnalysisSpec,
    FitmentIdempotencyConflict,
    FitmentIntelligenceError,
    FitmentNotFoundError,
    FitmentSourceBlocked,
    SubmittedEvidence,
    add_fitment_review,
    add_seller_relation,
    enqueue_fitment_analysis,
    fitment_metrics,
    get_fitment_analysis,
    list_fitment_candidates,
    list_source_capabilities,
    list_source_reliability,
    record_cross_reference,
    register_fitment_source,
    register_source_document,
    retry_fitment_analysis,
    search_cross_references,
)
from marko.services.fitment_hitl import (
    generate_fitment_recommendation,
    get_fitment_recommendation,
    list_fitment_notifications,
    mark_fitment_notification_read,
    review_fitment_recommendation,
)
from marko.services.fitment_source_routing import route_fitment_sources
from marko.services.market_price import effective_observation_price
from marko.worker.celery_app import celery_app
from metis.fitment import (
    CommercialContext,
    EvidenceClaim,
    PartIdentity,
    RecommendationDecision,
    SellerRelation,
    resolve_seller_relation,
)


router = APIRouter()


def _part_identity(payload) -> PartIdentity:
    data = payload.model_dump()
    data["oe_numbers"] = tuple(data["oe_numbers"])
    return PartIdentity(**data)


def _commercial_context(payload) -> CommercialContext:
    return CommercialContext(**payload.model_dump())


def _submitted_evidence(payload) -> SubmittedEvidence:
    data = payload.model_dump(exclude={"source_document_id"})
    return SubmittedEvidence(
        claim=EvidenceClaim(**data),
        source_document_id=payload.source_document_id,
    )


def _raise_fitment_http(exc: Exception) -> None:
    if isinstance(exc, FitmentNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, (FitmentIdempotencyConflict, FitmentSourceBlocked)):
        raise HTTPException(
            status_code=409,
            detail={"code": type(exc).__name__, "message": str(exc)},
        ) from exc
    if isinstance(exc, (FitmentIntelligenceError, ValueError)):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.post(
    "/sources",
    response_model=FitmentSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_source(
    payload: FitmentSourceRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FitmentSourceResponse:
    try:
        record = await register_fitment_source(
            session,
            workspace_id=current.workspace_id,
            actor_user_id=current.user.id,
            **payload.model_dump(),
        )
    except (FitmentIntelligenceError, FitmentNotFoundError) as exc:
        _raise_fitment_http(exc)
    return FitmentSourceResponse.model_validate(record)


@router.post(
    "/sources/{source_id}/documents",
    response_model=SourceDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_source_document(
    source_id: UUID,
    payload: SourceDocumentRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SourceDocumentResponse:
    try:
        record = await register_source_document(
            session,
            workspace_id=current.workspace_id,
            actor_user_id=current.user.id,
            source_id=source_id,
            **payload.model_dump(),
        )
    except (FitmentIntelligenceError, FitmentNotFoundError) as exc:
        _raise_fitment_http(exc)
    return SourceDocumentResponse.model_validate(record)


@router.get(
    "/sources/{source_id}/capabilities",
    response_model=list[FitmentSourceCapabilityResponse],
)
async def get_source_capabilities(
    source_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[FitmentSourceCapabilityResponse]:
    try:
        rows = await list_source_capabilities(
            session,
            workspace_id=current.workspace_id,
            source_id=source_id,
        )
    except FitmentNotFoundError as exc:
        _raise_fitment_http(exc)
    return [FitmentSourceCapabilityResponse.model_validate(row) for row in rows]


@router.get(
    "/sources/{source_id}/reliability",
    response_model=list[FitmentSourceReliabilityResponse],
)
async def get_source_reliability(
    source_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[FitmentSourceReliabilityResponse]:
    try:
        rows = await list_source_reliability(
            session,
            workspace_id=current.workspace_id,
            source_id=source_id,
        )
    except FitmentNotFoundError as exc:
        _raise_fitment_http(exc)
    return [FitmentSourceReliabilityResponse.model_validate(row) for row in rows]


@router.get("/source-routing", response_model=SourceRouteResponse)
async def get_source_route(
    current: CurrentUser,
    brand: Annotated[str | None, Query(max_length=255)] = None,
) -> SourceRouteResponse:
    del current
    return SourceRouteResponse.model_validate(route_fitment_sources(brand))


@router.post(
    "/products/{catalog_item_id}/analyze",
    response_model=FitmentAnalysisResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_product(
    catalog_item_id: UUID,
    payload: FitmentAnalyzeRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FitmentAnalysisResponse:
    try:
        candidates = tuple(
            CandidateAnalysisSpec(
                market_observation_id=item.market_observation_id,
                identity=_part_identity(item.identity),
                commercial_context=_commercial_context(item.commercial_context),
                evidence=tuple(_submitted_evidence(claim) for claim in item.evidence),
            )
            for item in payload.candidates
        )
        record = await enqueue_fitment_analysis(
            session,
            workspace_id=current.workspace_id,
            actor_user_id=current.user.id,
            catalog_item_id=catalog_item_id,
            pricing_run_id=payload.pricing_run_id,
            idempotency_key=payload.idempotency_key,
            spec=AnalysisSpec(
                target_identity=_part_identity(payload.target_identity),
                target_commercial_context=_commercial_context(
                    payload.target_commercial_context
                ),
                candidates=candidates,
                source_policy_snapshot=payload.source_policy_snapshot,
            ),
            celery_app=celery_app,
        )
    except (
        FitmentIntelligenceError,
        FitmentNotFoundError,
        ValueError,
    ) as exc:
        _raise_fitment_http(exc)
    return FitmentAnalysisResponse.model_validate(record)


@router.get(
    "/products/{catalog_item_id}/candidates",
    response_model=FitmentCandidatePageResponse,
)
async def get_product_candidates(
    catalog_item_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    analysis_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FitmentCandidatePageResponse:
    try:
        rows, total, analysis = await list_fitment_candidates(
            session,
            workspace_id=current.workspace_id,
            catalog_item_id=catalog_item_id,
            analysis_id=analysis_id,
            limit=limit,
            offset=offset,
        )
    except (FitmentIntelligenceError, FitmentNotFoundError) as exc:
        _raise_fitment_http(exc)
    items = []
    for assessment, observation, evidence_claims in rows:
        data = {
            name: getattr(assessment, name)
            for name in FitmentCandidateResponse.model_fields
            if hasattr(assessment, name)
        }
        data.update(
            seller_id=observation.seller_id,
            seller_name=observation.seller_name,
            title=observation.title,
            brand=observation.brand_raw,
            url=observation.url,
            price=effective_observation_price(observation),
            reference_price=observation.reference_price,
            currency=observation.currency,
            observed_at=observation.observed_at,
            evidence_claim_ids=[claim.id for claim in evidence_claims],
            evidence=evidence_claims,
        )
        items.append(FitmentCandidateResponse.model_validate(data))
    return FitmentCandidatePageResponse(
        items=items,
        total=total,
        analysis_id=analysis.id if analysis else None,
        limit=limit,
        offset=offset,
    )


@router.get("/analysis-jobs/{analysis_id}", response_model=FitmentAnalysisResponse)
async def get_analysis_job(
    analysis_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FitmentAnalysisResponse:
    try:
        record = await get_fitment_analysis(
            session, workspace_id=current.workspace_id, analysis_id=analysis_id
        )
    except FitmentNotFoundError as exc:
        _raise_fitment_http(exc)
    return FitmentAnalysisResponse.model_validate(record)


@router.get("/analysis-jobs/{analysis_id}/metrics")
async def get_analysis_metrics(
    analysis_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    try:
        return await fitment_metrics(
            session, workspace_id=current.workspace_id, analysis_id=analysis_id
        )
    except FitmentNotFoundError as exc:
        _raise_fitment_http(exc)


@router.post(
    "/analysis-jobs/{analysis_id}/retry",
    response_model=FitmentAnalysisResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_analysis_job(
    analysis_id: UUID,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FitmentAnalysisResponse:
    try:
        record = await retry_fitment_analysis(
            session,
            workspace_id=current.workspace_id,
            actor_user_id=current.user.id,
            analysis_id=analysis_id,
            celery_app=celery_app,
        )
    except (FitmentIntelligenceError, FitmentNotFoundError) as exc:
        _raise_fitment_http(exc)
    return FitmentAnalysisResponse.model_validate(record)


@router.post(
    "/products/{catalog_item_id}/recommendations",
    response_model=FitmentRecommendationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_fitment_recommendation(
    catalog_item_id: UUID,
    payload: FitmentRecommendationCreateRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FitmentRecommendationResponse:
    try:
        record = await generate_fitment_recommendation(
            session,
            workspace_id=current.workspace_id,
            actor_user_id=current.user.id,
            catalog_item_id=catalog_item_id,
            **payload.model_dump(),
        )
    except (FitmentIntelligenceError, FitmentNotFoundError, ValueError) as exc:
        _raise_fitment_http(exc)
    return FitmentRecommendationResponse.model_validate(record)


@router.get(
    "/products/{catalog_item_id}/recommendation",
    response_model=FitmentRecommendationResponse,
)
async def get_product_fitment_recommendation(
    catalog_item_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    recommendation_id: UUID | None = None,
) -> FitmentRecommendationResponse:
    record = await get_fitment_recommendation(
        session,
        workspace_id=current.workspace_id,
        catalog_item_id=catalog_item_id,
        recommendation_id=recommendation_id,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="fitment recommendation not found")
    return FitmentRecommendationResponse.model_validate(record)


async def _review_recommendation(
    *,
    recommendation_id: UUID,
    decision: RecommendationDecision,
    payload: FitmentRecommendationReviewRequest,
    current,
    session: AsyncSession,
) -> FitmentRecommendationReviewResponse:
    resolved_decision = (
        RecommendationDecision.ACCEPTED_WITH_MODIFICATION
        if decision == RecommendationDecision.ACCEPTED
        and payload.accept_with_modification
        else decision
    )
    try:
        record = await review_fitment_recommendation(
            session,
            workspace_id=current.workspace_id,
            actor_user_id=current.user.id,
            recommendation_id=recommendation_id,
            idempotency_key=payload.idempotency_key,
            decision=resolved_decision,
            approved_price=payload.approved_price,
            reason_code=payload.reason_code,
            comment=payload.comment,
            allow_below_floor=payload.allow_below_floor,
            below_floor_warning_confirmed=payload.below_floor_warning_confirmed,
        )
    except (FitmentIntelligenceError, FitmentNotFoundError, ValueError) as exc:
        _raise_fitment_http(exc)
    return FitmentRecommendationReviewResponse.model_validate(record)


@router.post(
    "/recommendations/{recommendation_id}/accept",
    response_model=FitmentRecommendationReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_fitment_recommendation(
    recommendation_id: UUID,
    payload: FitmentRecommendationReviewRequest,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FitmentRecommendationReviewResponse:
    return await _review_recommendation(
        recommendation_id=recommendation_id,
        decision=RecommendationDecision.ACCEPTED,
        payload=payload,
        current=current,
        session=session,
    )


@router.post(
    "/recommendations/{recommendation_id}/reject",
    response_model=FitmentRecommendationReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reject_fitment_recommendation(
    recommendation_id: UUID,
    payload: FitmentRecommendationReviewRequest,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FitmentRecommendationReviewResponse:
    return await _review_recommendation(
        recommendation_id=recommendation_id,
        decision=RecommendationDecision.REJECTED,
        payload=payload,
        current=current,
        session=session,
    )


@router.post(
    "/recommendations/{recommendation_id}/defer",
    response_model=FitmentRecommendationReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def defer_fitment_recommendation(
    recommendation_id: UUID,
    payload: FitmentRecommendationReviewRequest,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FitmentRecommendationReviewResponse:
    return await _review_recommendation(
        recommendation_id=recommendation_id,
        decision=RecommendationDecision.DEFERRED,
        payload=payload,
        current=current,
        session=session,
    )


@router.post(
    "/recommendations/{recommendation_id}/research",
    response_model=FitmentRecommendationReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def research_fitment_recommendation(
    recommendation_id: UUID,
    payload: FitmentRecommendationReviewRequest,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FitmentRecommendationReviewResponse:
    return await _review_recommendation(
        recommendation_id=recommendation_id,
        decision=RecommendationDecision.RESEARCH_REQUESTED,
        payload=payload,
        current=current,
        session=session,
    )


@router.get("/notifications", response_model=FitmentNotificationPageResponse)
async def get_fitment_notifications(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    notification_status: Annotated[
        str | None,
        Query(alias="status", pattern="^(pending|delivered|read|dismissed)$"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FitmentNotificationPageResponse:
    try:
        rows, total = await list_fitment_notifications(
            session,
            workspace_id=current.workspace_id,
            notification_status=notification_status,
            limit=limit,
            offset=offset,
        )
    except FitmentIntelligenceError as exc:
        _raise_fitment_http(exc)
    return FitmentNotificationPageResponse(
        items=[FitmentNotificationResponse.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/notifications/{notification_id}/read",
    response_model=FitmentNotificationResponse,
)
async def read_fitment_notification(
    notification_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FitmentNotificationResponse:
    try:
        record = await mark_fitment_notification_read(
            session,
            workspace_id=current.workspace_id,
            actor_user_id=current.user.id,
            notification_id=notification_id,
        )
    except (FitmentIntelligenceError, FitmentNotFoundError) as exc:
        _raise_fitment_http(exc)
    return FitmentNotificationResponse.model_validate(record)


@router.post(
    "/candidates/{assessment_id}/review",
    response_model=FitmentReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def review_candidate(
    assessment_id: UUID,
    payload: FitmentReviewRequest,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FitmentReviewResponse:
    try:
        review = await add_fitment_review(
            session,
            workspace_id=current.workspace_id,
            actor_user_id=current.user.id,
            assessment_id=assessment_id,
            **payload.model_dump(),
        )
    except (FitmentIntelligenceError, FitmentNotFoundError) as exc:
        _raise_fitment_http(exc)
    return FitmentReviewResponse.model_validate(review)


async def _mark_seller(
    *,
    seller_external_id: str,
    relation: SellerRelation,
    payload: SellerRelationRequest,
    current,
    session: AsyncSession,
) -> SellerRelationResponse:
    try:
        record = await add_seller_relation(
            session,
            workspace_id=current.workspace_id,
            actor_user_id=current.user.id,
            marketplace="prom",
            seller_external_id=seller_external_id,
            seller_name=payload.seller_name,
            relation=relation,
            confidence=payload.confidence,
            evidence=payload.evidence,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
        )
    except (FitmentIntelligenceError, FitmentNotFoundError) as exc:
        _raise_fitment_http(exc)
    return SellerRelationResponse.model_validate(record)


@router.post("/sellers/resolve", response_model=SellerResolutionResponse)
async def resolve_seller(
    payload: SellerResolutionRequest,
    current: CurrentUser,
) -> SellerResolutionResponse:
    del current
    try:
        result = resolve_seller_relation(
            payload.matches,
            known_own_registry_match=payload.known_own_registry_match,
        )
    except ValueError as exc:
        _raise_fitment_http(exc)
    return SellerResolutionResponse(
        relation=result.relation.value,
        relation_score=result.relation_score,
        strong_identifier_present=result.strong_identifier_present,
        deterministic_match=result.deterministic_match,
        contributions=dict(result.contributions),
        reason_codes=list(result.reason_codes),
        version=result.version,
    )


@router.post(
    "/sellers/{seller_external_id}/mark-own",
    response_model=SellerRelationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def mark_seller_own(
    seller_external_id: str,
    payload: SellerRelationRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SellerRelationResponse:
    return await _mark_seller(
        seller_external_id=seller_external_id,
        relation=SellerRelation.OWN,
        payload=payload,
        current=current,
        session=session,
    )


@router.post(
    "/sellers/{seller_external_id}/mark-related",
    response_model=SellerRelationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def mark_seller_related(
    seller_external_id: str,
    payload: SellerRelationRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SellerRelationResponse:
    return await _mark_seller(
        seller_external_id=seller_external_id,
        relation=SellerRelation.RELATED,
        payload=payload,
        current=current,
        session=session,
    )


@router.get("/cross-references/search", response_model=CrossReferencePageResponse)
async def get_cross_references(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    article: Annotated[str | None, Query(max_length=255)] = None,
    oe: Annotated[str | None, Query(max_length=255)] = None,
    relation_status: Annotated[str | None, Query(max_length=24)] = None,
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CrossReferencePageResponse:
    try:
        rows, total = await search_cross_references(
            session,
            workspace_id=current.workspace_id,
            article=article,
            oe=oe,
            relation_status=relation_status,
            limit=limit,
            offset=offset,
        )
    except FitmentIntelligenceError as exc:
        _raise_fitment_http(exc)
    return CrossReferencePageResponse(
        items=[CrossReferenceResponse.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def _record_cross(
    *,
    relation_status: str,
    payload: CrossReferenceRequest,
    current,
    session: AsyncSession,
) -> CrossReferenceResponse:
    try:
        record = await record_cross_reference(
            session,
            workspace_id=current.workspace_id,
            actor_user_id=current.user.id,
            relation_status=relation_status,
            **payload.model_dump(),
        )
    except (FitmentIntelligenceError, FitmentNotFoundError) as exc:
        _raise_fitment_http(exc)
    return CrossReferenceResponse.model_validate(record)


@router.post(
    "/cross-references/confirm",
    response_model=CrossReferenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def confirm_cross_reference(
    payload: CrossReferenceRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CrossReferenceResponse:
    return await _record_cross(
        relation_status="human_confirmed",
        payload=payload,
        current=current,
        session=session,
    )


@router.post(
    "/cross-references/reject",
    response_model=CrossReferenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reject_cross_reference(
    payload: CrossReferenceRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CrossReferenceResponse:
    return await _record_cross(
        relation_status="human_rejected",
        payload=payload,
        current=current,
        session=session,
    )
