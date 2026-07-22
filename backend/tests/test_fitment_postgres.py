"""Opt-in PostgreSQL proof for the distributed fitment migration."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import os
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from marko.infrastructure.db.models import (
    CatalogImportBatch,
    CatalogItem,
    FitmentAnalysis,
    FitmentCandidateAssessment,
    FitmentFeedbackEvent,
    FitmentMarketRecommendation,
    FitmentNotification,
    FitmentRecommendationReview,
    MarketObservation,
    PricingRun,
    PricingRunItem,
    RawMarketCapture,
    ScrapeDispatchOutbox,
    User,
    Workspace,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.fitment_intelligence import (
    AnalysisSpec,
    CandidateAnalysisSpec,
    SubmittedEvidence,
    enqueue_fitment_analysis,
    process_fitment_analysis_job,
)
from marko.services.fitment_hitl import (
    generate_fitment_recommendation,
    review_fitment_recommendation,
)
from metis.fitment import (
    Availability,
    CommercialContext,
    Condition,
    EvidenceClaim,
    EvidencePolarity,
    FeedbackReason,
    FitmentFeature,
    PartIdentity,
    PricingStrategy,
    RecommendationDecision,
    SellerRelation,
    SourceTier,
    StatementStatus,
)
from metis.pricing.types import ProductTier


pytestmark = pytest.mark.postgres


def _enabled() -> bool:
    return os.environ.get("MARKO_RUN_FITMENT_POSTGRES") == "1"


@pytest.mark.skipif(
    not _enabled(),
    reason="set MARKO_RUN_FITMENT_POSTGRES=1 with a disposable fitment database",
)
@pytest.mark.asyncio(loop_scope="module")
async def test_fitment_schema_and_append_only_guards_hold() -> None:
    database_name = make_url(os.environ["DATABASE_URL"]).database or ""
    if "fitment" not in database_name.casefold():
        pytest.fail("refusing to run against a non-disposable database")

    workspace_id = uuid4()
    source_id = uuid4()
    async with async_session_factory() as session:
        revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == "20260721_0020"
        table_count = await session.scalar(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND "
                "(table_name LIKE 'fitment_%' OR table_name='seller_relation_records')"
            )
        )
        assert table_count == 15
        trigger_count = await session.scalar(
            text(
                "SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal "
                "AND (tgname LIKE 'trg_fitment_%_append_only' "
                "OR tgname='trg_seller_relation_records_append_only')"
            )
        )
        assert trigger_count == 13
        no_auto_constraint = await session.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname='ck_fit_assessment_no_auto_price'"
            )
        )
        assert "NOT automatic_price_change_allowed" in no_auto_constraint
        queue_columns = set(
            (
                await session.scalars(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema='public' AND "
                        "table_name='fitment_analyses'"
                    )
                )
            ).all()
        )
        assert {
            "request_payload",
            "dispatch_task_id",
            "owner_task_id",
            "attempt_count",
            "lease_expires_at",
            "last_attempt_at",
            "workflow_state",
        }.issubset(queue_columns)

        await session.execute(
            text(
                "INSERT INTO workspaces (id, name, slug) VALUES (:id, 'Fitment', :slug)"
            ),
            {"id": workspace_id, "slug": f"fitment-{workspace_id.hex}"},
        )
        await session.execute(
            text(
                "INSERT INTO fitment_sources "
                "(id, workspace_id, source_key, source_type, source_tier, "
                "base_reliability, domain, access_method, access_status, "
                "access_reference, robots_checked, terms_checked, rate_limit, cache_policy, "
                "policy_version, reviewed_at) VALUES "
                "(:id, :workspace_id, 'official-test', "
                "'official_manufacturer_catalog', 'A', 0.95, 'example.test', "
                "'licensed_api', 'PERMITTED', 'contract:test-v1', true, true, '10/min', "
                "'fact_level_only', 'v1', now())"
            ),
            {"id": source_id, "workspace_id": workspace_id},
        )
        await session.commit()

    async with async_session_factory() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(
                text("UPDATE fitment_sources SET base_reliability=0.10 WHERE id=:id"),
                {"id": source_id},
            )
            await session.commit()
        await session.rollback()

    async with async_session_factory() as session:
        with pytest.raises(DBAPIError, match="ck_fit_source_tier_reliability"):
            await session.execute(
                text(
                    "INSERT INTO fitment_sources "
                    "(id, workspace_id, source_key, source_type, source_tier, "
                    "base_reliability, domain, access_method, access_status, "
                    "access_reference, robots_checked, terms_checked, rate_limit, "
                    "cache_policy, policy_version, reviewed_at) VALUES "
                    "(:id, :workspace_id, 'spoofed-tier', 'marketplace', 'A', "
                    "0.50, 'example.test', 'browser', 'PERMITTED', "
                    "'review:test', true, true, '1/min', 'fact_level_only', "
                    "'v1', now())"
                ),
                {"id": uuid4(), "workspace_id": workspace_id},
            )
            await session.commit()
        await session.rollback()


def _fitment_claim(feature: FitmentFeature) -> EvidenceClaim:
    return EvidenceClaim(
        evidence_id=f"postgres-{feature.value}",
        feature=feature,
        value=Decimal("1"),
        source_id="postgres-fixture",
        source_type="persisted_replay",
        source_tier=SourceTier.D,
        source_reliability=Decimal("0.55"),
        extraction_confidence=Decimal("0.95"),
        independence_factor=Decimal("1"),
        freshness_factor=Decimal("1"),
        correlation_group="postgres-fixture",
        polarity=EvidencePolarity.SUPPORTS,
        statement_status=StatementStatus.INFERENCE,
        claim_value={"synthetic": True},
        retrieved_at=datetime(2026, 7, 21, tzinfo=UTC),
        source_url="https://fixture.invalid/evidence",
        source_document_sha256="f" * 64,
    )


@pytest.mark.skipif(
    not _enabled(),
    reason="set MARKO_RUN_FITMENT_POSTGRES=1 with a disposable fitment database",
)
@pytest.mark.asyncio(loop_scope="module")
async def test_fitment_queue_is_idempotent_and_worker_persists_assessment() -> None:
    database_name = make_url(os.environ["DATABASE_URL"]).database or ""
    if "fitment" not in database_name.casefold():
        pytest.fail("refusing to run against a non-disposable database")

    workspace_id = uuid4()
    actor_id = uuid4()
    batch_id = uuid4()
    item_id = uuid4()
    run_id = uuid4()
    run_item_id = uuid4()
    capture_id = uuid4()
    observation_id = uuid4()
    now = datetime.now(UTC)
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())

    async with async_session_factory() as session:
        session.add_all(
            [
                Workspace(
                    id=workspace_id,
                    name="Fitment queue",
                    slug=f"fitment-queue-{workspace_id.hex}",
                ),
                User(
                    id=actor_id,
                    email=f"fitment-{actor_id.hex}@example.test",
                    display_name="Fitment test",
                    is_active=True,
                ),
            ]
        )
        await session.flush()
        session.add(
            CatalogImportBatch(
                id=batch_id,
                workspace_id=workspace_id,
                filename="fitment.xlsx",
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
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                source_row=2,
                sku="FITMENT-QUEUE-1",
                oe_raw="48530-89025",
                oe_norm="4853089025",
                name="Rear right shock absorber",
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
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                status="collecting",
                policy_version="fitment-test-v1",
                policy_config={},
                parser_version="fixture-v1",
            )
        )
        await session.flush()
        session.add(
            PricingRunItem(
                id=run_item_id,
                pricing_run_id=run_id,
                catalog_item_id=item_id,
                status="collected",
                idempotency_key=f"fitment:{run_item_id}",
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
                raw_size_bytes=1,
                structured_size_bytes=1,
                metadata_size_bytes=1,
                structured_completeness=Decimal("1"),
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
                source_listing_id="fitment-listing-1",
                seller_id="independent-seller-1",
                seller_name="Independent seller",
                url="https://fixture.invalid/item-1",
                title="Rear right shock absorber",
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
        await session.commit()

        identity = PartIdentity(
            category="shock_absorber",
            axle="rear",
            side="right",
            vehicle_make="Toyota",
            vehicle_model="Camry",
            generation="XV40",
            year_from=2006,
            year_to=2011,
            engine="2.4",
            body="sedan",
            manufacturer_article="21956RR",
            oe_numbers=("48530-89025",),
            side_specific=True,
        )
        commercial = CommercialContext(
            condition=Condition.NEW,
            package_quantity=Decimal("1"),
            unit_basis="piece",
            currency="UAH",
            tier=ProductTier.AFTERMARKET_B,
            availability=Availability.IN_STOCK,
            seller_relation=SellerRelation.INDEPENDENT,
            stable_seller_id_verified=True,
            seller_group_id="independent-seller-1",
            product_identity_key="kyb:21956rr",
        )
        spec = AnalysisSpec(
            target_identity=identity,
            target_commercial_context=commercial,
            candidates=(
                CandidateAnalysisSpec(
                    market_observation_id=observation_id,
                    identity=identity,
                    commercial_context=commercial,
                    evidence=tuple(
                        SubmittedEvidence(_fitment_claim(feature))
                        for feature in FitmentFeature
                        if feature
                        not in {
                            FitmentFeature.OE_SUPERSESSION,
                            FitmentFeature.CROSS_CONFIRMED,
                        }
                    ),
                ),
            ),
            source_policy_snapshot={"data_class": "synthetic_adversarial"},
        )

        first = await enqueue_fitment_analysis(
            session,
            workspace_id=workspace_id,
            actor_user_id=actor_id,
            catalog_item_id=item_id,
            pricing_run_id=run_id,
            idempotency_key="postgres-fitment-queue",
            spec=spec,
            celery_app=fake_celery,
        )
        duplicate = await enqueue_fitment_analysis(
            session,
            workspace_id=workspace_id,
            actor_user_id=actor_id,
            catalog_item_id=item_id,
            pricing_run_id=run_id,
            idempotency_key="postgres-fitment-queue",
            spec=spec,
            celery_app=fake_celery,
        )

        assert first.id == duplicate.id
        assert first.status == "queued"
        assert first.dispatch_task_id is not None
        assert fake_celery.send_task.call_count == 1
        assert await session.scalar(
            select(func.count(FitmentAnalysis.id)).where(
                FitmentAnalysis.workspace_id == workspace_id
            )
        ) == 1

        assert await session.scalar(
            select(func.count(ScrapeDispatchOutbox.id)).where(
                ScrapeDispatchOutbox.aggregate_id == first.id
            )
        ) == 1

        completed = await process_fitment_analysis_job(
            session,
            analysis_id=first.id,
            task_id="postgres-worker-1",
        )
        assert completed is not None
        assert completed.status == "completed"
        assert completed.attempt_count == 1
        assert completed.completed_candidate_count == 1
        assessment = await session.scalar(
            select(FitmentCandidateAssessment).where(
                FitmentCandidateAssessment.analysis_id == first.id
            )
        )
        assert assessment is not None
        assert assessment.automatic_price_change_allowed is False
        assert assessment.requires_manual_review is True

        replayed = await process_fitment_analysis_job(
            session,
            analysis_id=first.id,
            task_id="postgres-worker-redelivery",
        )
        assert replayed is not None
        assert replayed.status == "completed"
        assert await session.scalar(
            select(func.count(FitmentCandidateAssessment.id)).where(
                FitmentCandidateAssessment.analysis_id == first.id
            )
        ) == 1

        recommendation = await generate_fitment_recommendation(
            session,
            workspace_id=workspace_id,
            actor_user_id=actor_id,
            analysis_id=first.id,
            catalog_item_id=item_id,
            idempotency_key="postgres-fitment-recommendation",
            strategy=PricingStrategy.BALANCED,
            approved_price_floor=None,
            absolute_buffer=Decimal("0"),
            percentage_buffer=Decimal("0.02"),
            max_decrease_rate=Decimal("0.15"),
            max_increase_rate=Decimal("0.20"),
            deadband=Decimal("0.04"),
            minimum_confidence=Decimal("0.65"),
            price_tick=Decimal("1"),
            custom_anchor=None,
        )
        duplicate_recommendation = await generate_fitment_recommendation(
            session,
            workspace_id=workspace_id,
            actor_user_id=actor_id,
            analysis_id=first.id,
            catalog_item_id=item_id,
            idempotency_key="postgres-fitment-recommendation",
            strategy=PricingStrategy.BALANCED,
            approved_price_floor=None,
            absolute_buffer=Decimal("0"),
            percentage_buffer=Decimal("0.02"),
            max_decrease_rate=Decimal("0.15"),
            max_increase_rate=Decimal("0.20"),
            deadband=Decimal("0.04"),
            minimum_confidence=Decimal("0.65"),
            price_tick=Decimal("1"),
            custom_anchor=None,
        )
        assert recommendation.id == duplicate_recommendation.id
        assert recommendation.action == "insufficient_evidence"
        assert recommendation.recommended_price is None
        assert recommendation.automatic_price_change_allowed is False
        assert await session.scalar(
            select(func.count(FitmentMarketRecommendation.id)).where(
                FitmentMarketRecommendation.analysis_id == first.id
            )
        ) == 1
        assert await session.scalar(
            select(func.count(FitmentNotification.id)).where(
                FitmentNotification.recommendation_id == recommendation.id
            )
        ) == 1

        review = await review_fitment_recommendation(
            session,
            workspace_id=workspace_id,
            actor_user_id=actor_id,
            recommendation_id=recommendation.id,
            idempotency_key="postgres-fitment-research",
            decision=RecommendationDecision.RESEARCH_REQUESTED,
            approved_price=None,
            reason_code=FeedbackReason.SOURCE_ERROR,
            comment="Need stronger independent evidence",
            allow_below_floor=False,
            below_floor_warning_confirmed=False,
        )
        assert review.decision == "research_requested"
        assert review.approved_price is None
        assert await session.scalar(
            select(func.count(FitmentRecommendationReview.id)).where(
                FitmentRecommendationReview.recommendation_id == recommendation.id
            )
        ) == 1
        assert await session.scalar(
            select(func.count(FitmentFeedbackEvent.id)).where(
                FitmentFeedbackEvent.entity_id == str(recommendation.id)
            )
        ) == 1
