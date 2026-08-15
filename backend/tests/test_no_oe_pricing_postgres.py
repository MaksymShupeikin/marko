from __future__ import annotations

from decimal import Decimal
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

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
    NoOePricingError,
    decide_offer,
    offer_snapshot,
    resume_pricing_run,
    review_queue,
)


pytestmark = pytest.mark.postgres


@pytest.mark.skipif(
    os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_human_decisions_are_exact_idempotent_and_resume_is_snapshot_safe() -> (
    None
):
    workspace_id = uuid4()
    async with async_session_factory() as session:
        workspace = Workspace(
            id=workspace_id,
            name="No OE review contract",
            slug=f"no-oe-{workspace_id.hex}",
        )
        session.add(workspace)
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
            sku="SUP-NO-OE-1",
            oe_raw="",
            oe_norm="",
            mpn_raw="MPN-1",
            mpn_norm="MPN1",
            internal_code_raw="776A1",
            internal_code_norm="776A1",
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
            policy_version="no-oe-test-v1",
            policy_config={},
            parser_version="no-oe-test-v1",
            total_items=1,
        )
        session.add(run)
        await session.flush()
        discovery = CatalogDiscoveryRun(
            workspace_id=workspace_id,
            product_key="b" * 64,
            query="MPN1",
            sku="SUP-NO-OE-1",
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
        for position in range(3):
            offer = CatalogDiscoveryOffer(
                discovery_run_id=discovery.id,
                raw_offer_index=position,
                source_listing_id=f"listing-{position}",
                seller_id=f"seller-{position}",
                seller_name=f"Seller {position}",
                title=f"Exact MPN1 offer {position}",
                url=f"https://prom.ua/p12345678{position}-offer.html",
                sku="MPN1",
                brand="Brand",
                sale_price=Decimal(str(90 + position * 10)),
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
                    canonical_input={},
                    canonical_output={},
                )
            )
            offers.append((offer, snapshot_hash))
        await session.commit()

        before = await review_queue(session, workspace_id=workspace_id, run_id=run.id)
        first, first_hash = offers[0]
        decision = await decide_offer(
            session,
            workspace_id=workspace_id,
            run_id=run.id,
            offer_id=first.id,
            decision="APPROVE",
            reason="operator verified exact MPN",
            idempotency_key=f"approve-{first.id}",
            expected_offer_sha256=first_hash,
            actor_id="operator-1",
        )
        duplicate = await decide_offer(
            session,
            workspace_id=workspace_id,
            run_id=run.id,
            offer_id=first.id,
            decision="APPROVE",
            reason="operator verified exact MPN",
            idempotency_key=f"approve-{first.id}",
            expected_offer_sha256=first_hash,
            actor_id="operator-1",
        )
        assert duplicate.id == decision.id

        with pytest.raises(NoOePricingError) as stale:
            await resume_pricing_run(
                session,
                workspace_id=workspace_id,
                run_id=run.id,
                expected_review_snapshot_hash=before["review_snapshot_hash"],
                min_sellers=3,
            )
        assert stale.value.code == "REVIEW_SNAPSHOT_CHANGED"

        for offer, snapshot_hash in offers[1:]:
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
        resumed = await resume_pricing_run(
            session,
            workspace_id=workspace_id,
            run_id=run.id,
            expected_review_snapshot_hash=frozen["review_snapshot_hash"],
            min_sellers=3,
        )
        recommendation = await session.scalar(
            select(PricingRecommendation).where(
                PricingRecommendation.pricing_run_item_id == run_item.id
            )
        )
        decision_count = int(
            await session.scalar(
                select(func.count(PricingDiscoveryDecision.id)).where(
                    PricingDiscoveryDecision.pricing_run_id == run.id
                )
            )
            or 0
        )

        assert resumed.status == "collecting"
        assert recommendation is not None
        assert recommendation.action == "MANUAL_REVIEW"
        assert recommendation.fair_price == Decimal("100.00")
        assert recommendation.recommended_price == Decimal("100.00")
        assert recommendation.automatic_eligible is False
        assert recommendation.unique_seller_count == 3
        assert decision_count == 3
        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "UPDATE pricing_discovery_decisions "
                    "SET reason = 'mutated' WHERE id = :decision_id"
                ),
                {"decision_id": decision.id},
            )
        await session.rollback()
