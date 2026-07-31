"""Populated rollback proof for the reviewed catalog identity migration."""

from __future__ import annotations

from decimal import Decimal
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from sqlalchemy import text

from marko.infrastructure.db.models import CatalogImportBatch, CatalogItem, Workspace
from marko.infrastructure.db.session import async_session_factory


pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        os.getenv("MARKO_RUN_MIGRATION_GUARD") != "1",
        reason="set MARKO_RUN_MIGRATION_GUARD=1 on a disposable migration database",
    ),
]


def _assert_disposable_database() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    database_name = urlparse(database_url.replace("+asyncpg", "")).path.rsplit("/", 1)[-1]
    assert "migration_guard" in database_name, (
        "identity migration guard must run on a database whose name contains "
        "'migration_guard'"
    )


@pytest.mark.asyncio
async def test_0025_downgrade_refuses_to_erase_reviewed_identity() -> None:
    _assert_disposable_database()
    workspace_id = uuid4()
    batch_id = uuid4()
    item_id = uuid4()
    async with async_session_factory() as session:
        session.add(
            Workspace(
                id=workspace_id,
                name="Migration guard",
                slug=f"migration-guard-{workspace_id.hex}",
            )
        )
        await session.flush()
        session.add(
            CatalogImportBatch(
                id=batch_id,
                workspace_id=workspace_id,
                filename="migration-guard.xlsx",
                content_sha256="f" * 64,
                content_size=1,
                status="completed",
                column_mapping={"article": "sku"},
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
                sku="REVIEWED-MPN",
                oe_raw="",
                oe_norm="",
                mpn_raw="REVIEWED-MPN",
                mpn_norm="REVIEWEDMPN",
                identity_status="MPN_ONLY",
                identity_reason="BRAND_IS_AFTERMARKET",
                name="Reviewed supplier article",
                category="test",
                brand="KEMP",
                current_price=Decimal("100"),
                currency="UAH",
                is_available=True,
                raw_row={},
            )
        )
        await session.commit()

    backend_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "alembic.ini",
            "downgrade",
            "20260728_0024",
        ],
        cwd=backend_root,
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode != 0, completed.stdout
    assert "IRREVERSIBLE_MIGRATION_20260729_0025" in completed.stdout

    async with async_session_factory() as session:
        retained = (
            await session.execute(
                text(
                    "SELECT identity_status, identity_reason "
                    "FROM catalog_items WHERE id = :item_id"
                ),
                {"item_id": item_id},
            )
        ).one()
    assert retained == ("MPN_ONLY", "BRAND_IS_AFTERMARKET")
