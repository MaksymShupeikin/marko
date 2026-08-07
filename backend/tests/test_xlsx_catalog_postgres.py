"""Opt-in PostgreSQL proof for catalog-import request idempotency."""

from __future__ import annotations

from io import BytesIO
import os
from uuid import uuid4

from openpyxl import Workbook
import pytest
from sqlalchemy import delete, func, select

from marko.infrastructure.db.models import (
    CatalogImportBatch,
    CatalogItem,
    PricingRun,
    PricingRunItem,
    Workspace,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.xlsx_catalog import (
    build_catalog_terminal_manifest,
    import_catalog_xlsx,
)


pytestmark = pytest.mark.postgres


def _workbook_bytes() -> bytes:
    stream = BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Export Products Sheet"
    sheet.append(["SKU", "OE", "Name", "Category", "Price"])
    sheet.append(["S-1", "OE-1", "Part", "Filters", 100])
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


@pytest.mark.skipif(
    os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_identical_catalog_import_reuses_batch_and_items() -> None:
    workspace_id = uuid4()
    content = _workbook_bytes()
    async with async_session_factory() as session:
        session.add(
            Workspace(
                id=workspace_id,
                name="Catalog import idempotency",
                slug=f"catalog-import-{workspace_id.hex}",
            )
        )
        await session.commit()

    try:
        async with async_session_factory() as session:
            first = await import_catalog_xlsx(
                session,
                workspace_id=workspace_id,
                user_id=uuid4(),
                filename="catalog.xlsx",
                content=content,
                sheet_name="Export Products Sheet",
            )
            second = await import_catalog_xlsx(
                session,
                workspace_id=workspace_id,
                user_id=uuid4(),
                filename="renamed.xlsx",
                content=content,
                sheet_name="Export Products Sheet",
                explicit_mapping={
                    "sku": "SKU",
                    "oe": "OE",
                    "name": "Name",
                    "category": "Category",
                    "price": "Price",
                },
            )
            batches = int(
                await session.scalar(
                    select(func.count(CatalogImportBatch.id)).where(
                        CatalogImportBatch.workspace_id == workspace_id
                    )
                )
                or 0
            )
            items = int(
                await session.scalar(
                    select(func.count(CatalogItem.id)).where(
                        CatalogItem.workspace_id == workspace_id
                    )
                )
                or 0
            )
            item = await session.scalar(
                select(CatalogItem).where(CatalogItem.import_batch_id == first.id)
            )
            assert item is not None
            run = PricingRun(
                workspace_id=workspace_id,
                import_batch_id=first.id,
                status="failed",
                policy_version="catalog-terminal-manifest-test-v1",
                policy_config={},
                parser_version="catalog-terminal-manifest-test-v1",
                total_items=1,
                failed_items=1,
            )
            session.add(run)
            await session.flush()
            run_item = PricingRunItem(
                pricing_run_id=run.id,
                catalog_item_id=item.id,
                status="failed",
                idempotency_key=f"catalog-terminal-manifest:{run.id}:{item.id}",
                error="terminal fixture failure",
            )
            session.add(run_item)
            await session.commit()
            manifest = await build_catalog_terminal_manifest(
                session,
                workspace_id=workspace_id,
                batch_id=first.id,
            )
            replay_manifest = await build_catalog_terminal_manifest(
                session,
                workspace_id=workspace_id,
                batch_id=first.id,
                run_id=run.id,
            )
            run.status = "completed"
            run_item.status = "calculated"
            run_item.error = None
            await session.commit()
            incomplete_replay_manifest = await build_catalog_terminal_manifest(
                session,
                workspace_id=workspace_id,
                batch_id=first.id,
                run_id=run.id,
            )
            wrong_run = await build_catalog_terminal_manifest(
                session,
                workspace_id=workspace_id,
                batch_id=first.id,
                run_id=uuid4(),
            )
            wrong_tenant = await build_catalog_terminal_manifest(
                session,
                workspace_id=uuid4(),
                batch_id=first.id,
            )

        assert second.id == first.id
        assert first.request_fingerprint == second.request_fingerprint
        assert batches == 1
        assert items == 1
        assert manifest is not None
        assert manifest["verification_status"] == "VERIFIED"
        assert manifest["hash_verified"] is True
        assert manifest["silent_loss_count"] == 0
        assert manifest["rows"][0]["source_ordinal"] == 1
        assert manifest["rows"][0]["source_row"] == 2
        assert manifest["rows"][0]["terminal_status"] == "IMPORTED"
        assert replay_manifest is not None
        assert replay_manifest["manifest_version"] == (
            "catalog-pricing-replay-terminal-manifest-v2"
        )
        assert replay_manifest["pricing_run_id"] == run.id
        assert replay_manifest["pricing_replay_complete"] is True
        assert replay_manifest["pricing_terminal_rows"] == 1
        assert replay_manifest["pricing_missing_run_items"] == 0
        assert replay_manifest["rows"][0]["pricing_terminal_status"] == "FAILED"
        assert replay_manifest["rows"][0]["pricing_terminal_reason"] == (
            "RUN_ITEM_TERMINAL_FAILURE"
        )
        assert replay_manifest["rows"][0]["pricing_run_item_id"] == str(run_item.id)
        assert replay_manifest["replay_manifest_sha256"]
        assert incomplete_replay_manifest is not None
        assert incomplete_replay_manifest["pricing_replay_complete"] is False
        assert incomplete_replay_manifest["pricing_nonterminal_rows"] == 1
        assert incomplete_replay_manifest["rows"][0]["pricing_terminal_reason"] == (
            "RECOMMENDATION_MISSING"
        )
        assert wrong_run is None
        assert wrong_tenant is None
    finally:
        async with async_session_factory() as session:
            await session.execute(
                delete(PricingRun).where(PricingRun.workspace_id == workspace_id)
            )
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await session.commit()
