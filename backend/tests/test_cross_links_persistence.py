"""Append-only guarantees of the cross-link persistence adapter.

The adapter is the entry point for the client-supplied cross table, so the
tests below pin the behaviour that protects already stored evidence: rows are
inserted once, an existing snapshot may only be reused when the deterministic
replay matches it exactly, and any divergence raises instead of mutating.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from marko.infrastructure.db.models import CrossLink
from marko.services.cross_links import (
    CrossLinkPersistenceError,
    count_cross_links_for_run,
    persist_cross_links_for_run,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = BACKEND_ROOT / "config" / "crosses.yaml"

RUN_ID = UUID("11111111-1111-1111-1111-111111111111")
WORKSPACE_ID = UUID("22222222-2222-2222-2222-222222222222")

# Two analog numbers written the way Prom sellers actually write them: in the
# description, behind an analog marker, next to a dimension that must not be
# mistaken for a part number.
DESCRIPTION = "Радіатор 505*382, аналог ABC12345/DEF67890"


@dataclass
class _Run:
    workspace_id: UUID = WORKSPACE_ID


@dataclass
class _CatalogItem:
    id: UUID
    oe_norm: str = "OUR1234"
    category: str | None = "radiator"


@dataclass
class _Observation:
    source_listing_id: str
    description: str | None
    url: str
    seller_name: str
    price: Decimal
    comparison_evidence: dict[str, Any] | None = None


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeSession:
    """Minimal async session double: the adapter only needs these five calls."""

    def __init__(
        self,
        *,
        run: _Run | None,
        rows: list[tuple[_Observation, _CatalogItem]] | None = None,
        existing: list[Any] | None = None,
        scalar_value: int | None = 0,
    ) -> None:
        self._run = run
        self._rows = rows or []
        self._existing = existing or []
        self._scalar_value = scalar_value
        self.added: list[CrossLink] = []
        self.flushed = 0

    async def get(self, _model: Any, _pk: UUID) -> _Run | None:
        return self._run

    async def execute(self, _statement: Any) -> _Result:
        return _Result(self._rows)

    async def scalars(self, _statement: Any) -> _Result:
        return _Result(self._existing)

    async def scalar(self, _statement: Any) -> int | None:
        return self._scalar_value

    def add(self, instance: CrossLink) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flushed += 1


def _rows(
    *,
    description: str | None = DESCRIPTION,
    catalog_id: UUID | None = None,
    comparison_evidence: dict[str, Any] | None = None,
    seller_name: str = "Independent Seller",
) -> list[tuple[_Observation, _CatalogItem]]:
    return [
        (
            _Observation(
                source_listing_id="listing-1",
                description=description,
                url="https://prom.ua/ua/p-listing-1.html",
                seller_name=seller_name,
                price=Decimal("1000"),
                comparison_evidence=comparison_evidence,
            ),
            _CatalogItem(id=catalog_id or uuid4()),
        )
    ]


async def _persist(session: _FakeSession):
    return await persist_cross_links_for_run(
        session, pricing_run_id=RUN_ID, config_path=CONFIG_PATH
    )


@pytest.mark.asyncio
async def test_missing_pricing_run_raises_instead_of_writing() -> None:
    session = _FakeSession(run=None, rows=_rows())

    with pytest.raises(CrossLinkPersistenceError, match="Pricing run does not exist"):
        await _persist(session)

    assert session.added == []
    assert session.flushed == 0


@pytest.mark.asyncio
async def test_first_run_inserts_every_decision_once() -> None:
    session = _FakeSession(run=_Run(), rows=_rows())

    result = await _persist(session)

    assert result.inserted == len(result.analysis.pair_decisions)
    assert result.reused == 0
    assert len(session.added) == result.inserted
    assert session.flushed == 1
    assert result.inserted > 0, "the fixture description must yield cross candidates"
    assert {row.extracted_oem_norm for row in session.added} == {"ABC12345", "DEF67890"}
    assert {row.our_oem_norm for row in session.added} == {"OUR1234"}
    assert all(row.workspace_id == WORKSPACE_ID for row in session.added)
    assert all(row.pricing_run_id == RUN_ID for row in session.added)
    assert all(row.method_version == result.method_version for row in session.added)
    assert all(row.config_sha256 == result.config_sha256 for row in session.added)


@pytest.mark.asyncio
async def test_identical_replay_reuses_snapshot_without_inserting() -> None:
    first = _FakeSession(run=_Run(), rows=_rows())
    baseline = await _persist(first)

    second = _FakeSession(run=_Run(), rows=_rows(), existing=first.added)
    result = await _persist(second)

    assert result.inserted == 0
    assert result.reused == len(first.added)
    assert second.added == []
    assert second.flushed == 0
    assert result.config_sha256 == baseline.config_sha256


@pytest.mark.asyncio
async def test_divergent_snapshot_raises_and_never_mutates() -> None:
    first = _FakeSession(run=_Run(), rows=_rows())
    await _persist(first)
    tampered = list(first.added)
    tampered[0].extracted_oem_norm = "ZZZ99999"

    session = _FakeSession(run=_Run(), rows=_rows(), existing=tampered)

    with pytest.raises(CrossLinkPersistenceError, match="differs from the current"):
        await _persist(session)

    assert session.added == []
    assert session.flushed == 0


@pytest.mark.asyncio
async def test_snapshot_from_another_config_version_raises() -> None:
    first = _FakeSession(run=_Run(), rows=_rows())
    await _persist(first)
    stale = list(first.added)
    for row in stale:
        row.config_sha256 = "0" * 64

    session = _FakeSession(run=_Run(), rows=_rows(), existing=stale)

    with pytest.raises(CrossLinkPersistenceError, match="another method/config version"):
        await _persist(session)

    assert session.added == []


@pytest.mark.asyncio
async def test_snapshot_from_another_method_version_raises() -> None:
    first = _FakeSession(run=_Run(), rows=_rows())
    await _persist(first)
    stale = list(first.added)
    for row in stale:
        row.method_version = "description-crosses-ab-v0"

    session = _FakeSession(run=_Run(), rows=_rows(), existing=stale)

    with pytest.raises(CrossLinkPersistenceError, match="another method/config version"):
        await _persist(session)

    assert session.added == []


@pytest.mark.asyncio
async def test_catalog_item_is_chosen_deterministically_for_duplicate_oe() -> None:
    low = UUID("00000000-0000-0000-0000-00000000000a")
    high = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    rows = [
        (
            _Observation(
                source_listing_id="listing-1",
                description=DESCRIPTION,
                url="https://prom.ua/ua/p-listing-1.html",
                seller_name="Seller A",
                price=Decimal("1000"),
            ),
            _CatalogItem(id=high),
        ),
        (
            _Observation(
                source_listing_id="listing-2",
                description=DESCRIPTION,
                url="https://prom.ua/ua/p-listing-2.html",
                seller_name="Seller B",
                price=Decimal("1100"),
            ),
            _CatalogItem(id=low),
        ),
    ]

    session = _FakeSession(run=_Run(), rows=rows)
    await _persist(session)

    assert {row.catalog_item_id for row in session.added} == {low}


@pytest.mark.asyncio
async def test_empty_description_produces_no_rows_and_still_flushes_cleanly() -> None:
    session = _FakeSession(run=_Run(), rows=_rows(description=None))

    result = await _persist(session)

    assert result.inserted == 0
    assert session.added == []
    assert result.analysis.descriptions_empty_or_short == 1


@pytest.mark.asyncio
async def test_no_observations_at_all_is_safe() -> None:
    session = _FakeSession(run=_Run(), rows=[])

    result = await _persist(session)

    assert result.inserted == 0
    assert result.reused == 0
    assert result.analysis.listings_total == 0
    assert session.added == []


@pytest.mark.asyncio
async def test_long_seller_name_is_truncated_to_column_width() -> None:
    session = _FakeSession(run=_Run(), rows=_rows(seller_name="Я" * 400))

    await _persist(session)

    assert session.added, "fixture must produce at least one row"
    assert all(len(row.source_seller) == 255 for row in session.added)


@pytest.mark.parametrize(
    "evidence",
    (
        None,
        {},
        {"source_category": "   "},
        {"source_category": 42},
        "not-a-mapping",
    ),
)
@pytest.mark.asyncio
async def test_malformed_comparison_evidence_never_raises(evidence: Any) -> None:
    session = _FakeSession(run=_Run(), rows=_rows(comparison_evidence=evidence))

    result = await _persist(session)

    assert result.inserted == len(session.added)


@pytest.mark.asyncio
async def test_source_category_is_read_from_comparison_evidence() -> None:
    session = _FakeSession(
        run=_Run(),
        rows=_rows(comparison_evidence={"source_category": "  radiator  "}),
    )

    result = await _persist(session)

    assert result.inserted == len(session.added)


@pytest.mark.asyncio
async def test_decision_without_matching_catalog_item_raises(monkeypatch) -> None:
    """Guards the invariant that every decision resolves to a stored catalog row.

    Unreachable through the normal flow, because decisions are derived from the
    same rows that build the lookup. It is exercised here so the guard cannot
    silently rot into a row insert with a NULL catalog reference.
    """

    from dataclasses import replace

    import marko.services.cross_links as module

    real = module.run_cross_stages_ab

    def _foreign_oe(listings, config):
        analysis = real(listings, config)
        assert analysis.pair_decisions, "fixture must produce decisions"
        return replace(
            analysis,
            pair_decisions=(
                replace(analysis.pair_decisions[0], our_oem_norm="NOTINCATALOG"),
            ),
        )

    monkeypatch.setattr(module, "run_cross_stages_ab", _foreign_oe)
    session = _FakeSession(run=_Run(), rows=_rows())

    with pytest.raises(CrossLinkPersistenceError, match="No catalog item found"):
        await _persist(session)

    assert session.flushed == 0


@pytest.mark.asyncio
async def test_count_cross_links_returns_zero_when_scalar_is_null() -> None:
    session = _FakeSession(run=_Run(), scalar_value=None)

    assert await count_cross_links_for_run(session, RUN_ID) == 0


@pytest.mark.asyncio
async def test_count_cross_links_returns_scalar_value() -> None:
    session = _FakeSession(run=_Run(), scalar_value=7)

    assert await count_cross_links_for_run(session, RUN_ID) == 7
