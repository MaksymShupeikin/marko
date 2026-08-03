"""Личность старта и родительский прогон членства — на живом PostgreSQL.

Независимая проверка 2026-08-02 воспроизвела три разрыва уже ПОСЛЕ прошлой
правки:

* F1 — «идемпотентный победитель» опознавался по совпадению области и источника
  подтверждения.  Два канонически разных тела старта, нормализующихся в одну
  область, считались одним запросом; второй актор со своим законным контрактом
  предпросмотра называл чужой ключ идемпотентности и получал чужой прогон.
* F3 — ограниченный прогон без отпечатка политики тихо перечитывал ТЕКУЩИЙ файл
  развёртывания.
* F5 — ``pricing_run_items.pricing_run_id`` не входил в неизменяемые колонки:
  строку членства можно было перевесить на другой прогон, обнулив состав
  источника.

Набору нужна одноразовая база, имя которой содержит ``p15017``.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
import os
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from marko.core.config import get_settings
from marko.infrastructure.db.models import (
    CatalogImportBatch,
    CatalogItem,
    PricingRecommendation,
    PricingRun,
    PricingRunItem,
    PricingRunPreviewContract,
    Workspace,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.pricing_runs import (
    ACTOR_TYPE_SERVICE,
    ACTOR_TYPE_USER,
    CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
    EXPLICIT_ITEMS_SCOPE,
    PRICING_RUN_START_PERMISSION,
    RUN_START_LANE_OPERATOR,
    RUN_START_LANE_TRUSTED,
    OperatorRunStart,
    PreviewActor,
    PricingRunExecutionPolicyError,
    PricingRunIdempotencyConflictError,
    PricingRunMembershipError,
    TrustedRunStart,
    canonical_start_request_hash,
    create_pricing_run,
    load_run_execution_policy,
    preview_pricing_run_for_operator,
    verify_run_membership,
)


pytestmark = pytest.mark.postgres
BACKEND_ROOT = Path(__file__).resolve().parents[1]
# Тело старта, нормализующееся в политику по умолчанию: политика, область и её
# отпечаток совпадают с ``policy_config=None``, а каноническое тело — нет.
NORMALIZED_POLICY = {"version": "pricing-v2"}


def _postgres_enabled() -> bool:
    return os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") == "1"


requires_postgres = pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)


def _require_disposable_database() -> None:
    database_name = make_url(os.environ.get("DATABASE_URL", "")).database or ""
    if "p15017" not in database_name.casefold():
        pytest.fail(
            "Refusing run-identity test: DATABASE_URL must name a disposable "
            "database containing 'p15017'"
        )


def _authorized_source_environment(monkeypatch) -> None:
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


def _e2e_replay_environment(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "e2e")
    monkeypatch.setenv("E2E_AUTH_BYPASS", "true")
    monkeypatch.setenv("E2E_AUTH_TOKEN", "p15017-integration-token-00000001")
    monkeypatch.setenv(
        "PRICING_BRAND_TIERS_PATH",
        str(BACKEND_ROOT / "src/marko/e2e/fixtures/brands.yaml"),
    )
    get_settings.cache_clear()


def _actor(actor_id: str = "00000000-0000-0000-0000-0000000000aa") -> PreviewActor:
    return PreviewActor(
        actor_id=actor_id,
        actor_type=ACTOR_TYPE_USER,
        workspace_role="admin",
        permissions=(PRICING_RUN_START_PERMISSION,),
    )


async def _seed_catalog(
    *, workspace_id: UUID, batch_id: UUID, item_ids: tuple[UUID, ...]
) -> None:
    async with async_session_factory() as session:
        session.add(
            Workspace(
                id=workspace_id,
                name="P15017 run identity",
                slug=f"p15017-identity-{workspace_id.hex}",
            )
        )
        await session.flush()
        session.add(
            CatalogImportBatch(
                id=batch_id,
                workspace_id=workspace_id,
                filename="run-identity.xlsx",
                content_sha256="e" * 64,
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
                    sku=f"SKU-IDENTITY-{position}",
                    oe_raw=f"1K0 33325{position}",
                    oe_norm=f"1K033325{position}",
                    name=f"Позиция каталога {position}",
                    category="brakes",
                    brand="KEMP",
                    product_url=None,
                    current_price=Decimal("800") + position,
                    currency="UAH",
                    is_available=True,
                    stock_qty=Decimal("5"),
                    units_sold_30d=Decimal("3"),
                    raw_row={},
                )
            )
        await session.commit()


async def _cleanup(workspace_id: UUID) -> None:
    """Убрать за собой ДАЖЕ если тест упал на середине.

    Уборка обязана быть безусловной, а не «работать, пока тест зелёный».  Пока
    она полагалась на каскад от строки прогона, упавший тест мог оставить строку
    членства, перевешенную на чужой прогон: каскад её уже не доставал, позиция
    каталога держалась внешним ключом RESTRICT, рабочее пространство не
    удалялось — и следующий набор в общей одноразовой базе падал на чужом мусоре,
    как будто сломали его.  Поэтому строки членства снимаются явно и по обоим
    признакам: и по прогонам этого пространства, и по позициям его каталога.
    """

    disabled = (
        ("pricing_run_items", "trg_pricing_run_items_no_delete"),
        ("catalog_item_overrides", "trg_catalog_item_overrides_append_only"),
        ("pricing_recommendations", "trg_pricing_recommendations_append_only"),
    )
    async with async_session_factory() as session:
        try:
            for table, trigger in disabled:
                await session.execute(
                    text(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")
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
                    "DELETE FROM pricing_run_items WHERE pricing_run_id IN ("
                    "SELECT id FROM pricing_runs WHERE workspace_id = :w) "
                    "OR catalog_item_id IN ("
                    "SELECT id FROM catalog_items WHERE workspace_id = :w)"
                ),
                {"w": workspace_id},
            )
            await session.execute(
                delete(PricingRun).where(PricingRun.workspace_id == workspace_id)
            )
            await session.execute(
                delete(PricingRunPreviewContract).where(
                    PricingRunPreviewContract.workspace_id == workspace_id
                )
            )
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            for table, trigger in reversed(disabled):
                await session.execute(
                    text(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _issue(
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
    catalog_item_ids: list[UUID],
    actor: PreviewActor | None = None,
    policy_config: dict | None = None,
):
    async with async_session_factory() as session:
        scope, contract = await preview_pricing_run_for_operator(
            session,
            workspace_id=workspace_id,
            import_batch_id=import_batch_id,
            actor=actor or _actor(),
            scope_mode=EXPLICIT_ITEMS_SCOPE,
            catalog_item_ids=catalog_item_ids,
            policy_config=policy_config,
            confirm_full_catalog=False,
        )
        await session.commit()
    return scope, contract


async def _start(
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
    catalog_item_ids: list[UUID],
    contract,
    idempotency_key: str,
    actor: PreviewActor | None = None,
    policy_config: dict | None = None,
) -> PricingRun:
    celery = Mock()
    celery.send_task = Mock(return_value=Mock())
    async with async_session_factory() as session:
        run = await create_pricing_run(
            session,
            workspace_id=workspace_id,
            import_batch_id=import_batch_id,
            celery_app=celery,
            scope_mode=EXPLICIT_ITEMS_SCOPE,
            catalog_item_ids=catalog_item_ids,
            policy_config=policy_config,
            start=OperatorRunStart(
                idempotency_key=idempotency_key,
                preview_token=contract.token,
                actor=actor or _actor(),
                confirm_full_catalog=False,
            ),
        )
        await session.commit()
        run_id = run.id
    async with async_session_factory() as session:
        refreshed = await session.get(PricingRun, run_id)
    assert refreshed is not None
    return refreshed


# --------------------------------------------------------------------- F1


@requires_postgres
@pytest.mark.asyncio
async def test_the_run_persists_its_canonical_request_actor_and_lane(
    monkeypatch,
) -> None:
    """F1: личность старта записана тем же INSERT, что и область, и совпадает с телом."""

    _require_disposable_database()
    _authorized_source_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    actor = _actor()
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        _, contract = await _issue(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
        )
        run = await _start(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
            contract=contract,
            idempotency_key="identity-persist-0001",
        )

        expected = canonical_start_request_hash(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            scope_mode=EXPLICIT_ITEMS_SCOPE,
            catalog_item_ids=[item_ids[0]],
            policy_config=None,
            confirm_full_catalog=False,
        )
        assert run.canonical_start_request_hash == expected
        # Тот же отпечаток закрывал контракт предпросмотра: один документ, а не
        # два похожих.
        assert contract.request_hash == expected
        assert run.start_lane == RUN_START_LANE_OPERATOR
        assert run.start_actor_id == actor.actor_id
        assert run.start_actor_type == ACTOR_TYPE_USER
        provenance = run.scope_manifest["provenance"]
        assert provenance["canonical_start_request_hash"] == expected
        assert provenance["start_lane"] == RUN_START_LANE_OPERATOR
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_the_bound_start_identity_is_immutable_in_the_database(
    monkeypatch,
) -> None:
    """F1: сравнивать личность бессмысленно, если её можно переписать одним UPDATE."""

    _require_disposable_database()
    _authorized_source_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        _, contract = await _issue(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
        )
        run = await _start(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
            contract=contract,
            idempotency_key="identity-immutable-0001",
        )
        for statement in (
            "UPDATE pricing_runs SET canonical_start_request_hash = repeat('b', 64) "
            "WHERE id = :i",
            "UPDATE pricing_runs SET canonical_start_request_hash = NULL WHERE id = :i",
            "UPDATE pricing_runs SET start_actor_id = 'someone-else' WHERE id = :i",
            "UPDATE pricing_runs SET start_actor_type = 'service' WHERE id = :i",
            "UPDATE pricing_runs SET start_lane = 'TRUSTED' WHERE id = :i",
        ):
            async with async_session_factory() as session:
                with pytest.raises(DBAPIError, match="immutable"):
                    await session.execute(text(statement), {"i": run.id})
                    await session.commit()
                await session.rollback()

        async with async_session_factory() as session:
            after = await session.get(PricingRun, run.id)
        assert after is not None
        assert after.canonical_start_request_hash == run.canonical_start_request_hash
        assert after.start_actor_id == run.start_actor_id
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_the_exact_retry_of_one_attempt_returns_the_same_run(monkeypatch) -> None:
    """F1: разница между «сеть уронила ответ» и «второй запуск» обязана сохраниться."""

    _require_disposable_database()
    _authorized_source_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        _, contract = await _issue(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
        )
        first = await _start(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
            contract=contract,
            idempotency_key="exact-retry-0001",
        )
        retry = await _start(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
            contract=contract,
            idempotency_key="exact-retry-0001",
        )
        assert retry.id == first.id

        async with async_session_factory() as session:
            runs = list(
                (
                    await session.scalars(
                        select(PricingRun).where(PricingRun.workspace_id == workspace_id)
                    )
                ).all()
            )
        assert len(runs) == 1, [str(run.id) for run in runs]
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_a_canonically_different_request_cannot_reuse_the_key(monkeypatch) -> None:
    """F1, ровно репро: одна область, два РАЗНЫХ канонических тела старта.

    ``policy: null`` и ``policy: {"version": "pricing-v2"}`` дают одну и ту же
    политику, один и тот же ``policy_hash`` и один и тот же ``scope_hash``.
    Прежняя проверка на этом и останавливалась, поэтому второе тело молча
    получало прогон, запущенный по первому.
    """

    _require_disposable_database()
    _authorized_source_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        bare_scope, bare_contract = await _issue(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
            policy_config=None,
        )
        first = await _start(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
            contract=bare_contract,
            idempotency_key="normalized-body-0001",
            policy_config=None,
        )
        named_scope, named_contract = await _issue(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
            policy_config=NORMALIZED_POLICY,
        )
        # Предпосылка теста: область и политика неотличимы, тело — различимо.
        assert named_scope.scope_hash == bare_scope.scope_hash
        assert named_scope.policy_hash == bare_scope.policy_hash
        assert named_contract.request_hash != bare_contract.request_hash

        with pytest.raises(
            PricingRunIdempotencyConflictError,
            match="canonical_start_request_hash",
        ):
            await _start(
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                catalog_item_ids=[item_ids[0]],
                contract=named_contract,
                idempotency_key="normalized-body-0001",
                policy_config=NORMALIZED_POLICY,
            )

        async with async_session_factory() as session:
            runs = list(
                (
                    await session.scalars(
                        select(PricingRun).where(PricingRun.workspace_id == workspace_id)
                    )
                ).all()
            )
        assert [run.id for run in runs] == [first.id]
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_a_second_actor_with_its_own_token_never_receives_the_first_actors_run(
    monkeypatch,
) -> None:
    """F1, ровно репро: чужой ключ идемпотентности — это не своя идемпотентность.

    Второй актор предъявляет СВОЙ законный, непогашенный контракт предпросмотра;
    единственное, что он берёт чужого, — имя попытки.  Прежде этого хватало,
    чтобы получить прогон первого актора в ответ.
    """

    _require_disposable_database()
    _authorized_source_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    actor_a = _actor("00000000-0000-0000-0000-0000000000aa")
    actor_b = _actor("00000000-0000-0000-0000-0000000000bb")
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        _, contract_a = await _issue(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
            actor=actor_a,
        )
        run_a = await _start(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
            contract=contract_a,
            idempotency_key="shared-key-0001",
            actor=actor_a,
        )
        _, contract_b = await _issue(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
            actor=actor_b,
        )
        with pytest.raises(PricingRunIdempotencyConflictError) as failure:
            await _start(
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                catalog_item_ids=[item_ids[0]],
                contract=contract_b,
                idempotency_key="shared-key-0001",
                actor=actor_b,
            )

        message = str(failure.value)
        assert "IDEMPOTENCY_KEY_REUSED" in message
        # Отказ не превращается в канал утечки.
        assert str(run_a.id) not in message
        assert (run_a.scope_hash or "") not in message
        assert actor_a.actor_id not in message

        async with async_session_factory() as session:
            runs = list(
                (
                    await session.scalars(
                        select(PricingRun).where(PricingRun.workspace_id == workspace_id)
                    )
                ).all()
            )
        assert [run.id for run in runs] == [run_a.id]
        assert runs[0].start_actor_id == actor_a.actor_id
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_the_trusted_lane_cannot_replay_an_operator_key(monkeypatch) -> None:
    """F1: полоса власти — часть личности, а не украшение манифеста.

    Прогон оператора здесь уже завершён, поэтому защита активного прогона в деле
    не участвует: остаётся ровно вопрос о ключе идемпотентности.
    """

    _require_disposable_database()
    _authorized_source_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    celery = Mock()
    celery.send_task = Mock(return_value=Mock())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        _, contract = await _issue(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
        )
        operator_run = await _start(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
            contract=contract,
            idempotency_key="lane-key-0001",
        )
        assert operator_run.start_lane == RUN_START_LANE_OPERATOR
        async with async_session_factory() as session:
            await session.execute(
                text("UPDATE pricing_runs SET status = 'completed' WHERE id = :i"),
                {"i": operator_run.id},
            )
            await session.commit()

        _e2e_replay_environment(monkeypatch)
        async with async_session_factory() as session:
            with pytest.raises(PricingRunIdempotencyConflictError) as failure:
                await create_pricing_run(
                    session,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    celery_app=celery,
                    source_mode="e2e_fixture_replay",
                    scope_mode=EXPLICIT_ITEMS_SCOPE,
                    catalog_item_ids=[item_ids[0]],
                    start=TrustedRunStart(
                        confirmation_source=CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
                        reason="isolated e2e stack replays seeded fixtures",
                        idempotency_key="lane-key-0001",
                    ),
                )
            await session.rollback()
        assert str(operator_run.id) not in str(failure.value)
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_a_trusted_run_binds_its_service_actor_and_lane(monkeypatch) -> None:
    """F1: доверенная полоса не остаётся безымянной — её носитель тоже записан."""

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    celery = Mock()
    celery.send_task = Mock(return_value=Mock())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        async with async_session_factory() as session:
            run = await create_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                celery_app=celery,
                source_mode="e2e_fixture_replay",
                scope_mode=EXPLICIT_ITEMS_SCOPE,
                catalog_item_ids=[item_ids[0]],
                start=TrustedRunStart(
                    confirmation_source=CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
                    reason="isolated e2e stack replays seeded fixtures",
                    idempotency_key="trusted-lane-0001",
                ),
            )
            await session.commit()
            run_id = run.id

        async with async_session_factory() as session:
            stored = await session.get(PricingRun, run_id)
        assert stored is not None
        assert stored.start_lane == RUN_START_LANE_TRUSTED
        assert stored.start_actor_type == ACTOR_TYPE_SERVICE
        assert stored.start_actor_id == f"system:{CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY}"
        assert len(stored.canonical_start_request_hash or "") == 64
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_concurrent_starts_under_one_key_yield_exactly_one_run(
    monkeypatch,
) -> None:
    """F1: победитель гонки один, а проигравший получает отказ, а не чужой прогон.

    Оба актора законны и у каждого свой контракт предпросмотра; общий у них
    только ключ идемпотентности.  Разрешать спор «кто успел, тот и владелец
    ответа» нельзя: проигравший обязан узнать об отказе, а не увидеть чужой
    расчёт как свой.
    """

    _require_disposable_database()
    _authorized_source_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    actor_a = _actor("00000000-0000-0000-0000-0000000000aa")
    actor_b = _actor("00000000-0000-0000-0000-0000000000bb")
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        _, contract_a = await _issue(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
            actor=actor_a,
        )
        _, contract_b = await _issue(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
            actor=actor_b,
        )

        started = asyncio.Event()
        arrived = 0
        lock = asyncio.Lock()

        async def _attempt(contract, actor) -> object:
            nonlocal arrived
            celery = Mock()
            celery.send_task = Mock(return_value=Mock())
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
                        celery_app=celery,
                        scope_mode=EXPLICIT_ITEMS_SCOPE,
                        catalog_item_ids=[item_ids[0]],
                        start=OperatorRunStart(
                            idempotency_key="concurrent-key-0001",
                            preview_token=contract.token,
                            actor=actor,
                        ),
                    )
                    await session.commit()
                    return (actor.actor_id, run.id)
                except Exception as exc:  # noqa: BLE001 - проигравший обязан упасть
                    await session.rollback()
                    return exc

        outcomes = await asyncio.gather(
            _attempt(contract_a, actor_a),
            _attempt(contract_b, actor_b),
            return_exceptions=True,
        )
        winners = [item for item in outcomes if isinstance(item, tuple)]
        losers = [item for item in outcomes if not isinstance(item, tuple)]
        assert len(winners) == 1, outcomes
        assert len(losers) == 1, outcomes

        async with async_session_factory() as session:
            runs = list(
                (
                    await session.scalars(
                        select(PricingRun).where(PricingRun.workspace_id == workspace_id)
                    )
                ).all()
            )
        assert len(runs) == 1, [str(run.id) for run in runs]
        winner_actor, winner_run_id = winners[0]
        assert runs[0].id == winner_run_id
        # Строка принадлежит победителю и никому больше.
        assert runs[0].start_actor_id == winner_actor
        assert str(runs[0].id) not in str(losers[0])
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


# --------------------------------------------------------------------- F3


@requires_postgres
@pytest.mark.asyncio
async def test_a_pre_0035_bounded_row_fails_closed_on_real_postgres(
    monkeypatch,
) -> None:
    """F3: строка «ограниченная, завершённая, без отпечатка политики» — из базы.

    Такие строки существуют: миграция 0035 добавила ``policy_snapshot_hash`` и
    оставила его NULL у всего, что уже завершилось.  Здесь она собирается ровно
    такой же вставкой, а не подделкой объекта в памяти.
    """

    _require_disposable_database()
    _authorized_source_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    legacy_bounded_id = uuid4()
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        async with async_session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO pricing_runs (id, workspace_id, import_batch_id, "
                    "status, policy_version, policy_config, policy_snapshot_hash, "
                    "parser_version, scope_contract_version, scope_mode, "
                    "scope_confirmation_source, catalog_snapshot_hash, scope_hash, "
                    "scope_frozen_at, created_at, updated_at) "
                    "VALUES (:id, :w, :b, 'completed', 'pricing-v2', "
                    "'{\"version\": \"pricing-v2\"}'::json, NULL, 'p', "
                    "'pricing-run-scope-v2', 'EXPLICIT_ITEMS', 'SYSTEM_REPLAY', "
                    ":c, :s, now(), now(), now())"
                ),
                {
                    "id": legacy_bounded_id,
                    "w": workspace_id,
                    "b": batch_id,
                    "c": "c" * 64,
                    "s": "d" * 64,
                },
            )
            await session.commit()

        async with async_session_factory() as session:
            row = await session.get(PricingRun, legacy_bounded_id)
            assert row is not None
            assert row.policy_snapshot_hash is None
            with pytest.raises(
                PricingRunExecutionPolicyError, match="EXECUTION_POLICY_NOT_FROZEN"
            ):
                load_run_execution_policy(row)
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_a_bounded_row_with_an_invalid_hash_fails_closed_on_real_postgres(
    monkeypatch,
) -> None:
    """F3: испорченный отпечаток тоже закрывает путь к живой политике."""

    _require_disposable_database()
    _authorized_source_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    run_id = uuid4()
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        async with async_session_factory() as session:
            # ``ck_pricing_run_policy_snapshot_hash`` требует ровно 64 символа,
            # поэтому «испорченный» здесь — это правильной длины, но не hex.
            await session.execute(
                text(
                    "INSERT INTO pricing_runs (id, workspace_id, import_batch_id, "
                    "status, policy_version, policy_config, policy_snapshot_hash, "
                    "parser_version, scope_contract_version, scope_mode, "
                    "scope_confirmation_source, catalog_snapshot_hash, scope_hash, "
                    "scope_frozen_at, created_at, updated_at) "
                    "VALUES (:id, :w, :b, 'completed', 'pricing-v2', "
                    "'{\"version\": \"pricing-v2\"}'::json, :h, 'p', "
                    "'pricing-run-scope-v2', 'EXPLICIT_ITEMS', 'OPERATOR', "
                    ":c, :s, now(), now(), now())"
                ),
                {
                    "id": run_id,
                    "w": workspace_id,
                    "b": batch_id,
                    "h": "z" * 64,
                    "c": "c" * 64,
                    "s": "d" * 64,
                },
            )
            await session.commit()

        async with async_session_factory() as session:
            row = await session.get(PricingRun, run_id)
            assert row is not None
            with pytest.raises(
                PricingRunExecutionPolicyError, match="EXECUTION_POLICY_NOT_FROZEN"
            ):
                load_run_execution_policy(row)
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_a_true_legacy_unbounded_row_still_loads_on_real_postgres(
    monkeypatch,
) -> None:
    """F3: совместимость сохранена ровно там, где контракт её и допускает."""

    _require_disposable_database()
    _authorized_source_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    run_id = uuid4()
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        async with async_session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO pricing_runs (id, workspace_id, import_batch_id, "
                    "status, policy_version, policy_config, parser_version, "
                    "created_at, updated_at) VALUES (:id, :w, :b, 'completed', "
                    "'pricing-v2', '{\"version\": \"pricing-v2\"}'::json, 'p', "
                    "now(), now())"
                ),
                {"id": run_id, "w": workspace_id, "b": batch_id},
            )
            await session.commit()

        async with async_session_factory() as session:
            row = await session.get(PricingRun, run_id)
            assert row is not None
            assert row.scope_contract_version is None
            assert row.scope_confirmation_source == "LEGACY_UNBOUNDED"
            assert load_run_execution_policy(row).version == "pricing-v2"
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


# --------------------------------------------------------------------- F5


async def _bounded_run_with_items(
    *, workspace_id: UUID, batch_id: UUID, catalog_item_ids: list[UUID], key: str
) -> UUID:
    celery = Mock()
    celery.send_task = Mock(return_value=Mock())
    async with async_session_factory() as session:
        run = await create_pricing_run(
            session,
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            celery_app=celery,
            source_mode="e2e_fixture_replay",
            scope_mode=EXPLICIT_ITEMS_SCOPE,
            catalog_item_ids=catalog_item_ids,
            start=TrustedRunStart(
                confirmation_source=CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
                reason="isolated e2e stack replays seeded fixtures",
                idempotency_key=key,
            ),
        )
        await session.commit()
        return run.id


async def _insert_empty_run(*, workspace_id: UUID, batch_id: UUID) -> UUID:
    """Пустой доконтрактный прогон: место 0 свободно, уникальные индексы не мешают."""

    run_id = uuid4()
    async with async_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO pricing_runs (id, workspace_id, import_batch_id, "
                "status, policy_version, policy_config, parser_version, "
                "created_at, updated_at) VALUES (:id, :w, :b, 'completed', "
                "'pricing-v2', '{}'::json, 'p', now(), now())"
            ),
            {"id": run_id, "w": workspace_id, "b": batch_id},
        )
        await session.commit()
    return run_id


@requires_postgres
@pytest.mark.asyncio
async def test_membership_cannot_be_reassigned_to_another_run(monkeypatch) -> None:
    """F5, ровно репро: переезд строки членства на другой прогон обнулял состав.

    Барьер 0035 срабатывает на INSERT, а переезд — это UPDATE, поэтому состав
    источника становился нулевым, состав цели — единичным, и обе стороны
    переставали отвечать своим манифестам.
    """

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        source_run = await _bounded_run_with_items(
            workspace_id=workspace_id,
            batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
            key="f5-source-0001",
        )
        target_run = await _insert_empty_run(
            workspace_id=workspace_id, batch_id=batch_id
        )

        async with async_session_factory() as session:
            item = await session.scalar(
                select(PricingRunItem).where(
                    PricingRunItem.pricing_run_id == source_run
                )
            )
            assert item is not None
            item_id = item.id
            frozen_catalog_item = item.catalog_item_id
            frozen_position = item.membership_position
            frozen_snapshot_hash = item.start_snapshot_hash

        async with async_session_factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(
                    text(
                        "UPDATE pricing_run_items SET pricing_run_id = :t "
                        "WHERE id = :i"
                    ),
                    {"t": target_run, "i": item_id},
                )
                await session.commit()
            await session.rollback()

        async with async_session_factory() as session:
            source_count = await session.scalar(
                text(
                    "SELECT count(*) FROM pricing_run_items WHERE pricing_run_id = :i"
                ).bindparams(i=source_run)
            )
            target_count = await session.scalar(
                text(
                    "SELECT count(*) FROM pricing_run_items WHERE pricing_run_id = :i"
                ).bindparams(i=target_run)
            )
            after = await session.get(PricingRunItem, item_id)
        assert source_count == 1
        assert target_count == 0
        # Ни одна другая колонка улики не сдвинулась.
        assert after is not None
        assert after.pricing_run_id == source_run
        assert after.catalog_item_id == frozen_catalog_item
        assert after.membership_position == frozen_position
        assert after.start_snapshot_hash == frozen_snapshot_hash

        async with async_session_factory() as session:
            run_row = await session.get(PricingRun, source_run)
            assert run_row is not None
            await verify_run_membership(session, run_row)
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_membership_cannot_be_moved_across_workspaces(monkeypatch) -> None:
    """F5: переезд в чужое рабочее пространство — та же запись, но ещё и утечка."""

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    first_workspace, first_batch = uuid4(), uuid4()
    second_workspace, second_batch = uuid4(), uuid4()
    first_items = (uuid4(),)
    second_items = (uuid4(),)
    try:
        await _seed_catalog(
            workspace_id=first_workspace, batch_id=first_batch, item_ids=first_items
        )
        await _seed_catalog(
            workspace_id=second_workspace, batch_id=second_batch, item_ids=second_items
        )
        source_run = await _bounded_run_with_items(
            workspace_id=first_workspace,
            batch_id=first_batch,
            catalog_item_ids=[first_items[0]],
            key="f5-cross-0001",
        )
        foreign_run = await _insert_empty_run(
            workspace_id=second_workspace, batch_id=second_batch
        )

        async with async_session_factory() as session:
            item = await session.scalar(
                select(PricingRunItem).where(
                    PricingRunItem.pricing_run_id == source_run
                )
            )
            assert item is not None
            item_id = item.id

        async with async_session_factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(
                    text(
                        "UPDATE pricing_run_items SET pricing_run_id = :t "
                        "WHERE id = :i"
                    ),
                    {"t": foreign_run, "i": item_id},
                )
                await session.commit()
            await session.rollback()

        async with async_session_factory() as session:
            foreign_count = await session.scalar(
                text(
                    "SELECT count(*) FROM pricing_run_items WHERE pricing_run_id = :i"
                ).bindparams(i=foreign_run)
            )
            source_count = await session.scalar(
                text(
                    "SELECT count(*) FROM pricing_run_items WHERE pricing_run_id = :i"
                ).bindparams(i=source_run)
            )
        assert foreign_count == 0
        assert source_count == 1
    finally:
        await _cleanup(first_workspace)
        await _cleanup(second_workspace)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_the_exact_item_is_enforced_at_each_membership_position(
    monkeypatch,
) -> None:
    """F5: место N обязано нести именно ту позицию, которую назвал манифест.

    Прежний барьер спрашивал только «числится ли эта позиция в составе», поэтому
    правильную позицию можно было вставить на ЧУЖОЕ место: множество совпадало,
    порядок — нет.
    """

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(), uuid4())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        run_id = await _bounded_run_with_items(
            workspace_id=workspace_id,
            batch_id=batch_id,
            catalog_item_ids=[item_ids[0], item_ids[1]],
            key="f5-positions-0001",
        )

        async with async_session_factory() as session:
            run_row = await session.get(PricingRun, run_id)
            assert run_row is not None
            frozen = run_row.scope_manifest["execution"]["membership"][
                "catalog_item_ids"
            ]
        assert len(frozen) == 2

        # Освобождаем место 1 — законная вставка на него обязана пройти, а
        # вставка ЧУЖОЙ позиции на то же место — нет.
        async with async_session_factory() as session:
            await session.execute(
                text(
                    "ALTER TABLE pricing_run_items "
                    "DISABLE TRIGGER trg_pricing_run_items_no_delete"
                )
            )
            await session.execute(
                text(
                    "DELETE FROM pricing_run_items WHERE pricing_run_id = :i "
                    "AND membership_position = 1"
                ),
                {"i": run_id},
            )
            await session.execute(
                text(
                    "ALTER TABLE pricing_run_items "
                    "ENABLE TRIGGER trg_pricing_run_items_no_delete"
                )
            )
            await session.commit()

        misplaced = UUID(frozen[0])
        async with async_session_factory() as session:
            session.add(
                PricingRunItem(
                    pricing_run_id=run_id,
                    catalog_item_id=misplaced,
                    status="queued",
                    idempotency_key=f"misplaced:{run_id}",
                    start_snapshot={},
                    membership_position=1,
                )
            )
            with pytest.raises((DBAPIError, IntegrityError)):
                await session.commit()
            await session.rollback()

        async with async_session_factory() as session:
            count = await session.scalar(
                text(
                    "SELECT count(*) FROM pricing_run_items WHERE pricing_run_id = :i"
                ).bindparams(i=run_id)
            )
        assert count == 1, count
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_concurrent_inserts_cannot_both_claim_one_position(monkeypatch) -> None:
    """F5: точная проверка места обязана быть безгоночной.

    Две одновременные вставки претендуют на одно свободное место: одна несёт ту
    позицию каталога, которую назвал манифест, другая — чужую.  Пройти обязана
    ровно одна, и именно правильная.
    """

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(), uuid4())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        run_id = await _bounded_run_with_items(
            workspace_id=workspace_id,
            batch_id=batch_id,
            catalog_item_ids=[item_ids[0], item_ids[1]],
            key="f5-concurrent-0001",
        )
        async with async_session_factory() as session:
            run_row = await session.get(PricingRun, run_id)
            assert run_row is not None
            frozen = run_row.scope_manifest["execution"]["membership"][
                "catalog_item_ids"
            ]
        expected_at_one = UUID(frozen[1])
        wrong_at_one = UUID(frozen[0])

        async with async_session_factory() as session:
            await session.execute(
                text(
                    "ALTER TABLE pricing_run_items "
                    "DISABLE TRIGGER trg_pricing_run_items_no_delete"
                )
            )
            await session.execute(
                text(
                    "DELETE FROM pricing_run_items WHERE pricing_run_id = :i "
                    "AND membership_position = 1"
                ),
                {"i": run_id},
            )
            await session.execute(
                text(
                    "ALTER TABLE pricing_run_items "
                    "ENABLE TRIGGER trg_pricing_run_items_no_delete"
                )
            )
            await session.commit()

        started = asyncio.Event()
        arrived = 0
        lock = asyncio.Lock()

        async def _insert(catalog_item_id: UUID) -> bool:
            nonlocal arrived
            async with async_session_factory() as session:
                async with lock:
                    arrived += 1
                    if arrived == 2:
                        started.set()
                await started.wait()
                session.add(
                    PricingRunItem(
                        pricing_run_id=run_id,
                        catalog_item_id=catalog_item_id,
                        status="queued",
                        idempotency_key=f"race:{run_id}:{catalog_item_id}",
                        start_snapshot={},
                        membership_position=1,
                    )
                )
                try:
                    await session.commit()
                    return True
                except Exception:  # noqa: BLE001 - проигравший обязан упасть
                    await session.rollback()
                    return False

        results = await asyncio.gather(
            _insert(expected_at_one), _insert(wrong_at_one), return_exceptions=True
        )
        assert sum(1 for outcome in results if outcome is True) <= 1, results

        async with async_session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(
                            PricingRunItem.membership_position,
                            PricingRunItem.catalog_item_id,
                        )
                        .where(PricingRunItem.pricing_run_id == run_id)
                        .order_by(PricingRunItem.membership_position)
                    )
                ).all()
            )
        for position, catalog_item_id in rows:
            assert str(catalog_item_id) == frozen[position], (position, rows)
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_verification_names_the_position_that_disagrees(monkeypatch) -> None:
    """F5: проверка перед расчётом называет МЕСТО расхождения, а не только факт."""

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(), uuid4())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        run_id = await _bounded_run_with_items(
            workspace_id=workspace_id,
            batch_id=batch_id,
            catalog_item_ids=[item_ids[0], item_ids[1]],
            key="f5-verify-0001",
        )
        async with async_session_factory() as session:
            run_row = await session.get(PricingRun, run_id)
            assert run_row is not None
            await verify_run_membership(session, run_row)
            frozen = run_row.scope_manifest["execution"]["membership"][
                "catalog_item_ids"
            ]

        # Обе строки на месте, но поменялись местами: число сходится, порядок нет.
        async with async_session_factory() as session:
            for table_trigger in (
                "trg_pricing_run_items_immutable_start_snapshot",
                "trg_pricing_run_items_no_delete",
            ):
                await session.execute(
                    text(
                        "ALTER TABLE pricing_run_items DISABLE TRIGGER "
                        f"{table_trigger}"
                    )
                )
            await session.execute(
                text(
                    "UPDATE pricing_run_items SET membership_position = 9 "
                    "WHERE pricing_run_id = :i AND membership_position = 0"
                ),
                {"i": run_id},
            )
            await session.execute(
                text(
                    "UPDATE pricing_run_items SET membership_position = 0 "
                    "WHERE pricing_run_id = :i AND membership_position = 1"
                ),
                {"i": run_id},
            )
            await session.execute(
                text(
                    "UPDATE pricing_run_items SET membership_position = 1 "
                    "WHERE pricing_run_id = :i AND membership_position = 9"
                ),
                {"i": run_id},
            )
            for table_trigger in (
                "trg_pricing_run_items_no_delete",
                "trg_pricing_run_items_immutable_start_snapshot",
            ):
                await session.execute(
                    text(
                        "ALTER TABLE pricing_run_items ENABLE TRIGGER "
                        f"{table_trigger}"
                    )
                )
            await session.commit()

        async with async_session_factory() as session:
            run_row = await session.get(PricingRun, run_id)
            assert run_row is not None
            with pytest.raises(
                PricingRunMembershipError, match="membership position 0"
            ) as failure:
                await verify_run_membership(session, run_row)
        assert frozen[0] in str(failure.value)
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()
