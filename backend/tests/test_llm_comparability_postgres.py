"""Opt-in PostgreSQL proof for semantic-review persistence and cache behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError

from marko.core.config import Settings, get_settings
from marko.infrastructure.db.models import (
    CandidateComparabilityFeedback,
    CandidateComparabilityReview,
    CatalogImportBatch,
    CatalogItem,
    MarketObservation,
    PricingRun,
    PricingRunItem,
    RawMarketCapture,
    User,
    Workspace,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.llm_comparability import (
    ComparabilityMatchLevel,
    ComparabilityVerdict,
    FindingOutcome,
    LLMComparabilityOutput,
    ProviderReview,
    ReviewDimensionFinding,
    add_comparability_feedback,
    load_effective_review_map,
    request_observation_comparability_review,
)
from marko.services.market_collection import claim_collection_finalization
from metis.pricing import comparison_evidence_to_dict, verified_comparison_evidence


pytestmark = pytest.mark.postgres
_APPEND_ONLY_TABLES = (
    "candidate_comparability_feedback",
    "candidate_comparability_reviews",
    "market_observations",
    "raw_market_captures",
)


class _CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def review(
        self,
        *,
        input_snapshot: object,
        image_urls: object,
    ) -> ProviderReview:
        del input_snapshot, image_urls
        self.calls += 1
        output = LLMComparabilityOutput(
            verdict=ComparabilityVerdict.COMPARABLE,
            match_level=ComparabilityMatchLevel.ACCEPTABLE_ANALOGUE,
            confidence=Decimal("0.9300"),
            rationale="OE and part type agree in the retained product evidence.",
            dimension_findings=[
                ReviewDimensionFinding(
                    dimension="oe_reference",
                    outcome=FindingOutcome.MATCH,
                    our_value="1K0615301",
                    candidate_value="1K0615301",
                    explanation="Normalized OE identifiers match.",
                ),
                ReviewDimensionFinding(
                    dimension="part_type",
                    outcome=FindingOutcome.MATCH,
                    our_value="brake disc",
                    candidate_value="brake disc",
                    explanation="Both cards identify a front brake disc.",
                ),
            ],
        )
        return ProviderReview(
            output=output,
            response_id=f"response-{self.calls}",
            model="integration-model",
            usage={"input_tokens": 100, "output_tokens": 40},
            latency_ms=12,
        )


async def _seed_identical_observations(
    *,
    workspace_id: UUID,
    user_id: UUID,
) -> tuple[list[UUID], list[UUID], list[UUID]]:
    batch_id = uuid4()
    item_id = uuid4()
    run_ids = [uuid4() for _ in range(5)]
    run_item_ids = [uuid4() for _ in range(5)]
    capture_ids = [uuid4() for _ in range(5)]
    observation_ids = [uuid4() for _ in range(5)]
    now = datetime.now(UTC)
    evidence = comparison_evidence_to_dict(
        verified_comparison_evidence(
            stable_seller_id="seller-cache-proof",
            source_record_id="listing-cache-proof",
        )
    )

    async with async_session_factory() as session:
        session.add_all(
            [
                Workspace(
                    id=workspace_id,
                    name="LLM comparability integration",
                    slug=f"llm-comparability-{workspace_id.hex}",
                ),
                User(
                    id=user_id,
                    email=f"llm-comparability-{user_id.hex}@example.test",
                    is_active=True,
                ),
            ]
        )
        await session.flush()
        session.add(
            CatalogImportBatch(
                id=batch_id,
                workspace_id=workspace_id,
                filename="llm-comparability.xlsx",
                content_sha256="a" * 64,
                request_fingerprint=uuid4().hex * 2,
                content_size=1,
                status="completed",
                column_mapping={"sku": "SKU"},
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
                sku="SKU-LLM-CACHE",
                oe_raw="1K0 615 301",
                oe_norm="1K0615301",
                name="Front brake disc",
                category="brake_pad",
                brand="KEMP",
                description="New front brake disc",
                product_url=None,
                current_price=Decimal("1000"),
                currency="UAH",
                is_available=True,
                raw_row={},
                part_numbers_norm=["1K0615301"],
                applicability_brands=["VW"],
                applicability_models=["Golf"],
                characteristics_raw={"part_type": "brake disc"},
                identity_status="OE_CONFIRMED",
            )
        )
        await session.flush()

        for index, run_id in enumerate(run_ids):
            run_item_id = run_item_ids[index]
            capture_id = capture_ids[index]
            observation_id = observation_ids[index]
            session.add(
                PricingRun(
                    id=run_id,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    status="collecting",
                    policy_version="integration-v1",
                    policy_config={},
                    parser_version="integration-v1",
                    total_items=1,
                )
            )
            await session.flush()
            session.add(
                PricingRunItem(
                    id=run_item_id,
                    pricing_run_id=run_id,
                    catalog_item_id=item_id,
                    status="classified",
                    idempotency_key=f"llm-comparability:{run_item_id}",
                )
            )
            await session.flush()
            session.add(
                RawMarketCapture(
                    id=capture_id,
                    pricing_run_item_id=run_item_id,
                    source="prom_public",
                    payload={"listing": "listing-cache-proof"},
                    content_sha256=f"{index + 1:064x}",
                    parser_version="integration-v1",
                )
            )
            await session.flush()
            session.add(
                MarketObservation(
                    id=observation_id,
                    pricing_run_item_id=run_item_id,
                    catalog_item_id=item_id,
                    raw_capture_id=capture_id,
                    source="prom_public",
                    source_listing_id="listing-cache-proof",
                    seller_id="seller-cache-proof",
                    seller_name="Competitor",
                    url="https://prom.ua/ua/p1-front-brake-disc.html",
                    title="Front brake disc 1K0615301",
                    description="New front brake disc for VW Golf",
                    description_available=True,
                    condition_raw="new",
                    condition_state="NEW",
                    candidate_snapshot={
                        "characteristics": {
                            "part_type": "brake disc",
                            "position": "front",
                        },
                        "images": ["https://images.prom.ua/cache-proof.jpg"],
                    },
                    brand_raw="Budget analogue",
                    matched_oe_norm="1K0615301",
                    search_oe_norm="1K0615301",
                    extracted_oe_norms=["1K0615301"],
                    verified_matched_oe_norm="1K0615301",
                    comparison_identity_key="oe:1K0615301",
                    oe_verification_status="VERIFIED_EXACT",
                    oe_evidence=[],
                    oe_extractor_version="integration-v1",
                    price=Decimal("1100"),
                    sale_price=Decimal("1100"),
                    currency="UAH",
                    currency_raw="UAH",
                    currency_inferred=False,
                    is_available=True,
                    match_confidence=Decimal("1"),
                    source_confidence=Decimal("1"),
                    parser_version="integration-v1",
                    evidence_contract_version="comparison-evidence-v3",
                    comparability_policy_id="integration-v1",
                    comparability_policy_hash="b" * 64,
                    comparison_evidence=evidence,
                    comparability_hard_gate_result="PASS",
                    seller_identity_verified=True,
                    source_provenance_verified=True,
                    automatic_eligible=False,
                    observed_at=now,
                )
            )
        await session.commit()
    return run_ids, run_item_ids, observation_ids


async def _cleanup(workspace_id: UUID, user_id: UUID) -> None:
    async with async_session_factory() as session:
        try:
            for table_name in _APPEND_ONLY_TABLES:
                await session.execute(
                    text(
                        f"ALTER TABLE {table_name} "
                        f"DISABLE TRIGGER trg_{table_name}_append_only"
                    )
                )
            await session.execute(
                delete(CandidateComparabilityFeedback).where(
                    CandidateComparabilityFeedback.workspace_id == workspace_id
                )
            )
            await session.execute(
                delete(CandidateComparabilityReview).where(
                    CandidateComparabilityReview.workspace_id == workspace_id
                )
            )
            await session.execute(
                text(
                    "DELETE FROM market_observations WHERE catalog_item_id IN "
                    "(SELECT id FROM catalog_items WHERE workspace_id=:workspace_id)"
                ),
                {"workspace_id": workspace_id},
            )
            await session.execute(
                text(
                    "DELETE FROM raw_market_captures WHERE pricing_run_item_id IN "
                    "(SELECT item.id FROM pricing_run_items AS item "
                    "JOIN pricing_runs AS run ON run.id=item.pricing_run_id "
                    "WHERE run.workspace_id=:workspace_id)"
                ),
                {"workspace_id": workspace_id},
            )
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await session.execute(delete(User).where(User.id == user_id))
            for table_name in reversed(_APPEND_ONLY_TABLES):
                await session.execute(
                    text(
                        f"ALTER TABLE {table_name} "
                        f"ENABLE TRIGGER trg_{table_name}_append_only"
                    )
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.mark.skipif(
    os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_reviews_cache_feedback_and_finalizer_barrier_are_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid4()
    user_id = uuid4()
    provider = _CountingProvider()
    settings = Settings(
        pricing_llm_comparability_mode="required",
        pricing_llm_api_key="integration-test-key",
        pricing_llm_model="integration-model",
    )
    monkeypatch.setenv("PRICING_LLM_COMPARABILITY_MODE", "required")
    monkeypatch.setenv("PRICING_LLM_API_KEY", "integration-test-key")
    monkeypatch.setenv("PRICING_LLM_MODEL", "integration-model")
    get_settings.cache_clear()

    try:
        run_ids, run_item_ids, observation_ids = await _seed_identical_observations(
            workspace_id=workspace_id,
            user_id=user_id,
        )

        first = await request_observation_comparability_review(
            observation_ids[0],
            workspace_id=workspace_id,
            settings=settings,
            provider=provider,
        )
        duplicate = await request_observation_comparability_review(
            observation_ids[0],
            workspace_id=workspace_id,
            settings=settings,
            provider=provider,
        )
        cached = await request_observation_comparability_review(
            observation_ids[1],
            workspace_id=workspace_id,
            settings=settings,
            provider=provider,
        )

        assert provider.calls == 1
        assert duplicate.review_id == first.review_id
        assert cached.decision_source == "CACHE"
        assert cached.cache_hit_review_id == first.review_id

        async with async_session_factory() as session:
            corrected = await add_comparability_feedback(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
                review_id=first.review_id,
                decision="CORRECT",
                corrected_verdict="NOT_COMPARABLE",
                corrected_match_level="NOT_APPLICABLE",
                confidence=Decimal("0"),
                reason="Customer confirmed that the package contents differ.",
                evidence_corrections=[
                    {
                        "dimension": "package_quantity",
                        "outcome": "CONFLICT",
                        "our_value": "1",
                        "candidate_value": "2",
                        "explanation": "The competitor card contains a two-part kit.",
                        "evidence": [],
                    }
                ],
            )
        assert corrected.decision_source == "HUMAN"
        assert corrected.verdict is ComparabilityVerdict.NOT_COMPARABLE
        assert corrected.confidence == 0

        human_cached = await request_observation_comparability_review(
            observation_ids[2],
            workspace_id=workspace_id,
            settings=settings,
            provider=provider,
        )
        assert provider.calls == 1
        assert human_cached.decision_source == "HUMAN_CACHE"
        assert human_cached.cache_hit_review_id == first.review_id
        assert human_cached.verdict is ComparabilityVerdict.NOT_COMPARABLE

        assert (
            await claim_collection_finalization(run_ids[3], task_id="finalizer")
            is False
        )
        await request_observation_comparability_review(
            observation_ids[3],
            workspace_id=workspace_id,
            settings=settings,
            provider=provider,
        )
        assert (
            await claim_collection_finalization(run_ids[3], task_id="finalizer") is True
        )

        async with async_session_factory() as session:
            failed_item = await session.get(PricingRunItem, run_item_ids[4])
            assert failed_item is not None
            failed_item.status = "failed"
            await session.commit()
        assert (
            await claim_collection_finalization(
                run_ids[4],
                task_id="failed-item-finalizer",
            )
            is True
        )

        async with async_session_factory() as session:
            effective = await load_effective_review_map(
                session,
                [observation_ids[0], observation_ids[1], observation_ids[2]],
            )
            assert effective[observation_ids[0]].confidence == 0
            assert effective[observation_ids[2]].verdict is (
                ComparabilityVerdict.NOT_COMPARABLE
            )
            assert (
                await session.scalar(
                    select(func.count(CandidateComparabilityReview.id)).where(
                        CandidateComparabilityReview.workspace_id == workspace_id
                    )
                )
                == 4
            )

        async with async_session_factory() as session:
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(
                    text(
                        "UPDATE candidate_comparability_reviews "
                        "SET rationale='mutated' WHERE id=:id"
                    ),
                    {"id": first.review_id},
                )
                await session.commit()
            await session.rollback()
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id, user_id)
