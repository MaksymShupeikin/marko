"""Opt-in PostgreSQL integration coverage for store registration and outbox identity."""

from __future__ import annotations

import os
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from marko.api import main as api_main
from marko.api.dependencies import get_current_user
from marko.api.routers.v1 import stores as stores_router
from marko.infrastructure.db.models import (
    ScrapeDispatchOutbox,
    SyncRun,
    User,
    Workspace,
    WorkspaceRole,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services import stores as stores_service
from marko.services.auth import AuthContext


pytestmark = pytest.mark.postgres


@pytest.mark.skipif(
    os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_post_store_uses_one_non_null_sync_identity(monkeypatch) -> None:
    workspace_id = uuid4()
    workspace_slug = f"store-sync-test-{workspace_id.hex}"
    async with async_session_factory() as session:
        session.add(
            Workspace(
                id=workspace_id,
                name="Store sync integration test",
                slug=workspace_slug,
            )
        )
        await session.commit()

    auth = AuthContext(
        user=User(
            id=uuid4(),
            email=f"store-sync-{workspace_id.hex}@example.com",
            is_active=True,
        ),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.owner,
    )
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())
    monkeypatch.setattr(
        stores_service,
        "require_live_prom_marketplace_collection",
        lambda: None,
    )
    monkeypatch.setattr(stores_router, "celery_app", fake_celery)

    application = api_main.create_app()

    async def current_user_override() -> AuthContext:
        return auth

    application.dependency_overrides[get_current_user] = current_user_override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            first = await client.post(
                "/api/v1/stores",
                json={"url": "https://prom.ua/ua/c2257594-pilot-avto.html"},
            )
            second = await client.post(
                "/api/v1/stores",
                json={"url": "https://prom.ua/ua/c2257594-pilot-avto.html"},
            )

        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        first_body = first.json()
        second_body = second.json()
        assert first_body["sync_run_id"]
        assert second_body["sync_run_id"] == first_body["sync_run_id"]

        sync_run_id = first_body["sync_run_id"]
        sync_run_uuid = UUID(sync_run_id)
        async with async_session_factory() as session:
            sync_run = await session.get(SyncRun, sync_run_uuid)
            outbox = await session.scalar(
                select(ScrapeDispatchOutbox).where(
                    ScrapeDispatchOutbox.aggregate_id == sync_run_uuid
                )
            )
            assert sync_run is not None
            assert outbox is not None
            assert str(outbox.aggregate_id) == sync_run_id
            assert outbox.event_key == f"store-sync:{sync_run_id}:start:v1"
            assert outbox.task_args == [sync_run_id]
            assert sync_run.scrape_deduplicated_submissions == 1
        assert fake_celery.send_task.call_count == 1
    finally:
        application.dependency_overrides.clear()
        async with async_session_factory() as session:
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await session.commit()
