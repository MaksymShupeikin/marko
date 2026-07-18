from __future__ import annotations

from uuid import uuid4

import pytest

import marko.repositories.stores as stores_repo
from marko.services.dead_letters import list_dead_letters
from marko.services.pricing_runs import (
    RecommendationNotFoundError,
    get_recommendation,
)


class _EmptyResult:
    def one_or_none(self):
        return None

    def all(self):
        return []


class _EmptyScalars:
    def all(self):
        return []


class _RecordingSession:
    def __init__(self) -> None:
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return 0

    async def scalars(self, statement):
        self.statements.append(statement)
        return _EmptyScalars()

    async def execute(self, statement):
        self.statements.append(statement)
        return _EmptyResult()


def _assert_workspace_scoped(statement, workspace_id) -> None:
    compiled = statement.compile()
    assert "workspace_id" in str(compiled)
    assert workspace_id in compiled.params.values()


@pytest.mark.asyncio
async def test_store_lookup_binds_object_and_workspace_together() -> None:
    session = _RecordingSession()
    workspace_id = uuid4()
    store_id = uuid4()

    result = await stores_repo.get_store_by_id(
        session,
        store_id,
        workspace_id,
    )

    assert result is None
    statement = session.statements[-1]
    _assert_workspace_scoped(statement, workspace_id)
    assert store_id in statement.compile().params.values()


@pytest.mark.asyncio
async def test_recommendation_lookup_is_workspace_scoped() -> None:
    session = _RecordingSession()
    workspace_id = uuid4()

    with pytest.raises(RecommendationNotFoundError):
        await get_recommendation(
            session,
            workspace_id=workspace_id,
            recommendation_id=uuid4(),
        )

    _assert_workspace_scoped(session.statements[-1], workspace_id)


@pytest.mark.asyncio
async def test_dead_letter_registry_scopes_every_query_to_workspace() -> None:
    session = _RecordingSession()
    workspace_id = uuid4()

    page = await list_dead_letters(
        session,
        workspace_id=workspace_id,
        limit=25,
        offset=0,
    )

    assert page.total == 0
    assert page.items == []
    assert len(session.statements) == 4
    for statement in session.statements:
        _assert_workspace_scoped(statement, workspace_id)
