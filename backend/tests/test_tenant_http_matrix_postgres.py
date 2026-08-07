"""Exhaustive two-workspace HTTP isolation proof for parameterized resources.

This suite is deliberately opt-in and must run against a disposable database:

    MARKO_RUN_TENANT_MATRIX=1 \
    DATABASE_URL=postgresql+asyncpg://.../marko_tenant_matrix_<suffix> \
    pytest -q tests/test_tenant_http_matrix_postgres.py

The test seeds every resource family in workspace B, authenticates as an owner
of workspace A, and exercises every parameterized resource operation exposed by
OpenAPI.  A valid foreign identifier must be indistinguishable from an unknown
identifier (404), and no database row count or mutable workflow state may
change.  The two seller-external-id routes are covered separately because they
are scoped write commands, not lookups of an existing tenant-owned resource.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import os
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from marko.api.dependencies import get_current_user
from marko.api.main import create_app
from marko.core.config import get_settings
from marko.infrastructure.db.base import Base
from marko.infrastructure.db.models import (
    CandidateComparabilityReview,
    CatalogImportBatch,
    CatalogItem,
    FitmentAnalysis,
    FitmentCandidateAssessment,
    FitmentMarketRecommendation,
    FitmentNotification,
    FitmentSource,
    Listing,
    MarketplaceStore,
    MarketObservation,
    PricingRecommendation,
    PricingRun,
    PricingRunItem,
    RawMarketCapture,
    SellerRelationRecord,
    StoreKind,
    SyncRun,
    SyncStatus,
    User,
    Workspace,
    WorkspaceStore,
    WorkspaceRole,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.auth import AuthContext


pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        os.getenv("MARKO_RUN_TENANT_MATRIX") != "1",
        reason="set MARKO_RUN_TENANT_MATRIX=1 for the disposable tenant matrix",
    ),
]


@dataclass(frozen=True)
class ForeignResourceFixture:
    workspace_a_id: UUID
    workspace_b_id: UUID
    user_a_id: UUID
    own_store_id: UUID
    store_id: UUID
    sync_run_id: UUID
    batch_id: UUID
    catalog_item_id: UUID
    catalog_product_id: str
    pricing_run_id: UUID
    observation_id: UUID
    comparability_review_id: UUID
    pricing_recommendation_id: UUID
    fitment_source_id: UUID
    fitment_analysis_id: UUID
    fitment_assessment_id: UUID
    fitment_recommendation_id: UUID
    fitment_notification_id: UUID


@dataclass(frozen=True)
class EndpointCase:
    method: str
    template: str
    path: str
    json: dict[str, Any] | None = None
    params: dict[str, Any] | None = None


def _assert_disposable_database() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    database_name = urlparse(database_url.replace("+asyncpg", "")).path.rsplit("/", 1)[
        -1
    ]
    assert "tenant_matrix" in database_name, (
        "tenant isolation proof is destructive test setup and must target a "
        "database whose name contains 'tenant_matrix'"
    )


async def _table_counts() -> dict[str, int]:
    async with async_session_factory() as session:
        return {
            table.name: int(
                (
                    await session.execute(select(func.count()).select_from(table))
                ).scalar_one()
            )
            for table in Base.metadata.sorted_tables
        }


async def _mutable_state(fixture: ForeignResourceFixture) -> dict[str, Any]:
    async with async_session_factory() as session:
        sync_run = await session.get(SyncRun, fixture.sync_run_id)
        pricing_run = await session.get(PricingRun, fixture.pricing_run_id)
        analysis = await session.get(FitmentAnalysis, fixture.fitment_analysis_id)
        notification = await session.get(
            FitmentNotification, fixture.fitment_notification_id
        )
        workspace_store_count = (
            await session.execute(
                select(func.count())
                .select_from(WorkspaceStore)
                .where(
                    WorkspaceStore.workspace_id == fixture.workspace_b_id,
                    WorkspaceStore.store_id == fixture.store_id,
                )
            )
        ).scalar_one()
        assert sync_run is not None
        assert pricing_run is not None
        assert analysis is not None
        assert notification is not None
        return {
            "sync_status": sync_run.status.value,
            "sync_scrape_state": sync_run.scrape_state,
            "sync_task_id": sync_run.task_id,
            "pricing_status": pricing_run.status,
            "pricing_cancel_requested": pricing_run.cancel_requested,
            "fitment_status": analysis.status,
            "fitment_dispatch_task_id": analysis.dispatch_task_id,
            "fitment_owner_task_id": analysis.owner_task_id,
            "notification_status": notification.status,
            "workspace_store_count": int(workspace_store_count),
        }


async def _seed_foreign_workspace() -> ForeignResourceFixture:
    now = datetime.now(UTC)
    workspace_a_id = uuid4()
    workspace_b_id = uuid4()
    user_a_id = uuid4()
    own_store_id = uuid4()
    store_id = uuid4()
    sync_run_id = uuid4()
    batch_id = uuid4()
    item_id = uuid4()
    run_id = uuid4()
    run_item_id = uuid4()
    capture_id = uuid4()
    observation_id = uuid4()
    comparability_review_id = uuid4()
    pricing_recommendation_id = uuid4()
    source_id = uuid4()
    analysis_id = uuid4()
    assessment_id = uuid4()
    fitment_recommendation_id = uuid4()
    notification_id = uuid4()

    async with async_session_factory() as session:
        session.add_all(
            [
                Workspace(
                    id=workspace_a_id,
                    name="Tenant matrix A",
                    slug=f"tenant-matrix-a-{workspace_a_id.hex}",
                ),
                Workspace(
                    id=workspace_b_id,
                    name="Tenant matrix B",
                    slug=f"tenant-matrix-b-{workspace_b_id.hex}",
                ),
                User(
                    id=user_a_id,
                    email=f"tenant-matrix-{user_a_id.hex}@example.test",
                    display_name="Tenant matrix owner A",
                    is_active=True,
                ),
            ]
        )
        await session.flush()

        own_store = MarketplaceStore(
            id=own_store_id,
            external_id=f"tenant-a-{own_store_id.hex}",
            name="Authenticated workspace store",
            canonical_url=f"https://tenant-a-{own_store_id.hex}.prom.ua",
        )
        foreign_store = MarketplaceStore(
            id=store_id,
            external_id=f"tenant-b-{store_id.hex}",
            name="Foreign owned store",
            canonical_url=f"https://tenant-b-{store_id.hex}.prom.ua",
        )
        session.add_all([own_store, foreign_store])
        await session.flush()
        session.add_all(
            [
                WorkspaceStore(
                    workspace_id=workspace_a_id,
                    store_id=own_store_id,
                    kind=StoreKind.owned,
                ),
                WorkspaceStore(
                    workspace_id=workspace_b_id,
                    store_id=store_id,
                    kind=StoreKind.owned,
                ),
            ]
        )
        shared_identity = "TENANT-LEAK-PROBE-484848"
        session.add(
            Listing(
                store_id=own_store_id,
                external_id=f"listing-{uuid4().hex}",
                name="Authenticated workspace reference",
                url="https://tenant-a.invalid/listing",
                sku=shared_identity,
                brand="KEMP",
                current_price=Decimal("800"),
                is_available=True,
                raw_data={"oe_raw": shared_identity},
            )
        )
        listing = Listing(
            store_id=store_id,
            external_id=f"listing-{uuid4().hex}",
            name="Foreign tenant shock absorber",
            url="https://tenant-b.invalid/listing",
            sku="TENANT-B-SKU-1",
            model_id="TENANT-B-MODEL-1",
            brand="KEMP",
            current_price=Decimal("850"),
            is_available=True,
            raw_data={"oe_raw": "48530-89025", "description": "foreign evidence"},
        )
        session.add_all(
            [
                listing,
                Listing(
                    store_id=store_id,
                    external_id=f"listing-{uuid4().hex}",
                    name="Foreign workspace leak sentinel",
                    url="https://tenant-b.invalid/leak-sentinel",
                    sku=shared_identity,
                    brand="KEMP",
                    current_price=Decimal("999"),
                    is_available=True,
                    raw_data={"oe_raw": shared_identity},
                ),
            ]
        )
        session.add(
            SyncRun(
                id=sync_run_id,
                workspace_id=workspace_b_id,
                store_id=store_id,
                kind="catalog_import",
                status=SyncStatus.failed,
                scrape_state="failed",
                error="tenant matrix fixture",
                finished_at=now,
            )
        )
        await session.flush()
        await session.refresh(listing)
        catalog_product_id = hashlib.sha256(
            f"{listing.catalog_identity_kind}:{listing.catalog_identity_value}".encode()
        ).hexdigest()[:32]

        session.add(
            CatalogImportBatch(
                id=batch_id,
                workspace_id=workspace_b_id,
                filename="tenant-b.xlsx",
                content_sha256="a" * 64,
                content_size=1,
                status="completed",
                column_mapping={"oe": "oe"},
                total_rows=1,
                imported_rows=1,
                rejected_rows=0,
                error_log=[],
            )
        )
        await session.flush()
        session.add(
            CatalogItem(
                id=item_id,
                workspace_id=workspace_b_id,
                import_batch_id=batch_id,
                store_id=store_id,
                source_row=2,
                sku="TENANT-B-SKU-1",
                oe_raw="48530-89025",
                oe_norm="4853089025",
                name="Foreign tenant shock absorber",
                category="shock_absorber",
                brand="KEMP",
                current_price=Decimal("850"),
                currency="UAH",
                is_available=True,
                raw_row={},
            )
        )
        session.add(
            PricingRun(
                id=run_id,
                workspace_id=workspace_b_id,
                import_batch_id=batch_id,
                status="failed",
                policy_version="tenant-matrix-v1",
                policy_config={},
                parser_version="fixture-v1",
                error="tenant matrix fixture",
                finished_at=now,
            )
        )
        await session.flush()
        session.add(
            PricingRunItem(
                id=run_item_id,
                pricing_run_id=run_id,
                catalog_item_id=item_id,
                status="collected",
                idempotency_key=f"tenant-matrix:{run_item_id}",
                attempts=1,
            )
        )
        await session.flush()
        session.add(
            RawMarketCapture(
                id=capture_id,
                pricing_run_item_id=run_item_id,
                source="fixture",
                capture_kind="test_fixture",
                payload={"synthetic": True},
                content_sha256="b" * 64,
                parser_version="fixture-v1",
            )
        )
        await session.flush()
        session.add(
            MarketObservation(
                id=observation_id,
                pricing_run_item_id=run_item_id,
                catalog_item_id=item_id,
                raw_capture_id=capture_id,
                source="fixture",
                source_listing_id="tenant-b-listing-1",
                seller_id="tenant-b-seller",
                seller_name="Foreign seller",
                url="https://tenant-b.invalid/offer",
                title="Foreign tenant shock absorber",
                description="Synthetic retained evidence",
                description_available=True,
                condition_raw="new",
                condition_state="NEW",
                condition_reason_codes=["FIXTURE"],
                cross_candidates=[],
                brand_raw="KYB",
                search_oe_norm="4853089025",
                extracted_oe_norms=["4853089025"],
                oe_verification_status="UNKNOWN",
                oe_evidence=[],
                price=Decimal("1100"),
                currency="UAH",
                currency_raw="UAH",
                is_available=True,
                match_confidence=Decimal("0.95"),
                source_confidence=Decimal("0.55"),
                source_confidence_factors={"fixture": "0.55"},
                source_confidence_method_version="fixture-v1",
                parser_version="fixture-v1",
                calibration_exclusion_codes=["SYNTHETIC_FIXTURE"],
                observed_at=now,
            )
        )
        await session.flush()
        session.add(
            PricingRecommendation(
                id=pricing_recommendation_id,
                pricing_run_id=run_id,
                pricing_run_item_id=run_item_id,
                catalog_item_id=item_id,
                catalog_snapshot_id=batch_id,
                context_snapshot={},
                calculation_trace={},
                action="HOLD",
                current_price=Decimal("850"),
                confidence=Decimal("0.50"),
                confidence_grade="LOW",
                factor_scores={},
                competitor_count=1,
                raw_competitor_count=1,
                unique_seller_count=1,
                clean_competitor_count=1,
                effective_competitor_count=Decimal("1"),
                outlier_method="none",
                outlier_count=0,
                action_gates_passed=False,
                priority_score=Decimal("0"),
                priority_score_type="manual_review",
                review_priority=Decimal("0"),
                reason_codes=["TENANT_MATRIX_FIXTURE"],
                evidence_observation_ids=[str(observation_id)],
                excluded_observations=[],
                policy_version="tenant-matrix-v1",
                parser_version="fixture-v1",
                classifier_version="fixture-v1",
                currency="UAH",
                price_tick=Decimal("1"),
                price_tick_version="fixture-v1",
            )
        )
        session.add(
            FitmentSource(
                id=source_id,
                workspace_id=workspace_b_id,
                source_key="tenant-b-source",
                source_type="official_catalog",
                source_tier="A",
                base_reliability=Decimal("0.95"),
                domain="tenant-b.invalid",
                access_method="manual_fixture",
                access_status="NOT_PERMITTED",
                access_reference="tenant matrix fixture",
                robots_checked=True,
                terms_checked=True,
                rate_limit="none",
                cache_policy="no-cache",
                policy_version="tenant-matrix-v1",
                reviewed_at=now,
            )
        )
        session.add(
            FitmentAnalysis(
                id=analysis_id,
                workspace_id=workspace_b_id,
                catalog_item_id=item_id,
                pricing_run_id=run_id,
                idempotency_key=f"analysis-{analysis_id.hex}"[:64],
                status="failed",
                workflow_state="FAILED",
                target_identity={"oe_numbers": ["4853089025"]},
                target_commercial_context={"currency": "UAH"},
                source_policy_snapshot={},
                request_payload={},
                contract_version="fitment-contract-v1",
                scoring_version="fitment-score-v1",
                request_sha256="c" * 64,
                error="tenant matrix fixture",
                finished_at=now,
            )
        )
        await session.flush()
        session.add(
            FitmentCandidateAssessment(
                id=assessment_id,
                analysis_id=analysis_id,
                market_observation_id=observation_id,
                candidate_identity={"oe_numbers": ["4853089025"]},
                candidate_commercial_context={"currency": "UAH"},
                compatibility_status="uncertain",
                compatibility_probability=Decimal("0.50"),
                positive_evidence=Decimal("0"),
                negative_evidence=Decimal("0"),
                coverage=Decimal("0"),
                contradiction_rate=Decimal("0"),
                missing_critical_ratio=Decimal("1"),
                hard_rejections=[],
                reason_codes=["TENANT_MATRIX_FIXTURE"],
                missing_critical_fields=["fitment"],
                feature_consensus={},
                authoritative_confirmation=False,
                requires_manual_review=True,
                evidence_ids=[],
                price_comparability_status="manual_review",
                price_eligible=False,
                competitor_weight=Decimal("0"),
                price_factor_trace={},
                price_reason_codes=["TENANT_MATRIX_FIXTURE"],
                contract_version="fitment-contract-v1",
                scoring_version="fitment-score-v1",
            )
        )
        session.add(
            CandidateComparabilityReview(
                id=comparability_review_id,
                workspace_id=workspace_b_id,
                market_observation_id=observation_id,
                catalog_item_id=item_id,
                request_key=hashlib.sha256(
                    f"tenant-review-{comparability_review_id}".encode()
                ).hexdigest(),
                input_hash="9" * 64,
                attempt_no=1,
                prompt_version="tenant-matrix-v1",
                schema_version="tenant-matrix-v1",
                contract_version="comparability-v1",
                provider="hard_rule",
                model_id="none",
                decision_source="HARD_RULE",
                status="COMPLETED",
                verdict="INSUFFICIENT_DATA",
                match_level="SUSPICIOUS",
                confidence=Decimal("0.5"),
                reason_codes=["TENANT_MATRIX_FIXTURE"],
                rationale="Foreign review used only for tenant isolation proof.",
                dimension_findings=[],
                hard_stop_conflicts=[],
                input_snapshot={},
                image_urls=[],
                usage={},
                latency_ms=0,
                estimated_cost={},
                reviewed_at=now,
            )
        )
        session.add(
            FitmentMarketRecommendation(
                id=fitment_recommendation_id,
                workspace_id=workspace_b_id,
                analysis_id=analysis_id,
                catalog_item_id=item_id,
                idempotency_key=f"fitment-rec-{fitment_recommendation_id.hex}"[:64],
                input_fingerprint="d" * 64,
                action="hold",
                strategy="balanced",
                current_price=Decimal("850"),
                currency="UAH",
                confidence=Decimal("0.50"),
                confidence_factors={},
                market_summary={},
                price_statistics={},
                candidate_decisions=[],
                reason_codes=["TENANT_MATRIX_FIXTURE"],
                warnings=[],
                configuration_snapshot={},
                contract_version="fitment-contract-v1",
                recommendation_version="fitment-rec-v1",
            )
        )
        await session.flush()
        session.add(
            FitmentNotification(
                id=notification_id,
                workspace_id=workspace_b_id,
                recommendation_id=fitment_recommendation_id,
                notification_type="review_required",
                group_key="tenant-matrix",
                payload={"synthetic": True},
                status="pending",
            )
        )
        await session.commit()

    return ForeignResourceFixture(
        workspace_a_id=workspace_a_id,
        workspace_b_id=workspace_b_id,
        user_a_id=user_a_id,
        own_store_id=own_store_id,
        store_id=store_id,
        sync_run_id=sync_run_id,
        batch_id=batch_id,
        catalog_item_id=item_id,
        catalog_product_id=catalog_product_id,
        pricing_run_id=run_id,
        observation_id=observation_id,
        comparability_review_id=comparability_review_id,
        pricing_recommendation_id=pricing_recommendation_id,
        fitment_source_id=source_id,
        fitment_analysis_id=analysis_id,
        fitment_assessment_id=assessment_id,
        fitment_recommendation_id=fitment_recommendation_id,
        fitment_notification_id=notification_id,
    )


def _foreign_resource_cases(f: ForeignResourceFixture) -> tuple[EndpointCase, ...]:
    review_base = {
        "reason_code": "other",
        "comment": "tenant isolation probe",
    }
    analyze_payload = {
        "idempotency_key": "tenant-matrix-analyze",
        "pricing_run_id": str(f.pricing_run_id),
        "target_identity": {"oe_numbers": ["4853089025"]},
        "target_commercial_context": {"currency": "UAH"},
        "candidates": [
            {
                "market_observation_id": str(f.observation_id),
                "identity": {"oe_numbers": ["4853089025"]},
                "commercial_context": {"currency": "UAH"},
                "evidence": [],
            }
        ],
        "source_policy_snapshot": {},
    }
    return (
        EndpointCase(
            "GET",
            "/api/v1/catalog/products/{product_id}",
            f"/api/v1/catalog/products/{f.catalog_product_id}",
        ),
        EndpointCase(
            "GET",
            "/api/v1/catalog/imports/{batch_id}",
            f"/api/v1/catalog/imports/{f.batch_id}",
        ),
        EndpointCase(
            "GET",
            "/api/v1/catalog/imports/{batch_id}/terminal-manifest",
            f"/api/v1/catalog/imports/{f.batch_id}/terminal-manifest",
        ),
        EndpointCase(
            "GET", "/api/v1/stores/{store_id}", f"/api/v1/stores/{f.store_id}"
        ),
        EndpointCase(
            "DELETE", "/api/v1/stores/{store_id}", f"/api/v1/stores/{f.store_id}"
        ),
        EndpointCase(
            "POST",
            "/api/v1/stores/{store_id}/sync",
            f"/api/v1/stores/{f.store_id}/sync",
        ),
        EndpointCase(
            "GET",
            "/api/v1/stores/{store_id}/products",
            f"/api/v1/stores/{f.store_id}/products",
        ),
        EndpointCase(
            "GET",
            "/api/v1/stores/{store_id}/products/elsewhere",
            f"/api/v1/stores/{f.store_id}/products/elsewhere",
            params={"q": "TENANT-B-SKU-1"},
        ),
        EndpointCase(
            "GET", "/api/v1/jobs/{sync_run_id}", f"/api/v1/jobs/{f.sync_run_id}"
        ),
        EndpointCase(
            "GET",
            "/api/v1/jobs/{sync_run_id}/scrape-metrics",
            f"/api/v1/jobs/{f.sync_run_id}/scrape-metrics",
        ),
        EndpointCase(
            "GET",
            "/api/v1/jobs/{sync_run_id}/scrape-metrics/prometheus",
            f"/api/v1/jobs/{f.sync_run_id}/scrape-metrics/prometheus",
        ),
        EndpointCase(
            "POST",
            "/api/v1/operations/dead-letters/{kind}/{dead_letter_id}/replay",
            f"/api/v1/operations/dead-letters/store_sync/{f.sync_run_id}/replay",
        ),
        EndpointCase(
            "GET",
            "/api/v1/pricing/runs/{run_id}",
            f"/api/v1/pricing/runs/{f.pricing_run_id}",
        ),
        EndpointCase(
            "GET",
            "/api/v1/pricing/runs/{run_id}/collection-metrics",
            f"/api/v1/pricing/runs/{f.pricing_run_id}/collection-metrics",
        ),
        EndpointCase(
            "GET",
            "/api/v1/pricing/runs/{run_id}/comparability-report",
            f"/api/v1/pricing/runs/{f.pricing_run_id}/comparability-report",
        ),
        EndpointCase(
            "GET",
            "/api/v1/pricing/runs/{run_id}/collection-metrics/prometheus",
            f"/api/v1/pricing/runs/{f.pricing_run_id}/collection-metrics/prometheus",
        ),
        EndpointCase(
            "POST",
            "/api/v1/pricing/runs/{run_id}/cancel",
            f"/api/v1/pricing/runs/{f.pricing_run_id}/cancel",
        ),
        EndpointCase(
            "POST",
            "/api/v1/pricing/catalog-items/{catalog_item_id}/overrides",
            f"/api/v1/pricing/catalog-items/{f.catalog_item_id}/overrides",
            json={"stock_status": "fresh", "reason": "tenant isolation probe"},
        ),
        EndpointCase(
            "GET",
            "/api/v1/pricing/recommendations/{recommendation_id}",
            f"/api/v1/pricing/recommendations/{f.pricing_recommendation_id}",
        ),
        EndpointCase(
            "GET",
            "/api/v1/pricing/recommendations/{recommendation_id}/evidence",
            (f"/api/v1/pricing/recommendations/{f.pricing_recommendation_id}/evidence"),
        ),
        EndpointCase(
            "GET",
            "/api/v1/pricing/recommendations/{recommendation_id}/replay",
            f"/api/v1/pricing/recommendations/{f.pricing_recommendation_id}/replay",
        ),
        EndpointCase(
            "POST",
            "/api/v1/pricing/observations/{observation_id}/tier-overrides",
            f"/api/v1/pricing/observations/{f.observation_id}/tier-overrides",
            json={"tier": "budget", "reason": "tenant isolation probe"},
        ),
        EndpointCase(
            "GET",
            "/api/v1/pricing/observations/{observation_id}/ai-evidence",
            f"/api/v1/pricing/observations/{f.observation_id}/ai-evidence",
        ),
        EndpointCase(
            "POST",
            "/api/v1/pricing/observations/{observation_id}/comparability-reviews",
            f"/api/v1/pricing/observations/{f.observation_id}/comparability-reviews",
            json={"force": False},
        ),
        EndpointCase(
            "POST",
            "/api/v1/pricing/comparability-reviews/{review_id}/feedback",
            (
                "/api/v1/pricing/comparability-reviews/"
                f"{f.comparability_review_id}/feedback"
            ),
            json={"decision": "CONFIRM", "reason": "tenant isolation probe"},
        ),
        EndpointCase(
            "POST",
            "/api/v1/pricing/recommendations/{recommendation_id}/decisions",
            (
                "/api/v1/pricing/recommendations/"
                f"{f.pricing_recommendation_id}/decisions"
            ),
            json={"decision": "rejected", "reason": "tenant isolation probe"},
        ),
        EndpointCase(
            "POST",
            "/api/v1/fitment/sources/{source_id}/documents",
            f"/api/v1/fitment/sources/{f.fitment_source_id}/documents",
            json={
                "source_url": "https://tenant-b.invalid/document",
                "retrieval_query": "tenant isolation probe",
                "content_sha256": "e" * 64,
                "response_metadata": {},
                "retrieved_at": datetime.now(UTC).isoformat(),
            },
        ),
        EndpointCase(
            "GET",
            "/api/v1/fitment/sources/{source_id}/capabilities",
            f"/api/v1/fitment/sources/{f.fitment_source_id}/capabilities",
        ),
        EndpointCase(
            "GET",
            "/api/v1/fitment/sources/{source_id}/reliability",
            f"/api/v1/fitment/sources/{f.fitment_source_id}/reliability",
        ),
        EndpointCase(
            "POST",
            "/api/v1/fitment/products/{catalog_item_id}/analyze",
            f"/api/v1/fitment/products/{f.catalog_item_id}/analyze",
            json=analyze_payload,
        ),
        EndpointCase(
            "GET",
            "/api/v1/fitment/products/{catalog_item_id}/candidates",
            f"/api/v1/fitment/products/{f.catalog_item_id}/candidates",
        ),
        EndpointCase(
            "GET",
            "/api/v1/fitment/analysis-jobs/{analysis_id}",
            f"/api/v1/fitment/analysis-jobs/{f.fitment_analysis_id}",
        ),
        EndpointCase(
            "GET",
            "/api/v1/fitment/analysis-jobs/{analysis_id}/metrics",
            f"/api/v1/fitment/analysis-jobs/{f.fitment_analysis_id}/metrics",
        ),
        EndpointCase(
            "POST",
            "/api/v1/fitment/analysis-jobs/{analysis_id}/retry",
            f"/api/v1/fitment/analysis-jobs/{f.fitment_analysis_id}/retry",
        ),
        EndpointCase(
            "POST",
            "/api/v1/fitment/products/{catalog_item_id}/recommendations",
            f"/api/v1/fitment/products/{f.catalog_item_id}/recommendations",
            json={
                "idempotency_key": "tenant-matrix-recommendation",
                "analysis_id": str(f.fitment_analysis_id),
            },
        ),
        EndpointCase(
            "GET",
            "/api/v1/fitment/products/{catalog_item_id}/recommendation",
            f"/api/v1/fitment/products/{f.catalog_item_id}/recommendation",
            params={"recommendation_id": str(f.fitment_recommendation_id)},
        ),
        EndpointCase(
            "POST",
            "/api/v1/fitment/recommendations/{recommendation_id}/accept",
            f"/api/v1/fitment/recommendations/{f.fitment_recommendation_id}/accept",
            json={
                "idempotency_key": "tenant-matrix-accept",
                "approved_price": "850",
                **review_base,
            },
        ),
        EndpointCase(
            "POST",
            "/api/v1/fitment/recommendations/{recommendation_id}/reject",
            f"/api/v1/fitment/recommendations/{f.fitment_recommendation_id}/reject",
            json={"idempotency_key": "tenant-matrix-reject", **review_base},
        ),
        EndpointCase(
            "POST",
            "/api/v1/fitment/recommendations/{recommendation_id}/defer",
            f"/api/v1/fitment/recommendations/{f.fitment_recommendation_id}/defer",
            json={"idempotency_key": "tenant-matrix-defer", **review_base},
        ),
        EndpointCase(
            "POST",
            "/api/v1/fitment/recommendations/{recommendation_id}/research",
            (f"/api/v1/fitment/recommendations/{f.fitment_recommendation_id}/research"),
            json={"idempotency_key": "tenant-matrix-research", **review_base},
        ),
        EndpointCase(
            "POST",
            "/api/v1/fitment/notifications/{notification_id}/read",
            f"/api/v1/fitment/notifications/{f.fitment_notification_id}/read",
        ),
        EndpointCase(
            "POST",
            "/api/v1/fitment/candidates/{assessment_id}/review",
            f"/api/v1/fitment/candidates/{f.fitment_assessment_id}/review",
            json={
                "idempotency_key": "tenant-matrix-candidate-review",
                "decision": "postpone",
                "reason_code": "OTHER",
                "comment": "tenant isolation probe",
            },
        ),
    )


@pytest.fixture(autouse=True)
def _enable_deferred_fitment(monkeypatch):
    """The matrix covers fitment routes, which this delivery leaves unmounted.

    Tenant isolation must stay proven for them regardless: the code ships in the
    image, and the phase that mounts it must not have to rediscover whether a
    foreign workspace can read another tenant's fitment sources.
    """

    monkeypatch.setenv("FITMENT_API_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_every_resource_endpoint_hides_foreign_workspace_and_has_no_side_effects() -> (
    None
):
    _assert_disposable_database()
    fixture = await _seed_foreign_workspace()
    cases = _foreign_resource_cases(fixture)
    assert len(cases) == 42

    application = create_app()
    http_methods = {"get", "post", "put", "patch", "delete"}
    parameterized_openapi_operations = {
        (method.upper(), template)
        for template, path_item in application.openapi()["paths"].items()
        if "{" in template
        for method in path_item
        if method in http_methods
    }
    seller_commands = {
        ("POST", "/api/v1/fitment/sellers/{seller_external_id}/mark-own"),
        ("POST", "/api/v1/fitment/sellers/{seller_external_id}/mark-related"),
    }
    assert {(case.method, case.template) for case in cases} | seller_commands == (
        parameterized_openapi_operations
    )

    auth_user = User(
        id=fixture.user_a_id,
        email=f"tenant-matrix-{fixture.user_a_id.hex}@example.test",
        is_active=True,
    )

    async def current_user_override() -> AuthContext:
        return AuthContext(
            user=auth_user,
            workspace_id=fixture.workspace_a_id,
            workspace_role=WorkspaceRole.owner,
        )

    application.dependency_overrides[get_current_user] = current_user_override
    counts_before = await _table_counts()
    state_before = await _mutable_state(fixture)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            for case in cases:
                response = await client.request(
                    case.method,
                    case.path,
                    json=case.json,
                    params=case.params,
                )
                assert response.status_code == 404, (
                    f"{case.method} {case.template} leaked a foreign resource or "
                    f"failed before tenant lookup: {response.status_code} "
                    f"{response.text}"
                )
            populated_search = await client.get(
                f"/api/v1/stores/{fixture.own_store_id}/products/elsewhere",
                params={"q": "TENANT-LEAK-PROBE-484848"},
            )
            assert populated_search.status_code == 200, populated_search.text
            assert populated_search.json()["matches"] == []
    finally:
        application.dependency_overrides.clear()

    assert await _table_counts() == counts_before
    assert await _mutable_state(fixture) == state_before


@pytest.mark.asyncio
async def test_seller_external_id_commands_write_only_to_authenticated_workspace() -> (
    None
):
    _assert_disposable_database()
    fixture = await _seed_foreign_workspace()
    application = create_app()
    auth_user = User(
        id=fixture.user_a_id,
        email=f"tenant-matrix-{fixture.user_a_id.hex}@example.test",
        is_active=True,
    )

    async def current_user_override() -> AuthContext:
        return AuthContext(
            user=auth_user,
            workspace_id=fixture.workspace_a_id,
            workspace_role=WorkspaceRole.owner,
        )

    application.dependency_overrides[get_current_user] = current_user_override
    seller_external_id = f"shared-external-id-{uuid4().hex}"
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            for suffix, idempotency_key in (
                ("mark-own", "tenant-matrix-seller-own"),
                ("mark-related", "tenant-matrix-seller-related"),
            ):
                response = await client.post(
                    f"/api/v1/fitment/sellers/{seller_external_id}/{suffix}",
                    json={
                        "idempotency_key": idempotency_key,
                        "seller_name": "Shared public seller identifier",
                        "confidence": "1",
                        "evidence": [{"kind": "tenant-matrix-fixture"}],
                        "reason": "prove authenticated workspace ownership",
                    },
                )
                assert response.status_code == 201, response.text
                assert response.json()["workspace_id"] == str(fixture.workspace_a_id)
    finally:
        application.dependency_overrides.clear()

    async with async_session_factory() as session:
        rows = list(
            (
                await session.execute(
                    select(SellerRelationRecord).where(
                        SellerRelationRecord.seller_external_id == seller_external_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 2
    assert {row.workspace_id for row in rows} == {fixture.workspace_a_id}
    assert fixture.workspace_b_id not in {row.workspace_id for row in rows}
