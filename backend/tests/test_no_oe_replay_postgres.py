"""Replay must verify the lane the customer is actually priced on.

The OE lane has carried a replay contract since v1. The no-OE lane — the one
that produces a price when the customer has no OE number, and the reason the
product needs an LLM at all — wrote a calculation trace without one, so
«Проверить replay» answered «нет поддерживаемого контракта» for exactly the
recommendations the owner shows a buyer.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from marko.infrastructure.db.models import (
    CatalogDiscoveryOffer,
    CatalogDiscoveryRun,
    CatalogImportBatch,
    CatalogItem,
    PricingDiscoveryDecision,
    PricingDiscoveryReview,
    PricingRecommendation,
    PricingRun,
    PricingRunItem,
    Workspace,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.decision_fingerprint import canonical_sha256
from marko.services.no_oe_pricing import (
    NO_OE_REPLAY_CONTRACT_V1,
    decide_offer,
    offer_snapshot,
    resume_pricing_run,
    review_queue,
)
from marko.services.recommendation_replay import (
    RecommendationReplayUnavailable,
    _replay_no_oe,
    replay_recommendation,
)


pytestmark = pytest.mark.postgres


async def _seed_priced_no_oe_run(session, workspace_id: UUID):
    """Drive one item through the customer's own path to a published price."""

    session.add(
        Workspace(
            id=workspace_id,
            name="No OE replay",
            slug=f"no-oe-replay-{workspace_id.hex}",
        )
    )
    await session.flush()
    batch = CatalogImportBatch(
        workspace_id=workspace_id,
        filename="no-oe.xlsx",
        content_sha256="a" * 64,
        request_fingerprint=uuid4().hex * 2,
        content_size=1,
        status="completed",
        column_mapping={},
        total_rows=1,
        imported_rows=1,
        rejected_rows=0,
        error_log=[],
        row_outcomes=[],
    )
    session.add(batch)
    await session.flush()
    item = CatalogItem(
        workspace_id=workspace_id,
        import_batch_id=batch.id,
        source_row=2,
        sku="SUP-NO-OE-REPLAY",
        oe_raw="",
        oe_norm="",
        mpn_raw="MPN-9",
        mpn_norm="MPN9",
        internal_code_raw="776B2",
        internal_code_norm="776B2",
        name="No OE product",
        category="Filters",
        current_price=Decimal("100.00"),
        currency="UAH",
        stock_status="fresh",
        raw_row={},
        identity_status="MPN_ONLY",
        identity_reason="CUSTOMER_MPN_COLUMN",
    )
    session.add(item)
    await session.flush()
    run = PricingRun(
        workspace_id=workspace_id,
        import_batch_id=batch.id,
        status="awaiting_review",
        policy_version="no-oe-replay-v1",
        policy_config={},
        parser_version="no-oe-replay-v1",
        total_items=1,
    )
    session.add(run)
    await session.flush()
    discovery = CatalogDiscoveryRun(
        workspace_id=workspace_id,
        product_key="b" * 64,
        query="MPN9",
        sku=item.sku,
        reference_title=item.name,
        reference_currency="UAH",
        status="completed",
        search_page_limit=1,
    )
    session.add(discovery)
    await session.flush()
    run_item = PricingRunItem(
        pricing_run_id=run.id,
        catalog_item_id=item.id,
        no_oe_discovery_run_id=discovery.id,
        status="awaiting_discovery_review",
        idempotency_key=f"no-oe:{run.id}:{item.id}",
        start_snapshot={
            "sku": item.sku,
            "name": item.name,
            "category": item.category,
            "current_price": "100.00",
            "currency": "UAH",
            "identity_status": "MPN_ONLY",
        },
        membership_position=0,
    )
    session.add(run_item)
    await session.flush()

    offers = []
    # Четвёртое предложение остаётся НЕ одобренным: оно нужно проверке сноса,
    # чтобы было чем подменить доказательную базу задним числом.
    for position in range(4):
        offer = CatalogDiscoveryOffer(
            discovery_run_id=discovery.id,
            raw_offer_index=position,
            source_listing_id=f"listing-{position}",
            seller_id=f"seller-{position}",
            seller_name=f"Seller {position}",
            title=f"Exact MPN9 offer {position}",
            url=f"https://prom.ua/p87654321{position}-offer.html",
            sku="MPN9",
            brand="Brand",
            sale_price=Decimal(str(90 + position * 10))
            if position < 3
            else Decimal("60"),
            currency="UAH",
            measure_unit="piece",
            is_available=True,
            is_owned=False,
            title_contains_query=True,
            identity_status="QUERY_TOKEN_PRESENT",
            source_confidence=Decimal("1"),
            reason_codes=[],
            selection_status="REFERENCE_ONLY",
            selection_reason="DISCOVERY_ONLY_NOT_PRICING_EVIDENCE",
            passed_gates=[],
            selection_flags=[],
            selection_details={},
            predicted_tier="unknown",
            tier_confidence=Decimal("0"),
            raw_snapshot={"id": f"listing-{position}"},
        )
        session.add(offer)
        await session.flush()
        snapshot_hash = canonical_sha256(offer_snapshot(offer))
        session.add(
            PricingDiscoveryReview(
                workspace_id=workspace_id,
                pricing_run_id=run.id,
                pricing_run_item_id=run_item.id,
                catalog_discovery_offer_id=offer.id,
                verdict="MATCH",
                rationale="Exact public MPN and no deterministic conflict",
                evidence_references=[],
                conflicts=[],
                offer_sha256=snapshot_hash,
                prompt_sha256="c" * 64,
                schema_sha256="d" * 64,
                model_sha256="e" * 64,
                input_sha256="f" * 64,
                output_sha256="1" * 64,
                provider="codex_cli",
                model="gpt-5.6-luna",
                reasoning_effort="xhigh",
                canonical_input={
                    "deterministic_context": {
                        # Без пройденной проверки суммы одобрение не проходит
                        # шлюз — предложение с подозрительной ценой в цену не
                        # попадает. Здесь она пройдена намеренно: проверяется
                        # повтор расчёта, а не сам шлюз.
                        "offer_integrity_context": {
                            "assessment": {
                                "status": "PASS",
                                "reason_codes": ["OFFER_INTEGRITY_PASS"],
                                "evidence": [],
                            }
                        }
                    }
                },
                canonical_output={},
            )
        )
        offers.append((offer, snapshot_hash))
    await session.commit()

    for offer, snapshot_hash in offers[:3]:
        await decide_offer(
            session,
            workspace_id=workspace_id,
            run_id=run.id,
            offer_id=offer.id,
            decision="APPROVE",
            reason="operator verified exact MPN",
            idempotency_key=f"approve-{offer.id}",
            expected_offer_sha256=snapshot_hash,
            actor_id="operator-1",
        )
    frozen = await review_queue(session, workspace_id=workspace_id, run_id=run.id)
    await resume_pricing_run(
        session,
        workspace_id=workspace_id,
        run_id=run.id,
        expected_review_snapshot_hash=frozen["review_snapshot_hash"],
        min_sellers=2,
    )
    return run.id, run_item.id, offers


@pytest.mark.skipif(
    os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_no_oe_price_replays_exactly_and_reports_planted_evidence() -> None:
    workspace_id = uuid4()
    async with async_session_factory() as session:
        run_id, run_item_id, offers = await _seed_priced_no_oe_run(
            session, workspace_id
        )
        recommendation = await session.scalar(
            select(PricingRecommendation).where(
                PricingRecommendation.pricing_run_item_id == run_item_id
            )
        )
        assert recommendation is not None
        assert recommendation.fair_price == Decimal("90.00")
        assert recommendation.recommended_price == Decimal("85.50")

        replay = await replay_recommendation(
            session,
            workspace_id=workspace_id,
            recommendation_id=recommendation.id,
        )
        assert replay.replay_contract_version == NO_OE_REPLAY_CONTRACT_V1
        assert replay.exact_match is True
        assert replay.mismatches == {}
        assert replay.replayed["recommended_price"] == "85.50"
        assert replay.replayed["unique_seller_count"] == 3
        # Порог хранится в следе, а не читается из окружения: смена настройки
        # развёртывания не должна переписывать историю расчёта.
        assert replay.replayed["min_independent_sellers"] == 2

        # Сама рекомендация переписыванию не поддаётся — таблица append-only, —
        # поэтому подменять надо доказательную базу: подложить задним числом
        # одобрение более дешёвого предложения. Повтор считает цену заново из
        # решений оператора, поэтому подлог обязан всплыть.
        planted_offer, planted_hash = offers[3]
        review_id = await session.scalar(
            select(PricingDiscoveryReview.id).where(
                PricingDiscoveryReview.catalog_discovery_offer_id == planted_offer.id
            )
        )
        session.add(
            PricingDiscoveryDecision(
                workspace_id=workspace_id,
                pricing_run_id=run_id,
                pricing_run_item_id=run_item_id,
                catalog_discovery_offer_id=planted_offer.id,
                luna_review_id=review_id,
                decision="APPROVE",
                actor_id="intruder",
                actor_type="user",
                reason="planted after the price was published",
                idempotency_key=f"planted-{planted_offer.id}",
                offer_sha256=planted_hash,
                price=Decimal("60.00"),
                currency="UAH",
                measure_unit="piece",
                is_available=True,
                seller_id=planted_offer.seller_id,
                offer_snapshot={},
                created_at=datetime.fromisoformat(
                    recommendation.calculation_trace["calculated_at"]
                ),
            )
        )
        await session.commit()

        drifted = await replay_recommendation(
            session,
            workspace_id=workspace_id,
            recommendation_id=recommendation.id,
        )
        assert drifted.exact_match is False
        assert drifted.mismatches["fair_price"] == {
            "stored": "90.00",
            "replayed": "60.00",
        }
        assert drifted.mismatches["recommended_price"] == {
            "stored": "85.50",
            "replayed": "57.00",
        }
        assert "decision_fingerprint" in drifted.mismatches


@pytest.mark.skipif(
    os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_no_oe_recommendation_without_the_threshold_is_not_replayable() -> None:
    """Прежние рекомендации не «чинятся» задним числом.

    Проставить порог продавцов в старый след означало бы объявить повтором
    сверку с числом, которого при расчёте могло не быть: настройка уже менялась
    на живом проекте. Такая запись честно остаётся непроверяемой.
    """

    workspace_id = uuid4()
    async with async_session_factory() as session:
        _, run_item_id, _ = await _seed_priced_no_oe_run(session, workspace_id)
        recommendation = await session.scalar(
            select(PricingRecommendation).where(
                PricingRecommendation.pricing_run_item_id == run_item_id
            )
        )
        assert recommendation is not None
        legacy_trace = {
            key: value
            for key, value in recommendation.calculation_trace.items()
            if key != "min_independent_sellers"
        }
        with pytest.raises(RecommendationReplayUnavailable) as unavailable:
            await _replay_no_oe(
                session,
                recommendation=recommendation,
                trace=legacy_trace,
            )
        assert "independent-seller threshold" in str(unavailable.value)
