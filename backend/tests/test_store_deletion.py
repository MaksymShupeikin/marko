from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

import marko.repositories.stores as stores_repo
from marko.api.routers.v1 import stores as stores_router
from marko.infrastructure.db.models import StoreKind
from marko.services import stores as stores_service


class _DeleteResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _RecordingSession:
    def __init__(self, *, rowcount: int = 1) -> None:
        self.rowcount = rowcount
        self.statements = []
        self.commit_count = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return _DeleteResult(self.rowcount)

    async def commit(self) -> None:
        self.commit_count += 1


@pytest.mark.asyncio
async def test_owned_store_delete_is_scoped_to_workspace_and_store() -> None:
    session = _RecordingSession()
    workspace_id = uuid4()
    store_id = uuid4()

    deleted = await stores_repo.delete_owned_workspace_store(
        session,
        store_id=store_id,
        workspace_id=workspace_id,
    )

    assert deleted is True
    compiled = session.statements[0].compile()
    assert workspace_id in compiled.params.values()
    assert store_id in compiled.params.values()
    assert StoreKind.owned in compiled.params.values()


@pytest.mark.asyncio
async def test_delete_owned_store_commits_only_after_a_link_was_deleted() -> None:
    existing = _RecordingSession(rowcount=1)
    await stores_service.delete_owned_store(
        existing,
        store_id=uuid4(),
        workspace_id=uuid4(),
    )
    assert existing.commit_count == 1

    missing = _RecordingSession(rowcount=0)
    with pytest.raises(stores_service.StoreNotFoundError):
        await stores_service.delete_owned_store(
            missing,
            store_id=uuid4(),
            workspace_id=uuid4(),
        )
    assert missing.commit_count == 0


@pytest.mark.asyncio
async def test_delete_store_route_returns_no_content(monkeypatch) -> None:
    workspace_id = uuid4()
    store_id = uuid4()
    session = object()
    captured = {}

    async def fake_delete_owned_store(
        received_session,
        *,
        store_id,
        workspace_id,
    ) -> None:
        captured.update(
            session=received_session,
            store_id=store_id,
            workspace_id=workspace_id,
        )

    monkeypatch.setattr(
        stores_router,
        "delete_owned_store",
        fake_delete_owned_store,
    )

    response = await stores_router.delete_store(
        store_id,
        session,
        SimpleNamespace(workspace_id=workspace_id),
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert response.body == b""
    assert captured == {
        "session": session,
        "store_id": store_id,
        "workspace_id": workspace_id,
    }


@pytest.mark.asyncio
async def test_delete_store_route_maps_missing_owned_store_to_404(monkeypatch) -> None:
    async def fake_delete_owned_store(*_args, **_kwargs) -> None:
        raise stores_service.StoreNotFoundError("missing")

    monkeypatch.setattr(
        stores_router,
        "delete_owned_store",
        fake_delete_owned_store,
    )

    with pytest.raises(HTTPException) as caught:
        await stores_router.delete_store(
            uuid4(),
            object(),
            SimpleNamespace(workspace_id=uuid4()),
        )

    assert caught.value.status_code == status.HTTP_404_NOT_FOUND
    assert caught.value.detail == "Store not found"
