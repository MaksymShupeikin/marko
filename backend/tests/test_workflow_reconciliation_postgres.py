from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete

from marko.infrastructure.db.models import (
    CatalogDiscoveryRun,
    CatalogImportBatch,
    MarketplaceStore,
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
