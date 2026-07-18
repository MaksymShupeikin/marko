from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from marko.infrastructure.db.models import ScrapeAttempt, ScrapeTarget
from marko.services.catalog_import import (
    StoreSyncClaim,
    _store_claim_is_current,
)
from marko.services.market_collection import (
    CollectionClaim,
    _target_claim_is_current,
    _target_delivery_is_busy,
    _verified_target_output,
)
from marko.services.scraper_contract import (
    ScrapeOutput,
    ScraperBoundaryError,
    ScraperErrorCode,
)


def test_comparison_claim_is_rejected_after_generation_takeover() -> None:
    task_id = "task-1"
    target = ScrapeTarget(
        status="collecting",
        owner_task_id=task_id,
        network_attempts=2,
        fencing_token=7,
    )
    attempt = ScrapeAttempt(
        id=uuid4(),
        status="running",
        task_id=task_id,
        delivery_no=5,
        fencing_token=7,
    )
    claim = CollectionClaim(
        action="target_collect",
        run_id=uuid4(),
        run_item_id=uuid4(),
        catalog_item_id=uuid4(),
        product_url="https://prom.ua/ua/p1-product.html",
        oe_norm="OE-1",
        delivery_no=5,
        fencing_token=7,
        execution_no=2,
        task_id=task_id,
        scrape_attempt_id=attempt.id,
    )

    assert _target_claim_is_current(target, attempt, claim) is True
    target.network_attempts = 3
    assert _target_claim_is_current(target, attempt, claim) is False
    target.network_attempts = 2
    target.fencing_token = 8
    assert _target_claim_is_current(target, attempt, claim) is False


def test_store_sync_claim_is_rejected_after_new_execution_takes_over() -> None:
    execution_id = uuid4()
    task_id = "task-1"
    claim = StoreSyncClaim(
        sync_run_id=uuid4(),
        execution_id=execution_id,
        execution_no=2,
        store_id=uuid4(),
        store_url="https://prom.ua/ua/c1-store.html",
        max_task_executions=3,
        deadline_at=datetime.now(UTC),
        task_id=task_id,
        fencing_token=7,
    )
    sync_run = SimpleNamespace(
        scrape_state="running",
        scrape_task_executions=2,
        scrape_owner_task_id=task_id,
        scrape_fencing_token=7,
    )
    execution = SimpleNamespace(
        id=execution_id,
        execution_no=2,
        outcome="running",
        fencing_token=7,
    )

    assert _store_claim_is_current(sync_run, execution, claim) is True
    sync_run.scrape_task_executions = 3
    assert _store_claim_is_current(sync_run, execution, claim) is False
    sync_run.scrape_task_executions = 2
    sync_run.scrape_fencing_token = 8
    assert _store_claim_is_current(sync_run, execution, claim) is False


def test_broker_redelivery_can_take_over_an_unexpired_target_lease() -> None:
    now = datetime.now(UTC)
    target = ScrapeTarget(
        status="collecting",
        lease_expires_at=now + timedelta(minutes=5),
    )

    assert _target_delivery_is_busy(target, now, is_redelivery=False) is True
    assert _target_delivery_is_busy(target, now, is_redelivery=True) is False


def test_succeeded_target_requires_a_verified_content_identity() -> None:
    payload = {
        "schema_version": "prom-price-comparison-v1",
        "adapter_version": "prom-parser-adapter-v2",
        "input": {"input_hash": "abc"},
        "output": {"offers": []},
    }
    output = ScrapeOutput.from_payload(payload)
    target = ScrapeTarget(
        status="succeeded",
        payload=payload,
        content_sha256=None,
    )

    with pytest.raises(ScraperBoundaryError) as missing:
        _verified_target_output(target)
    assert missing.value.code == ScraperErrorCode.EVIDENCE_PERSISTENCE

    target.content_sha256 = "0" * 64
    with pytest.raises(ScraperBoundaryError):
        _verified_target_output(target)

    target.content_sha256 = output.content_sha256
    assert _verified_target_output(target).content_sha256 == output.content_sha256
