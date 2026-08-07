"""Замороженный контракт исполнения прогона: контракт старта, политика, снимок, состав.

Второе враждебное ревью 2026-08-01 показало, что «ограниченный прогон» из
миграций 0032/0033 ограничивал только область, но не то, ПО ЧЕМУ он исполняется:

* F1 — «контрактом предпросмотра» служили два хеша, которые сервер публиковал
  сам; ни токена, ни срока, ни актора у них не было, а безключевой доверенный
  старт получал активный прогон оператора как свой.
* F3 — политика не была заморожена: снимок терял большую часть полей
  ``RaisePolicy``, а расчёт перечитывал текущий файл развёртывания.  База при
  этом позволяла переписать ``policy_config`` уже начатого прогона.
* F4 — снимок позиции сохранялся, но исполнение продолжало читать живой
  ``CatalogItem``.
* F5 — барьер дозаписи членства опирался на изменяемый ``total_items`` и
  считал строки перед вставкой, то есть в гонке пропускал обоих.

Набору нужна одноразовая база, имя которой содержит ``p15017``.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace as dc_replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

import marko.services.market_collection as market_collection
import marko.services.pricing_runs as pricing_runs
from marko.core.config import get_settings
from marko.infrastructure.db.models import (
    CatalogImportBatch,
    CatalogItem,
    CatalogItemOverride,
    PricingRecommendation,
    PricingRun,
    PricingRunItem,
    PricingRunPreviewContract,
    Workspace,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.market_collection import _calculate_and_persist
from marko.services.pricing_runs import (
    ACTOR_TYPE_USER,
    CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
    EXPLICIT_ITEMS_SCOPE,
    FULL_CATALOG_SCOPE,
    PRICING_RUN_START_PERMISSION,
    OperatorRunStart,
    PreviewActor,
    PricingRunActiveScopeConflictError,
    PricingRunError,
    PricingRunIdempotencyConflictError,
    PricingRunMembershipError,
    PricingRunScopeConflictError,
    PricingRunSnapshotError,
    PricingRunStartContractError,
    TrustedRunStart,
    create_pricing_run,
    execution_policy_hash,
    load_run_execution_policy,
    preview_pricing_run_for_operator,
    start_snapshot_fingerprint,
    verify_run_membership,
)

pytestmark = pytest.mark.postgres
BACKEND_ROOT = Path(__file__).resolve().parents[1]


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
            "Refusing frozen-contract test: DATABASE_URL must name a disposable "
            "database containing 'p15017'"
        )


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
    """Развёртывание с записанным разрешением на сбор: сеть при этом не трогается."""

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


def _actor(**overrides) -> PreviewActor:
    kwargs: dict[str, object] = {
        "actor_id": "00000000-0000-0000-0000-00000000beef",
        "actor_type": ACTOR_TYPE_USER,
        "workspace_role": "admin",
        "permissions": (PRICING_RUN_START_PERMISSION,),
    }
    kwargs.update(overrides)
    return PreviewActor(**kwargs)


def _replay_start(**overrides) -> TrustedRunStart:
    kwargs: dict[str, object] = {
        "confirmation_source": CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
        "reason": "isolated e2e stack replays seeded fixtures",
    }
    kwargs.update(overrides)
    return TrustedRunStart(**kwargs)


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
                name="P15017 frozen execution",
                slug=f"p15017-frozen-{workspace_id.hex}",
            )
        )
        await session.flush()
        session.add(
            CatalogImportBatch(
                id=batch_id,
                workspace_id=workspace_id,
                filename="frozen-execution.xlsx",
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
                    sku=f"SKU-FROZEN-{position}",
                    oe_raw=f"1K0 33325{position}",
                    oe_norm=f"1K033325{position}",
                    name=f"Позиция каталога {position}",
                    category="brakes",
                    brand="KEMP",
                    identity_status="OE_CONFIRMED",
                    identity_reason="EXPLICIT_OE_TEST_FIXTURE",
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
    async with async_session_factory() as session:
        try:
            for table in ("catalog_item_overrides", "pricing_recommendations"):
                await session.execute(
                    text(f"ALTER TABLE {table} DISABLE TRIGGER trg_{table}_append_only")
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
                delete(PricingRun).where(PricingRun.workspace_id == workspace_id)
            )
            await session.execute(
                delete(PricingRunPreviewContract).where(
                    PricingRunPreviewContract.workspace_id == workspace_id
                )
            )
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            for table in ("pricing_recommendations", "catalog_item_overrides"):
                await session.execute(
                    text(f"ALTER TABLE {table} ENABLE TRIGGER trg_{table}_append_only")
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _issue(
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
    scope_mode: str = EXPLICIT_ITEMS_SCOPE,
    catalog_item_ids: list[UUID] | None = None,
    actor: PreviewActor | None = None,
    policy_config: dict | None = None,
):
    async with async_session_factory() as session:
        scope, contract = await preview_pricing_run_for_operator(
            session,
            workspace_id=workspace_id,
            import_batch_id=import_batch_id,
            actor=actor or _actor(),
            scope_mode=scope_mode,
            catalog_item_ids=catalog_item_ids,
            policy_config=policy_config,
            confirm_full_catalog=scope_mode == FULL_CATALOG_SCOPE,
        )
        await session.commit()
    return scope, contract


async def _start(
    *,
    workspace_id: UUID,
    import_batch_id: UUID,
    contract,
    idempotency_key: str,
    actor: PreviewActor | None = None,
    scope_mode: str = EXPLICIT_ITEMS_SCOPE,
    catalog_item_ids: list[UUID] | None = None,
    policy_config: dict | None = None,
    token: str | None = None,
    commit: bool = True,
) -> PricingRun:
    celery = Mock()
    celery.send_task = Mock(return_value=Mock())
    async with async_session_factory() as session:
        run = await create_pricing_run(
            session,
            workspace_id=workspace_id,
            import_batch_id=import_batch_id,
            celery_app=celery,
            scope_mode=scope_mode,
            catalog_item_ids=catalog_item_ids,
            policy_config=policy_config,
            start=OperatorRunStart(
                idempotency_key=idempotency_key,
                preview_token=token or contract.token,
                actor=actor or _actor(),
                confirm_full_catalog=scope_mode == FULL_CATALOG_SCOPE,
            ),
        )
        if commit:
            await session.commit()
        run_id = run.id
    async with async_session_factory() as session:
        refreshed = await session.get(PricingRun, run_id)
    assert refreshed is not None
    return refreshed


# --------------------------------------------------------------------- F1


@requires_postgres
@pytest.mark.asyncio
async def test_a_forged_or_unknown_preview_token_cannot_start_a_run(
    monkeypatch,
) -> None:
    """F1: старт без выданного сервером контракта закрыт наглухо.

    Повтор ревью: ``arbitrary_well_formed_hashes_accepted_as_operator_start``
    было True, потому что «контракт» состоял из значений, которые сервер сам и
    публикует.  Теперь предъявляется непрозрачный токен, которого у злоумышленника
    нет и подобрать который нельзя.
    """

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
        forged = "mrp1_" + "A" * 43
        assert forged != contract.token
        with pytest.raises(
            PricingRunStartContractError, match="PREVIEW_CONTRACT_UNKNOWN"
        ):
            await _start(
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                contract=contract,
                token=forged,
                idempotency_key="forged-token-0001",
                catalog_item_ids=[item_ids[0]],
            )
        async with async_session_factory() as session:
            created = await session.scalar(
                select(PricingRun).where(PricingRun.workspace_id == workspace_id)
            )
        assert created is None, "подделанный токен создал прогон"
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_an_expired_preview_contract_fails_closed(monkeypatch) -> None:
    """F1: у контракта есть срок, и просроченный контракт основанием не является."""

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
        async with async_session_factory() as session:
            await session.execute(
                text(
                    "UPDATE pricing_run_preview_contracts "
                    "SET issued_at = now() - interval '2 hours', "
                    "expires_at = now() - interval '1 hour' WHERE id = :i"
                ),
                {"i": contract.contract_id},
            )
            await session.commit()

        with pytest.raises(
            PricingRunStartContractError, match="PREVIEW_CONTRACT_EXPIRED"
        ):
            await _start(
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                contract=contract,
                idempotency_key="expired-contract-0001",
                catalog_item_ids=[item_ids[0]],
            )
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"actor_id": "00000000-0000-0000-0000-0000000000aa"}, "ACTOR_MISMATCH"),
        ({"actor_type": "service"}, "ACTOR_MISMATCH"),
        ({"workspace_role": "member"}, "ROLE_CHANGED"),
        ({"permissions": ()}, "PERMISSIONS_CHANGED"),
        (
            {"permissions": (PRICING_RUN_START_PERMISSION, "pricing_run:cancel")},
            "PERMISSIONS_CHANGED",
        ),
    ],
)
async def test_a_contract_issued_to_another_authority_cannot_start_a_run(
    monkeypatch, overrides, expected
) -> None:
    """F1: контракт привязан к актору, его роли и правам, а не только к области."""

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
        with pytest.raises(PricingRunStartContractError, match=expected):
            await _start(
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                contract=contract,
                idempotency_key="foreign-authority-0001",
                actor=_actor(**overrides),
                catalog_item_ids=[item_ids[0]],
            )
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_a_contract_from_another_workspace_is_not_recognized(
    monkeypatch,
) -> None:
    """F1: контракт чужого рабочего пространства не существует для этого."""

    _require_disposable_database()
    _authorized_source_environment(monkeypatch)
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
        _, foreign = await _issue(
            workspace_id=first_workspace,
            import_batch_id=first_batch,
            catalog_item_ids=[first_items[0]],
        )
        with pytest.raises(
            PricingRunStartContractError, match="PREVIEW_CONTRACT_UNKNOWN"
        ):
            await _start(
                workspace_id=second_workspace,
                import_batch_id=second_batch,
                contract=foreign,
                idempotency_key="cross-workspace-0001",
                catalog_item_ids=[second_items[0]],
            )
    finally:
        await _cleanup(first_workspace)
        await _cleanup(second_workspace)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_a_contract_does_not_authorize_a_different_request_body(
    monkeypatch,
) -> None:
    """F1: контракт закрывает ИМЕННО тот запрос, который был предпросмотрен."""

    _require_disposable_database()
    _authorized_source_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(), uuid4())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        _, contract = await _issue(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
        )
        # Тот же импорт, тот же оператор, но другой состав — другой запрос.
        with pytest.raises(
            PricingRunStartContractError, match="PREVIEW_CONTRACT_REQUEST_MISMATCH"
        ):
            await _start(
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                contract=contract,
                idempotency_key="altered-request-0001",
                catalog_item_ids=[item_ids[1]],
            )
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_a_contract_does_not_authorize_a_changed_policy(monkeypatch) -> None:
    """F1/F3: сдвиг политики между предпросмотром и стартом — типизированный отказ."""

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
        # Файл развёртывания поменялся уже после предпросмотра.
        drifted = dc_replace(
            pricing_runs._configured_raise_policy(),
            target_quantile=Decimal("0.01"),
            source_sha256="d" * 64,
        )
        monkeypatch.setattr(
            pricing_runs, "_configured_raise_policy", lambda: drifted
        )
        with pytest.raises(PricingRunScopeConflictError, match="POLICY_CHANGED"):
            await _start(
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                contract=contract,
                idempotency_key="drifted-policy-0001",
                catalog_item_ids=[item_ids[0]],
            )
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_a_contract_does_not_authorize_a_changed_scope(monkeypatch) -> None:
    """F1: каталог, сдвинувшийся между предпросмотром и стартом, — отказ."""

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
        async with async_session_factory() as session:
            await session.execute(
                text("UPDATE catalog_items SET current_price = 999 WHERE id = :i"),
                {"i": item_ids[0]},
            )
            await session.commit()
        with pytest.raises(
            PricingRunScopeConflictError, match="CATALOG_SNAPSHOT_CHANGED"
        ):
            await _start(
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                contract=contract,
                idempotency_key="drifted-catalog-0001",
                catalog_item_ids=[item_ids[0]],
            )
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_the_same_attempt_retries_and_a_second_deliberate_run_is_refused(
    monkeypatch,
) -> None:
    """F1: контракт одноразов, но повтор ТОЙ ЖЕ попытки обязан пройти.

    Разница между «сеть уронила ответ, нажали ещё раз» и «намеренно запустили
    второй прогон» — это ключ идемпотентности, а не удача.
    """

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
            contract=contract,
            idempotency_key="single-attempt-0001",
            catalog_item_ids=[item_ids[0]],
        )
        retry = await _start(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            contract=contract,
            idempotency_key="single-attempt-0001",
            catalog_item_ids=[item_ids[0]],
        )
        assert retry.id == first.id, "повтор той же попытки создал второй прогон"

        # Тот же токен под другим ключом — намеренно другой запуск: отказ.
        with pytest.raises(
            PricingRunIdempotencyConflictError,
            match="PREVIEW_CONTRACT_ALREADY_CONSUMED",
        ):
            await _start(
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                contract=contract,
                idempotency_key="second-deliberate-0002",
                catalog_item_ids=[item_ids[0]],
            )
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
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_a_trusted_lane_cannot_adopt_an_active_operator_run(monkeypatch) -> None:
    """F1: воспроизведение репро — доверенная полоса и полоса оператора разделены.

    Ровно это ревью и предъявило: безключевой ``TrustedRunStart`` возвращал
    keyed-прогон оператора как свой, потому что совпадение области принималось
    за совпадение запроса.
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
            contract=contract,
            idempotency_key="operator-active-0001",
            catalog_item_ids=[item_ids[0]],
        )
        assert operator_run.scope_confirmation_source == "OPERATOR"

        _e2e_replay_environment(monkeypatch)
        async with async_session_factory() as session:
            with pytest.raises(
                PricingRunActiveScopeConflictError, match="ACTIVE_RUN_SCOPE_CONFLICT"
            ):
                await create_pricing_run(
                    session,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    celery_app=celery,
                    source_mode="e2e_fixture_replay",
                    scope_mode=EXPLICIT_ITEMS_SCOPE,
                    catalog_item_ids=[item_ids[0]],
                    start=_replay_start(),
                )
            await session.rollback()
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


# --------------------------------------------------------------------- F3


@requires_postgres
@pytest.mark.asyncio
async def test_the_run_freezes_a_complete_policy_snapshot_with_its_hash(
    monkeypatch,
) -> None:
    """F3: снимок политики полон, а его отпечаток посчитан по тем же байтам."""

    _require_disposable_database()
    _authorized_source_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        scope, contract = await _issue(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            catalog_item_ids=[item_ids[0]],
        )
        run = await _start(
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            contract=contract,
            idempotency_key="policy-snapshot-0001",
            catalog_item_ids=[item_ids[0]],
        )
        raise_policy = run.policy_config["raise_policy"]
        # Именно те поля, которых прежде не было в снимке.
        for name in ("target_quantile", "min_evidence", "max_step_pct"):
            assert name in raise_policy, name
        assert run.policy_snapshot_hash == execution_policy_hash(run.policy_config)
        # Хеш области и сохранённая политика связаны одними байтами.
        assert run.policy_snapshot_hash == scope.policy_hash
        assert contract.policy_snapshot_hash == run.policy_snapshot_hash
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_calculation_never_re_reads_a_changed_deployment_policy(
    monkeypatch,
) -> None:
    """F3, убитый мутант «load-current-policy».

    Репро ревью: после подмены файла развёртывания ``policy_from_dict`` отдавала
    новую политику (``calculation_reload_raise_sha=dddd…``,
    ``target_quantile=0.01``), и никто этого не отвергал.
    """

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
            contract=contract,
            idempotency_key="policy-drift-0001",
            catalog_item_ids=[item_ids[0]],
        )
        frozen = load_run_execution_policy(run)
        frozen_sha = frozen.raise_policy.source_sha256
        frozen_quantile = frozen.raise_policy.target_quantile

        drifted = dc_replace(
            pricing_runs._configured_raise_policy(),
            target_quantile=Decimal("0.01"),
            source_sha256="d" * 64,
        )
        monkeypatch.setattr(
            pricing_runs, "_configured_raise_policy", lambda: drifted
        )
        reloaded = load_run_execution_policy(run)

        assert reloaded.raise_policy.source_sha256 == frozen_sha
        assert reloaded.raise_policy.target_quantile == frozen_quantile
        assert reloaded.raise_policy.source_sha256 != "d" * 64
        assert reloaded.raise_policy.target_quantile != Decimal("0.01")
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_the_database_refuses_to_rewrite_a_bounded_runs_policy(
    monkeypatch,
) -> None:
    """F3, убитый мутант «mutate run.policy_config».

    Репро ревью: ``UPDATE pricing_runs SET policy_config = ...`` проходил, и
    ``policy_version`` становился ``tampered``.
    """

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
            contract=contract,
            idempotency_key="policy-immutability-0001",
            catalog_item_ids=[item_ids[0]],
        )
        for statement in (
            "UPDATE pricing_runs SET policy_config = "
            "'{\"version\": \"tampered\"}'::json WHERE id = :i",
            "UPDATE pricing_runs SET policy_version = 'tampered' WHERE id = :i",
            "UPDATE pricing_runs SET policy_snapshot_hash = NULL WHERE id = :i",
            "UPDATE pricing_runs SET parser_version = 'tampered' WHERE id = :i",
            "UPDATE pricing_runs SET classifier_version = 'tampered' WHERE id = :i",
            "UPDATE pricing_runs SET coefficient_model = 'simple' WHERE id = :i",
        ):
            async with async_session_factory() as session:
                with pytest.raises(DBAPIError, match="immutable"):
                    await session.execute(text(statement), {"i": run.id})
                    await session.commit()
                await session.rollback()

        async with async_session_factory() as session:
            after = await session.get(PricingRun, run.id)
            assert after is not None
            assert after.policy_version != "tampered"
            assert after.policy_snapshot_hash == execution_policy_hash(
                after.policy_config
            )
        # Ход прогона по-прежнему записывается: заморожены входы, а не счётчики.
        async with async_session_factory() as session:
            await session.execute(
                text("UPDATE pricing_runs SET completed_items = 1 WHERE id = :i"),
                {"i": run.id},
            )
            await session.commit()
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_a_corrupted_policy_snapshot_fails_closed(monkeypatch) -> None:
    """F3: расхождение снимка и отпечатка — отказ, а не тихий возврат к файлу."""

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
            contract=contract,
            idempotency_key="policy-corrupt-0001",
            catalog_item_ids=[item_ids[0]],
        )
        tampered = dict(run.policy_config)
        tampered["raise_policy"] = {
            **tampered["raise_policy"],
            "target_quantile": "0.01",
        }
        run.policy_config = tampered
        with pytest.raises(PricingRunError, match="EXECUTION_POLICY_TAMPERED"):
            load_run_execution_policy(run)

        run.policy_config = {"version": "pricing-v2"}
        with pytest.raises(PricingRunError, match="EXECUTION_POLICY_TAMPERED"):
            load_run_execution_policy(run)
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


# --------------------------------------------------------------------- F4


@requires_postgres
@pytest.mark.asyncio
async def test_calculation_stays_frozen_for_every_catalog_field_class(
    monkeypatch,
) -> None:
    """F4: OE, категория, цена, валюта, статус, запас и продажи — все заморожены.

    Репро ревью: ветка bounded была True, снимок нёс замороженные значения, а
    контекст расчёта всё равно показывал живые (``LIVE-DRIFT``, ``4242``,
    ``USD``, ``stock_qty=77``).

    Правки оператора здесь намеренно нет: она перекрывает поля позиции в
    ``build_pricing_context``, и тест, где она есть, не может отличить
    замороженную позицию каталога от замороженной правки.  Класс полей, который
    в снимке рекомендации не виден (OE и категория уходят в подбор
    коэффициентов), проверяется по тому, что подбор получил на вход.
    """

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    celery = Mock()
    celery.send_task = Mock(return_value=Mock())
    lookups: list[dict[str, object]] = []
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
            snapshot = dict(run_item.start_snapshot)
            snapshot_hash = run_item.start_snapshot_hash
        # Снимок обязан нести КАЖДЫЙ класс входов, а не только цену и категорию.
        for name in (
            "oe_norm",
            "category",
            "current_price",
            "currency",
            "stock_status",
            "stock_qty",
            "units_sold_30d",
            "override_values",
        ):
            assert name in snapshot, name
        frozen_oe = snapshot["oe_norm"]
        frozen_category = snapshot["category"]
        assert snapshot_hash == start_snapshot_fingerprint(snapshot)

        # Подбор коэффициентов читает OE и категорию: записываем, что он получил.
        real_lookup = market_collection.load_target_tier_coefficients

        async def _recording_lookup(
            session,
            *,
            run,
            category,
            oe_norm,
            policy,
            comparison_identity_keys=(),
        ):
            lookups.append({"category": category, "oe_norm": oe_norm})
            return await real_lookup(
                session,
                run=run,
                category=category,
                oe_norm=oe_norm,
                policy=policy,
                comparison_identity_keys=comparison_identity_keys,
            )

        monkeypatch.setattr(
            market_collection, "load_target_tier_coefficients", _recording_lookup
        )

        # Каждый класс входов сдвигается уже ПОСЛЕ старта.
        async with async_session_factory() as session:
            await session.execute(
                text(
                    "UPDATE catalog_items SET oe_norm = 'LIVEDRIFT', "
                    "category = 'LIVE-DRIFT', current_price = 4242, "
                    "currency = 'USD', stock_qty = 77, units_sold_30d = 999, "
                    "units_sold_60d = 999, stock_age_days = 999, "
                    "stock_status = 'dead_stock' WHERE id = :i"
                ),
                {"i": item_ids[0]},
            )
            await session.commit()

        await _calculate_and_persist(run_item_id)

        async with async_session_factory() as session:
            recommendation = await session.scalar(
                select(PricingRecommendation).where(
                    PricingRecommendation.pricing_run_item_id == run_item_id
                )
            )
        assert recommendation is not None
        context = recommendation.context_snapshot
        assert context["category"] == frozen_category, context["category"]
        assert context["category"] != "LIVE-DRIFT"
        assert Decimal(context["current_price"]) == Decimal("800.00")
        assert context["currency"] == "UAH"
        assert context["stock_status"] == "unknown", context["stock_status"]
        assert Decimal(context["stock_qty"]) == Decimal("5")
        assert Decimal(context["units_sold_30d"]) == Decimal("3")
        # OE и категория, ушедшие в подбор коэффициентов, тоже замороженные.
        assert lookups, "подбор коэффициентов не был вызван"
        for seen in lookups:
            assert seen["oe_norm"] == frozen_oe, seen
            assert seen["oe_norm"] != "LIVEDRIFT"
            assert seen["category"] == frozen_category, seen
            assert seen["category"] != "LIVE-DRIFT"
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_calculation_stays_frozen_for_the_resolved_operator_override(
    monkeypatch,
) -> None:
    """F4: операторский контекст берётся из снимка, а не по ссылке в живую строку.

    Хранить один ``override_id`` было недостаточно: расчёт всё равно шёл в
    строку правки за значениями.  Правки append-only, поэтому «подмена» здесь —
    это новая правка, поданная уже после старта.
    """

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    frozen_override_id = uuid4()
    celery = Mock()
    celery.send_task = Mock(return_value=Mock())
    try:
        await _seed_catalog(
            workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids
        )
        async with async_session_factory() as session:
            session.add(
                CatalogItemOverride(
                    id=frozen_override_id,
                    catalog_item_id=item_ids[0],
                    user_id=None,
                    stock_qty=Decimal("11"),
                    stock_status="fresh",
                    units_sold_30d=Decimal("7"),
                    reason="Операторский контекст на момент старта",
                )
            )
            await session.commit()

        async with async_session_factory() as session:
            run = await create_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                celery_app=celery,
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
            snapshot = dict(run_item.start_snapshot)
            frozen_reference = run_item.catalog_item_override_id
        assert frozen_reference == frozen_override_id
        # В снимке лежат ЗНАЧЕНИЯ правки, а не только её идентификатор.
        assert snapshot["override_values"] is not None
        assert Decimal(snapshot["override_values"]["stock_qty"]) == Decimal("11")
        assert snapshot["override_values"]["stock_status"] == "fresh"

        async with async_session_factory() as session:
            session.add(
                CatalogItemOverride(
                    id=uuid4(),
                    catalog_item_id=item_ids[0],
                    user_id=None,
                    stock_qty=Decimal("99"),
                    stock_status="dead_stock",
                    units_sold_30d=Decimal("555"),
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
        assert recommendation is not None
        context = recommendation.context_snapshot
        assert Decimal(context["stock_qty"]) == Decimal("11"), context["stock_qty"]
        assert context["stock_status"] == "fresh", context["stock_status"]
        assert Decimal(context["units_sold_30d"]) == Decimal("7")
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_a_tampered_start_snapshot_fails_closed_instead_of_reading_live_rows(
    monkeypatch,
) -> None:
    """F4: испорченный снимок — отказ, а не молчаливый возврат к живому каталогу."""

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
                scope_mode=FULL_CATALOG_SCOPE,
                start=_replay_start(full_catalog_confirmed=True),
            )
            await session.commit()
            run_id = run.id

        # Снимок и его отпечаток неизменяемы в базе.
        for statement in (
            "UPDATE pricing_run_items SET start_snapshot = '{}'::json "
            "WHERE pricing_run_id = :i",
            "UPDATE pricing_run_items SET start_snapshot_hash = NULL "
            "WHERE pricing_run_id = :i",
            "UPDATE pricing_run_items SET membership_position = 5 "
            "WHERE pricing_run_id = :i",
        ):
            async with async_session_factory() as session:
                with pytest.raises(DBAPIError, match="immutable"):
                    await session.execute(text(statement), {"i": run_id})
                    await session.commit()
                await session.rollback()

        # И сам расчёт отказывается считать по снимку, не сходящемуся с
        # отпечатком.  Строки читаются заранее и отсоединяются: проверяется путь
        # расчёта, а не то, что база и так отвергает запись.
        async with async_session_factory() as session:
            run_row = await session.get(PricingRun, run_id)
            run_item = await session.scalar(
                select(PricingRunItem).where(PricingRunItem.pricing_run_id == run_id)
            )
            live_item = await session.get(CatalogItem, item_ids[0])
            assert run_item is not None and run_row is not None
            session.expunge_all()

        run_item.start_snapshot = {**run_item.start_snapshot, "category": "SMUGGLED"}
        with pytest.raises(PricingRunSnapshotError, match="START_SNAPSHOT_TAMPERED"):
            pricing_runs.resolve_execution_catalog_item(run_row, run_item, live_item)

        run_item.start_snapshot = {}
        with pytest.raises(PricingRunSnapshotError, match="START_SNAPSHOT_MISSING"):
            pricing_runs.resolve_execution_catalog_item(run_row, run_item, live_item)
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


# --------------------------------------------------------------------- F5


@requires_postgres
@pytest.mark.asyncio
async def test_membership_defining_columns_are_immutable(monkeypatch) -> None:
    """F5, убитый мутант: ``UPDATE pricing_runs SET total_items = 2`` запрещён.

    Репро ревью начиналось именно с него: барьер 0033 доверял изменяемому
    счётчику, поэтому его хватало, чтобы открыть дозапись.
    """

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(), uuid4())
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
                start=_replay_start(),
            )
            await session.commit()
            run_id = run.id

        for statement in (
            "UPDATE pricing_runs SET total_items = 2 WHERE id = :i",
            "UPDATE pricing_runs SET scope_manifest = '{}'::json WHERE id = :i",
            "UPDATE pricing_runs SET scope_hash = repeat('a', 64) WHERE id = :i",
            "UPDATE pricing_runs SET scope_confirmation_source = 'OPERATOR' "
            "WHERE id = :i",
        ):
            async with async_session_factory() as session:
                with pytest.raises(DBAPIError, match="immutable"):
                    await session.execute(text(statement), {"i": run_id})
                    await session.commit()
                await session.rollback()

        async with async_session_factory() as session:
            after = await session.get(PricingRun, run_id)
            assert after is not None and after.total_items == 1
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_the_growth_barrier_reads_the_manifest_not_total_items(
    monkeypatch,
) -> None:
    """F5: барьер обязан НЕ ЗАВИСЕТЬ от ``total_items``, даже если тот подменён.

    Прошлый барьер спрашивал границу у изменяемого счётчика, поэтому вся атака
    сводилась к одному ``UPDATE``.  Здесь неизменяемость колонки снимается
    намеренно (одноразовая база), счётчик поднимается до 99 — и дозапись всё
    равно обязана быть отвергнутой, потому что граница берётся из неизменяемого
    манифеста.  Иначе «запрет менять total_items» — единственная защита, и её
    достаточно обойти один раз.
    """

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(), uuid4())
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
                start=_replay_start(),
            )
            await session.commit()
            run_id = run.id

        async with async_session_factory() as session:
            await session.execute(
                text(
                    "ALTER TABLE pricing_runs "
                    "DISABLE TRIGGER trg_pricing_runs_immutable_scope"
                )
            )
            await session.execute(
                text("UPDATE pricing_runs SET total_items = 99 WHERE id = :i"),
                {"i": run_id},
            )
            await session.execute(
                text(
                    "ALTER TABLE pricing_runs "
                    "ENABLE TRIGGER trg_pricing_runs_immutable_scope"
                )
            )
            await session.commit()

        async with async_session_factory() as session:
            session.add(
                PricingRunItem(
                    pricing_run_id=run_id,
                    catalog_item_id=item_ids[1],
                    status="queued",
                    idempotency_key=f"smuggled-after-counter:{run_id}",
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
        async with async_session_factory() as session:
            # Счётчик вернуть на место, иначе уборка спорит с триггером.
            await session.execute(
                text(
                    "ALTER TABLE pricing_runs "
                    "DISABLE TRIGGER trg_pricing_runs_immutable_scope"
                )
            )
            await session.execute(
                text(
                    "UPDATE pricing_runs SET total_items = 1 "
                    "WHERE workspace_id = :w"
                ),
                {"w": workspace_id},
            )
            await session.execute(
                text(
                    "ALTER TABLE pricing_runs "
                    "ENABLE TRIGGER trg_pricing_runs_immutable_scope"
                )
            )
            await session.commit()
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_insert_after_freeze_cannot_grow_or_reshape_the_membership(
    monkeypatch,
) -> None:
    """F5: дозапись после заморозки не проходит, а состав и порядок сверяются."""

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(), uuid4())
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
                start=_replay_start(),
            )
            await session.commit()
            run_id = run.id

        # Ровно репро ревью, но уже без возможности поднять total_items.
        async with async_session_factory() as session:
            session.add(
                PricingRunItem(
                    pricing_run_id=run_id,
                    catalog_item_id=item_ids[1],
                    status="queued",
                    idempotency_key=f"smuggled:{run_id}",
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
            run_row = await session.get(PricingRun, run_id)
            assert run_row is not None
            # Материализованный состав по-прежнему сходится с манифестом.
            await verify_run_membership(session, run_row)
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_concurrent_inserts_cannot_exceed_the_frozen_membership(
    monkeypatch,
) -> None:
    """F5: барьер обязан быть безгоночным.

    Прежний «посчитать, затем вставить» в двух одновременных транзакциях видел
    одно и то же число и пропускал обе вставки.  Здесь две вставки идут
    параллельно на одну свободную позицию, и пройти обязана ровно одна.
    """

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(), uuid4(), uuid4())
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
                catalog_item_ids=[item_ids[0], item_ids[1]],
                start=_replay_start(),
            )
            await session.commit()
            run_id = run.id

        # Освобождаем одно место, чтобы «дозаписать» можно было ровно одну
        # строку: две одновременные попытки обязаны разойтись, а не пройти обе.
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
                        idempotency_key=f"{run_id}:{catalog_item_id}",
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
            _insert(item_ids[1]), _insert(item_ids[1]), return_exceptions=True
        )
        succeeded = sum(1 for outcome in results if outcome is True)
        assert succeeded <= 1, results

        async with async_session_factory() as session:
            count = await session.scalar(
                text(
                    "SELECT count(*) FROM pricing_run_items WHERE pricing_run_id = :i"
                ).bindparams(i=run_id)
            )
        assert count <= 2, count
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()


@requires_postgres
@pytest.mark.asyncio
async def test_membership_verification_rejects_a_reshaped_run(monkeypatch) -> None:
    """F5: проверка перед расчётом сверяет и число, и упорядоченный отпечаток."""

    _require_disposable_database()
    _e2e_replay_environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(), uuid4())
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
                catalog_item_ids=[item_ids[0], item_ids[1]],
                start=_replay_start(),
            )
            await session.commit()
            run_id = run.id

        async with async_session_factory() as session:
            run_row = await session.get(PricingRun, run_id)
            assert run_row is not None
            await verify_run_membership(session, run_row)

        # Одна позиция исчезла: и число, и отпечаток обязаны это увидеть.
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

        async with async_session_factory() as session:
            run_row = await session.get(PricingRun, run_id)
            assert run_row is not None
            with pytest.raises(
                PricingRunMembershipError, match="RUN_MEMBERSHIP_CHANGED"
            ):
                await verify_run_membership(session, run_row)
    finally:
        await _cleanup(workspace_id)
        get_settings.cache_clear()
