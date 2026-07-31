from datetime import UTC, datetime
from uuid import uuid4

import pytest

from marko.services import catalog_import
from marko.services.catalog_import import (
    StoreSyncClaim,
    _checkpoint_next_page,
    _chunk_reached_page_budget,
)
from marko.services.scrape_runtime import ScrapeExecutionTrace
from marko.worker.tasks.fitment import process_fitment_analysis_task
from marko.worker.tasks.import_store import import_store_catalog_task
from marko.worker.tasks.pricing import (
    calculate_pricing_item_task,
    finalize_pricing_collection_task,
    process_pricing_item_task,
    re_enrich_market_observations_task,
    start_pricing_run_task,
)
from marko.worker.tasks.system import (
    cleanup_scrape_evidence,
    healthcheck,
    reconcile_scrape_outbox,
    reconcile_stale_workflows_task,
)


def _claim(*, page_budget: int = 100) -> StoreSyncClaim:
    return StoreSyncClaim(
        sync_run_id=uuid4(),
        execution_id=uuid4(),
        execution_no=1,
        store_id=uuid4(),
        store_url="https://prom.ua/ua/c1-store.html",
        max_task_executions=3,
        deadline_at=datetime.now(UTC),
        task_id="task-1",
        start_page=101,
        page_budget=page_budget,
        total_page_limit=1000,
    )


def test_store_sync_chunk_boundary_is_explicit_and_checkpoint_monotonic() -> None:
    claim = _claim(page_budget=100)

    assert _chunk_reached_page_budget(claim, 99) is False
    assert _chunk_reached_page_budget(claim, 100) is True
    assert _checkpoint_next_page({"next_page": 201}, fallback=101) == 201
    assert _checkpoint_next_page({"next_page": "invalid"}, fallback=101) == 101
    assert _checkpoint_next_page({"next_page": 1}, fallback=101) == 101


@pytest.mark.asyncio
async def test_store_sync_gateway_receives_bounded_resume_window(monkeypatch) -> None:
    captured = {}

    class FakeGateway:
        def __init__(self, config) -> None:
            captured["config"] = config

        def scrape(self, url: str, *, strict: bool):
            captured["url"] = url
            captured["strict"] = strict
            return iter(())

    async def fake_persist_progress(claim, trace, products) -> int:
        return claim.page_budget

    async def fake_persisted_product_count(sync_run_id) -> int:
        return 321

    monkeypatch.setattr(catalog_import, "PromGateway", FakeGateway)
    monkeypatch.setattr(
        catalog_import,
        "_persist_progress",
        fake_persist_progress,
    )
    monkeypatch.setattr(
        catalog_import,
        "_persisted_product_count",
        fake_persisted_product_count,
    )
    claim = _claim(page_budget=100)
    trace = ScrapeExecutionTrace(item_kind="store_sync", execution_no=1)

    result = await catalog_import._run_import(claim, trace)

    assert captured["config"].start_page == 101
    assert captured["config"].max_pages == 100
    assert captured["strict"] is True
    assert result.persisted_products == 321
    assert result.catalog_pages_fetched == 100


@pytest.mark.asyncio
async def test_store_sync_flushes_partial_batch_before_propagating_page_failure(
    monkeypatch,
) -> None:
    persisted_batches: list[list[object]] = []

    class FailingGateway:
        def __init__(self, _config) -> None:
            pass

        def scrape(self, _url: str, *, strict: bool):
            assert strict is True
            yield from (object(), object(), object(), object())
            raise RuntimeError("page 2 failed")

    async def fake_persist_progress(_claim, _trace, products) -> int:
        persisted_batches.append(list(products))
        return 1

    monkeypatch.setattr(catalog_import, "PromGateway", FailingGateway)
    monkeypatch.setattr(
        catalog_import,
        "_persist_progress",
        fake_persist_progress,
    )

    with pytest.raises(RuntimeError, match="page 2 failed"):
        await catalog_import._run_import(
            _claim(page_budget=100),
            ScrapeExecutionTrace(item_kind="store_sync", execution_no=1),
        )

    assert [len(batch) for batch in persisted_batches] == [4]


def test_every_worker_task_has_an_explicit_hard_and_soft_time_limit() -> None:
    tasks = (
        import_store_catalog_task,
        start_pricing_run_task,
        process_pricing_item_task,
        finalize_pricing_collection_task,
        calculate_pricing_item_task,
        re_enrich_market_observations_task,
        process_fitment_analysis_task,
        healthcheck,
        cleanup_scrape_evidence,
        reconcile_scrape_outbox,
        reconcile_stale_workflows_task,
    )

    assert len(tasks) == 11
    assert len({task.name for task in tasks}) == len(tasks)
    for task in tasks:
        assert task.acks_late is True, task.name
        assert task.reject_on_worker_lost is True, task.name
        assert task.soft_time_limit is not None, task.name
        assert task.time_limit is not None, task.name
        assert 0 < task.soft_time_limit < task.time_limit, task.name
        assert task.max_retries is not None and task.max_retries >= 0, task.name
