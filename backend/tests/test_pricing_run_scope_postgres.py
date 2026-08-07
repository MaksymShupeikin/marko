"""Opt-in PostgreSQL proof for the bounded, immutable pricing-run contract.

Требуется одноразовая база, имя которой содержит ``p15017``: набор выполняет
Alembic upgrade/downgrade и намеренно провоцирует гонки на уникальных индексах.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from marko.core.config import get_settings
from marko.infrastructure.db.models import (
    CatalogIdentityLink,
    CatalogImportBatch,
    CatalogItem,
    CatalogItemOverride,
    CrossLink,
    FitmentAnalysis,
    FitmentCandidateAssessment,
    FitmentCrossReference,
    FitmentEvidenceClaim,
    FitmentSource,
    FitmentSourceDocument,
    MarketObservation,
    PricingRecommendation,
    PricingRun,
    PricingRunItem,
    RawMarketCapture,
    ScrapeTarget,
    Workspace,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services import market_collection as market_collection_service
from marko.services.catalog_identity_safety import (
    active_identity_graph_config,
    active_identity_runtime_sha256,
)
from marko.services.dead_letters import (
    DeadLetterReplayError,
    replay_dead_letter,
)
from marko.services.fitment_intelligence import FITMENT_CROSS_METHOD_VERSION
from marko.services.market_collection import (
    _calculate_and_persist,
    process_pricing_item,
)
from marko.services.pricing_runs import (
    ACTOR_TYPE_USER,
    CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
    CONFIRMATION_SOURCE_SYSTEM_REPLAY,
    EXPLICIT_ITEMS_SCOPE,
    FULL_CATALOG_SCOPE,
    PRICING_RUN_SCOPE_CONTRACT_VERSION,
    PRICING_RUN_START_PERMISSION,
    SCOPE_MANIFEST_ADVISORY_SECTION,
    SCOPE_MANIFEST_EXECUTION_SECTION,
    SCOPE_MANIFEST_PROVENANCE_SECTION,
    OperatorRunStart,
    PreviewActor,
    PricingRunActiveScopeConflictError,
    PricingRunIdempotencyConflictError,
    PricingRunScopeConflictError,
    TrustedRunStart,
    create_pricing_run,
    load_run_item_start_override,
    load_scope_candidates,
    preview_pricing_run,
    preview_pricing_run_for_operator,
    scope_manifest_hash,
)

pytestmark = pytest.mark.postgres
BACKEND_ROOT = Path(__file__).resolve().parents[1]
APPEND_ONLY_TABLES = (
    "catalog_item_overrides",
    "fitment_candidate_assessments",
    "fitment_cross_references",
    "fitment_evidence_claims",
    "fitment_source_documents",
    "fitment_sources",
    "market_observations",
    "raw_market_captures",
)


def _postgres_enabled() -> bool:
    return os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") == "1"


def _require_disposable_database() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    database_name = make_url(database_url).database or ""
    if "p15017" not in database_name.casefold():
        pytest.fail(
            "Refusing scope-contract test: DATABASE_URL must name a disposable "
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


def _operator_actor(**overrides) -> PreviewActor:
    kwargs: dict[str, object] = {
        "actor_id": "00000000-0000-0000-0000-0000000000ff",
        "actor_type": ACTOR_TYPE_USER,
        "workspace_role": "admin",
        "permissions": (PRICING_RUN_START_PERMISSION,),
    }
    kwargs.update(overrides)
    return PreviewActor(**kwargs)


async def _issued_preview(
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
    scope_mode: str,
    catalog_item_ids: list[UUID] | None = None,
    actor: PreviewActor | None = None,
    policy_config: dict | None = None,
    confirm_full_catalog: bool | None = None,
):
    """Предпросмотр оператора вместе с выданным сервером контрактом."""

    if confirm_full_catalog is None:
        confirm_full_catalog = scope_mode == FULL_CATALOG_SCOPE
    async with async_session_factory() as session:
        scope, contract = await preview_pricing_run_for_operator(
            session,
            workspace_id=workspace_id,
            import_batch_id=import_batch_id,
            actor=actor or _operator_actor(),
            scope_mode=scope_mode,
            catalog_item_ids=catalog_item_ids,
            policy_config=policy_config,
            confirm_full_catalog=confirm_full_catalog,
        )
        await session.commit()
    return scope, contract


def _replay_start(**overrides) -> TrustedRunStart:
    """Доверенный путь подстановки фикстур — единственный способ стартовать здесь."""

    kwargs: dict[str, object] = {
        "confirmation_source": CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
        "reason": "isolated e2e stack replays seeded fixtures",
    }
    kwargs.update(overrides)
    return TrustedRunStart(**kwargs)


def _e2e_replay_environment(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "e2e")
    monkeypatch.setenv("E2E_AUTH_BYPASS", "true")
    monkeypatch.setenv("E2E_AUTH_TOKEN", "p15017-integration-token-00000001")
    monkeypatch.setenv(
        "PRICING_BRAND_TIERS_PATH",
        str(BACKEND_ROOT / "src/marko/e2e/fixtures/brands.yaml"),
    )
    get_settings.cache_clear()


def _authorized_source_environment(monkeypatch) -> None:
    """Развёртывание с записанным разрешением на сбор — путь повтора живой.

    Сеть здесь не задействована: допуск ``admit_prom_public_item`` — это
    решение политики, а исполнение прогона отдано подменённому Celery.
    """

    monkeypatch.setenv(
        "PRICING_BRAND_TIERS_PATH",
        str(BACKEND_ROOT / "src/marko/e2e/fixtures/brands.yaml"),
    )
    monkeypatch.setenv("PROM_MARKETPLACE_SOURCE_ACCESS_VERDICT", "PERMITTED_LIMITED")
    monkeypatch.setenv(
        "PROM_MARKETPLACE_SOURCE_ACCESS_REFERENCE",
        "p15017-disposable-authorization-record",
    )
    get_settings.cache_clear()


async def _fail_run_with_a_dead_letter(run_id: UUID) -> UUID:
    """Довести прогон до терминального отказа и вернуть id мёртвого письма."""

    async with async_session_factory() as session:
        await session.execute(
            text("UPDATE pricing_runs SET status = 'failed' WHERE id = :id"),
            {"id": run_id},
        )
        await session.execute(
            text(
                "UPDATE scrape_targets SET status = 'terminal_failure', "
                "execution_status = 'TERMINAL_FAILED', "
                "error_category = 'network', "
                "error_detail = 'p15017 disposable failure', "
                "finished_at = now() WHERE pricing_run_id = :id"
            ),
            {"id": run_id},
        )
        await session.commit()
        target_id = await session.scalar(
            select(ScrapeTarget.id)
            .where(ScrapeTarget.pricing_run_id == run_id)
            .order_by(ScrapeTarget.id)
            .limit(1)
        )
    assert target_id is not None
    return target_id


async def _delete_disposable_workspace(workspace_id: UUID) -> None:
    async with async_session_factory() as session:
        try:
            for table_name in APPEND_ONLY_TABLES:
                await session.execute(
                    text(
                        f"ALTER TABLE {table_name} "
                        f"DISABLE TRIGGER trg_{table_name}_append_only"
                    )
                )
            # Членство прогона держит позицию каталога через RESTRICT (миграция
            # 0033): улику расчёта нельзя унести задним числом.  Одноразовая
            # уборка снимает сначала прогоны, а не ослабляет это правило.
            analysis_ids = select(FitmentAnalysis.id).where(
                FitmentAnalysis.workspace_id == workspace_id
            )
            source_ids = select(FitmentSource.id).where(
                FitmentSource.workspace_id == workspace_id
            )
            run_item_ids = (
                select(PricingRunItem.id)
                .join(PricingRun)
                .where(PricingRun.workspace_id == workspace_id)
            )
            await session.execute(
                delete(FitmentEvidenceClaim).where(
                    FitmentEvidenceClaim.analysis_id.in_(analysis_ids)
                )
            )
            await session.execute(
                delete(FitmentCandidateAssessment).where(
                    FitmentCandidateAssessment.analysis_id.in_(analysis_ids)
                )
            )
            await session.execute(
                delete(FitmentAnalysis).where(
                    FitmentAnalysis.workspace_id == workspace_id
                )
            )
            await session.execute(
                delete(FitmentSourceDocument).where(
                    FitmentSourceDocument.source_id.in_(source_ids)
                )
            )
            await session.execute(
                delete(FitmentSource).where(FitmentSource.workspace_id == workspace_id)
            )
            await session.execute(
                delete(MarketObservation).where(
                    MarketObservation.pricing_run_item_id.in_(run_item_ids)
                )
            )
            await session.execute(
                delete(RawMarketCapture).where(
                    RawMarketCapture.pricing_run_item_id.in_(run_item_ids)
                )
            )
            await session.execute(
                delete(CrossLink).where(CrossLink.workspace_id == workspace_id)
            )
            await session.execute(
                delete(CatalogIdentityLink).where(
                    CatalogIdentityLink.workspace_id == workspace_id
                )
            )
            await session.execute(
                delete(PricingRun).where(PricingRun.workspace_id == workspace_id)
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


async def _seed_catalog(
    *,
    workspace_id: UUID,
    batch_id: UUID,
    item_ids: tuple[UUID, ...],
) -> None:
    async with async_session_factory() as session:
        session.add(
            Workspace(
                id=workspace_id,
                name="P15017 bounded run",
                slug=f"p15017-scope-{workspace_id.hex}",
            )
        )
        await session.flush()
        session.add(
            CatalogImportBatch(
                id=batch_id,
                workspace_id=workspace_id,
                filename="bounded-run.xlsx",
                content_sha256="d" * 64,
                content_size=1,
                status="completed",
                column_mapping={"Код_товару": "oe"},
                total_rows=len(item_ids),
                imported_rows=len(item_ids),
                rejected_rows=0,
                error_log=[],
            )
        )
        await session.flush()
        for position, item_id in enumerate(item_ids):
            session.add(
                CatalogItem(
                    id=item_id,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    source_row=position + 2,
                    sku=f"SKU-SCOPE-{position}",
                    oe_raw=f"1K0 12125{position}",
                    oe_norm=f"1K012125{position}",
                    name=f"Позиция каталога {position}",
                    category="brakes",
                    brand="KEMP",
                    identity_status="OE_CONFIRMED",
                    identity_reason="EXPLICIT_OE_COLUMN",
                    product_url=None,
                    current_price=Decimal("800") + position,
                    currency="UAH",
                    is_available=True,
                    raw_row={},
                )
            )
        await session.commit()


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_missing_customer_identity_is_terminal_without_network_or_url_dedup(
    monkeypatch,
) -> None:
    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id = uuid4()
    batch_id = uuid4()
    identified_id, missing_id = uuid4(), uuid4()
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())
    shared_url = "https://example.test/catalog/shared-product"
    network_called = False

    def _network_must_not_run(*_args, **_kwargs):
        nonlocal network_called
        network_called = True
        raise AssertionError("missing customer identity reached network collection")

    monkeypatch.setattr(
        market_collection_service,
        "_collect_target_output",
        _network_must_not_run,
    )
    try:
        await _seed_catalog(
            workspace_id=workspace_id,
            batch_id=batch_id,
            item_ids=(identified_id, missing_id),
        )
        async with async_session_factory() as session:
            identified = await session.get(CatalogItem, identified_id)
            missing = await session.get(CatalogItem, missing_id)
            assert identified is not None and missing is not None
            identified.product_url = shared_url
            missing.product_url = shared_url
            missing.identity_status = "UNRESOLVED"
            missing.identity_reason = "CUSTOMER_IDENTITY_MISSING"
            missing.mpn_raw = ""
            missing.mpn_norm = ""
            await session.commit()

        async with async_session_factory() as session:
            preview = await preview_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                scope_mode=EXPLICIT_ITEMS_SCOPE,
                catalog_item_ids=[identified_id, missing_id],
            )
        assert preview.estimate.eligible_items == 2
        assert preview.estimate.network_eligible_items == 1
        assert preview.estimate.identity_blocked_items == 1
        assert preview.estimate.unique_scrape_inputs == 1

        async with async_session_factory() as session:
            run = await create_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                celery_app=fake_celery,
                source_mode="e2e_fixture_replay",
                scope_mode=EXPLICIT_ITEMS_SCOPE,
                catalog_item_ids=[identified_id, missing_id],
                start=_replay_start(
                    expected_scope_hash=preview.scope_hash,
                    expected_catalog_snapshot_hash=preview.catalog_snapshot_hash,
                ),
            )
            run_id = run.id

        async with async_session_factory() as session:
            targets = list(
                (
                    await session.scalars(
                        select(ScrapeTarget)
                        .where(ScrapeTarget.pricing_run_id == run_id)
                        .order_by(ScrapeTarget.input_hash)
                    )
                ).all()
            )
            assert len(targets) == 2, "blocked row deduplicated onto a valid URL target"
            missing_item = await session.scalar(
                select(PricingRunItem).where(
                    PricingRunItem.pricing_run_id == run_id,
                    PricingRunItem.catalog_item_id == missing_id,
                )
            )
            assert missing_item is not None
            missing_run_item_id = missing_item.id
            missing_target = await session.get(
                ScrapeTarget, missing_item.scrape_target_id
            )
            assert missing_target is not None
            assert missing_target.status == "terminal_failure"
            assert missing_target.execution_status == "TERMINAL_FAILED"
            assert missing_target.acquisition_status == "BLOCKED"
            assert missing_target.error_category == "customer_identity_missing"
            assert missing_target.reason_codes == ["customer_identity_missing"]
            assert missing_target.network_attempts == 0
            assert missing_target.query == ""

        # Simulate a stale/replayed target being reset to a collectable state.
        # The worker must re-check the frozen customer namespace instead of
        # trusting the target status and sending the MPN-only row to Prom.
        async with async_session_factory() as session:
            missing_item = await session.get(PricingRunItem, missing_run_item_id)
            assert missing_item is not None
            stale_target = await session.get(ScrapeTarget, missing_item.scrape_target_id)
            assert stale_target is not None
            stale_target.status = "queued"
            stale_target.execution_status = "QUEUED"
            stale_target.acquisition_status = "NOT_STARTED"
            stale_target.parse_status = "NOT_STARTED"
            stale_target.evidence_status = "NONE"
            stale_target.downstream_eligibility = "UNKNOWN"
            stale_target.reason_codes = []
            stale_target.error_category = None
            stale_target.error_detail = None
            stale_target.finished_at = None
            missing_item.status = "queued"
            await session.commit()

        assert (
            await process_pricing_item(
                missing_run_item_id,
                task_id="missing-identity-test",
            )
            == run_id
        )
        assert network_called is False
        async with async_session_factory() as session:
            missing_item = await session.get(PricingRunItem, missing_run_item_id)
            assert missing_item is not None
            assert missing_item.status == "classified"
            assert missing_item.checkpoint["reason"] == "customer_identity_missing"
            missing_target = await session.get(
                ScrapeTarget, missing_item.scrape_target_id
            )
            assert missing_target is not None
            assert missing_target.network_attempts == 0
    finally:
        await _delete_disposable_workspace(workspace_id)
        get_settings.cache_clear()


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_concurrent_creates_yield_exactly_one_active_run(monkeypatch) -> None:
    """Две одновременные попытки старта обязаны оставить ровно один активный прогон."""

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id = uuid4()
    batch_id = uuid4()
    item_ids = (uuid4(), uuid4())
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )

        started = asyncio.Event()
        arrived = 0
        lock = asyncio.Lock()

        async def _create() -> UUID | None:
            nonlocal arrived
            async with async_session_factory() as session:
                # Обе задачи входят в create_pricing_run одновременно: это и есть
                # окно между «racy SELECT» и вставкой строки.
                async with lock:
                    arrived += 1
                    if arrived == 2:
                        started.set()
                await started.wait()
                try:
                    run = await create_pricing_run(
                        session,
                        workspace_id=workspace_id,
                        import_batch_id=batch_id,
                        celery_app=fake_celery,
                        source_mode="e2e_fixture_replay",
                        start=_replay_start(),
                    )
                except Exception:  # noqa: BLE001 - проигравший может упасть
                    await session.rollback()
                    return None
                return run.id

        results = await asyncio.gather(_create(), _create())

        async with async_session_factory() as session:
            runs = list(
                (
                    await session.scalars(
                        select(PricingRun).where(
                            PricingRun.workspace_id == workspace_id,
                            PricingRun.import_batch_id == batch_id,
                        )
                    )
                ).all()
            )
        assert len(runs) == 1, (
            "гонка создала несколько активных прогонов: "
            f"{[str(run.id) for run in runs]}"
        )
        # Проигравший обязан вернуть победителя, а не упасть: иначе уникальный
        # индекс просто превращает гонку в случайную ошибку оператора.
        assert results == [runs[0].id, runs[0].id], results
    finally:
        await _delete_disposable_workspace(workspace_id)
        get_settings.cache_clear()


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_preview_freezes_the_scope_and_the_start_time_replay_inputs(
    monkeypatch,
) -> None:
    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id = uuid4()
    batch_id = uuid4()
    item_ids = (uuid4(), uuid4(), uuid4())
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        override_id = uuid4()
        async with async_session_factory() as session:
            session.add_all(
                [
                    CatalogItemOverride(
                        id=override_id,
                        catalog_item_id=item_ids[0],
                        user_id=None,
                        stock_status="dead_stock",
                        reason="Правка оператора до старта прогона",
                    ),
                    CatalogIdentityLink(
                        id=uuid4(),
                        workspace_id=workspace_id,
                        catalog_item_id=item_ids[0],
                        our_oem_norm="1K0121250",
                        extracted_oem_norm="7L6121253C",
                        extracted_raw="7L6 121 253 C",
                        raw_context="customer reference row",
                        extraction_method="KEMP_REFERENCE_MAP_V2",
                        validation_status="CONFIRMED",
                        anomaly=None,
                        corroborating_sources=["KEMP_REFERENCE_MAP_V2"],
                        validation_details={
                            "source": "customer_reference",
                            "confidence": "0.90",
                            "automatic_eligible": True,
                        },
                        method_version=active_identity_graph_config().method_version,
                        config_sha256=active_identity_runtime_sha256(),
                    ),
                ]
            )
            await session.commit()

        async with async_session_factory() as session:
            preview = await preview_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                scope_mode=EXPLICIT_ITEMS_SCOPE,
                catalog_item_ids=[item_ids[0], item_ids[1]],
            )
        assert preview.estimate.eligible_items == 2
        assert preview.requires_full_catalog_confirmation is False
        # Предпросмотр не создаёт прогон.
        async with async_session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count(PricingRun.id)).where(
                        PricingRun.workspace_id == workspace_id
                    )
                )
                == 0
            )

        async with async_session_factory() as session:
            run = await create_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                celery_app=fake_celery,
                source_mode="e2e_fixture_replay",
                scope_mode=EXPLICIT_ITEMS_SCOPE,
                catalog_item_ids=[item_ids[0], item_ids[1]],
                start=_replay_start(
                    expected_scope_hash=preview.scope_hash,
                    expected_catalog_snapshot_hash=preview.catalog_snapshot_hash,
                ),
            )
            run_id = run.id
            assert run.scope_contract_version == PRICING_RUN_SCOPE_CONTRACT_VERSION
            assert run.scope_hash == preview.scope_hash
            assert run.catalog_snapshot_hash == preview.catalog_snapshot_hash
            assert run.scope_mode == EXPLICIT_ITEMS_SCOPE
            assert run.total_items == 2
            assert (
                run.scope_manifest[SCOPE_MANIFEST_ADVISORY_SECTION]["estimate"][
                    "eligible_items"
                ]
                == 2
            )
            # Сохранённый манифест сам себя удостоверяет: хеш прогона — это хеш
            # его же канонических байт, а не отдельно посчитанный отпечаток.
            assert scope_manifest_hash(run.scope_manifest) == run.scope_hash

        # Правка, поданная уже после старта, не должна попасть в идущий прогон.
        async with async_session_factory() as session:
            session.add(
                CatalogItemOverride(
                    id=uuid4(),
                    catalog_item_id=item_ids[0],
                    user_id=None,
                    stock_status="fresh",
                    reason="Правка оператора после старта прогона",
                )
            )
            await session.commit()

        async with async_session_factory() as session:
            run_items = list(
                (
                    await session.scalars(
                        select(PricingRunItem)
                        .where(PricingRunItem.pricing_run_id == run_id)
                        .order_by(PricingRunItem.idempotency_key)
                    )
                ).all()
            )
            assert len(run_items) == 2
            assert {item.catalog_item_id for item in run_items} == {
                item_ids[0],
                item_ids[1],
            }
            frozen = next(
                item for item in run_items if item.catalog_item_id == item_ids[0]
            )
            assert frozen.catalog_item_override_id == override_id
            assert frozen.start_snapshot["catalog_item_override_id"] == str(override_id)
            assert frozen.start_snapshot["current_price"] == "800.00"
            assert len(frozen.start_snapshot["confirmed_identity_links"]) == 1
            frozen_cross = await session.scalar(
                select(CrossLink).where(
                    CrossLink.pricing_run_id == run_id,
                    CrossLink.our_oem_norm == "1K0121250",
                    CrossLink.extracted_oem_norm == "7L6121253C",
                )
            )
            assert frozen_cross is not None
            assert frozen_cross.validation_status == "CONFIRMED"
            assert frozen_cross.extraction_method == "CATALOG_IDENTITY_SNAPSHOT"
            assert frozen_cross.validation_details["evidence_kind"] == (
                "FROZEN_CATALOG_IDENTITY"
            )
            replay_override = await load_run_item_start_override(session, frozen)
            assert replay_override is not None
            assert replay_override.id == override_id
            assert replay_override.stock_status == "dead_stock"
    finally:
        await _delete_disposable_workspace(workspace_id)
        get_settings.cache_clear()


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_scope_loader_rejects_fanout_private_and_stale_identity_edges() -> None:
    """Only current, one-item, public identities may widen a pricing scope."""

    _require_disposable_database()
    workspace_id = uuid4()
    batch_id = uuid4()
    item_ids = (uuid4(), uuid4(), uuid4())
    active_method = active_identity_graph_config().method_version
    active_hash = active_identity_runtime_sha256()

    def link(
        item_id: UUID,
        our_oem: str,
        extracted_oem: str,
        *,
        method: str = active_method,
        config_hash: str = active_hash,
    ) -> CatalogIdentityLink:
        return CatalogIdentityLink(
            id=uuid4(),
            workspace_id=workspace_id,
            catalog_item_id=item_id,
            our_oem_norm=our_oem,
            extracted_oem_norm=extracted_oem,
            extracted_raw=extracted_oem,
            raw_context="p15017 identity safety",
            extraction_method="KEMP_REFERENCE_MAP_V2",
            validation_status="CONFIRMED",
            anomaly=None,
            corroborating_sources=["KEMP_REFERENCE_MAP_V2"],
            validation_details={
                "confidence": "0.90",
                "automatic_eligible": True,
            },
            method_version=method,
            config_sha256=config_hash,
        )

    try:
        await _seed_catalog(
            workspace_id=workspace_id,
            batch_id=batch_id,
            item_ids=item_ids,
        )
        async with async_session_factory() as session:
            session.add_all(
                [
                    # Same number claims two catalog items: both edges fail
                    # closed even though each row says CONFIRMED.
                    link(item_ids[0], "1K0121250", "SHARED777"),
                    link(item_ids[1], "1K0121251", "SHARED777"),
                    # A private shelf value is not a part identity.
                    link(item_ids[2], "1K0121252", "77643352C"),
                    # An edge from an older algorithm cannot be revived.
                    link(
                        item_ids[2],
                        "1K0121252",
                        "STALE123",
                        method="identity-graph-v1",
                    ),
                    # Control: one current, public, unambiguous edge survives.
                    link(item_ids[2], "1K0121252", "SAFE123"),
                ]
            )
            await session.commit()

        async with async_session_factory() as session:
            candidates = await load_scope_candidates(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
            )

        by_id = {candidate.catalog_item_id: candidate for candidate in candidates}
        assert by_id[item_ids[0]].confirmed_identity_links == ()
        assert by_id[item_ids[1]].confirmed_identity_links == ()
        links = by_id[item_ids[2]].confirmed_identity_links
        assert [entry["extracted_oem_norm"] for entry in links] == ["SAFE123"]
    finally:
        await _delete_disposable_workspace(workspace_id)


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_scope_loader_freezes_only_effective_verified_fitment_crosses() -> None:
    _require_disposable_database()
    workspace_id = uuid4()
    batch_id = uuid4()
    item_ids = (uuid4(), uuid4(), uuid4())
    now = datetime.now(UTC)
    evidence_claim_id = uuid4()
    weak_claim_id = uuid4()
    wrong_numbers_claim_id = uuid4()

    def cross(
        position: int,
        article: str,
        *,
        status: str = "source_confirmed",
        installation_position: str | None = None,
        evidence_ids: list[str] | None = None,
        source_count: int = 2,
        fingerprint: str,
    ) -> FitmentCrossReference:
        return FitmentCrossReference(
            id=uuid4(),
            workspace_id=workspace_id,
            brand="External catalog",
            normalized_brand="externalcatalog",
            article=article,
            normalized_article=article,
            oe=f"1K012125{position}",
            normalized_oe=f"1K012125{position}",
            installation_position=installation_position,
            vehicle_key=None,
            relation_status=status,
            confidence=Decimal("0.90"),
            evidence_ids=evidence_ids or [str(uuid4()), str(uuid4())],
            source_count=source_count,
            human_feedback_count=1 if status == "human_rejected" else 0,
            record_fingerprint=fingerprint,
            method_version=FITMENT_CROSS_METHOD_VERSION,
            valid_from=now,
            last_verified_at=now,
        )

    try:
        await _seed_catalog(
            workspace_id=workspace_id,
            batch_id=batch_id,
            item_ids=item_ids,
        )
        async with async_session_factory() as session:
            source_id = uuid4()
            document_id = uuid4()
            run_id = uuid4()
            run_item_id = uuid4()
            capture_id = uuid4()
            observation_id = uuid4()
            analysis_id = uuid4()
            assessment_id = uuid4()
            source_url = "https://catalog.example.test/cross/EXTA123"
            session.add(
                FitmentSource(
                    id=source_id,
                    workspace_id=workspace_id,
                    source_key="official-cross-catalog",
                    source_type="official_catalog",
                    source_tier="A",
                    base_reliability=Decimal("0.95"),
                    domain="catalog.example.test",
                    access_method="licensed_api",
                    access_status="PERMITTED",
                    access_reference="p15017-authority-fixture",
                    robots_checked=True,
                    terms_checked=True,
                    rate_limit="1/min",
                    cache_policy="fact-level-only",
                    policy_version="authority-v1",
                    reviewed_at=now,
                )
            )
            await session.flush()
            session.add(
                FitmentSourceDocument(
                    id=document_id,
                    source_id=source_id,
                    source_url=source_url,
                    retrieval_query="1K0121250",
                    content_sha256="e" * 64,
                    content_locator="fixture://official-cross-catalog/EXTA123",
                    response_metadata={"data_class": "synthetic_adversarial"},
                    retrieved_at=now,
                    expires_at=now + timedelta(days=30),
                )
            )
            session.add(
                PricingRun(
                    id=run_id,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    status="failed",
                    policy_version="authority-fixture-v1",
                    policy_config={},
                    parser_version="fixture-v1",
                    error="authority fixture",
                    finished_at=now,
                )
            )
            await session.flush()
            session.add(
                PricingRunItem(
                    id=run_item_id,
                    pricing_run_id=run_id,
                    catalog_item_id=item_ids[0],
                    status="collected",
                    idempotency_key=f"authority:{run_item_id}",
                    attempts=1,
                )
            )
            await session.flush()
            session.add(
                RawMarketCapture(
                    id=capture_id,
                    pricing_run_item_id=run_item_id,
                    source="fixture",
                    capture_kind="test_fixture",
                    payload={"synthetic": True},
                    content_sha256="f" * 64,
                    parser_version="fixture-v1",
                )
            )
            await session.flush()
            session.add(
                MarketObservation(
                    id=observation_id,
                    pricing_run_item_id=run_item_id,
                    catalog_item_id=item_ids[0],
                    raw_capture_id=capture_id,
                    source="fixture",
                    source_listing_id="authority-listing-1",
                    seller_id="authority-seller",
                    seller_name="Independent authority fixture",
                    url="https://market.example.test/EXTA123",
                    title="External cross EXTA123",
                    description="Synthetic persisted authority chain",
                    description_available=True,
                    condition_raw="new",
                    condition_state="NEW",
                    condition_reason_codes=["FIXTURE"],
                    cross_candidates=[],
                    brand_raw="External catalog",
                    search_oe_norm="1K0121250",
                    extracted_oe_norms=["1K0121250"],
                    oe_verification_status="UNKNOWN",
                    oe_evidence=[],
                    price=Decimal("1000"),
                    currency="UAH",
                    currency_raw="UAH",
                    is_available=True,
                    match_confidence=Decimal("0.95"),
                    source_confidence=Decimal("0.55"),
                    source_confidence_factors={"fixture": "0.55"},
                    source_confidence_method_version="fixture-v1",
                    parser_version="fixture-v1",
                    calibration_exclusion_codes=["SYNTHETIC_FIXTURE"],
                    observed_at=now,
                )
            )
            session.add(
                FitmentAnalysis(
                    id=analysis_id,
                    workspace_id=workspace_id,
                    catalog_item_id=item_ids[0],
                    pricing_run_id=run_id,
                    idempotency_key=f"authority-{analysis_id.hex}"[:64],
                    status="completed",
                    workflow_state="FITMENT_EVALUATED",
                    target_identity={"oe_numbers": ["1K0121250"]},
                    target_commercial_context={"currency": "UAH"},
                    source_policy_snapshot={"policy": "authority-v1"},
                    request_payload={},
                    contract_version="fitment-contract-v1",
                    scoring_version="fitment-score-v1",
                    request_sha256="1" * 64,
                    finished_at=now,
                )
            )
            await session.flush()
            session.add(
                FitmentCandidateAssessment(
                    id=assessment_id,
                    analysis_id=analysis_id,
                    market_observation_id=observation_id,
                    candidate_identity={"manufacturer_article": "EXTA123"},
                    candidate_commercial_context={"currency": "UAH"},
                    compatibility_status="confirmed_compatible",
                    compatibility_probability=Decimal("0.99"),
                    positive_evidence=Decimal("1"),
                    negative_evidence=Decimal("0"),
                    coverage=Decimal("1"),
                    contradiction_rate=Decimal("0"),
                    missing_critical_ratio=Decimal("0"),
                    hard_rejections=[],
                    reason_codes=["AUTHORITATIVE_CROSS"],
                    missing_critical_fields=[],
                    feature_consensus={},
                    authoritative_confirmation=True,
                    requires_manual_review=False,
                    evidence_ids=[
                        str(evidence_claim_id),
                        str(weak_claim_id),
                        str(wrong_numbers_claim_id),
                    ],
                    price_comparability_status="manual_review",
                    price_eligible=False,
                    competitor_weight=Decimal("0"),
                    price_factor_trace={},
                    price_reason_codes=["IDENTITY_ONLY"],
                    contract_version="fitment-contract-v1",
                    scoring_version="fitment-score-v1",
                )
            )
            await session.flush()
            session.add(
                FitmentEvidenceClaim(
                    id=evidence_claim_id,
                    analysis_id=analysis_id,
                    assessment_id=assessment_id,
                    source_document_id=document_id,
                    evidence_key=f"authority:{evidence_claim_id}",
                    feature="cross_confirmed",
                    evidence_value=Decimal("1"),
                    source_external_id="official-cross-catalog",
                    source_type="official_catalog",
                    source_tier="A",
                    source_reliability=Decimal("0.95"),
                    extraction_confidence=Decimal("0.99"),
                    directness=Decimal("1"),
                    independence_factor=Decimal("1"),
                    freshness_factor=Decimal("1"),
                    correlation_group="official-cross-catalog",
                    polarity="supports",
                    statement_status="FACT",
                    claim_value={"article": "EXTA123", "oe": "1K0121250"},
                    source_url=source_url,
                    raw_fragment="EXTA123 -> 1K0121250",
                    source_document_sha256="e" * 64,
                    retrieved_at=now,
                )
            )
            session.add_all(
                [
                    FitmentEvidenceClaim(
                        id=weak_claim_id,
                        analysis_id=analysis_id,
                        assessment_id=assessment_id,
                        source_document_id=document_id,
                        evidence_key=f"authority:{weak_claim_id}",
                        feature="cross_confirmed",
                        evidence_value=Decimal("1"),
                        source_external_id="official-cross-catalog",
                        source_type="official_catalog",
                        source_tier="A",
                        source_reliability=Decimal("0.95"),
                        extraction_confidence=Decimal("0.10"),
                        directness=Decimal("1"),
                        independence_factor=Decimal("1"),
                        freshness_factor=Decimal("1"),
                        correlation_group="official-cross-catalog",
                        polarity="supports",
                        statement_status="FACT",
                        claim_value={"article": "EXTA123", "oe": "1K0121250"},
                        source_url=source_url,
                        raw_fragment="EXTA123 -> 1K0121250",
                        source_document_sha256="e" * 64,
                        retrieved_at=now,
                    ),
                    FitmentEvidenceClaim(
                        id=wrong_numbers_claim_id,
                        analysis_id=analysis_id,
                        assessment_id=assessment_id,
                        source_document_id=document_id,
                        evidence_key=f"authority:{wrong_numbers_claim_id}",
                        feature="cross_confirmed",
                        evidence_value=Decimal("1"),
                        source_external_id="official-cross-catalog",
                        source_type="official_catalog",
                        source_tier="A",
                        source_reliability=Decimal("0.95"),
                        extraction_confidence=Decimal("0.99"),
                        directness=Decimal("1"),
                        independence_factor=Decimal("1"),
                        freshness_factor=Decimal("1"),
                        correlation_group="official-cross-catalog",
                        polarity="supports",
                        statement_status="FACT",
                        claim_value={"article": "OTHER123", "oe": "OTHER456"},
                        source_url=source_url,
                        raw_fragment="OTHER123 -> OTHER456",
                        source_document_sha256="e" * 64,
                        retrieved_at=now,
                    ),
                ]
            )
            session.add_all(
                [
                    # The first row has a complete, current, Tier-A primary
                    # evidence chain and is safe for one-hop widening.
                    cross(
                        0,
                        "EXTA123",
                        evidence_ids=[str(evidence_claim_id)],
                        source_count=1,
                        fingerprint="a" * 64,
                    ),
                    # These cached conclusions name the same pair, but their
                    # primary evidence is weak or names other numbers.  They
                    # must not create additional frozen authority.
                    cross(
                        0,
                        "EXTA123",
                        evidence_ids=[str(weak_claim_id)],
                        source_count=1,
                        fingerprint="e" * 64,
                    ),
                    cross(
                        0,
                        "EXTA123",
                        evidence_ids=[str(wrong_numbers_claim_id)],
                        source_count=1,
                        fingerprint="f" * 64,
                    ),
                    # A live rejection of the same pair blocks the older
                    # confirmation even if the caller omitted supersedes_id.
                    cross(1, "EXTB123", fingerprint="b" * 64),
                    cross(
                        1,
                        "EXTB123",
                        status="human_rejected",
                        fingerprint="c" * 64,
                    ),
                    # Position-limited evidence cannot become a global edge
                    # until the catalog row carries matching structured fitment.
                    cross(
                        2,
                        "EXTC123",
                        installation_position="rear-right",
                        fingerprint="d" * 64,
                    ),
                ]
            )
            await session.commit()

        async with async_session_factory() as session:
            candidates = await load_scope_candidates(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
            )

        by_id = {candidate.catalog_item_id: candidate for candidate in candidates}
        admitted = by_id[item_ids[0]].confirmed_identity_links
        assert len(admitted) == 1
        assert admitted[0]["identity_evidence_kind"] == "FITMENT_CROSS_REFERENCE"
        assert admitted[0]["extracted_oem_norm"] == "EXTA123"
        assert by_id[item_ids[1]].confirmed_identity_links == ()
        assert by_id[item_ids[2]].confirmed_identity_links == ()

        # A later source-policy row is authoritative.  The immutable evidence
        # remains in storage, but it must stop widening the next preview as
        # soon as access is revoked.
        async with async_session_factory() as session:
            session.add(
                FitmentSource(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    source_key="official-cross-catalog",
                    source_type="official_catalog",
                    source_tier="A",
                    base_reliability=Decimal("0.95"),
                    domain="catalog.example.test",
                    access_method="licensed_api",
                    access_status="NOT_PERMITTED",
                    access_reference="p15017-revoked-policy",
                    robots_checked=True,
                    terms_checked=True,
                    rate_limit="0/min",
                    cache_policy="retain-evidence-only",
                    policy_version="authority-v2-revoked",
                    reviewed_at=now + timedelta(seconds=1),
                )
            )
            await session.commit()

        async with async_session_factory() as session:
            revoked = await load_scope_candidates(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
            )
        revoked_by_id = {candidate.catalog_item_id: candidate for candidate in revoked}
        assert revoked_by_id[item_ids[0]].confirmed_identity_links == ()
    finally:
        await _delete_disposable_workspace(workspace_id)


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_catalog_drift_between_preview_and_start_is_rejected(monkeypatch) -> None:
    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id = uuid4()
    batch_id = uuid4()
    item_ids = (uuid4(), uuid4())
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        async with async_session_factory() as session:
            preview = await preview_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
            )
        async with async_session_factory() as session:
            session.add(
                CatalogItemOverride(
                    id=uuid4(),
                    catalog_item_id=item_ids[0],
                    user_id=None,
                    stock_status="dead_stock",
                    reason="Правка, сдвинувшая каталог после предпросмотра",
                )
            )
            await session.commit()

        async with async_session_factory() as session:
            with pytest.raises(
                PricingRunScopeConflictError, match="CATALOG_SNAPSHOT_CHANGED"
            ):
                await create_pricing_run(
                    session,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    celery_app=fake_celery,
                    source_mode="e2e_fixture_replay",
                    scope_mode=FULL_CATALOG_SCOPE,
                    start=_replay_start(
                        expected_catalog_snapshot_hash=preview.catalog_snapshot_hash,
                        expected_scope_hash=preview.scope_hash,
                    ),
                )
            await session.rollback()

        async with async_session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count(PricingRun.id)).where(
                        PricingRun.workspace_id == workspace_id
                    )
                )
                == 0
            )
    finally:
        await _delete_disposable_workspace(workspace_id)
        get_settings.cache_clear()


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_client_idempotency_key_replays_one_run_and_refuses_a_new_scope(
    monkeypatch,
) -> None:
    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id = uuid4()
    batch_id = uuid4()
    item_ids = (uuid4(), uuid4())
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        async with async_session_factory() as session:
            first = await create_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                celery_app=fake_celery,
                source_mode="e2e_fixture_replay",
                scope_mode=EXPLICIT_ITEMS_SCOPE,
                catalog_item_ids=[item_ids[0]],
                start=_replay_start(idempotency_key="operator-retry-0001"),
            )
            first_id = first.id
        async with async_session_factory() as session:
            replayed = await create_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                celery_app=fake_celery,
                source_mode="e2e_fixture_replay",
                scope_mode=EXPLICIT_ITEMS_SCOPE,
                catalog_item_ids=[item_ids[0]],
                start=_replay_start(idempotency_key="operator-retry-0001"),
            )
            assert replayed.id == first_id
        async with async_session_factory() as session:
            with pytest.raises(
                PricingRunIdempotencyConflictError, match="IDEMPOTENCY_KEY_REUSED"
            ):
                await create_pricing_run(
                    session,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    celery_app=fake_celery,
                    source_mode="e2e_fixture_replay",
                    scope_mode=EXPLICIT_ITEMS_SCOPE,
                    catalog_item_ids=[item_ids[1]],
                    start=_replay_start(idempotency_key="operator-retry-0001"),
                )
            await session.rollback()
        async with async_session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count(PricingRun.id)).where(
                        PricingRun.workspace_id == workspace_id
                    )
                )
                == 1
            )
    finally:
        await _delete_disposable_workspace(workspace_id)
        get_settings.cache_clear()


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_scope_and_start_snapshot_are_immutable_after_creation(
    monkeypatch,
) -> None:
    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id = uuid4()
    batch_id = uuid4()
    item_ids = (uuid4(),)
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        async with async_session_factory() as session:
            run = await create_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                celery_app=fake_celery,
                source_mode="e2e_fixture_replay",
                scope_mode=EXPLICIT_ITEMS_SCOPE,
                catalog_item_ids=[item_ids[0]],
                start=_replay_start(),
            )
            run_id = run.id

        async with async_session_factory() as session:
            # Прогресс по статусу разрешён и не задевает область.
            await session.execute(
                text("UPDATE pricing_runs SET status = 'collecting' WHERE id = :id"),
                {"id": run_id},
            )
            await session.commit()

        for statement in (
            "UPDATE pricing_runs SET scope_hash = 'f' || repeat('0', 63) "
            "WHERE id = :id",
            "UPDATE pricing_runs SET scope_mode = 'FULL_CATALOG' WHERE id = :id",
            "UPDATE pricing_runs SET scope_manifest = '{}'::json WHERE id = :id",
            "UPDATE pricing_runs SET full_catalog_confirmed = true WHERE id = :id",
        ):
            async with async_session_factory() as session:
                with pytest.raises(DBAPIError, match="immutable"):
                    await session.execute(text(statement), {"id": run_id})
                    await session.commit()
                await session.rollback()

        async with async_session_factory() as session:
            run_item_id = await session.scalar(
                select(PricingRunItem.id).where(PricingRunItem.pricing_run_id == run_id)
            )
        async with async_session_factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(
                    text(
                        "UPDATE pricing_run_items SET start_snapshot = '{}'::json "
                        "WHERE id = :id"
                    ),
                    {"id": run_item_id},
                )
                await session.commit()
            await session.rollback()
    finally:
        await _delete_disposable_workspace(workspace_id)
        get_settings.cache_clear()


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_operator_full_catalog_without_confirmation_is_rejected_by_database(
    monkeypatch,
) -> None:
    """Подтверждение полного каталога держится проверкой БД, а не только кодом."""

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id = uuid4()
    batch_id = uuid4()
    item_ids = (uuid4(),)
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        async with async_session_factory() as session:
            session.add(
                PricingRun(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    status="queued",
                    policy_version="pricing-v2",
                    policy_config={},
                    parser_version="p",
                    scope_contract_version=PRICING_RUN_SCOPE_CONTRACT_VERSION,
                    scope_mode=FULL_CATALOG_SCOPE,
                    scope_confirmation_source="OPERATOR",
                    full_catalog_confirmed=False,
                    catalog_snapshot_hash="a" * 64,
                    scope_hash="b" * 64,
                    scope_manifest={},
                    scope_frozen_at=datetime.now(UTC),
                )
            )
            with pytest.raises(
                IntegrityError, match="ck_pricing_run_full_catalog_confirmation"
            ):
                await session.commit()
            await session.rollback()
    finally:
        await _delete_disposable_workspace(workspace_id)
        get_settings.cache_clear()


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_an_active_run_with_a_foreign_scope_is_refused_not_returned(
    monkeypatch,
) -> None:
    """Защита от второго прогона не вправе выдавать чужой прогон за свой.

    Совпадает только импорт; область другая.  Вернуть уже идущий прогон значило
    бы сказать оператору «запущено», не запустив ничего из того, что он выбрал.
    """

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id = uuid4()
    batch_id = uuid4()
    item_ids = (uuid4(), uuid4())
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        async with async_session_factory() as session:
            first = await create_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                celery_app=fake_celery,
                source_mode="e2e_fixture_replay",
                scope_mode=EXPLICIT_ITEMS_SCOPE,
                catalog_item_ids=[item_ids[0]],
                start=_replay_start(idempotency_key="first-scope-0001"),
            )
            first_id = first.id
            first_scope_hash = first.scope_hash

        async with async_session_factory() as session:
            with pytest.raises(
                PricingRunActiveScopeConflictError, match="ACTIVE_RUN_SCOPE_CONFLICT"
            ):
                await create_pricing_run(
                    session,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    celery_app=fake_celery,
                    source_mode="e2e_fixture_replay",
                    scope_mode=EXPLICIT_ITEMS_SCOPE,
                    catalog_item_ids=[item_ids[1]],
                    start=_replay_start(idempotency_key="second-scope-0001"),
                )
            await session.rollback()

        # Та же область тем же ключом по-прежнему возвращает тот же прогон.
        async with async_session_factory() as session:
            same = await create_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                celery_app=fake_celery,
                source_mode="e2e_fixture_replay",
                scope_mode=EXPLICIT_ITEMS_SCOPE,
                catalog_item_ids=[item_ids[0]],
                start=_replay_start(idempotency_key="first-scope-0001"),
            )
            assert same.id == first_id
            assert same.scope_hash == first_scope_hash

        async with async_session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count(PricingRun.id)).where(
                        PricingRun.workspace_id == workspace_id
                    )
                )
                == 1
            )
    finally:
        await _delete_disposable_workspace(workspace_id)
        get_settings.cache_clear()


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_concurrent_starts_with_different_scopes_never_share_a_run(
    monkeypatch,
) -> None:
    """Гонка двух разных областей: победитель один, проигравший получает отказ."""

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id = uuid4()
    batch_id = uuid4()
    item_ids = (uuid4(), uuid4())
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )

        started = asyncio.Event()
        arrived = 0
        lock = asyncio.Lock()

        async def _create(position: int) -> tuple[UUID | None, str | None]:
            nonlocal arrived
            async with async_session_factory() as session:
                async with lock:
                    arrived += 1
                    if arrived == 2:
                        started.set()
                await started.wait()
                try:
                    run = await create_pricing_run(
                        session,
                        workspace_id=workspace_id,
                        import_batch_id=batch_id,
                        celery_app=fake_celery,
                        source_mode="e2e_fixture_replay",
                        scope_mode=EXPLICIT_ITEMS_SCOPE,
                        catalog_item_ids=[item_ids[position]],
                        start=_replay_start(idempotency_key=f"racing-scope-{position}"),
                    )
                except Exception as exc:  # noqa: BLE001 - важен именно тип отказа
                    await session.rollback()
                    return None, type(exc).__name__
                return run.id, None

        results = await asyncio.gather(_create(0), _create(1))

        async with async_session_factory() as session:
            runs = list(
                (
                    await session.scalars(
                        select(PricingRun).where(
                            PricingRun.workspace_id == workspace_id
                        )
                    )
                ).all()
            )
        assert len(runs) == 1, [str(run.id) for run in runs]
        winners = [run_id for run_id, _ in results if run_id is not None]
        failures = [name for _, name in results if name is not None]
        assert winners == [runs[0].id], results
        assert failures == ["PricingRunActiveScopeConflictError"], results
        # Проигравший обязан получить отказ, а не чужой прогон.
        assert runs[0].scope_hash is not None
    finally:
        await _delete_disposable_workspace(workspace_id)
        get_settings.cache_clear()


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_concurrent_starts_with_the_same_key_reuse_exactly_one_run(
    monkeypatch,
) -> None:
    """Гонка одного и того же запроса: обе попытки получают один и тот же прогон."""

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id = uuid4()
    batch_id = uuid4()
    item_ids = (uuid4(), uuid4())
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )

        started = asyncio.Event()
        arrived = 0
        lock = asyncio.Lock()

        async def _create() -> UUID | None:
            nonlocal arrived
            async with async_session_factory() as session:
                async with lock:
                    arrived += 1
                    if arrived == 2:
                        started.set()
                await started.wait()
                try:
                    run = await create_pricing_run(
                        session,
                        workspace_id=workspace_id,
                        import_batch_id=batch_id,
                        celery_app=fake_celery,
                        source_mode="e2e_fixture_replay",
                        scope_mode=EXPLICIT_ITEMS_SCOPE,
                        catalog_item_ids=[item_ids[0]],
                        start=_replay_start(idempotency_key="operator-retry-0007"),
                    )
                except Exception:  # noqa: BLE001 - проигравший не обязан падать
                    await session.rollback()
                    return None
                return run.id

        results = await asyncio.gather(_create(), _create())

        async with async_session_factory() as session:
            runs = list(
                (
                    await session.scalars(
                        select(PricingRun).where(
                            PricingRun.workspace_id == workspace_id
                        )
                    )
                ).all()
            )
        assert len(runs) == 1, [str(run.id) for run in runs]
        assert results == [runs[0].id, runs[0].id], results
        assert runs[0].idempotency_key == "operator-retry-0007"
    finally:
        await _delete_disposable_workspace(workspace_id)
        get_settings.cache_clear()


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_dead_letter_replay_keeps_the_bounded_scope_of_the_failed_run(
    monkeypatch,
) -> None:
    """Одна упавшая позиция ограниченного прогона не повторяется как весь каталог."""

    _require_disposable_database()
    _authorized_source_environment(monkeypatch)
    workspace_id = uuid4()
    batch_id = uuid4()
    item_ids = (uuid4(), uuid4(), uuid4())
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        preview, contract = await _issued_preview(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            scope_mode=EXPLICIT_ITEMS_SCOPE,
            catalog_item_ids=[item_ids[0], item_ids[1]],
        )
        async with async_session_factory() as session:
            failed = await create_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                celery_app=fake_celery,
                scope_mode=EXPLICIT_ITEMS_SCOPE,
                catalog_item_ids=[item_ids[0], item_ids[1]],
                start=OperatorRunStart(
                    idempotency_key="operator-bounded-0001",
                    preview_token=contract.token,
                    actor=_operator_actor(),
                ),
            )
            failed_id = failed.id
            failed_scope_hash = failed.scope_hash
            failed_membership = failed.scope_manifest[SCOPE_MANIFEST_EXECUTION_SECTION][
                "membership"
            ]["catalog_item_ids"]
        assert failed_membership == [str(item_ids[0]), str(item_ids[1])]

        dead_letter_id = await _fail_run_with_a_dead_letter(failed_id)

        async with async_session_factory() as session:
            replay = await replay_dead_letter(
                session,
                workspace_id=workspace_id,
                kind="pricing_target",
                dead_letter_id=dead_letter_id,
                celery_app=fake_celery,
            )
            replay_id = replay.workflow_id
        assert replay_id != failed_id

        async with async_session_factory() as session:
            replayed = await session.get(PricingRun, replay_id)
        assert replayed is not None
        assert replayed.scope_mode == EXPLICIT_ITEMS_SCOPE, (
            "повтор расширил область до полного каталога"
        )
        assert replayed.total_items == 2, replayed.total_items
        assert replayed.scope_hash == failed_scope_hash
        assert replayed.catalog_snapshot_hash is not None
        execution = replayed.scope_manifest[SCOPE_MANIFEST_EXECUTION_SECTION]
        assert execution["membership"]["catalog_item_ids"] == failed_membership
        assert execution["policy_hash"]
        provenance = replayed.scope_manifest[SCOPE_MANIFEST_PROVENANCE_SECTION]
        assert provenance["source_run_id"] == str(failed_id)
        assert replayed.scope_confirmation_source == CONFIRMATION_SOURCE_SYSTEM_REPLAY

        async with async_session_factory() as session:
            run_items = list(
                (
                    await session.scalars(
                        select(PricingRunItem.catalog_item_id).where(
                            PricingRunItem.pricing_run_id == replay_id
                        )
                    )
                ).all()
            )
        assert set(run_items) == {item_ids[0], item_ids[1]}
        assert item_ids[2] not in set(run_items)

        # Повторное нажатие на то же мёртвое письмо не плодит прогоны.
        async with async_session_factory() as session:
            again = await replay_dead_letter(
                session,
                workspace_id=workspace_id,
                kind="pricing_target",
                dead_letter_id=dead_letter_id,
                celery_app=fake_celery,
            )
        assert again.workflow_id == replay_id
    finally:
        await _delete_disposable_workspace(workspace_id)
        get_settings.cache_clear()


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_dead_letter_replay_is_refused_when_the_frozen_scope_moved(
    monkeypatch,
) -> None:
    """Сдвинувшийся каталог — отказ повторить, а не тихо другая область."""

    _require_disposable_database()
    _authorized_source_environment(monkeypatch)
    workspace_id = uuid4()
    batch_id = uuid4()
    item_ids = (uuid4(), uuid4())
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        preview, contract = await _issued_preview(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            scope_mode=EXPLICIT_ITEMS_SCOPE,
            catalog_item_ids=[item_ids[0]],
        )
        async with async_session_factory() as session:
            failed = await create_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                celery_app=fake_celery,
                scope_mode=EXPLICIT_ITEMS_SCOPE,
                catalog_item_ids=[item_ids[0]],
                start=OperatorRunStart(
                    idempotency_key="operator-bounded-0002",
                    preview_token=contract.token,
                    actor=_operator_actor(),
                ),
            )
            failed_id = failed.id

        dead_letter_id = await _fail_run_with_a_dead_letter(failed_id)

        async with async_session_factory() as session:
            session.add(
                CatalogItemOverride(
                    id=uuid4(),
                    catalog_item_id=item_ids[0],
                    user_id=None,
                    stock_status="dead_stock",
                    reason="Правка каталога после падения прогона",
                )
            )
            await session.commit()

        async with async_session_factory() as session:
            with pytest.raises(DeadLetterReplayError, match="CATALOG_SNAPSHOT_CHANGED"):
                await replay_dead_letter(
                    session,
                    workspace_id=workspace_id,
                    kind="pricing_target",
                    dead_letter_id=dead_letter_id,
                    celery_app=fake_celery,
                )
            await session.rollback()

        async with async_session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count(PricingRun.id)).where(
                        PricingRun.workspace_id == workspace_id
                    )
                )
                == 1
            )
    finally:
        await _delete_disposable_workspace(workspace_id)
        get_settings.cache_clear()


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_zz_migration_round_trip_and_irreversibility_guard(monkeypatch) -> None:
    """upgrade -> downgrade -> upgrade и отказ стирать уже сохранённые области."""

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    _alembic("upgrade", "head")

    async with async_session_factory() as session:
        residual = int(
            await session.scalar(
                select(func.count(PricingRun.id)).where(
                    PricingRun.scope_contract_version.is_not(None)
                )
            )
            or 0
        )
    if residual:
        pytest.skip(
            f"{residual} scoped run(s) left by another suite block the structural "
            "round trip; run this module on its own"
        )
    _alembic("downgrade", "20260731_0031")
    _alembic("upgrade", "head")

    workspace_id = uuid4()
    batch_id = uuid4()
    item_ids = (uuid4(),)
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        async with async_session_factory() as session:
            await create_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                celery_app=fake_celery,
                source_mode="e2e_fixture_replay",
                scope_mode=EXPLICIT_ITEMS_SCOPE,
                catalog_item_ids=[item_ids[0]],
                start=_replay_start(),
            )
        completed = subprocess.run(
            ["uv", "run", "alembic", "-c", "alembic.ini", "downgrade", "20260731_0031"],
            cwd=BACKEND_ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        assert completed.returncode != 0
        # Откат идёт от головы вниз, поэтому первым срабатывает сторож САМОЙ
        # ПОЗДНЕЙ миграции, которая отказывается стирать улику: сегодня это
        # 0038 (личность старта), до неё была 0035 (снимок политики и отпечаток
        # снимка позиции), а завтра появится следующая.  Проверяется само
        # утверждение «улику не стирают молча», а не имя сторожа: иначе тест
        # приходится править на каждой миграции, то есть перестать читать.
        output = completed.stdout + completed.stderr
        assert "IRREVERSIBLE_MIGRATION_" in output, output
        # И данные обязаны пережить отказ.
        async with async_session_factory() as session:
            survived = await session.scalar(
                select(func.count(PricingRun.id)).where(
                    PricingRun.workspace_id == workspace_id
                )
            )
        assert survived == 1, survived
    finally:
        await _delete_disposable_workspace(workspace_id)
        _alembic("upgrade", "head")
        get_settings.cache_clear()


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_calculation_reads_the_frozen_snapshot_not_the_live_override(
    monkeypatch,
) -> None:
    """Настоящий расчёт обязан читать вход, замороженный на старте прогона.

    Предикат ``uses_frozen_start_inputs`` покрыт отдельно, но сам по себе он
    ничего не доказывает: пока не проверено, что путь расчёта его спрашивает,
    правка, поданная оператором уже во время прогона, продолжает попадать в
    идущий расчёт, и один и тот же прогон невоспроизводим.

    Здесь прогон стартует по настоящему ``create_pricing_run``, затем живая
    правка каталога подменяется на другую, и выполняется настоящий
    ``_calculate_and_persist``. Снимок контекста в рекомендации обязан
    показывать значение на момент старта.
    """

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id = uuid4()
    batch_id = uuid4()
    item_ids = (uuid4(),)
    frozen_override_id = uuid4()
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())

    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )

        # Правка, действующая на момент старта.
        async with async_session_factory() as session:
            session.add(
                CatalogItemOverride(
                    id=frozen_override_id,
                    catalog_item_id=item_ids[0],
                    user_id=None,
                    stock_qty=11,
                    stock_status="fresh",
                    reason="Состояние запаса на момент старта прогона",
                )
            )
            await session.commit()

        async with async_session_factory() as session:
            run = await create_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                celery_app=fake_celery,
                source_mode="e2e_fixture_replay",
                scope_mode=FULL_CATALOG_SCOPE,
                start=_replay_start(full_catalog_confirmed=True),
            )
            await session.commit()
            run_id = run.id

        async with async_session_factory() as session:
            run_item = await session.scalar(
                select(PricingRunItem).where(PricingRunItem.pricing_run_id == run_id)
            )
            assert run_item is not None
            run_item_id = run_item.id
            assert run_item.catalog_item_override_id == frozen_override_id, (
                "старт обязан заморозить действующую правку"
            )

        # Оператор правит каталог уже после старта: расчёт этого видеть не должен.
        async with async_session_factory() as session:
            session.add(
                CatalogItemOverride(
                    id=uuid4(),
                    catalog_item_id=item_ids[0],
                    user_id=None,
                    stock_qty=99,
                    stock_status="dead_stock",
                    reason="Правка, поданная уже во время расчёта",
                )
            )
            await session.commit()

        await _calculate_and_persist(run_item_id)

        async with async_session_factory() as session:
            recommendation = await session.scalar(
                select(PricingRecommendation).where(
                    PricingRecommendation.pricing_run_item_id == run_item_id
                )
            )
        assert recommendation is not None, "расчёт обязан оставить рекомендацию"
        snapshot = recommendation.context_snapshot
        # Сравнение как Decimal: снимок хранит строку и масштаб может отличаться.
        assert Decimal(snapshot["stock_qty"]) == Decimal("11"), (
            "расчёт прочитал текущую правку вместо замороженной: "
            f"{snapshot['stock_qty']!r}"
        )
        assert snapshot["stock_status"] == "fresh", (
            "статус запаса взят из правки, поданной уже во время расчёта: "
            f"{snapshot['stock_status']!r}"
        )
    finally:
        get_settings.cache_clear()
        # Только этот тест доводит дело до рекомендации, а она держит
        # import_batch внешним ключом. Общий помощник её не знает, поэтому
        # снимаем здесь, не меняя уборку остальных тестов.
        async with async_session_factory() as session:
            # Таблица append-only: на одноразовой базе триггер снимается только
            # на время уборки, как это уже делает набор по сопоставимости.
            await session.execute(
                text(
                    "ALTER TABLE pricing_recommendations "
                    "DISABLE TRIGGER trg_pricing_recommendations_append_only"
                )
            )
            await session.execute(
                delete(PricingRecommendation).where(
                    PricingRecommendation.pricing_run_id.in_(
                        select(PricingRun.id).where(
                            PricingRun.workspace_id == workspace_id
                        )
                    )
                )
            )
            await session.execute(
                text(
                    "ALTER TABLE pricing_recommendations "
                    "ENABLE TRIGGER trg_pricing_recommendations_append_only"
                )
            )
            await session.commit()
        await _delete_disposable_workspace(workspace_id)
