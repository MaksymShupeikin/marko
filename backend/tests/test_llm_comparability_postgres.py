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
from marko.infrastructure.db.session import async_session_factory, engine
from marko.services.llm_call_budget import ensure_provider_call_budget_table
from marko.services.llm_comparability import (
    ComparabilityMatchLevel,
    ComparabilityVerdict,
    FindingOutcome,
    LLMComparabilityOutput,
    ProviderReview,
    ReviewDimensionFinding,
    add_comparability_feedback,
    ensure_run_item_comparability_reviews,
    load_effective_review_map,
    request_observation_comparability_review,
)
from marko.services.market_collection import claim_collection_finalization
from metis.pricing import comparison_evidence_to_dict, verified_comparison_evidence


pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
async def _provider_call_budget_ledger() -> None:
    """Create the provider-call ledger until its migration lands.

    Every provider call is now paid for out of a durable per-position budget
    (F9), so without this table the review path fails closed and judges nothing.
    ``checkfirst`` makes this a no-op the moment the migration exists.
    """

    if os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") != "1":
        return
    await ensure_provider_call_budget_table(engine)


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
    # One import batch per run.  ``uq_pricing_run_active_import_batch`` allows a
    # single active run per batch, so the older shape — five ``collecting`` runs
    # sharing one batch — was only ever possible because the duplicate-run
    # defect existed.  The fixture, not the constraint, was wrong.
    batch_ids = [uuid4() for _ in range(5)]
    batch_id = batch_ids[0]
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
        session.add_all(
            [
                CatalogImportBatch(
                    id=value,
                    workspace_id=workspace_id,
                    filename=f"llm-comparability-{index}.xlsx",
                    content_sha256=f"{index:064x}",
                    request_fingerprint=uuid4().hex * 2,
                    content_size=1,
                    status="completed",
                    column_mapping={"sku": "SKU"},
                    total_rows=1,
                    imported_rows=1,
                    rejected_rows=0,
                    error_log=[],
                )
                for index, value in enumerate(batch_ids)
            ]
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
                    import_batch_id=batch_ids[index],
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


async def _seed_wide_cohort(
    *,
    workspace_id: UUID,
    user_id: UUID,
    offers: int,
) -> tuple[UUID, UUID, list[UUID]]:
    """One position carrying more offers than the review ceiling.

    A part-code page keeps a median 81 offers past the gates, so the cohort that
    exceeds the ceiling is the normal case, not an edge case.  Prices ascend so
    the cheapest-first walk has a defined order.
    """

    batch_id = uuid4()
    item_id = uuid4()
    run_id = uuid4()
    run_item_id = uuid4()
    capture_id = uuid4()
    observation_ids = [uuid4() for _ in range(offers)]
    now = datetime.now(UTC)
    evidence = comparison_evidence_to_dict(
        verified_comparison_evidence(
            stable_seller_id="seller-wide-cohort",
            source_record_id="listing-wide-cohort",
        )
    )

    async with async_session_factory() as session:
        session.add_all(
            [
                Workspace(
                    id=workspace_id,
                    name="LLM ceiling barrier",
                    slug=f"llm-ceiling-{workspace_id.hex}",
                ),
                User(
                    id=user_id,
                    email=f"llm-ceiling-{user_id.hex}@example.test",
                    is_active=True,
                ),
            ]
        )
        await session.flush()
        session.add(
            CatalogImportBatch(
                id=batch_id,
                workspace_id=workspace_id,
                filename="llm-ceiling.xlsx",
                content_sha256="c" * 64,
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
                sku="SKU-LLM-CEILING",
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
                idempotency_key=f"llm-ceiling:{run_item_id}",
            )
        )
        await session.flush()
        session.add(
            RawMarketCapture(
                id=capture_id,
                pricing_run_item_id=run_item_id,
                source="prom_public",
                payload={"listing": "listing-wide-cohort"},
                content_sha256=f"{7:064x}",
                parser_version="integration-v1",
            )
        )
        await session.flush()
        for index, observation_id in enumerate(observation_ids):
            session.add(
                MarketObservation(
                    id=observation_id,
                    pricing_run_item_id=run_item_id,
                    catalog_item_id=item_id,
                    raw_capture_id=capture_id,
                    source="prom_public",
                    source_listing_id=f"listing-wide-{index}",
                    seller_id=f"seller-wide-{index}",
                    seller_name=f"Competitor {index}",
                    url=f"https://prom.ua/ua/p{index}-front-brake-disc.html",
                    title="Front brake disc 1K0615301",
                    description="New front brake disc for VW Golf",
                    description_available=True,
                    condition_raw="new",
                    condition_state="NEW",
                    candidate_snapshot={
                        "characteristics": {
                            "part_type": "brake disc",
                            "position": "front",
                        }
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
                    # Ascending, so "cheapest first" has a defined meaning.
                    price=Decimal(1000 + index * 10),
                    sale_price=Decimal(1000 + index * 10),
                    currency="UAH",
                    currency_raw="UAH",
                    currency_inferred=False,
                    is_available=True,
                    match_confidence=Decimal("1"),
                    source_confidence=Decimal("1"),
                    parser_version="integration-v1",
                    evidence_contract_version="comparison-evidence-v3",
                    comparability_policy_id="integration-v1",
                    comparability_policy_hash="d" * 64,
                    comparison_evidence=evidence,
                    comparability_hard_gate_result="PASS",
                    seller_identity_verified=True,
                    source_provenance_verified=True,
                    automatic_eligible=False,
                    observed_at=now,
                )
            )
        await session.commit()
    return run_id, run_item_id, observation_ids


async def _seed_hard_stop_pair(
    *,
    workspace_id: UUID,
    user_id: UUID,
) -> list[UUID]:
    """Two identical, deterministically hard-stopped candidates.

    The second observation shares the first's content hash, so the cross
    observation cache lookup returns the first (persisted as ``HARD_STOP``).
    Both still hard-stop deterministically, so the second must persist as a
    ``HARD_RULE`` decision that records no cache hit.
    """

    # One batch per run: see the note in ``_seed_identical_observations``.
    batch_ids = [uuid4() for _ in range(2)]
    batch_id = batch_ids[0]
    item_id = uuid4()
    run_ids = [uuid4() for _ in range(2)]
    run_item_ids = [uuid4() for _ in range(2)]
    capture_ids = [uuid4() for _ in range(2)]
    observation_ids = [uuid4() for _ in range(2)]
    now = datetime.now(UTC)
    evidence = comparison_evidence_to_dict(
        verified_comparison_evidence(
            stable_seller_id="seller-hard-stop",
            source_record_id="listing-hard-stop",
        )
    )

    async with async_session_factory() as session:
        session.add_all(
            [
                Workspace(
                    id=workspace_id,
                    name="LLM hard-stop cache",
                    slug=f"llm-hardstop-{workspace_id.hex}",
                ),
                User(
                    id=user_id,
                    email=f"llm-hardstop-{user_id.hex}@example.test",
                    is_active=True,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                CatalogImportBatch(
                    id=value,
                    workspace_id=workspace_id,
                    filename=f"llm-hardstop-{index}.xlsx",
                    content_sha256=f"{0xC0 + index:064x}",
                    request_fingerprint=uuid4().hex * 2,
                    content_size=1,
                    status="completed",
                    column_mapping={"sku": "SKU"},
                    total_rows=1,
                    imported_rows=1,
                    rejected_rows=0,
                    error_log=[],
                )
                for index, value in enumerate(batch_ids)
            ]
        )
        await session.flush()
        session.add(
            CatalogItem(
                id=item_id,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                source_row=2,
                sku="SKU-LLM-HARDSTOP",
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

        for index in range(2):
            session.add(
                PricingRun(
                    id=run_ids[index],
                    workspace_id=workspace_id,
                    import_batch_id=batch_ids[index],
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
                    id=run_item_ids[index],
                    pricing_run_id=run_ids[index],
                    catalog_item_id=item_id,
                    status="classified",
                    idempotency_key=f"llm-hardstop:{run_item_ids[index]}",
                )
            )
            await session.flush()
            session.add(
                RawMarketCapture(
                    id=capture_ids[index],
                    pricing_run_item_id=run_item_ids[index],
                    source="prom_public",
                    payload={"listing": "listing-hard-stop"},
                    content_sha256=f"{index + 100:064x}",
                    parser_version="integration-v1",
                )
            )
            await session.flush()
            session.add(
                MarketObservation(
                    id=observation_ids[index],
                    pricing_run_item_id=run_item_ids[index],
                    catalog_item_id=item_id,
                    raw_capture_id=capture_ids[index],
                    source="prom_public",
                    source_listing_id="listing-hard-stop",
                    seller_id="seller-hard-stop",
                    seller_name="Competitor",
                    url="https://prom.ua/ua/p1-front-brake-disc.html",
                    title="Front brake disc 1K0615301",
                    description="Used front brake disc for VW Golf",
                    description_available=True,
                    condition_raw="б/у",
                    condition_state="USED_OR_REFURBISHED",
                    candidate_snapshot={
                        "characteristics": {
                            "part_type": "brake disc",
                            "position": "front",
                        },
                        "images": ["https://images.prom.ua/hard-stop.jpg"],
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
    return observation_ids


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
            # Migration 0033 turned ``pricing_run_items.catalog_item_id`` into a
            # RESTRICT foreign key so a run's membership can no longer be erased
            # by deleting the catalogue position it cites.  Teardown therefore
            # has to release the membership itself instead of relying on the
            # workspace cascade to reach ``catalog_items``.  The seeded runs
            # carry no scope contract, so the immutability trigger the same
            # migration installs does not apply to them.
            await session.execute(
                text(
                    "DELETE FROM pricing_run_items WHERE pricing_run_id IN "
                    "(SELECT id FROM pricing_runs WHERE workspace_id=:workspace_id)"
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


@pytest.mark.skipif(
    os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_hard_stop_reuse_does_not_record_a_false_cache_hit() -> None:
    """A deterministic hard stop must never masquerade as a cache decision.

    The second identical candidate finds the first (a cache-eligible
    ``HARD_STOP`` review) via the content-hash cache lookup, but it also
    hard-stops deterministically.  The hard-stop branch wins, so the persisted
    record must be a ``HARD_RULE`` decision with no ``cache_hit_review_id`` —
    otherwise it violates ``ck_candidate_comparability_review_cache_source`` and
    the whole review request raises, blocking the run's finalizer barrier.
    """

    workspace_id = uuid4()
    user_id = uuid4()
    provider = _CountingProvider()
    settings = Settings(
        pricing_llm_comparability_mode="required",
        pricing_llm_api_key="integration-test-key",
        pricing_llm_model="integration-model",
    )
    get_settings.cache_clear()

    try:
        observation_ids = await _seed_hard_stop_pair(
            workspace_id=workspace_id,
            user_id=user_id,
        )

        first = await request_observation_comparability_review(
            observation_ids[0],
            workspace_id=workspace_id,
            settings=settings,
            provider=provider,
        )
        assert first.decision_source == "HARD_RULE"
        assert first.status == "HARD_STOP"
        assert first.verdict is ComparabilityVerdict.NOT_COMPARABLE
        assert first.cache_hit_review_id is None

        # Before the fix this raised IntegrityError on the CHECK constraint
        # because the hard-stop branch copied the cross-observation cache hit.
        second = await request_observation_comparability_review(
            observation_ids[1],
            workspace_id=workspace_id,
            settings=settings,
            provider=provider,
        )
        assert second.decision_source == "HARD_RULE"
        assert second.status == "HARD_STOP"
        assert second.verdict is ComparabilityVerdict.NOT_COMPARABLE
        assert second.cache_hit_review_id is None
        assert second.review_id != first.review_id
        # A deterministic hard stop is decided without ever calling the model.
        assert provider.calls == 0

        async with async_session_factory() as session:
            persisted = list(
                (
                    await session.scalars(
                        select(CandidateComparabilityReview).where(
                            CandidateComparabilityReview.workspace_id == workspace_id
                        )
                    )
                ).all()
            )
        assert len(persisted) == 2
        assert all(row.decision_source == "HARD_RULE" for row in persisted)
        assert all(row.cache_hit_review_id is None for row in persisted)
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id, user_id)


@pytest.mark.skipif(
    os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_ceiling_leaves_no_unreviewed_tail_and_the_run_can_finalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cohort wider than the ceiling must not strand the run.

    ``claim_collection_finalization`` refuses to finalize while any observation
    of a classified item lacks a review row, and
    ``finalize_pricing_collection_task`` returns 0 without retrying when that
    barrier is unmet.  So an early stop that simply walked away would leave the
    run stuck short of a terminal state forever.  The ceiling must bound the
    provider cost without bounding the decisions on record.
    """

    workspace_id = uuid4()
    user_id = uuid4()
    provider = _CountingProvider()
    offers = 8
    ceiling = 3

    monkeypatch.setenv("PRICING_LLM_COMPARABILITY_MODE", "shadow")
    monkeypatch.setenv("PRICING_LLM_API_KEY", "integration-test-key")
    monkeypatch.setenv("PRICING_LLM_MODEL", "integration-model")
    monkeypatch.setenv("PRICING_LLM_MAX_CONFIRMED_REVIEWS", str(ceiling))
    monkeypatch.setenv("PRICING_LLM_MAX_CONCURRENCY", "1")
    get_settings.cache_clear()

    try:
        run_id, run_item_id, observation_ids = await _seed_wide_cohort(
            workspace_id=workspace_id,
            user_id=user_id,
            offers=offers,
        )

        judged = await ensure_run_item_comparability_reviews(
            run_item_id,
            provider=provider,
        )

        # Bounded cost: the dear tail cost no provider call.
        assert provider.calls == ceiling
        assert judged == ceiling

        async with async_session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(CandidateComparabilityReview).where(
                            CandidateComparabilityReview.market_observation_id.in_(
                                observation_ids
                            )
                        )
                    )
                ).all()
            )

        # The barrier's precondition: every observation carries a decision.
        assert {row.market_observation_id for row in rows} == set(observation_ids)

        skipped = [row for row in rows if row.status == "SKIPPED"]
        assert len(skipped) == offers - ceiling
        # Fail-closed: a skipped offer is never eligible evidence.
        assert all(row.verdict == "INSUFFICIENT_DATA" for row in skipped)
        assert all(row.match_level == "NOT_APPLICABLE" for row in skipped)
        assert all(row.decision_source == "HARD_RULE" for row in skipped)
        assert all(row.cache_hit_review_id is None for row in skipped)

        # The judged ones are the cheapest, in price order.
        judged_ids = {
            row.market_observation_id for row in rows if row.status != "SKIPPED"
        }
        assert judged_ids == set(observation_ids[:ceiling])

        # The point of the whole exercise: the run is no longer stranded.
        claimed = await claim_collection_finalization(run_id, task_id="barrier-proof")
        assert claimed is True

        async with async_session_factory() as session:
            run = await session.get(PricingRun, run_id)
            assert run is not None
            assert run.status == "calibrating"
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id, user_id)


@pytest.mark.skipif(
    os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_required_mode_provider_budget_bounds_calls_and_still_finalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HIGH 7: ``required`` mode is bounded, and the bound is visible on the row.

    The confirmation ceiling is raised to the cohort size in this mode on
    purpose, so ``pricing_llm_max_provider_calls_per_position`` is the only hard
    bound on the bill.  Spending it must not strand the run: the offers it
    declines still carry an ``INSUFFICIENT_DATA`` decision, which keeps them out
    of the evidence base (``engine.py`` reads it as
    ``MANUAL_LLM_COMPARABILITY_INSUFFICIENT``) while letting the finalizer
    barrier clear.  The ``LLM_PROVIDER_CALL_BUDGET_EXHAUSTED`` stamp is what
    tells an operator these offers were never asked about, rather than judged
    and found wanting.
    """

    workspace_id = uuid4()
    user_id = uuid4()
    provider = _CountingProvider()
    offers = 8
    budget = 3

    monkeypatch.setenv("PRICING_LLM_COMPARABILITY_MODE", "required")
    monkeypatch.setenv("PRICING_LLM_API_KEY", "integration-test-key")
    monkeypatch.setenv("PRICING_LLM_MODEL", "integration-model")
    monkeypatch.setenv("PRICING_LLM_MAX_PROVIDER_CALLS_PER_POSITION", str(budget))
    monkeypatch.setenv("PRICING_LLM_MAX_CONCURRENCY", "2")
    get_settings.cache_clear()

    try:
        run_id, run_item_id, observation_ids = await _seed_wide_cohort(
            workspace_id=workspace_id,
            user_id=user_id,
            offers=offers,
        )

        judged = await ensure_run_item_comparability_reviews(
            run_item_id,
            provider=provider,
        )

        # The bound is hard and exact: a concurrency of 2 against a budget of 3
        # would cost 4 calls if the last wave were not trimmed.
        assert provider.calls == budget
        assert judged == budget

        async with async_session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(CandidateComparabilityReview).where(
                            CandidateComparabilityReview.market_observation_id.in_(
                                observation_ids
                            )
                        )
                    )
                ).all()
            )

        # The barrier's precondition: every observation carries a decision.
        assert {row.market_observation_id for row in rows} == set(observation_ids)

        declined = [row for row in rows if row.status == "SKIPPED"]
        assert len(declined) == offers - budget
        # Fail-closed: a declined offer is never eligible evidence.
        assert all(row.verdict == "INSUFFICIENT_DATA" for row in declined)
        assert all(row.match_level == "NOT_APPLICABLE" for row in declined)
        assert all(row.decision_source == "HARD_RULE" for row in declined)
        assert all(row.cache_hit_review_id is None for row in declined)
        # Visible: the bound names itself, and the API surfaces error_code.
        assert all(
            row.error_code == "LLM_PROVIDER_CALL_BUDGET_EXHAUSTED" for row in declined
        )
        # Not a silent downgrade to shadow: the mode is untouched.
        assert get_settings().pricing_llm_comparability_mode == "required"

        # The calls were spent on the cheapest offers, which is where a decision
        # against the cheapest comparable offer is taken.
        judged_ids = {
            row.market_observation_id for row in rows if row.status != "SKIPPED"
        }
        assert judged_ids == set(observation_ids[:budget])

        # The point of the whole exercise: the run is not stranded.
        claimed = await claim_collection_finalization(
            run_id, task_id="budget-barrier-proof"
        )
        assert claimed is True

        async with async_session_factory() as session:
            run = await session.get(PricingRun, run_id)
            assert run is not None
            assert run.status == "calibrating"
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id, user_id)
