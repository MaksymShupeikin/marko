"""The summary counts must describe the run, not the queue tab in front of it.

Regression proof for a screen that told the operator "0 recommendations, connect
your stores" while eight finished recommendations sat under a different tab: the
aggregate query reused the queue-filtered conditions, so every tile read zero.
"""

from __future__ import annotations

from decimal import Decimal
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, text

from marko.infrastructure.db.models import (
    CatalogImportBatch,
    CatalogItem,
    PricingRecommendation,
    PricingRun,
    PricingRunItem,
    User,
    Workspace,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.pricing_runs import list_recommendations

pytestmark = pytest.mark.postgres

# One of each bucket the tiles show, so a queue filter can never coincidentally
# match the whole population.
_ACTIONS = ("RAISE", "LOWER", "INSUFFICIENT_DATA", "HOLD")


async def _seed_run(*, workspace_id: UUID, user_id: UUID) -> UUID:
    batch_id = uuid4()
    run_id = uuid4()

    async with async_session_factory() as session:
        session.add_all(
            [
                Workspace(
                    id=workspace_id,
                    name="Queue counts regression",
                    slug=f"queue-counts-{workspace_id.hex}",
                ),
                User(
                    id=user_id,
                    email=f"queue-counts-{user_id.hex}@example.test",
                    is_active=True,
                ),
            ]
        )
        await session.flush()
        session.add(
            CatalogImportBatch(
                id=batch_id,
                workspace_id=workspace_id,
                filename="queue-counts.xlsx",
                content_sha256="c" * 64,
                request_fingerprint=uuid4().hex * 2,
                content_size=1,
                status="completed",
                column_mapping={"sku": "SKU"},
                total_rows=len(_ACTIONS),
                imported_rows=len(_ACTIONS),
                rejected_rows=0,
                error_log=[],
            )
        )
        await session.flush()
        session.add(
            PricingRun(
                id=run_id,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                status="completed",
                policy_version="queue-counts-v1",
                policy_config={},
                parser_version="queue-counts-v1",
                total_items=len(_ACTIONS),
            )
        )
        await session.flush()

        for index, action in enumerate(_ACTIONS):
            item_id = uuid4()
            run_item_id = uuid4()
            # RAISE/LOWER are only storable as passed gates carrying a price that
            # actually moves in the direction the action names.
            priced = action in {"RAISE", "LOWER"}
            recommended = {
                "RAISE": Decimal("1100"),
                "LOWER": Decimal("900"),
            }.get(action)
            session.add(
                CatalogItem(
                    id=item_id,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    source_row=index + 2,
                    sku=f"SKU-QUEUE-{index}",
                    oe_raw="1K0 615 301",
                    oe_norm="1K0615301",
                    name=f"Queue counts item {index}",
                    category="brake_pad",
                    brand="KEMP",
                    current_price=Decimal("1000"),
                    currency="UAH",
                    is_available=True,
                    # A priced fixture must carry the same identity contract
                    # as a real admitted run.  ``UNRESOLVED`` is intentionally
                    # excluded from price-bearing recommendation reads.
                    identity_status="OE_CONFIRMED",
                    raw_row={},
                )
            )
            await session.flush()
            session.add(
                PricingRunItem(
                    id=run_item_id,
                    pricing_run_id=run_id,
                    catalog_item_id=item_id,
                    status="calculated",
                    idempotency_key=f"queue-counts:{run_item_id}",
                )
            )
            await session.flush()
            session.add(
                PricingRecommendation(
                    id=uuid4(),
                    pricing_run_id=run_id,
                    pricing_run_item_id=run_item_id,
                    catalog_item_id=item_id,
                    catalog_snapshot_id=batch_id,
                    context_snapshot={},
                    calculation_trace={},
                    action=action,
                    current_price=Decimal("1000"),
                    recommended_price=recommended,
                    absolute_recommended_change=(
                        Decimal("100") if priced else None
                    ),
                    percentage_recommended_change=(
                        Decimal("0.1") if priced else None
                    ),
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
                    action_gates_passed=priced,
                    priority_score=Decimal("0"),
                    priority_score_type="manual_review",
                    review_priority=Decimal("0"),
                    reason_codes=["QUEUE_COUNTS_FIXTURE"],
                    evidence_observation_ids=[],
                    excluded_observations=[],
                    policy_version="queue-counts-v1",
                    parser_version="queue-counts-v1",
                    classifier_version="queue-counts-v1",
                    currency="UAH",
                    price_tick=Decimal("1"),
                    price_tick_version="queue-counts-v1",
                )
            )
            await session.flush()
        await session.commit()
    return run_id


async def _counts(*, workspace_id: UUID, run_id: UUID, queue: str):
    async with async_session_factory() as session:
        rows, total, _resolved, action_counts = await list_recommendations(
            session,
            workspace_id=workspace_id,
            run_id=run_id,
            action=None,
            confidence_grade=None,
            category=None,
            queue=queue,
            priority_score_type=None,
            confidence_min=None,
            confidence_max=None,
            sort="NEWEST",
            limit=50,
            offset=0,
        )
    return rows, total, action_counts


async def _drop_workspace(workspace_id: UUID, user_id: UUID) -> None:
    """Remove the fixture, including its append-only recommendations.

    `pricing_recommendations` is guarded by a trigger so real decisions can never
    be rewritten. Seeded fixtures still have to go, so the guard is lifted for
    the delete and restored in the same transaction, as in the other
    append-only integration tests.
    """

    async with async_session_factory() as session:
        try:
            await session.execute(
                text(
                    "ALTER TABLE pricing_recommendations "
                    "DISABLE TRIGGER trg_pricing_recommendations_append_only"
                )
            )
            await session.execute(
                text(
                    "DELETE FROM pricing_recommendations WHERE pricing_run_id IN "
                    "(SELECT id FROM pricing_runs WHERE workspace_id=:workspace_id)"
                ),
                {"workspace_id": workspace_id},
            )
            # Членство прогона держит позиции каталога внешним ключом
            # RESTRICT (миграция 0033): улику расчёта нельзя снести каскадом от
            # воркспейса. Уборка снимает её явно и в обратном порядке — сама
            # защита при этом не ослабляется.
            await session.execute(
                text(
                    "ALTER TABLE pricing_run_items "
                    "DISABLE TRIGGER trg_pricing_run_items_no_delete"
                )
            )
            await session.execute(
                text(
                    "DELETE FROM pricing_run_items WHERE pricing_run_id IN "
                    "(SELECT id FROM pricing_runs WHERE workspace_id=:workspace_id)"
                ),
                {"workspace_id": workspace_id},
            )
            await session.execute(
                text(
                    "ALTER TABLE pricing_run_items "
                    "ENABLE TRIGGER trg_pricing_run_items_no_delete"
                )
            )
            await session.execute(
                delete(Workspace).where(Workspace.id == workspace_id)
            )
            await session.execute(delete(User).where(User.id == user_id))
            await session.execute(
                text(
                    "ALTER TABLE pricing_recommendations "
                    "ENABLE TRIGGER trg_pricing_recommendations_append_only"
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
async def test_summary_counts_survive_a_queue_filter() -> None:
    workspace_id = uuid4()
    user_id = uuid4()
    run_id = await _seed_run(workspace_id=workspace_id, user_id=user_id)
    try:
        _rows, all_total, all_counts = await _counts(
            workspace_id=workspace_id, run_id=run_id, queue="all"
        )
        assert all_total == len(_ACTIONS)
        assert all_counts == {
            "raise": 1,
            "lower": 1,
            "review": 1,
            "hold": 1,
            "total": len(_ACTIONS),
        }

        # Standing on the "raise" tab must not make the other buckets disappear:
        # the tiles are how the operator learns which tab holds the work.
        raise_rows, raise_total, raise_counts = await _counts(
            workspace_id=workspace_id, run_id=run_id, queue="raise"
        )
        assert len(raise_rows) == 1
        assert raise_total == 1, "paging total must follow the active tab"
        assert raise_counts == all_counts, "tiles must describe the whole run"

        # The bucket the demo run actually lands in.
        review_rows, review_total, review_counts = await _counts(
            workspace_id=workspace_id, run_id=run_id, queue="review"
        )
        assert len(review_rows) == 1
        assert review_total == 1
        assert review_counts == all_counts
    finally:
        await _drop_workspace(workspace_id, user_id)
