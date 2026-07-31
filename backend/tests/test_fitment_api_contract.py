from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from marko.api.dependencies import get_current_user
from marko.api.main import create_app
from marko.core.config import get_settings
from marko.api.schemas.fitment import (
    CrossReferenceRequest,
    FitmentCandidateResponse,
    FitmentRecommendationCreateRequest,
)
from marko.infrastructure.db.models import (
    FitmentAnalysis,
    FitmentAuditEvent,
    FitmentCandidateAssessment,
    FitmentCrossReference,
    FitmentEvidenceClaim,
    FitmentFeedbackEvent,
    FitmentHumanReview,
    FitmentMarketRecommendation,
    FitmentNotification,
    FitmentRecommendationReview,
    FitmentSource,
    FitmentSourceCapability,
    FitmentSourceDocument,
    FitmentSourceReliabilitySnapshot,
    SellerRelationRecord,
    User,
    WorkspaceRole,
)
from marko.services.auth import AuthContext
from marko.services.fitment_source_routing import route_fitment_sources
from marko.worker.celery_app import celery_app


def _auth_context() -> AuthContext:
    return AuthContext(
        user=User(id=uuid4(), email="fitment@example.com", is_active=True),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.owner,
    )


def test_fitment_schema_contains_append_only_lineage_and_no_auto_price_gate() -> None:
    tables = {
        model.__tablename__
        for model in (
            FitmentSource,
            FitmentSourceDocument,
            SellerRelationRecord,
            FitmentAnalysis,
            FitmentCandidateAssessment,
            FitmentEvidenceClaim,
            FitmentHumanReview,
            FitmentCrossReference,
            FitmentAuditEvent,
            FitmentSourceCapability,
            FitmentSourceReliabilitySnapshot,
            FitmentMarketRecommendation,
            FitmentRecommendationReview,
            FitmentFeedbackEvent,
            FitmentNotification,
        )
    }
    assert tables == {
        "fitment_sources",
        "fitment_source_documents",
        "seller_relation_records",
        "fitment_analyses",
        "fitment_candidate_assessments",
        "fitment_evidence_claims",
        "fitment_human_reviews",
        "fitment_cross_references",
        "fitment_audit_events",
        "fitment_source_capabilities",
        "fitment_source_reliability_snapshots",
        "fitment_market_recommendations",
        "fitment_recommendation_reviews",
        "fitment_feedback_events",
        "fitment_notifications",
    }
    constraint_names = {
        constraint.name
        for constraint in FitmentCandidateAssessment.__table__.constraints
    }
    assert "ck_fit_assessment_no_auto_price" in constraint_names
    assert (
        FitmentCandidateAssessment.__table__.c.automatic_price_change_allowed.server_default
        is not None
    )


def test_fitment_cross_reference_has_workspace_lookup_index() -> None:
    index_names = {index.name for index in FitmentCrossReference.__table__.indexes}
    assert "ix_fit_cross_lookup" in index_names
    assert "uq_fit_cross_fingerprint" in {
        constraint.name for constraint in FitmentCrossReference.__table__.constraints
    }


def test_cross_metrics_are_derived_server_side() -> None:
    request_fields = CrossReferenceRequest.model_fields

    assert "evidence_ids" in request_fields
    assert "source_count" not in request_fields
    assert "human_feedback_count" not in request_fields
    assert "evidence_claim_ids" in FitmentCandidateResponse.model_fields
    assert "reference_price" in FitmentCandidateResponse.model_fields


def test_recommendation_request_never_accepts_raw_cost_or_auto_publish() -> None:
    fields = FitmentRecommendationCreateRequest.model_fields

    assert "approved_price_floor" in fields
    assert "cost" not in fields
    assert "cost_of_goods" not in fields
    assert "automatic_price_change_allowed" not in fields
    assert "publish" not in fields


def test_source_routing_prefers_official_brand_catalog_but_never_authorizes_access() -> (
    None
):
    route = route_fitment_sources("SACHS")

    assert route["preferred_sources"][0]["source_key"] == "zf_aftermarket"
    assert route["preferred_sources"][0]["source_tier"] == "A"
    assert {item["source_key"] for item in route["preferred_sources"]} >= {
        "partsouq",
        "seven_zap",
    }
    assert route["retrieval_mode"] == "query_level"
    assert route["automatic_access_authorized"] is False


def test_unknown_brand_route_is_fail_closed_and_still_has_catalog_fallbacks() -> None:
    route = route_fitment_sources("Unknown Budget Brand")

    assert route["preferred_sources"][0]["source_key"] == "partsouq"
    assert route["fallback_sources"][-1]["purpose"] == (
        "discovery_only_until_independent_confirmation"
    )
    assert route["automatic_access_authorized"] is False


@pytest.fixture(autouse=True)
def _enable_deferred_fitment(monkeypatch):
    """Fitment is unmounted by default; these tests are about it, so they opt in."""

    monkeypatch.setenv("FITMENT_API_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()



@pytest.mark.asyncio
async def test_fitment_routes_are_authenticated_and_source_route_is_read_only() -> None:
    application = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        unauthenticated = await client.get(
            "/api/v1/fitment/source-routing", params={"brand": "KYB"}
        )
    assert unauthenticated.status_code == 401

    async def current_user_override() -> AuthContext:
        return _auth_context()

    application.dependency_overrides[get_current_user] = current_user_override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/v1/fitment/source-routing", params={"brand": "KYB"}
            )
    finally:
        application.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["preferred_sources"][0]["source_key"] == "kyb_catalogue"
    assert response.json()["automatic_access_authorized"] is False


def test_openapi_exposes_complete_fitment_workflow() -> None:
    paths = create_app().openapi()["paths"]
    required = {
        "/api/v1/fitment/products/{catalog_item_id}/analyze",
        "/api/v1/fitment/products/{catalog_item_id}/candidates",
        "/api/v1/fitment/candidates/{assessment_id}/review",
        "/api/v1/fitment/sellers/{seller_external_id}/mark-own",
        "/api/v1/fitment/sellers/{seller_external_id}/mark-related",
        "/api/v1/fitment/cross-references/search",
        "/api/v1/fitment/cross-references/confirm",
        "/api/v1/fitment/cross-references/reject",
        "/api/v1/fitment/analysis-jobs/{analysis_id}",
        "/api/v1/fitment/analysis-jobs/{analysis_id}/metrics",
        "/api/v1/fitment/sources",
        "/api/v1/fitment/sources/{source_id}/documents",
        "/api/v1/fitment/sources/{source_id}/capabilities",
        "/api/v1/fitment/sources/{source_id}/reliability",
        "/api/v1/fitment/analysis-jobs/{analysis_id}/retry",
        "/api/v1/fitment/products/{catalog_item_id}/recommendations",
        "/api/v1/fitment/products/{catalog_item_id}/recommendation",
        "/api/v1/fitment/recommendations/{recommendation_id}/accept",
        "/api/v1/fitment/recommendations/{recommendation_id}/reject",
        "/api/v1/fitment/recommendations/{recommendation_id}/defer",
        "/api/v1/fitment/recommendations/{recommendation_id}/research",
        "/api/v1/fitment/sellers/resolve",
        "/api/v1/fitment/notifications",
        "/api/v1/fitment/notifications/{notification_id}/read",
    }
    assert required.issubset(paths)


def test_fitment_analysis_is_routed_to_the_durable_worker_queue() -> None:
    assert "marko.worker.tasks.fitment" in celery_app.conf.include
    assert celery_app.conf.task_routes["marko.worker.process_fitment_analysis"] == {
        "queue": "celery"
    }
