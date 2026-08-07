"""Opt-in PostgreSQL proof for migration, constraints and replay idempotency.

The database must be disposable and its name must contain ``p15017``.  The
suite intentionally performs Alembic downgrade/upgrade operations.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from marko.core.config import get_settings
from marko.e2e.fixture_seed import DEFAULT_FIXTURE, seed_fixture_replay
from marko.infrastructure.db.models import (
    CatalogImportBatch,
    CatalogItem,
    MarketObservation,
    OfferProcessingOutcome,
    PricingRun,
    PricingRunItem,
    RawMarketCapture,
    ScrapeAttempt,
    ScrapeTarget,
    Workspace,
)
from marko.infrastructure.db.session import async_session_factory, engine
from marko.services.market_collection import (
    _claim_item,
    _derive_calibration_pairs,
    _materialize_target_evidence,
    _persist_target_success,
    process_pricing_item,
)
from marko.services.offer_identity import OE_EXTRACTOR_VERSION
from marko.services.oe_reenrichment import (
    re_enrich_retained_observations_in_session,
)
from marko.services.offer_processing import (
    EvidenceAccountingError,
    OfferAccounting,
)
from marko.services.pricing_runs import (
    CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
    TrustedRunStart,
    create_pricing_run,
    policy_from_dict,
)
from marko.services.scrape_runtime import ScrapeExecutionTrace
from marko.services.scraper_contract import (
    AttemptMeasurement,
    QueryInput,
    ScrapeOutput,
)


pytestmark = pytest.mark.postgres
BACKEND_ROOT = Path(__file__).resolve().parents[1]
APPEND_ONLY_TABLES = (
    "offer_processing_outcomes",
    "raw_market_captures",
    "market_observations",
    "observation_tier_classifications",
    "pricing_recommendations",
    "recommendation_decisions",
    "catalog_item_overrides",
    "tier_calibration_pairs",
    "tier_coefficients",
)


def _postgres_enabled() -> bool:
    return os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") == "1"


def _require_disposable_database() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    database_name = make_url(database_url).database or ""
    if "p15017" not in database_name.casefold():
        pytest.fail(
            "Refusing migration test: DATABASE_URL must name a disposable "
            "database containing 'p15017'"
        )


def _alembic(operation: str, revision: str) -> None:
    completed = subprocess.run(
        ["uv", "run", "alembic", "-c", "alembic.ini", operation, revision],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


async def _delete_disposable_workspace(workspace_id: UUID) -> None:
    """Remove a fixture without weakening the production append-only contract."""

    async with async_session_factory() as session:
        try:
            for table_name in APPEND_ONLY_TABLES:
                await session.execute(
                    text(
                        f"ALTER TABLE {table_name} "
                        f"DISABLE TRIGGER trg_{table_name}_append_only"
                    )
                )
            # Членство прогона держит позиции каталога внешним ключом
            # RESTRICT (миграция 0033): улику расчёта нельзя снести каскадом от
            # воркспейса. Уборка снимает её явно и в обратном порядке — сама
            # защита при этом не ослабляется.
            await session.execute(
                text(
                    "ALTER TABLE pricing_run_items "
                    "DISABLE TRIGGER trg_pricing_run_items_no_delete"
                )
            )
            await session.execute(
                text(
                    "DELETE FROM pricing_run_items WHERE pricing_run_id IN "
                    "(SELECT id FROM pricing_runs WHERE workspace_id=:workspace_id)"
                ),
                {"workspace_id": workspace_id},
            )
            await session.execute(
                text(
                    "ALTER TABLE pricing_run_items "
                    "ENABLE TRIGGER trg_pricing_run_items_no_delete"
                )
            )
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            for table_name in reversed(APPEND_ONLY_TABLES):
                await session.execute(
                    text(
                        f"ALTER TABLE {table_name} "
                        f"ENABLE TRIGGER trg_{table_name}_append_only"
                    )
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_01_populated_0015_upgrade_backfills_fail_closed_and_constraints_hold() -> (
    None
):
    _require_disposable_database()
    _alembic("upgrade", "head")
    _alembic("downgrade", "20260719_0015")
    workspace_id = uuid4()
    batch_id = uuid4()
    item_id = uuid4()
    run_id = uuid4()
    run_item_id = uuid4()
    capture_id = uuid4()
    observation_id = uuid4()
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
            {"id": workspace_id, "name": "P15017 migration", "slug": workspace_id.hex},
        )
        await session.execute(
            text(
                "INSERT INTO catalog_import_batches "
                "(id, workspace_id, filename, content_sha256, content_size, status, "
                "column_mapping, total_rows, imported_rows, rejected_rows, error_log) "
                "VALUES (:id, :workspace_id, 'legacy.xlsx', :sha, 1, 'completed', "
                "CAST(:mapping AS json), 1, 1, 0, CAST(:errors AS json))"
            ),
            {
                "id": batch_id,
                "workspace_id": workspace_id,
                "sha": "a" * 64,
                "mapping": json.dumps({"Код_товару": "oe"}),
                "errors": "[]",
            },
        )
        await session.execute(
            text(
                "INSERT INTO catalog_items "
                "(id, workspace_id, import_batch_id, source_row, sku, oe_raw, oe_norm, "
                "name, category, current_price, raw_row) "
                "VALUES (:id, :workspace_id, :batch_id, 2, 'SKU-LEGACY', "
                "'1K0 121 251', '1K0121251', 'Legacy item', 'brakes', 850, "
                "CAST(:raw_row AS json))"
            ),
            {
                "id": item_id,
                "workspace_id": workspace_id,
                "batch_id": batch_id,
                "raw_row": "{}",
            },
        )
        await session.execute(
            text(
                "INSERT INTO pricing_runs "
                "(id, workspace_id, import_batch_id, status, policy_version, "
                "policy_config, parser_version, total_items) "
                "VALUES (:id, :workspace_id, :batch_id, 'completed', 'legacy-policy', "
                "CAST(:policy AS json), 'legacy-parser', 1)"
            ),
            {
                "id": run_id,
                "workspace_id": workspace_id,
                "batch_id": batch_id,
                "policy": "{}",
            },
        )
        await session.execute(
            text(
                "INSERT INTO pricing_run_items "
                "(id, pricing_run_id, catalog_item_id, status, idempotency_key) "
                "VALUES (:id, :run_id, :item_id, 'classified', :key)"
            ),
            {
                "id": run_item_id,
                "run_id": run_id,
                "item_id": item_id,
                "key": f"legacy:{run_item_id}",
            },
        )
        await session.execute(
            text(
                "INSERT INTO raw_market_captures "
                "(id, pricing_run_item_id, source, payload, content_sha256, parser_version) "
                "VALUES (:id, :run_item_id, 'prom_public', CAST(:payload AS json), "
                ":sha, 'legacy-parser')"
            ),
            {
                "id": capture_id,
                "run_item_id": run_item_id,
                "payload": "{}",
                "sha": "b" * 64,
            },
        )
        await session.execute(
            text(
                "INSERT INTO market_observations "
                "(id, pricing_run_item_id, catalog_item_id, raw_capture_id, source, "
                "source_listing_id, seller_id, seller_name, url, title, matched_oe_norm, "
                "price, currency, match_confidence, parser_version, observed_at, "
                "source_confidence, automatic_eligible) "
                "VALUES (:id, :run_item_id, :item_id, :capture_id, 'prom_public', "
                "'legacy-listing', 'legacy-seller', 'Legacy seller', "
                "'https://prom.ua/ua/p1-legacy.html', 'Legacy offer', '1K0121251', "
                "1000, 'UAH', 1, 'legacy-parser', :observed_at, 1, false)"
            ),
            {
                "id": observation_id,
                "run_item_id": run_item_id,
                "item_id": item_id,
                "capture_id": capture_id,
                "observed_at": now,
            },
        )
        await session.commit()

    _alembic("upgrade", "head")
    async with async_session_factory() as session:
        legacy = (
            await session.execute(
                text(
                    "SELECT search_oe_norm, extracted_oe_norms, "
                    "verified_matched_oe_norm, comparison_identity_key, "
                    "oe_verification_status, automatic_eligible, source_confidence, "
                    "oe_extractor_version FROM market_observations WHERE id = :id"
                ),
                {"id": observation_id},
            )
        ).one()
    assert legacy.search_oe_norm == "1K0121251"
    assert legacy.extracted_oe_norms == []
    assert legacy.verified_matched_oe_norm is None
    assert legacy.comparison_identity_key is None
    assert legacy.oe_verification_status == "LEGACY_UNVERIFIED"
    assert legacy.automatic_eligible is False
    assert Decimal(legacy.source_confidence) == 0
    assert legacy.oe_extractor_version == "legacy-unverified-v0"

    # A pre-0016 writer does not know search_oe_norm or the verified identity
    # fields.  It must fail during the coordinated deployment window rather
    # than create a row whose catalog/query OE looks candidate-verified.
    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO market_observations "
                    "(id, pricing_run_item_id, catalog_item_id, raw_capture_id, "
                    "source, source_listing_id, seller_id, seller_name, url, title, "
                    "matched_oe_norm, price, currency, match_confidence, "
                    "parser_version, observed_at, source_confidence, "
                    "automatic_eligible) VALUES "
                    "(:id, :run_item_id, :item_id, :capture_id, 'prom_public', "
                    "'old-writer-listing', 'old-writer-seller', 'Old writer', "
                    "'https://prom.ua/ua/p2-old.html', 'Old writer offer', "
                    "'1K0121251', 1000, 'UAH', 1, 'legacy-parser', :observed_at, "
                    "1, false)"
                ),
                {
                    "id": uuid4(),
                    "run_item_id": run_item_id,
                    "item_id": item_id,
                    "capture_id": capture_id,
                    "observed_at": now,
                },
            )
            await session.commit()
        await session.rollback()

    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "SELECT set_config('marko.identity_reenrichment', "
                    "'constraint-test-v1', true)"
                )
            )
            await session.execute(
                text(
                    "UPDATE market_observations SET "
                    "oe_verification_status='VERIFIED_EXACT', "
                    "oe_extractor_version='constraint-test-v1', "
                    "oe_reenriched_at=now() WHERE id=:id"
                ),
                {"id": observation_id},
            )
            await session.commit()
        await session.rollback()
    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "SELECT set_config('marko.identity_reenrichment', "
                    "'constraint-test-v1', true)"
                )
            )
            await session.execute(
                text(
                    "UPDATE market_observations SET automatic_eligible=true, "
                    "oe_extractor_version='constraint-test-v1', "
                    "oe_reenriched_at=now() "
                    "WHERE id=:id"
                ),
                {"id": observation_id},
            )
            await session.commit()
        await session.rollback()

    _alembic("downgrade", "20260719_0015")
    _alembic("upgrade", "head")
    await engine.dispose()


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_02_query_replay_materialization_and_redelivery_are_idempotent(
    monkeypatch,
) -> None:
    _require_disposable_database()
    monkeypatch.setenv("ENVIRONMENT", "e2e")
    monkeypatch.setenv("E2E_AUTH_BYPASS", "true")
    monkeypatch.setenv("E2E_AUTH_TOKEN", "p15017-integration-token-00000001")
    monkeypatch.setenv(
        "PRICING_BRAND_TIERS_PATH",
        str(BACKEND_ROOT / "src/marko/e2e/fixtures/brands.yaml"),
    )
    get_settings.cache_clear()
    workspace_id = uuid4()
    batch_id = uuid4()
    item_id = uuid4()
    item_id_2 = uuid4()
    item_id_3 = uuid4()
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())
    try:
        async with async_session_factory() as session:
            session.add(
                Workspace(
                    id=workspace_id,
                    name="P15017 replay",
                    slug=f"p15017-{workspace_id.hex}",
                )
            )
            await session.flush()
            session.add(
                CatalogImportBatch(
                    id=batch_id,
                    workspace_id=workspace_id,
                    filename="query-only.xlsx",
                    content_sha256="c" * 64,
                    content_size=1,
                    status="completed",
                    column_mapping={"Код_товару": "oe"},
                    total_rows=3,
                    imported_rows=3,
                    rejected_rows=0,
                    error_log=[],
                )
            )
            await session.flush()
            session.add(
                CatalogItem(
                    id=item_id,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    source_row=2,
                    sku="SKU-QUERY-ONLY",
                    oe_raw="1K0 121 251",
                    oe_norm="1K0121251",
                    name="Query-only brake pad",
                    category="brakes",
                    brand="KEMP",
                    identity_status="OE_CONFIRMED",
                    identity_reason="EXPLICIT_OE_TEST_FIXTURE",
                    product_url=None,
                    current_price=Decimal("850"),
                    currency="UAH",
                    is_available=True,
                    raw_row={},
                )
            )
            session.add(
                CatalogItem(
                    id=item_id_2,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    source_row=3,
                    sku="SKU-QUERY-ONLY-SECOND",
                    oe_raw="1K0 121 251",
                    oe_norm="1K0121251",
                    name="Second item sharing the same query",
                    category="brakes",
                    brand="KEMP",
                    identity_status="OE_CONFIRMED",
                    identity_reason="EXPLICIT_OE_TEST_FIXTURE",
                    product_url=None,
                    current_price=Decimal("860"),
                    currency="UAH",
                    is_available=True,
                    raw_row={},
                )
            )
            session.add(
                CatalogItem(
                    id=item_id_3,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    source_row=4,
                    sku="SKU-DIFFERENT-QUERY",
                    oe_raw="8K0 615 121",
                    oe_norm="8K0615121",
                    name="Item with a distinct query",
                    category="brakes",
                    brand="KEMP",
                    identity_status="OE_CONFIRMED",
                    identity_reason="EXPLICIT_OE_TEST_FIXTURE",
                    product_url=None,
                    current_price=Decimal("870"),
                    currency="UAH",
                    is_available=True,
                    raw_row={},
                )
            )
            await session.commit()
            run = await create_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                celery_app=fake_celery,
                source_mode="e2e_fixture_replay",
                start=TrustedRunStart(
                    confirmation_source=CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
                    reason="isolated e2e stack replays seeded fixtures",
                ),
            )
            targets = list(
                (
                    await session.scalars(
                        select(ScrapeTarget).where(
                            ScrapeTarget.pricing_run_id == run.id
                        )
                    )
                ).all()
            )
            run_items = list(
                (
                    await session.scalars(
                        select(PricingRunItem)
                        .where(PricingRunItem.pricing_run_id == run.id)
                        .order_by(PricingRunItem.id)
                    )
                ).all()
            )
            assert len(targets) == 2
            target = next(value for value in targets if value.query == "1K0121251")
            shared_items = [
                item for item in run_items if item.scrape_target_id == target.id
            ]
            assert len(run_items) == 3
            assert len(shared_items) == 2
            assert len({item.scrape_target_id for item in run_items}) == 2
            assert target.input_kind == "query"
            assert target.original_url is None
            assert target.canonical_url is None
            assert "invalid://" not in json.dumps(target.payload or {})

        first_claim = await _claim_item(
            shared_items[0].id,
            task_id="expired-lease-owner",
            is_redelivery=False,
        )
        assert first_claim is not None
        assert first_claim.action == "target_collect"
        async with async_session_factory() as session:
            leased_target = await session.get(ScrapeTarget, target.id)
            assert leased_target is not None
            leased_target.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        takeover_claim = await _claim_item(
            shared_items[1].id,
            task_id="expired-lease-redelivery",
            is_redelivery=True,
        )
        assert takeover_claim is not None
        assert takeover_claim.action == "target_collect"
        assert takeover_claim.fencing_token > first_claim.fencing_token
        async with async_session_factory() as session:
            superseded_attempt = await session.get(
                ScrapeAttempt,
                first_claim.scrape_attempt_id,
            )
            assert superseded_attempt is not None
            assert superseded_attempt.status == "worker_lost"

        assert isinstance(first_claim.scrape_input, QueryInput)
        stale_output = ScrapeOutput.from_search(first_claim.scrape_input, [])
        stale_trace = ScrapeExecutionTrace(
            item_kind="comparison_job",
            execution_no=first_claim.delivery_no,
        )
        try:
            stale_persisted = await _persist_target_success(
                first_claim,
                stale_trace,
                AttemptMeasurement(
                    wall_time_ms=1,
                    cpu_time_ms=1,
                    memory_peak_bytes=1,
                ),
                stale_output,
            )
        finally:
            stale_trace.close()
        assert stale_persisted is False
        async with async_session_factory() as session:
            fenced_target = await session.get(ScrapeTarget, target.id)
            assert fenced_target is not None
            assert fenced_target.owner_task_id == "expired-lease-redelivery"
            assert fenced_target.fencing_token == takeover_claim.fencing_token
            assert fenced_target.payload is None

        seeded = await seed_fixture_replay(run.id, DEFAULT_FIXTURE)
        assert seeded["live_requests"] == 0
        results = await asyncio.gather(
            process_pricing_item(shared_items[0].id, task_id="delivery-a"),
            process_pricing_item(
                shared_items[1].id,
                task_id="delivery-b",
                is_redelivery=True,
            ),
        )
        assert results == [run.id, run.id]

        async with async_session_factory() as session:
            all_observations = list(
                (
                    await session.scalars(
                        select(MarketObservation).where(
                            MarketObservation.pricing_run_item_id.in_(
                                [item.id for item in shared_items]
                            )
                        )
                    )
                ).all()
            )
            observations = [
                observation
                for observation in all_observations
                if observation.pricing_run_item_id == shared_items[0].id
            ]
            outcome_count = int(
                await session.scalar(
                    select(func.count(OfferProcessingOutcome.id)).where(
                        OfferProcessingOutcome.pricing_run_item_id.in_(
                            [item.id for item in shared_items]
                        )
                    )
                )
                or 0
            )
            capture_count = int(
                await session.scalar(
                    select(func.count(RawMarketCapture.id)).where(
                        RawMarketCapture.pricing_run_item_id.in_(
                            [item.id for item in shared_items]
                        )
                    )
                )
                or 0
            )
            assert len(all_observations) == 16
            assert len(observations) == 8
            assert outcome_count == 16
            assert capture_count == 2
            assert all(
                observation.oe_verification_status == "VERIFIED_EXACT"
                and observation.verified_matched_oe_norm
                in observation.extracted_oe_norms
                and observation.oe_extractor_version == OE_EXTRACTOR_VERSION
                for observation in observations
            )
            calibration_excluded_id = observations[0].id
            await session.execute(
                text(
                    "SELECT set_config('marko.identity_reenrichment', :version, true)"
                ),
                {"version": OE_EXTRACTOR_VERSION},
            )
            observations[0].automatic_eligible = False
            observations[0].oe_reenriched_at = datetime.now(UTC)
            await session.commit()

        await _materialize_target_evidence(target.id)
        async with async_session_factory() as session:
            assert (
                int(
                    await session.scalar(
                        select(func.count(OfferProcessingOutcome.id)).where(
                            OfferProcessingOutcome.pricing_run_item_id.in_(
                                [item.id for item in shared_items]
                            )
                        )
                    )
                    or 0
                )
                == outcome_count
            )
            persisted_run = await session.get(PricingRun, run.id)
            assert persisted_run is not None
            pairs = await _derive_calibration_pairs(
                session,
                run.id,
                policy_from_dict(persisted_run.policy_config),
            )
            await session.commit()
            assert pairs == []
            assert persisted_run.calibration_accounting["observations_considered"] == 16
            assert persisted_run.calibration_accounting["eligible_observations"] == 15
            assert persisted_run.calibration_accounting["excluded_observations"] == 1
            assert persisted_run.calibration_accounting[
                "exclusion_counts_by_reason"
            ] == {"CAL_NOT_AUTOMATIC_ELIGIBLE": 1}
            excluded = await session.get(MarketObservation, calibration_excluded_id)
            assert excluded is not None
            assert excluded.calibration_exclusion_codes == [
                "CAL_NOT_AUTOMATIC_ELIGIBLE"
            ]

            await session.execute(
                text(
                    "SELECT set_config('marko.identity_reenrichment', "
                    "'legacy-test-v0', true)"
                )
            )
            excluded.oe_extractor_version = "legacy-test-v0"
            excluded.oe_reenriched_at = datetime.now(UTC)
            await session.commit()

        async with async_session_factory() as session:
            report = await re_enrich_retained_observations_in_session(
                session,
                batch_size=1_000,
                dry_run=False,
            )
            assert report.updated >= 1
            assert report.network_requests == 0
        async with async_session_factory() as session:
            re_enriched = await session.get(
                MarketObservation,
                calibration_excluded_id,
            )
            assert re_enriched is not None
            assert re_enriched.oe_extractor_version == OE_EXTRACTOR_VERSION
            assert re_enriched.verified_matched_oe_norm in (
                re_enriched.extracted_oe_norms
            )
        async with async_session_factory() as session:
            outcome_id = await session.scalar(
                select(OfferProcessingOutcome.id).where(
                    OfferProcessingOutcome.pricing_run_item_id == shared_items[0].id
                )
            )
            assert outcome_id is not None
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(
                    text(
                        "UPDATE offer_processing_outcomes SET stage='mutated' "
                        "WHERE id=:id"
                    ),
                    {"id": outcome_id},
                )
                await session.commit()
            await session.rollback()
    finally:
        get_settings.cache_clear()
        try:
            await _delete_disposable_workspace(workspace_id)
        finally:
            await engine.dispose()


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_03_observations_and_outcome_ledger_rollback_atomically(
    monkeypatch,
) -> None:
    """A ledger constraint failure must leave no partial Metis evidence."""

    _require_disposable_database()
    monkeypatch.setenv("ENVIRONMENT", "e2e")
    monkeypatch.setenv("E2E_AUTH_BYPASS", "true")
    monkeypatch.setenv("E2E_AUTH_TOKEN", "p15017-integration-token-00000001")
    monkeypatch.setenv(
        "PRICING_BRAND_TIERS_PATH",
        str(BACKEND_ROOT / "src/marko/e2e/fixtures/brands.yaml"),
    )
    get_settings.cache_clear()
    workspace_id = uuid4()
    batch_id = uuid4()
    item_id = uuid4()
    accounting_item_id = uuid4()
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())
    try:
        async with async_session_factory() as session:
            session.add(
                Workspace(
                    id=workspace_id,
                    name="P15017 atomic rollback",
                    slug=f"p15017-rollback-{workspace_id.hex}",
                )
            )
            await session.flush()
            session.add(
                CatalogImportBatch(
                    id=batch_id,
                    workspace_id=workspace_id,
                    filename="query-only-rollback.xlsx",
                    content_sha256="d" * 64,
                    content_size=1,
                    status="completed",
                    column_mapping={"Код_товару": "oe"},
                    total_rows=2,
                    imported_rows=2,
                    rejected_rows=0,
                    error_log=[],
                )
            )
            await session.flush()
            session.add(
                CatalogItem(
                    id=item_id,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    source_row=2,
                    sku="SKU-ROLLBACK",
                    oe_raw="1K0 121 251",
                    oe_norm="1K0121251",
                    name="Atomic rollback brake pad",
                    category="brakes",
                    brand="KEMP",
                    identity_status="OE_CONFIRMED",
                    identity_reason="EXPLICIT_OE_TEST_FIXTURE",
                    product_url=None,
                    current_price=Decimal("850"),
                    currency="UAH",
                    is_available=True,
                    raw_row={},
                )
            )
            session.add(
                CatalogItem(
                    id=accounting_item_id,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    source_row=3,
                    sku="SKU-ACCOUNTING-ERROR",
                    oe_raw="8K0 615 121",
                    oe_norm="8K0615121",
                    name="Accounting error brake pad",
                    category="brakes",
                    brand="KEMP",
                    identity_status="OE_CONFIRMED",
                    identity_reason="EXPLICIT_OE_TEST_FIXTURE",
                    product_url=None,
                    current_price=Decimal("900"),
                    currency="UAH",
                    is_available=True,
                    raw_row={},
                )
            )
            await session.commit()
            run = await create_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                celery_app=fake_celery,
                source_mode="e2e_fixture_replay",
                start=TrustedRunStart(
                    confirmation_source=CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
                    reason="isolated e2e stack replays seeded fixtures",
                ),
            )
            targets = list(
                (
                    await session.scalars(
                        select(ScrapeTarget).where(
                            ScrapeTarget.pricing_run_id == run.id
                        )
                    )
                ).all()
            )
            run_items = list(
                (
                    await session.scalars(
                        select(PricingRunItem).where(
                            PricingRunItem.pricing_run_id == run.id
                        )
                    )
                ).all()
            )
            assert len(targets) == 2
            target = next(value for value in targets if value.query == "1K0121251")
            accounting_target = next(
                value for value in targets if value.query == "8K0615121"
            )
            run_item = next(
                value for value in run_items if value.catalog_item_id == item_id
            )
            accounting_run_item = next(
                value
                for value in run_items
                if value.catalog_item_id == accounting_item_id
            )

        await seed_fixture_replay(run.id, DEFAULT_FIXTURE)
        from marko.services import market_collection

        original_offer_outcome = market_collection._offer_outcome

        def duplicate_ledger_index(**kwargs):
            outcome = original_offer_outcome(**kwargs)
            outcome.raw_offer_index = 0
            return outcome

        monkeypatch.setattr(
            market_collection,
            "_offer_outcome",
            duplicate_ledger_index,
        )
        with pytest.raises(IntegrityError):
            await market_collection._materialize_target_evidence(target.id)

        async with async_session_factory() as session:
            assert (
                int(
                    await session.scalar(
                        select(func.count(RawMarketCapture.id)).where(
                            RawMarketCapture.pricing_run_item_id == run_item.id
                        )
                    )
                    or 0
                )
                == 0
            )
            assert (
                int(
                    await session.scalar(
                        select(func.count(MarketObservation.id)).where(
                            MarketObservation.pricing_run_item_id == run_item.id
                        )
                    )
                    or 0
                )
                == 0
            )
            assert (
                int(
                    await session.scalar(
                        select(func.count(OfferProcessingOutcome.id)).where(
                            OfferProcessingOutcome.pricing_run_item_id == run_item.id
                        )
                    )
                    or 0
                )
                == 0
            )

        monkeypatch.setattr(
            market_collection,
            "_offer_outcome",
            original_offer_outcome,
        )
        await market_collection._materialize_target_evidence(target.id)
        async with async_session_factory() as session:
            assert (
                int(
                    await session.scalar(
                        select(func.count(RawMarketCapture.id)).where(
                            RawMarketCapture.pricing_run_item_id == run_item.id
                        )
                    )
                    or 0
                )
                == 1
            )
            assert (
                int(
                    await session.scalar(
                        select(func.count(OfferProcessingOutcome.id)).where(
                            OfferProcessingOutcome.pricing_run_item_id == run_item.id
                        )
                    )
                    or 0
                )
                == 8
            )

        async def invalid_accounting(*_args, **_kwargs):
            return OfferAccounting(
                retrieved=8,
                observations_persisted=0,
                rejected=0,
                internal_failures=0,
            )

        monkeypatch.setattr(
            market_collection,
            "_persist_payload_observations",
            invalid_accounting,
        )
        with pytest.raises(EvidenceAccountingError, match=r"R != O \+ J \+ F"):
            await market_collection._materialize_target_evidence(accounting_target.id)

        async with async_session_factory() as session:
            failed_target = await session.get(ScrapeTarget, accounting_target.id)
            failed_item = await session.get(
                PricingRunItem,
                accounting_run_item.id,
            )
            assert failed_target is not None
            assert failed_item is not None
            assert failed_target.error_category == "EVIDENCE_ACCOUNTING_ERROR"
            assert failed_target.downstream_eligibility == "INELIGIBLE"
            assert failed_item.status == "failed"
            assert (
                int(
                    await session.scalar(
                        select(func.count(RawMarketCapture.id)).where(
                            RawMarketCapture.pricing_run_item_id
                            == accounting_run_item.id
                        )
                    )
                    or 0
                )
                == 0
            )
    finally:
        get_settings.cache_clear()
        try:
            await _delete_disposable_workspace(workspace_id)
        finally:
            await engine.dispose()
