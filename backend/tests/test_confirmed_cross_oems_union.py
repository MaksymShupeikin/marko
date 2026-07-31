"""Both link tables are read when widening an OE identity (WP-3).

The failure this guards against is silent and expensive: WP-3 adds a second
table of links, and if a reader keeps querying only ``cross_links`` the whole
graph exists in the database and changes nothing.  Nobody would see an error —
candidates would simply keep failing the gate for want of a cross.

No database is needed to prove which tables a query names, so a recording
session stands in for one rather than adding an sqlite driver to the project
for a test's sake.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from marko.services.catalog_discovery import (
    _confirmed_cross_oems as discovery_confirmed_cross_oems,
)
from marko.services.catalog_search import (
    _confirmed_cross_oems as search_confirmed_cross_oems,
)


class _EmptyResult:
    def all(self):
        return []


class _RecordingSession:
    """Answers every query with nothing and remembers what was asked."""

    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _EmptyResult()

    def rendered(self) -> list[str]:
        return [
            str(statement.compile(compile_kwargs={"literal_binds": True}))
            for statement in self.statements
        ]


@pytest.mark.asyncio
async def test_discovery_reads_both_link_tables() -> None:
    session = _RecordingSession()

    result = await discovery_confirmed_cross_oems(
        session, workspace_id=uuid4(), reference_oem="1K0413031BK"
    )

    tables = " ".join(session.rendered())
    assert "cross_links" in tables
    assert "catalog_identity_links" in tables
    assert result == frozenset()


@pytest.mark.asyncio
async def test_search_reads_both_link_tables() -> None:
    session = _RecordingSession()

    await search_confirmed_cross_oems(
        session, workspace_id=uuid4(), reference="1K0413031BK"
    )

    tables = " ".join(session.rendered())
    assert "cross_links" in tables
    assert "catalog_identity_links" in tables


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        lambda session: discovery_confirmed_cross_oems(
            session, workspace_id=uuid4(), reference_oem="1K0413031BK"
        ),
        lambda session: search_confirmed_cross_oems(
            session, workspace_id=uuid4(), reference="1K0413031BK"
        ),
    ],
)
async def test_every_query_filters_on_confirmed(call) -> None:
    """A REVIEW link must never widen an identity: every kemp.ua link no second
    source corroborated is REVIEW, as is every link carrying an anomaly."""

    session = _RecordingSession()

    await call(session)

    rendered = session.rendered()
    assert len(rendered) == 2
    for statement in rendered:
        assert "'CONFIRMED'" in statement
        assert "'REVIEW'" not in statement


@pytest.mark.asyncio
async def test_an_empty_reference_asks_the_database_nothing() -> None:
    session = _RecordingSession()

    result = await discovery_confirmed_cross_oems(
        session, workspace_id=uuid4(), reference_oem="   "
    )

    assert result == frozenset()
    assert session.statements == []
