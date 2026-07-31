"""What the reparse writes, and what it refuses to write (WP-6).

The claim being guarded is that running this twice is safe. It is cheap to
believe and expensive to be wrong about: the table is append-only, so a second
run that inserted instead of colliding would double every edge, and the union in
``_confirmed_cross_oems`` would go on widening identities off duplicated
evidence without anything looking broken.

No database is needed to prove which statements a run issues, so a recording
session stands in for one rather than adding a driver for a test's sake — the
same approach ``test_confirmed_cross_oems_union`` takes.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql

from marko.infrastructure.db.models import CatalogItem
from marko.services.catalog_identity_reparse import (
    OWN_EXPORT_SOURCE,
    SourceIndex,
    reparse_workspace_identity,
)
from metis.pricing.identity_graph import load_identity_graph_config

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CONFIG = load_identity_graph_config(BACKEND / "config/identity_graph.yaml")
WORKSPACE = UUID("11111111-1111-1111-1111-111111111111")

EMPTY_INDEX = SourceIndex(by_code={}, shared_articles=frozenset(), loaded_sources=())


class _Rows:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows

    def scalars(self) -> "_Rows":
        return self

    def scalar_one(self):  # pragma: no cover - not exercised here
        return self._rows[0]


class _RecordingSession:
    """Serves the two reads the reparse makes and remembers every write."""

    def __init__(self, items: list[CatalogItem], existing: list[tuple]) -> None:
        self._items = items
        self._existing = existing
        self._item_reads = 0
        self.inserts: list = []
        self.commits = 0

    async def execute(self, statement):
        text = str(statement)
        if text.lstrip().upper().startswith("INSERT"):
            self.inserts.append(statement)
            return _Rows([])
        if "catalog_items" in text:
            self._item_reads += 1
            # One page of rows, then nothing, which is what ends the loop.
            return _Rows(self._items if self._item_reads == 1 else [])
        return _Rows(self._existing)

    async def commit(self) -> None:
        self.commits += 1


def _item(sku: str, part_numbers: list[str], *, oe_norm: str = "") -> CatalogItem:
    return CatalogItem(
        id=uuid4(),
        workspace_id=WORKSPACE,
        sku=sku,
        oe_raw="",
        oe_norm=oe_norm,
        part_numbers_raw=part_numbers,
        source_row=1,
        identity_status="UNRESOLVED",
    )


async def _run(session, *, dry_run: bool = False):
    return await reparse_workspace_identity(
        session,
        workspace_id=WORKSPACE,
        index=EMPTY_INDEX,
        config=CONFIG,
        dry_run=dry_run,
    )


@pytest.mark.asyncio
async def test_a_dry_run_writes_nothing_at_all() -> None:
    item = _item("77641229", ["1K0413031BK", "27C06F"])
    session = _RecordingSession([item], [])

    report = await _run(session, dry_run=True)

    assert session.inserts == []
    assert session.commits == 0
    assert report.dry_run is True
    # And it still says what it would have done, or it is not a preview.
    assert report.links_created == 1
    assert item.identity_status == "UNRESOLVED"


@pytest.mark.asyncio
async def test_a_real_run_upserts_on_the_pair_and_source_constraint() -> None:
    session = _RecordingSession([_item("77641229", ["1K0413031BK", "27C06F"])], [])

    await _run(session)

    assert len(session.inserts) == 1
    # Compiled without literal binds: the JSON columns have no literal renderer,
    # and the clause under test is the conflict target, not the values.
    rendered = str(session.inserts[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT" in rendered.upper()
    assert "uq_catalog_identity_link_pair_source" in rendered
    assert session.commits == 1


@pytest.mark.asyncio
async def test_a_second_run_updates_instead_of_creating() -> None:
    """The whole idempotency claim, in the counter a reviewer reads."""

    item = _item("77641229", ["1K0413031BK", "27C06F"])
    existing = [(item.id, "1K0413031BK", "27C06F", OWN_EXPORT_SOURCE)]
    session = _RecordingSession([item], existing)

    report = await _run(session)

    assert report.links_created == 0
    assert report.links_updated == 1
    assert report.stale_links == 0


@pytest.mark.asyncio
async def test_a_link_the_files_no_longer_produce_is_reported_not_deleted() -> None:
    item = _item("77641229", ["1K0413031BK", "27C06F"])
    existing = [
        (item.id, "1K0413031BK", "27C06F", OWN_EXPORT_SOURCE),
        (item.id, "1K0413031BK", "GONE-FROM-THE-FILES", OWN_EXPORT_SOURCE),
    ]
    session = _RecordingSession([item], existing)

    report = await _run(session)

    assert report.stale_links == 1
    deletes = [
        statement
        for statement in session.inserts
        if str(statement).lstrip().upper().startswith("DELETE")
    ]
    assert deletes == []


@pytest.mark.asyncio
async def test_the_row_keeps_its_imported_oe_and_gains_its_status() -> None:
    item = _item("77641229", ["1K0413031BK", "27C06F"], oe_norm="ALREADYTHERE")
    session = _RecordingSession([item], [])

    report = await _run(session)

    assert item.oe_norm == "ALREADYTHERE"
    assert item.identity_status == "MPN_ONLY"
    assert item.identity_reason == "ONLY_CROSS_LIST_NUMBERS"
    assert report.oe_filled == 0


@pytest.mark.asyncio
async def test_a_row_with_nothing_to_say_produces_no_statement() -> None:
    session = _RecordingSession([_item("77641229", [])], [])

    report = await _run(session)

    assert session.inserts == []
    assert report.items_seen == 1
    assert report.items_with_links == 0
    assert report.identity_status_counts == {"UNRESOLVED": 1}
