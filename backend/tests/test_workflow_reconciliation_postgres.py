from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete

from marko.infrastructure.db.models import (
    CatalogDiscoveryRun,
    CatalogImportBatch,
    CatalogItem,
    MarketplaceStore,
    PricingRun,
    PricingRunItem,
    StoreSyncTaskExecution,
    SyncRun,
    SyncStatus,
    Workspace,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.workflow_reconciliation import reconcile_stale_workflows


pytestmark = pytest.mark.postgres


@pytest.mark.skipif(
    os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_reconciler_terminalizes_expired_work_and_preserves_partial_counts() -> None:
    now = datetime(2026, 7, 30, 3, 0, tzinfo=UTC)
    workspace_id = uuid4()
    store_id = uuid4()
    sync_run_id = uuid4()
    execution_id = uuid4()
    import_id = uuid4()
    discovery_id = uuid4()
    async with async_session_factory() as session:
        session.add(
            Workspace(
                id=workspace_id,
                name="Stale workflow integration",
                slug=f"stale-{workspace_id.hex}",
            )
        )
        session.add(
            MarketplaceStore(
                id=store_id,
                marketplace="prom",
                external_id=f"stale-{store_id.hex}",
                name="Stale store",
                canonical_url="https://prom.ua/ua/c1-stale.html",
            )
        )
        await session.flush()
        session.add(
            SyncRun(
                id=sync_run_id,
                workspace_id=workspace_id,
                store_id=store_id,
                kind="catalog_import",
                status=SyncStatus.running,
                scrape_state="running",
                scrape_owner_task_id="lost-task",
                scrape_lease_expires_at=now - timedelta(minutes=5),
                scrape_fencing_token=1,
                scrape_task_executions=1,
                scrape_catalog_pages=37,
                scrape_products_persisted=900,
                progress_current=900,
                started_at=now - timedelta(hours=2),
            )
        )
        await session.flush()
        session.add(
            StoreSyncTaskExecution(
                id=execution_id,
                sync_run_id=sync_run_id,
                task_id="lost-task",
                execution_no=1,
                fencing_token=1,
                outcome="running",
                started_at=now - timedelta(hours=2),
            )
        )
        session.add(
            CatalogImportBatch(
                id=import_id,
                workspace_id=workspace_id,
                filename="stale.xlsx",
                content_sha256="a" * 64,
                content_size=10,
                status="running",
                column_mapping={},
                error_log=[],
                started_at=now - timedelta(hours=2),
            )
        )
        session.add(
            CatalogDiscoveryRun(
                id=discovery_id,
                workspace_id=workspace_id,
                product_key="b" * 64,
                query="OE-STALE",
                status="running",
                search_page_limit=1,
                created_at=now - timedelta(hours=2),
            )
        )
        await session.commit()

        report = await reconcile_stale_workflows(
            session,
            now=now,
            stale_after_seconds=3600,
            limit=10,
        )
        session.expire_all()
        sync_run = await session.get(SyncRun, sync_run_id)
        execution = await session.get(StoreSyncTaskExecution, execution_id)
        batch = await session.get(CatalogImportBatch, import_id)
        discovery = await session.get(CatalogDiscoveryRun, discovery_id)

        assert report.sync_runs_failed == 1
        assert report.store_executions_worker_lost == 1
        assert report.catalog_imports_failed == 1
        assert report.catalog_discoveries_failed == 1
        assert sync_run.scrape_state == "failed"
        assert sync_run.scrape_products_persisted == 900
        assert sync_run.scrape_checkpoint["next_page"] == 38
        assert execution.outcome == "worker_lost"
        assert batch.status == "failed"
        assert batch.error_log[-1]["code"] == "WORKER_LOST"
        assert discovery.status == "failed"
        assert discovery.error_code == "WORKER_LOST"

        await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
        await session.execute(
            delete(MarketplaceStore).where(MarketplaceStore.id == store_id)
        )
        await session.commit()


@pytest.mark.skipif(
    os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_reconciler_preserves_old_pricing_run_with_recent_child_activity() -> None:
    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    old = now - timedelta(hours=2)
    workspace_id = uuid4()
    stale_batch_id = uuid4()
    active_batch_id = uuid4()
    stale_run_id = uuid4()
    active_run_id = uuid4()
    stale_item_id = uuid4()
    active_item_id = uuid4()
    stale_run_item_id = uuid4()
    active_run_item_id = uuid4()

    async with async_session_factory() as session:
        session.add(
            Workspace(
                id=workspace_id,
                name="Pricing activity reconciliation",
                slug=f"pricing-activity-{workspace_id.hex}",
            )
        )
        await session.flush()

        for batch_id, suffix in (
            (stale_batch_id, "stale"),
            (active_batch_id, "active"),
        ):
            session.add(
                CatalogImportBatch(
                    id=batch_id,
                    workspace_id=workspace_id,
                    filename=f"{suffix}.xlsx",
                    content_sha256=("c" if suffix == "stale" else "d") * 64,
                    content_size=1,
                    status="completed",
                    column_mapping={"sku": "SKU"},
                    total_rows=1,
                    imported_rows=1,
                    error_log=[],
                )
            )
        await session.flush()

        for item_id, batch_id, suffix in (
            (stale_item_id, stale_batch_id, "STALE"),
            (active_item_id, active_batch_id, "ACTIVE"),
        ):
            session.add(
                CatalogItem(
                    id=item_id,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    source_row=2,
                    sku=f"SKU-{suffix}",
                    oe_raw="",
                    oe_norm="",
                    name=f"Pricing {suffix.lower()} item",
                    category="test",
                    current_price=Decimal("100"),
                    currency="UAH",
                    is_available=True,
                    raw_row={},
                )
            )
        await session.flush()

        for run_id, batch_id in (
            (stale_run_id, stale_batch_id),
            (active_run_id, active_batch_id),
        ):
            session.add(
                PricingRun(
                    id=run_id,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    status="collecting",
                    policy_version="reconciliation-test-v1",
                    policy_config={},
                    parser_version="reconciliation-test-v1",
                    total_items=1,
                    started_at=old,
                    created_at=old,
                    updated_at=old,
                )
            )
        await session.flush()

        session.add_all(
            [
                PricingRunItem(
                    id=stale_run_item_id,
                    pricing_run_id=stale_run_id,
                    catalog_item_id=stale_item_id,
                    status="collecting",
                    idempotency_key=f"reconcile:{stale_run_item_id}",
                    started_at=old,
                    created_at=old,
                    updated_at=old,
                ),
                PricingRunItem(
                    id=active_run_item_id,
                    pricing_run_id=active_run_id,
                    catalog_item_id=active_item_id,
                    status="collecting",
                    idempotency_key=f"reconcile:{active_run_item_id}",
                    started_at=old,
                    created_at=old,
                    updated_at=now - timedelta(minutes=5),
                ),
            ]
        )
        await session.commit()

        report = await reconcile_stale_workflows(
            session,
            now=now,
            stale_after_seconds=3600,
            limit=10,
        )
        session.expire_all()
        stale_run = await session.get(PricingRun, stale_run_id)
        active_run = await session.get(PricingRun, active_run_id)
        stale_item = await session.get(PricingRunItem, stale_run_item_id)
        active_item = await session.get(PricingRunItem, active_run_item_id)

        assert report.pricing_runs_failed == 1
        assert report.pricing_items_failed == 1
        assert stale_run.status == "failed"
        assert stale_item.status == "failed"
        assert active_run.status == "collecting"
        assert active_item.status == "collecting"

        # PricingRunItem intentionally RESTRICTs direct CatalogItem deletion;
        # remove the run first so its CASCADE can clear immutable membership.
        await session.execute(
            delete(PricingRun).where(PricingRun.workspace_id == workspace_id)
        )
        await session.flush()
        await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
        await session.commit()
