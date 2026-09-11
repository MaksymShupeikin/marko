"""Catalog repricing: the plan, the coverage ledger, and the run loop."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from marko.infrastructure.db.models import (
    RepriceItemStatus,
    RepriceMode,
    RepriceOutcome,
    RepricePolicy,
    RepriceRun,
    RepriceRunItem,
    RepriceScope,
    SyncStatus,
)
from marko.services import repricing
from marko.services.bulk_products import CatalogFilter
from marko.services.pricing import PriceSuggestion


class FakeSession:
    def __init__(self) -> None:
        self.added: list = []
        self.executed: list = []
        self.commit = AsyncMock()
        self.flush = AsyncMock()
        self.refresh = AsyncMock()
        self._by_id: dict = {}

    def add(self, value) -> None:
        self.added.append(value)

    async def execute(self, statement, params=None):
        self.executed.append((statement, params))
        return None

    async def get(self, _model, key):
        return self._by_id.get(key)


class FakeSessionFactory:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def __call__(self) -> "FakeSessionFactory":
        return self

    async def __aenter__(self) -> FakeSession:
        return self._session

    async def __aexit__(self, *_exc) -> bool:
        return False


def _stub_catalog(monkeypatch, listing_ids: list, store_ids: list | None = None):
    monkeypatch.setattr(
        repricing.listings_repo,
        "manageable_workspace_listing_ids",
        AsyncMock(return_value=list(listing_ids)),
    )
    monkeypatch.setattr(
        repricing.stores_repo,
        "owned_store_ids",
        AsyncMock(return_value=list(store_ids or [])),
    )


async def test_signature_ignores_order_and_prices(monkeypatch):
    """Підпис описує склад каталогу, а не його ціни."""
    ids = [uuid4() for _ in range(5)]
    session = FakeSession()

    _stub_catalog(monkeypatch, ids)
    first = await repricing.catalog_signature(session, uuid4())

    # Той самий каталог, інший порядок рядків з бази — той самий підпис.
    _stub_catalog(monkeypatch, list(reversed(ids)))
    second = await repricing.catalog_signature(session, uuid4())

    assert first.value == second.value
    assert first.item_count == 5


async def test_signature_changes_when_a_product_appears(monkeypatch):
    ids = [uuid4() for _ in range(3)]
    session = FakeSession()

    _stub_catalog(monkeypatch, ids)
    before = await repricing.catalog_signature(session, uuid4())

    _stub_catalog(monkeypatch, ids + [uuid4()])
    after = await repricing.catalog_signature(session, uuid4())

    assert before.value != after.value
    assert after.item_count == before.item_count + 1


async def _queue(monkeypatch, *, rows, covered=(), **kwargs):
    session = FakeSession()
    sync_run = SimpleNamespace(
        id=uuid4(),
        status=SyncStatus.queued,
        progress_total=None,
        task_id=None,
        error=None,
        finished_at=None,
    )
    _stub_catalog(monkeypatch, [row[0] for row in rows])
    monkeypatch.setattr(
        repricing.listings_repo,
        "reprice_plan_rows",
        AsyncMock(return_value=list(rows)),
    )
    monkeypatch.setattr(
        repricing.repricing_repo,
        "covered_listing_ids",
        AsyncMock(return_value=set(covered)),
    )
    monkeypatch.setattr(
        repricing.stores_repo, "create_sync_run", AsyncMock(return_value=sync_run)
    )
    captured: list[list[dict]] = []

    async def capture(_session, plan_rows):
        captured.append(list(plan_rows))

    monkeypatch.setattr(repricing.repricing_repo, "insert_items", capture)

    sent: list[tuple] = []

    class FakeCelery:
        def send_task(self, name, args):
            sent.append((name, args))
            return SimpleNamespace(id="task-1")

    params = {
        "scope": RepriceScope.partial,
        "mode": RepriceMode.fresh,
        "policy": RepricePolicy.balanced,
        "requested_count": None,
        **kwargs,
    }
    run = await repricing.queue_reprice(
        session, uuid4(), CatalogFilter(), celery_app=FakeCelery(), **params
    )
    return run, sync_run, captured[0], sent


async def test_partial_run_takes_the_top_of_the_plan(monkeypatch):
    rows = [(uuid4(), f"SKU{i}", Decimal("100")) for i in range(10)]
    run, sync_run, plan, sent = await _queue(
        monkeypatch, rows=rows, scope=RepriceScope.partial, requested_count=3
    )

    assert len(plan) == 3
    assert [row["listing_id"] for row in plan] == [row[0] for row in rows[:3]]
    assert [row["position"] for row in plan] == [0, 1, 2]
    assert sync_run.progress_total == 3
    assert sync_run.task_id == "task-1"
    assert sent[0][0] == repricing.REPRICE_TASK
    assert sent[0][1] == [str(sync_run.id)]
    assert run.scope is RepriceScope.partial


async def test_full_run_ignores_the_slider(monkeypatch):
    rows = [(uuid4(), f"SKU{i}", Decimal("100")) for i in range(7)]
    _run, sync_run, plan, _sent = await _queue(
        monkeypatch, rows=rows, scope=RepriceScope.full, requested_count=2
    )
    assert len(plan) == 7
    assert sync_run.progress_total == 7


async def test_resume_plans_only_uncovered_items_keeping_order(monkeypatch):
    """«Продовжити» продовжує рівно там, де зупинилися."""
    rows = [(uuid4(), f"SKU{i}", Decimal("100")) for i in range(6)]
    covered = {rows[0][0], rows[2][0], rows[4][0]}
    _run, _sync_run, plan, _sent = await _queue(
        monkeypatch,
        rows=rows,
        covered=covered,
        mode=RepriceMode.resume,
        scope=RepriceScope.full,
    )

    assert [row["listing_id"] for row in plan] == [rows[1][0], rows[3][0], rows[5][0]]
    # Позиції перенумеровані, але відносний порядок плану збережено.
    assert [row["position"] for row in plan] == [0, 1, 2]


async def test_resume_slider_can_still_cut_the_tail(monkeypatch):
    rows = [(uuid4(), f"SKU{i}", Decimal("100")) for i in range(6)]
    _run, _sync_run, plan, _sent = await _queue(
        monkeypatch,
        rows=rows,
        covered={rows[0][0]},
        mode=RepriceMode.resume,
        scope=RepriceScope.partial,
        requested_count=2,
    )
    assert [row["listing_id"] for row in plan] == [rows[1][0], rows[2][0]]


async def test_dispatch_failure_marks_the_run_failed(monkeypatch):
    rows = [(uuid4(), "SKU", Decimal("100"))]

    class DeadCelery:
        def send_task(self, name, args):
            raise RuntimeError("broker down")

    session = FakeSession()
    sync_run = SimpleNamespace(
        id=uuid4(),
        status=SyncStatus.queued,
        progress_total=None,
        task_id=None,
        error=None,
        finished_at=None,
    )
    _stub_catalog(monkeypatch, [rows[0][0]])
    monkeypatch.setattr(
        repricing.listings_repo, "reprice_plan_rows", AsyncMock(return_value=rows)
    )
    monkeypatch.setattr(
        repricing.stores_repo, "create_sync_run", AsyncMock(return_value=sync_run)
    )
    monkeypatch.setattr(repricing.repricing_repo, "insert_items", AsyncMock())

    with pytest.raises(repricing.RepriceDispatchError):
        await repricing.queue_reprice(
            session,
            uuid4(),
            CatalogFilter(),
            scope=RepriceScope.full,
            mode=RepriceMode.fresh,
            policy=RepricePolicy.balanced,
            requested_count=None,
            celery_app=DeadCelery(),
        )

    assert sync_run.status is SyncStatus.failed
    assert "чергу" in sync_run.error


def _item() -> RepriceRunItem:
    return RepriceRunItem(run_id=uuid4(), listing_id=uuid4(), position=0)


def _run_row() -> RepriceRun:
    return RepriceRun(
        id=uuid4(),
        workspace_id=uuid4(),
        scope=RepriceScope.full,
        mode=RepriceMode.fresh,
        policy=RepricePolicy.balanced,
        catalog_scope_signature="sig",
        catalog_item_count=1,
        changed_count=0,
        unchanged_count=0,
        skipped_count=0,
        failed_count=0,
    )


def test_share_guard_ignores_small_plans():
    run = _run_row()
    run.changed_count = 5
    assert repricing._share_guard_tripped(run, 5) is False


def test_share_guard_trips_on_a_wholesale_change():
    run = _run_row()
    run.changed_count = 30
    assert repricing._share_guard_tripped(run, 100) is True
    run.changed_count = 20
    assert repricing._share_guard_tripped(run, 100) is False


def test_applying_a_suggestion_fills_the_delta_and_counters():
    run = _run_row()
    item = _item()
    item.old_price = Decimal("1000")
    repricing._apply_suggestion(
        run,
        item,
        PriceSuggestion(
            outcome="changed",
            method="legacy_min_minus",
            new_price=Decimal("900"),
            zone="premium",
            offers_total=12,
            evidence={"anchor": "min_price"},
        ),
    )
    assert item.status is RepriceItemStatus.done
    assert item.outcome is RepriceOutcome.changed
    assert item.delta_abs == Decimal("-100")
    assert item.delta_pct == Decimal("-10.00")
    assert run.changed_count == 1
    assert run.unchanged_count == 0


def test_unchanged_and_refused_land_in_different_counters():
    run = _run_row()
    repricing._apply_suggestion(
        run,
        _item(),
        PriceSuggestion(outcome="unchanged", method="m", new_price=Decimal("10")),
    )
    repricing._apply_suggestion(
        run,
        _item(),
        PriceSuggestion(outcome="no_recommendation", method="m", reason="тонкий ринок"),
    )
    assert (run.changed_count, run.unchanged_count, run.skipped_count) == (0, 1, 1)


class _Engine:
    name = "stub"

    def __init__(self, suggestion: PriceSuggestion) -> None:
        self._suggestion = suggestion
        self.calls = 0

    def suggest(self, *, current_price, report, policy):
        self.calls += 1
        return self._suggestion


def _listing_row(price: Decimal | None = Decimal("1000")):
    listing = SimpleNamespace(id=uuid4(), current_price=price)
    return (listing, SimpleNamespace(name="Магазин"), None)


async def test_cached_report_costs_no_check(monkeypatch):
    run, item = _run_row(), _item()
    monkeypatch.setattr(
        repricing.listings_repo,
        "get_manageable_workspace_listing",
        AsyncMock(return_value=_listing_row()),
    )
    monkeypatch.setattr(repricing, "listing_search_query", AsyncMock(return_value="q"))
    monkeypatch.setattr(
        repricing, "cached_report_for_query", AsyncMock(return_value={"stats": {}})
    )
    consume = AsyncMock(return_value=True)
    monkeypatch.setattr(repricing.billing, "try_consume_check", consume)
    live = AsyncMock()
    monkeypatch.setattr(repricing, "competitor_prices_for_query", live)

    engine = _Engine(
        PriceSuggestion(outcome="changed", method="stub", new_price=Decimal("900"))
    )
    spent = await repricing._process_item(
        FakeSession(), run, item, engine=engine, budget_spent=False
    )

    assert spent is False
    consume.assert_not_awaited()
    live.assert_not_awaited()
    assert engine.calls == 1


async def test_exhausted_budget_stops_paying_and_says_why(monkeypatch):
    run, item = _run_row(), _item()
    monkeypatch.setattr(
        repricing.listings_repo,
        "get_manageable_workspace_listing",
        AsyncMock(return_value=_listing_row()),
    )
    monkeypatch.setattr(repricing, "listing_search_query", AsyncMock(return_value="q"))
    monkeypatch.setattr(
        repricing, "cached_report_for_query", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        repricing.billing, "try_consume_check", AsyncMock(return_value=False)
    )
    live = AsyncMock()
    monkeypatch.setattr(repricing, "competitor_prices_for_query", live)

    spent = await repricing._process_item(
        FakeSession(), run, item, engine=_Engine(None), budget_spent=False
    )

    assert spent is True
    live.assert_not_awaited()
    assert item.outcome is RepriceOutcome.no_recommendation
    assert item.reason == repricing._LIMIT_REACHED
    assert run.skipped_count == 1


async def test_once_the_budget_is_gone_no_further_item_pays(monkeypatch):
    run, item = _run_row(), _item()
    monkeypatch.setattr(
        repricing.listings_repo,
        "get_manageable_workspace_listing",
        AsyncMock(return_value=_listing_row()),
    )
    monkeypatch.setattr(repricing, "listing_search_query", AsyncMock(return_value="q"))
    monkeypatch.setattr(
        repricing, "cached_report_for_query", AsyncMock(return_value=None)
    )
    consume = AsyncMock(return_value=True)
    monkeypatch.setattr(repricing.billing, "try_consume_check", consume)

    spent = await repricing._process_item(
        FakeSession(), run, item, engine=_Engine(None), budget_spent=True
    )

    assert spent is True
    consume.assert_not_awaited()
    assert item.reason == repricing._LIMIT_REACHED


async def test_vanished_product_fails_its_row_not_the_run(monkeypatch):
    run, item = _run_row(), _item()
    monkeypatch.setattr(
        repricing.listings_repo,
        "get_manageable_workspace_listing",
        AsyncMock(return_value=None),
    )
    await repricing._process_item(
        FakeSession(), run, item, engine=_Engine(None), budget_spent=False
    )
    assert item.status is RepriceItemStatus.failed
    assert item.reason == repricing._GONE
    assert run.failed_count == 1


async def test_cancelled_run_stops_between_chunks(monkeypatch):
    """Скасування має зупиняти прогін кооперативно, а не лише вбивати задачу."""
    sync_run = SimpleNamespace(
        id=uuid4(),
        workspace_id=uuid4(),
        status=SyncStatus.queued,
        progress_current=0,
        progress_total=10,
        started_at=None,
        finished_at=None,
        error=None,
    )
    session = FakeSession()
    session._by_id[sync_run.id] = sync_run

    async def cancel_on_refresh(target):
        target.status = SyncStatus.cancelled

    session.refresh = AsyncMock(side_effect=cancel_on_refresh)
    monkeypatch.setattr(repricing, "async_session_factory", FakeSessionFactory(session))
    monkeypatch.setattr(
        repricing.repricing_repo,
        "get_run_by_sync_run",
        AsyncMock(return_value=_run_row()),
    )
    pending = AsyncMock()
    monkeypatch.setattr(repricing.repricing_repo, "next_pending_items", pending)

    done = await repricing.run_reprice(sync_run.id)

    assert done == 0
    pending.assert_not_awaited()
    assert sync_run.status is SyncStatus.cancelled
    assert "зупинено" in sync_run.error.lower()
    assert sync_run.finished_at is not None


async def test_missing_sync_run_is_a_lookup_error(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(repricing, "async_session_factory", FakeSessionFactory(session))
    with pytest.raises(LookupError):
        await repricing.run_reprice(uuid4())


async def test_one_broken_product_never_stalls_the_whole_run(monkeypatch):
    """Рядок, що впав, лишається done/failed — інакше цикл візьме ту саму партію."""
    sync_run = SimpleNamespace(
        id=uuid4(),
        workspace_id=uuid4(),
        status=SyncStatus.running,
        progress_current=0,
        progress_total=1,
        started_at=None,
        finished_at=None,
        error=None,
    )
    session = FakeSession()
    session._by_id[sync_run.id] = sync_run
    monkeypatch.setattr(repricing, "async_session_factory", FakeSessionFactory(session))
    monkeypatch.setattr(
        repricing.repricing_repo,
        "get_run_by_sync_run",
        AsyncMock(return_value=_run_row()),
    )

    item = _item()
    batches = [[item], []]
    monkeypatch.setattr(
        repricing.repricing_repo,
        "next_pending_items",
        AsyncMock(side_effect=lambda *a, **k: batches.pop(0)),
    )
    monkeypatch.setattr(
        repricing,
        "_process_item",
        AsyncMock(side_effect=RuntimeError("джерело впало")),
    )

    done = await repricing.run_reprice(sync_run.id)

    assert done == 1
    assert item.status is RepriceItemStatus.failed
    assert "джерело впало" in item.reason
    assert sync_run.status is SyncStatus.completed


def _done_item(listing_id, *, outcome=RepriceOutcome.changed, price="100"):
    return RepriceRunItem(
        run_id=uuid4(),
        listing_id=listing_id,
        position=0,
        status=RepriceItemStatus.done,
        outcome=outcome,
        old_price=Decimal(price),
        new_price=Decimal(price),
        price_at_compute=Decimal(price),
    )


async def test_reconciliation_counts_what_survived_the_new_catalog(monkeypatch):
    """Після зміни складу каталогу людина має бачити, що доведеться рахувати."""
    kept = [uuid4(), uuid4()]
    gone = [uuid4()]
    fresh = [uuid4(), uuid4(), uuid4()]
    session = FakeSession()

    _stub_catalog(monkeypatch, kept + fresh)
    monkeypatch.setattr(
        repricing.repricing_repo,
        "list_runs",
        AsyncMock(
            return_value=[(SimpleNamespace(catalog_scope_signature="old"), None)]
        ),
    )
    monkeypatch.setattr(
        repricing.repricing_repo,
        "covered_listing_ids",
        AsyncMock(return_value=set(kept + gone)),
    )

    result = await repricing.reconciliation(session, uuid4())

    assert result.signature_changed is True
    assert (result.kept, result.gone, result.fresh) == (2, 1, 3)


async def test_carry_over_moves_surviving_results_under_the_new_signature(
    monkeypatch,
):
    kept = [uuid4(), uuid4()]
    gone = uuid4()
    session = FakeSession()

    _stub_catalog(monkeypatch, kept)
    monkeypatch.setattr(
        repricing.repricing_repo,
        "list_runs",
        AsyncMock(
            return_value=[(SimpleNamespace(catalog_scope_signature="old"), None)]
        ),
    )
    monkeypatch.setattr(
        repricing.repricing_repo,
        "latest_done_items",
        AsyncMock(
            return_value=[
                _done_item(kept[0]),
                _done_item(kept[1], outcome=RepriceOutcome.unchanged),
                _done_item(gone),
            ]
        ),
    )
    captured: list[list[dict]] = []

    async def capture(_session, rows):
        captured.append(list(rows))

    monkeypatch.setattr(repricing.repricing_repo, "insert_items", capture)

    run = await repricing.carry_over_coverage(session, uuid4())

    assert run is not None
    assert run.mode is RepriceMode.carry_over
    # Товар, якого в каталозі вже немає, не переноситься.
    assert {row["listing_id"] for row in captured[0]} == set(kept)
    assert all(row["status"] is RepriceItemStatus.done for row in captured[0])
    assert (run.changed_count, run.unchanged_count) == (1, 1)


async def test_carry_over_does_nothing_when_the_catalog_is_the_same(monkeypatch):
    ids = [uuid4()]
    session = FakeSession()
    _stub_catalog(monkeypatch, ids)
    signature = await repricing.catalog_signature(session, uuid4())

    _stub_catalog(monkeypatch, ids)
    monkeypatch.setattr(
        repricing.repricing_repo,
        "list_runs",
        AsyncMock(
            return_value=[
                (SimpleNamespace(catalog_scope_signature=signature.value), None)
            ]
        ),
    )
    assert await repricing.carry_over_coverage(session, uuid4()) is None
