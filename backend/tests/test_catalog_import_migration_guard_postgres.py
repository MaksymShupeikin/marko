"""Populated rollback proof for catalog-import idempotency fingerprints."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from sqlalchemy import text

from marko.infrastructure.db.models import CatalogImportBatch, Workspace
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
        "catalog-import migration guard must run on a database whose name "
        "contains 'migration_guard'"
    )


@pytest.mark.asyncio
async def test_0029_downgrade_refuses_to_erase_request_fingerprints() -> None:
    _assert_disposable_database()
    workspace_id = uuid4()
    batch_id = uuid4()
    fingerprint = "a" * 64
    async with async_session_factory() as session:
        session.add(
            Workspace(
                id=workspace_id,
                name="Catalog import migration guard",
                slug=f"catalog-import-migration-guard-{workspace_id.hex}",
            )
        )
        await session.flush()
        session.add(
            CatalogImportBatch(
                id=batch_id,
                workspace_id=workspace_id,
                filename="migration-guard.xlsx",
                content_sha256="f" * 64,
                request_fingerprint=fingerprint,
                content_size=1,
                status="completed",
                column_mapping={"sku": "SKU"},
                total_rows=0,
                imported_rows=0,
                rejected_rows=0,
                error_log=[],
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
            "20260730_0028",
        ],
        cwd=backend_root,
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode != 0, completed.stdout
    assert "IRREVERSIBLE_MIGRATION_20260730_0029" in completed.stdout

    async with async_session_factory() as session:
        retained = await session.scalar(
            text(
                "SELECT request_fingerprint "
                "FROM catalog_import_batches WHERE id = :batch_id"
            ),
            {"batch_id": batch_id},
        )
    assert retained == fingerprint
