from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
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
from marko.services.fitment_intelligence import (
    FitmentIntelligenceError,
    _resolve_cross_reference_evidence,
    record_cross_reference,
)
from marko.services.fitment_source_routing import (
    claim_names_both_numbers,
    route_fitment_sources,
    source_access_policy_allows,
    source_claim_quality_allows,
    source_confirmation_policy_allows,
    source_url_matches_domain,
)
from marko.worker.celery_app import celery_app
from metis.fitment import FitmentFeature


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
    cross_discovery = {item["source_key"]: item for item in route["fallback_sources"]}
    assert {"avto_pro", "exist_ua"} <= set(cross_discovery)
    assert cross_discovery["avto_pro"]["source_tier"] == "C"
    assert cross_discovery["exist_ua"]["independence_policy"] == (
        "prove_distinct_upstream_or_require_human_confirmation"
    )
    assert route["retrieval_mode"] == "query_level"
    assert route["automatic_access_authorized"] is False


def test_unknown_brand_route_is_fail_closed_and_still_has_catalog_fallbacks() -> None:
    route = route_fitment_sources("Unknown Budget Brand")

    assert route["preferred_sources"][0]["source_key"] == "partsouq"
    assert [item["source_key"] for item in route["fallback_sources"][:2]] == [
        "avto_pro",
        "exist_ua",
    ]
    assert route["fallback_sources"][-1]["purpose"] == (
        "discovery_only_until_independent_confirmation"
    )
    assert route["automatic_access_authorized"] is False


def test_avto_pro_and_exist_remain_discovery_even_as_two_named_sources() -> None:
    assert not source_confirmation_policy_allows(
        (("C", "avto_pro"), ("C", "exist_ua"))
    )
    assert not source_confirmation_policy_allows(
        (("B", "shared_tecdoc_upstream"), ("B", "shared_tecdoc_upstream"))
    )
    assert source_confirmation_policy_allows(
        (("B", "manufacturer_feed"), ("B", "independent_distributor_feed"))
    )
    assert source_confirmation_policy_allows((("A", "official_manufacturer"),))


def test_source_claim_quality_accepts_only_strong_factual_support() -> None:
    baseline = {
        "statement_status": "FACT",
        "evidence_value": "1",
        "polarity": "supports",
        "source_reliability": "0.75",
        "extraction_confidence": "0.85",
        "directness": "0.90",
        "independence_factor": "0.75",
    }

    assert source_claim_quality_allows(**baseline)

    rejected_overrides = (
        {"statement_status": "INFERENCE"},
        {"evidence_value": "0.5"},
        {"polarity": "contradicts"},
        {"source_reliability": "0.749"},
        {"extraction_confidence": "0.849"},
        {"directness": "0.899"},
        {"independence_factor": "0.749"},
        {"source_reliability": "not-a-number"},
        {"correlation_group": "unrecognized-extra-input"},
    )
    for override in rejected_overrides[:-1]:
        claim = baseline | override
        assert not source_claim_quality_allows(**claim)

    # The helper has an explicit keyword-only contract: unrelated provenance
    # cannot accidentally become authority by being silently accepted.
    with pytest.raises(TypeError):
        source_claim_quality_allows(**(baseline | rejected_overrides[-1]))


def test_source_authority_helpers_fail_closed_on_lineage_mismatch() -> None:
    assert source_access_policy_allows(
        access_status="PERMITTED",
        access_reference="contract:2026",
        robots_checked=True,
        terms_checked=True,
    )
    assert not source_access_policy_allows(
        access_status="PERMITTED",
        access_reference="legacy-unreviewed",
        robots_checked=True,
        terms_checked=True,
    )
    assert source_url_matches_domain(
        "https://catalog.example.test/cross/part",
        "example.test",
    )
    assert not source_url_matches_domain(
        "https://example.test.attacker.invalid/cross/part",
        "example.test",
    )
    assert claim_names_both_numbers(
        claim_value={"article": "1145200500"},
        raw_fragment="Cross reference to OE 330 422 371",
        article="1145200500",
        oe="330422371",
    )
    assert not claim_names_both_numbers(
        claim_value={"article": "1145200500"},
        raw_fragment="No OE shown",
        article="1145200500",
        oe="330422371",
    )
    assert not claim_names_both_numbers(
        claim_value={"number": "1234"},
        raw_fragment=None,
        article="123",
        oe="1234",
    )


@pytest.mark.asyncio
async def test_confirmed_cross_rejects_confidence_below_authority_floor() -> None:
    with pytest.raises(
        FitmentIntelligenceError,
        match="confidence is below the pricing authority floor",
    ):
        await record_cross_reference(
            object(),
            workspace_id=uuid4(),
            actor_user_id=uuid4(),
            brand="JP Group",
            article="1145200500",
            oe="330422371",
            installation_position=None,
            vehicle_key=None,
            relation_status="source_confirmed",
            confidence=Decimal("0.749"),
            evidence_ids=(uuid4(),),
        )


@pytest.mark.asyncio
async def test_write_time_source_confirmation_rejects_weak_persisted_claim() -> None:
    workspace_id = uuid4()
    claim_id = uuid4()
    claim = SimpleNamespace(
        id=claim_id,
        feature=FitmentFeature.OE_EXACT.value,
        evidence_value=Decimal("1"),
        statement_status="INFERENCE",
        polarity="supports",
        source_reliability=Decimal("1"),
        extraction_confidence=Decimal("1"),
        directness=Decimal("1"),
        independence_factor=Decimal("1"),
        source_tier="A",
        source_document_id=uuid4(),
        correlation_group="official_manufacturer",
    )
    assessment = SimpleNamespace(
        id=uuid4(),
        candidate_identity={"manufacturer_article": "1145200500"},
        compatibility_status="confirmed_compatible",
        authoritative_confirmation=True,
        hard_rejections=[],
    )
    analysis = SimpleNamespace(
        workspace_id=workspace_id,
        target_identity={"oe_numbers": ["330422371"]},
        status="completed",
    )

    class _Rows:
        def all(self):
            return [(claim, assessment, analysis)]

    class _Session:
        async def execute(self, _statement):
            return _Rows()

    with pytest.raises(
        FitmentIntelligenceError,
        match="requires strong persisted source evidence",
    ):
        await _resolve_cross_reference_evidence(
            _Session(),
            workspace_id=workspace_id,
            article="1145200500",
            oe="330422371",
            relation_status="source_confirmed",
            evidence_claim_ids=(claim_id,),
        )


def _strong_source_confirmation_fixture(*, current_access: str = "PERMITTED"):
    workspace_id = uuid4()
    now = datetime.now(UTC)
    source = SimpleNamespace(
        id=uuid4(),
        workspace_id=workspace_id,
        source_key="official_catalog",
        source_type="official_manufacturer_catalog",
        source_tier="A",
        domain="catalog.example.test",
        access_status="PERMITTED",
        access_reference="contract:accuracy-fixture",
        robots_checked=True,
        terms_checked=True,
        reviewed_at=now - timedelta(days=1),
        created_at=now - timedelta(days=1),
    )
    current_policy = SimpleNamespace(
        **(
            vars(source)
            | {
                "id": uuid4(),
                "access_status": current_access,
                "reviewed_at": now,
                "created_at": now,
            }
        )
    )
    document = SimpleNamespace(
        id=uuid4(),
        source_id=source.id,
        source_url="https://catalog.example.test/cross/1145200500",
        content_sha256="a" * 64,
        content_locator="fixture://official_catalog/1145200500",
        expires_at=now + timedelta(days=1),
    )
    claim = SimpleNamespace(
        id=uuid4(),
        feature=FitmentFeature.CROSS_CONFIRMED.value,
        evidence_value=Decimal("1"),
        statement_status="FACT",
        polarity="supports",
        source_reliability=Decimal("0.95"),
        extraction_confidence=Decimal("1"),
        directness=Decimal("1"),
        independence_factor=Decimal("1"),
        source_tier="A",
        source_type=source.source_type,
        source_external_id=source.source_key,
        source_document_id=document.id,
        source_document_sha256=document.content_sha256,
        source_url=document.source_url,
        correlation_group="official_manufacturer",
        claim_value={"article": "1145200500", "oe": "330422371"},
        raw_fragment="1145200500 cross 330422371",
    )
    assessment = SimpleNamespace(
        id=uuid4(),
        candidate_identity={"manufacturer_article": "1145200500"},
        compatibility_status="confirmed_compatible",
        authoritative_confirmation=True,
        hard_rejections=[],
    )
    analysis = SimpleNamespace(
        workspace_id=workspace_id,
        target_identity={"oe_numbers": ["330422371"]},
        status="completed",
    )

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Session:
        def __init__(self):
            self.execute_calls = 0

        async def execute(self, _statement):
            self.execute_calls += 1
            if self.execute_calls == 1:
                return _Rows([(claim, assessment, analysis)])
            return _Rows([(document, source)])

        async def scalars(self, _statement):
            return _Rows([current_policy])

    return workspace_id, claim, _Session()


@pytest.mark.asyncio
async def test_write_time_source_confirmation_accepts_live_primary_authority() -> None:
    workspace_id, claim, session = _strong_source_confirmation_fixture()

    evidence_ids, source_count, human_count = (
        await _resolve_cross_reference_evidence(
            session,
            workspace_id=workspace_id,
            article="1145200500",
            oe="330422371",
            relation_status="source_confirmed",
            evidence_claim_ids=(claim.id,),
        )
    )

    assert evidence_ids == [str(claim.id)]
    assert source_count == 1
    assert human_count == 0


@pytest.mark.asyncio
async def test_write_time_source_confirmation_rejects_revoked_current_policy() -> None:
    workspace_id, claim, session = _strong_source_confirmation_fixture(
        current_access="NOT_PERMITTED"
    )

    with pytest.raises(FitmentIntelligenceError, match="access is not approved"):
        await _resolve_cross_reference_evidence(
            session,
            workspace_id=workspace_id,
            article="1145200500",
            oe="330422371",
            relation_status="source_confirmed",
            evidence_claim_ids=(claim.id,),
        )


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
