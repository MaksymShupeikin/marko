"""Opt-in PostgreSQL proof for catalog-import request idempotency."""

from __future__ import annotations

from io import BytesIO
import os
from uuid import uuid4

from openpyxl import Workbook
import pytest
from sqlalchemy import delete, func, select

from marko.infrastructure.db.models import CatalogImportBatch, CatalogItem, Workspace
from marko.infrastructure.db.session import async_session_factory
from marko.services.xlsx_catalog import import_catalog_xlsx


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

        assert second.id == first.id
        assert first.request_fingerprint == second.request_fingerprint
        assert batches == 1
        assert items == 1
    finally:
        async with async_session_factory() as session:
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await session.commit()
