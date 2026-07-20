from uuid import uuid4

import pytest

from marko.infrastructure.db.models import SyncStatus
from marko.repositories.stores import create_sync_run


class _IdentityAssigningSession:
    def __init__(self) -> None:
        self.added = []
        self.flush_count = 0

    def add(self, value) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_count += 1
        for value in self.added:
            if value.id is None:
                value.id = uuid4()


@pytest.mark.asyncio
async def test_create_sync_run_returns_stable_identity_before_outbox_use() -> None:
    session = _IdentityAssigningSession()

    sync_run = await create_sync_run(
        session,
        workspace_id=uuid4(),
        store_id=uuid4(),
        kind="catalog_import",
        status=SyncStatus.queued,
    )

    assert sync_run.id is not None
    assert session.flush_count == 1
