"""Opt-in PostgreSQL proof that the calculation uses frozen start inputs.

Требуется одноразовая база, имя которой содержит ``p15017``.

Отдельный файл от ``test_pricing_run_scope_postgres.py``: там доказывается
контракт области, здесь — что настоящий расчёт читает именно замороженные
вход. Ревью 2026-08-01 показало, что прежнего доказательства недостаточно:
мутация, подменяющая только загрузчик себестоимости на «последнюю живую»,
проходила незамеченной, потому что в наборе не было ни одной записи
себестоимости.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from decimal import Decimal
import json
import os
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.engine import make_url

from marko.core.config import get_settings
from marko.core.cost_encryption import encrypt_cost, parse_cost_keyring
from marko.infrastructure.db.models import (
    CatalogImportBatch,
    CatalogItem,
    CatalogItemCostRecord,
    MarketObservation,
    MarketplaceStore,
    PricingRecommendation,
    PricingRun,
    PricingRunItem,
    RawMarketCapture,
    StoreKind,
    Workspace,
    WorkspaceStore,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services.matching import ComparisonParams, build_comparison
from marko.services.decision_fingerprint import canonical_sha256
from marko.services.parser_models import SeedInfo
from marko.services.scraper_contract import (
    RETRIEVAL_KIND_PROM_OE_PAGE,
    ScrapeInput,
    ScrapeOutput,
)
from factories import product
from marko.parsers.prom.gateway import MOTORS_IDENTITY_SOURCE
from marko.services.market_collection import (
    PROM_ADAPTER_VERSION,
    _calculate_and_persist,
    _persist_payload_observations,
    _owned_seller_external_ids,
)
from marko.services.pricing_runs import (
    CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
    FULL_CATALOG_SCOPE,
    TrustedRunStart,
    create_pricing_run,
    preview_pricing_run,
)


pytestmark = pytest.mark.postgres
BACKEND_ROOT = Path(__file__).resolve().parents[1]
_ACTIVE_KEY = "cost-frozen-v1"


def _postgres_enabled() -> bool:
    return os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") == "1"


def _require_disposable_database() -> None:
    database_name = make_url(os.environ.get("DATABASE_URL", "")).database or ""
    if "p15017" not in database_name.casefold():
        pytest.fail(
            "Refusing frozen-input test: DATABASE_URL must name a disposable "
            "database containing 'p15017'"
        )


def _keys_json() -> str:
    key = base64.urlsafe_b64encode(bytes([7]) * 32).decode().rstrip("=")
    return json.dumps({_ACTIVE_KEY: key})


def _environment(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "e2e")
    monkeypatch.setenv("E2E_AUTH_BYPASS", "true")
    monkeypatch.setenv("E2E_AUTH_TOKEN", "p15017-frozen-inputs-token-000000000001")
    monkeypatch.setenv(
        "PRICING_BRAND_TIERS_PATH",
        str(BACKEND_ROOT / "src/marko/e2e/fixtures/brands.yaml"),
    )
    # Себестоимость расшифровывается только в этом режиме; иначе загрузчик
    # обязан отказать, и тест ничего бы не проверял.
    monkeypatch.setenv("COST_PRIVACY_MODE", "SERVER_SIDE_ENCRYPTED")
    monkeypatch.setenv("COST_ENCRYPTION_ACTIVE_KEY_ID", _ACTIVE_KEY)
    monkeypatch.setenv("COST_ENCRYPTION_KEYS_JSON", _keys_json())
    get_settings.cache_clear()


def _cost_record(
    *,
    record_id: UUID,
    workspace_id: UUID,
    catalog_item_id: UUID,
    amount: Decimal,
    reason: str,
) -> CatalogItemCostRecord:
    encrypted = encrypt_cost(
        amount,
        workspace_id=workspace_id,
        catalog_item_id=catalog_item_id,
        record_id=record_id,
        keyring=parse_cost_keyring(
            active_key_id=_ACTIVE_KEY, keys_json=_keys_json()
        ),
    )
    return CatalogItemCostRecord(
        id=record_id,
        workspace_id=workspace_id,
        catalog_item_id=catalog_item_id,
        user_id=None,
        action="SET",
        ciphertext=encrypted.ciphertext,
        nonce=encrypted.nonce,
        key_id=encrypted.key_id,
        algorithm=encrypted.algorithm,
        format_version=encrypted.format_version,
        reason=reason,
    )


async def _seed(*, workspace_id: UUID, batch_id: UUID, item_id: UUID) -> None:
    async with async_session_factory() as session:
        session.add(
            Workspace(
                id=workspace_id,
                name="P15017 frozen inputs",
                slug=f"p15017-frozen-{workspace_id.hex}",
            )
        )
        await session.flush()
        session.add(
            CatalogImportBatch(
                id=batch_id,
                workspace_id=workspace_id,
                filename="frozen-inputs.xlsx",
                content_sha256="e" * 64,
                content_size=1,
                status="completed",
                column_mapping={"Код_товару": "oe"},
                total_rows=1,
                imported_rows=1,
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
                sku="SKU-FROZEN-COST",
                oe_raw="1K0 615 999",
                oe_norm="1K0615999",
                name="Позиция с себестоимостью",
                category="brakes",
                brand="KEMP",
                identity_status="OE_CONFIRMED",
                identity_reason="EXPLICIT_OE_TEST_FIXTURE",
                product_url=None,
                current_price=Decimal("800"),
                currency="UAH",
                is_available=True,
                raw_row={},
            )
        )
        await session.commit()


async def _cleanup(workspace_id: UUID) -> None:
    """Разобрать одноразовые данные.

    Уборка обязана снимать защиты явно: членство прогона теперь неудаляемо
    триггером, а ``catalog_items`` держится внешним ключом RESTRICT — то есть
    ровно то, что доказывает тест, мешает его же уборке. Порядок обратный
    порядку создания.
    """

    guarded = (
        "pricing_recommendations",
        "offer_processing_outcomes",
        "market_observations",
        "raw_market_captures",
        "pricing_run_items",
        "catalog_item_cost_records",
    )
    async with async_session_factory() as session:
        for table in guarded:
            await session.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER ALL"))
        run_ids = select(PricingRun.id).where(PricingRun.workspace_id == workspace_id)
        await session.execute(
            delete(PricingRecommendation).where(
                PricingRecommendation.pricing_run_id.in_(run_ids)
            )
        )
        run_item_ids = select(PricingRunItem.id).where(
            PricingRunItem.pricing_run_id.in_(run_ids)
        )
        # Наблюдения и захваты append-only: на одноразовой базе триггеры сняты
        # выше только на время уборки.
        await session.execute(
            text(
                "DELETE FROM offer_processing_outcomes WHERE pricing_run_item_id IN "
                "(SELECT item.id FROM pricing_run_items AS item JOIN pricing_runs AS "
                "run ON run.id=item.pricing_run_id WHERE run.workspace_id=:ws)"
            ),
            {"ws": workspace_id},
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
            delete(PricingRunItem).where(PricingRunItem.pricing_run_id.in_(run_ids))
        )
        await session.execute(
            delete(CatalogItemCostRecord).where(
                CatalogItemCostRecord.workspace_id == workspace_id
            )
        )
        for table in reversed(guarded):
            await session.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER ALL"))
        await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
        await session.commit()


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_calculation_uses_the_frozen_cost_record_not_the_latest_live_one(
    monkeypatch,
) -> None:
    """Себестоимость берётся та, что действовала на старте прогона.

    Прежнее доказательство мутацию по себестоимости не убивало: в наборе не
    было ни одной записи себестоимости, поэтому подмена загрузчика на «взять
    последнюю живую» ничего не меняла. Здесь запись есть, а после старта её
    снимают: живое чтение вернёт «себестоимость не задана», замороженное —
    настоящую запись.
    """

    _require_disposable_database()
    _environment(monkeypatch)
    workspace_id = uuid4()
    batch_id = uuid4()
    item_id = uuid4()
    frozen_cost_id = uuid4()
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())

    try:
        await _seed(workspace_id=workspace_id, batch_id=batch_id, item_id=item_id)

        # Себестоимость, действующая на момент старта.
        async with async_session_factory() as session:
            session.add(
                _cost_record(
                    record_id=frozen_cost_id,
                    workspace_id=workspace_id,
                    catalog_item_id=item_id,
                    amount=Decimal("100.00"),
                    reason="Себестоимость на момент старта прогона",
                )
            )
            await session.commit()

        async with async_session_factory() as session:
            preview = await preview_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                scope_mode=FULL_CATALOG_SCOPE,
                catalog_item_ids=[],
                policy_config=None,
            )
            run = await create_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                celery_app=fake_celery,
                source_mode="e2e_fixture_replay",
                scope_mode=FULL_CATALOG_SCOPE,
                # Полоса подстановки фикстур требует доверенного контракта:
                # обычный старт оператора по ней проехать не может, и это
                # проверяется отдельно набором контракта старта.
                start=TrustedRunStart(
                    confirmation_source=CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
                    reason="frozen-input integration proof",
                    idempotency_key=f"frozen-cost-{batch_id.hex}",
                    expected_scope_hash=preview.scope_hash,
                    expected_catalog_snapshot_hash=preview.catalog_snapshot_hash,
                    full_catalog_confirmed=True,
                ),
            )
            await session.commit()
            run_id = run.id

        async with async_session_factory() as session:
            run_item = await session.scalar(
                select(PricingRunItem).where(PricingRunItem.pricing_run_id == run_id)
            )
            assert run_item is not None
            run_item_id = run_item.id
            assert run_item.cost_record_id == frozen_cost_id, (
                "старт обязан заморозить действующую запись себестоимости"
            )

        # Себестоимость снимают уже после старта: живое чтение вернёт None.
        async with async_session_factory() as session:
            session.add(
                CatalogItemCostRecord(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    catalog_item_id=item_id,
                    user_id=None,
                    action="CLEAR",
                    reason="Себестоимость снята уже во время расчёта",
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
        assert recommendation.context_snapshot["cost_configured"] is True, (
            "расчёт прочитал текущую себестоимость (снятую после старта) "
            "вместо замороженной на старте"
        )
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id)


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_run_membership_survives_delete_growth_and_catalog_removal(
    monkeypatch,
) -> None:
    """Состав прогона — улика, а не рабочая таблица.

    Миграция 0032 закрывала только UPDATE. Членство можно было удалить, дописать
    после заморозки, а удаление позиции каталога уносило его каскадом: расчёт
    оставался, а доказательство того, что именно считали, исчезало.
    """

    _require_disposable_database()
    _environment(monkeypatch)
    workspace_id = uuid4()
    batch_id = uuid4()
    item_id = uuid4()
    fake_celery = Mock()
    fake_celery.send_task = Mock(return_value=Mock())

    try:
        await _seed(workspace_id=workspace_id, batch_id=batch_id, item_id=item_id)

        # Законное создание до заморозки обязано пройти.
        async with async_session_factory() as session:
            preview = await preview_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                scope_mode=FULL_CATALOG_SCOPE,
                catalog_item_ids=[],
                policy_config=None,
            )
            run = await create_pricing_run(
                session,
                workspace_id=workspace_id,
                import_batch_id=batch_id,
                celery_app=fake_celery,
                source_mode="e2e_fixture_replay",
                scope_mode=FULL_CATALOG_SCOPE,
                # Полоса подстановки фикстур требует доверенного контракта:
                # обычный старт оператора по ней проехать не может, и это
                # проверяется отдельно набором контракта старта.
                start=TrustedRunStart(
                    confirmation_source=CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
                    reason="frozen-input integration proof",
                    idempotency_key=f"membership-{batch_id.hex}",
                    expected_scope_hash=preview.scope_hash,
                    expected_catalog_snapshot_hash=preview.catalog_snapshot_hash,
                    full_catalog_confirmed=True,
                ),
            )
            await session.commit()
            run_id = run.id

        async with async_session_factory() as session:
            run_item = await session.scalar(
                select(PricingRunItem).where(PricingRunItem.pricing_run_id == run_id)
            )
            assert run_item is not None, "законное создание состава обязано проходить"
            run_item_id = run_item.id

        # 1. Удаление членства запрещено.
        with pytest.raises(DBAPIError, match="immutable evidence"):
            async with async_session_factory() as session:
                await session.execute(
                    delete(PricingRunItem).where(PricingRunItem.id == run_item_id)
                )
                await session.commit()

        # 2. Дозапись после заморозки запрещена: область заморожена на N позициях.
        async with async_session_factory() as session:
            extra_item_id = uuid4()
            session.add(
                CatalogItem(
                    id=extra_item_id,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    source_row=3,
                    sku="SKU-SNUCK-IN",
                    oe_raw="9Z9 999 999",
                    oe_norm="9Z9999999",
                    name="Позиция, добавленная после заморозки",
                    category="brakes",
                    brand="KEMP",
                    product_url=None,
                    current_price=Decimal("500"),
                    currency="UAH",
                    is_available=True,
                    raw_row={},
                )
            )
            await session.commit()

        with pytest.raises(DBAPIError, match="scope is frozen"):
            async with async_session_factory() as session:
                session.add(
                    PricingRunItem(
                        id=uuid4(),
                        pricing_run_id=run_id,
                        catalog_item_id=extra_item_id,
                        status="queued",
                        idempotency_key=f"snuck-in:{uuid4()}",
                    )
                )
                await session.commit()

        # 3. Удаление позиции каталога не уносит улику каскадом.
        with pytest.raises(DBAPIError):
            async with async_session_factory() as session:
                await session.execute(
                    delete(CatalogItem).where(CatalogItem.id == item_id)
                )
                await session.commit()

        async with async_session_factory() as session:
            survivors = list(
                (
                    await session.scalars(
                        select(PricingRunItem).where(
                            PricingRunItem.pricing_run_id == run_id
                        )
                    )
                ).all()
            )
        assert len(survivors) == 1, "состав прогона обязан пережить все три попытки"
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id)


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_owned_storefronts_are_excluded_before_the_seller_cap(
    monkeypatch,
) -> None:
    """Свои витрины не должны занимать места конкурентов в квоте.

    Прежнее доказательство было на подделках: соответствие SQL проверялось по
    форме запроса, а не на настоящих записях витрин. KEMP держит на prom.ua
    четыре витрины с одинаковыми карточками, и замер 2026-07-31 показал, что 48
    из 65 совпадений по названию были нашими собственными магазинами — каждый
    съедал слот ``max_sellers`` до того, как ценовые ворота их вообще видели.

    Здесь витрины зарегистрированы по-настоящему, и проверяется, что их
    идентификаторы доезжают до заявки на сбор — то есть до применения квоты.
    """

    _require_disposable_database()
    _environment(monkeypatch)
    workspace_id = uuid4()
    batch_id = uuid4()
    item_id = uuid4()
    # Четыре витрины KEMP на prom.ua — форма настоящая, но идентификаторы
    # уникальны на прогон: ``uq_store_marketplace_external`` глобален, и
    # литеральные номера сталкивались бы между прогонами.
    # Только цифры: идентификатор продавца у площадки числовой.
    prefix = str(workspace_id.int)[:6]
    owned_external_ids = {f"{prefix}{suffix}" for suffix in ("47093", "12822", "25174", "15921")}

    try:
        await _seed(workspace_id=workspace_id, batch_id=batch_id, item_id=item_id)

        async with async_session_factory() as session:
            for index, external_id in enumerate(sorted(owned_external_ids)):
                store_id = uuid4()
                session.add(
                    MarketplaceStore(
                        id=store_id,
                        marketplace="prom",
                        external_id=external_id,
                        name=f"KEMP витрина {index}",
                        canonical_url=f"https://prom.ua/c{external_id}",
                    )
                )
                await session.flush()
                session.add(
                    WorkspaceStore(
                        id=uuid4(),
                        workspace_id=workspace_id,
                        store_id=store_id,
                        kind=StoreKind.owned,
                    )
                )
            # Чужая витрина: она обязана остаться в рынке.
            competitor_store_id = uuid4()
            session.add(
                MarketplaceStore(
                    id=competitor_store_id,
                    marketplace="prom",
                    external_id=f"{prefix}99999",
                    name="Конкурент",
                    canonical_url="https://prom.ua/c9999999",
                )
            )
            await session.flush()
            session.add(
                WorkspaceStore(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    store_id=competitor_store_id,
                    kind=StoreKind.competitor,
                )
            )
            await session.commit()

        async with async_session_factory() as session:
            resolved = await _owned_seller_external_ids(session, workspace_id)

        assert resolved == owned_external_ids, (
            "заявка на сбор обязана нести идентификаторы всех своих витрин"
        )
        assert f"{prefix}99999" not in resolved, "конкурента исключать нельзя"

        # Витрина без внешнего идентификатора не должна превращаться в "None":
        # непустой набор исключений у воркспейса, который ничего не владеет,
        # вычистил бы рынок целиком.
        async with async_session_factory() as session:
            empty_workspace = uuid4()
            found = await _owned_seller_external_ids(session, empty_workspace)
        assert found == set(), "у чужого воркспейса своих витрин нет"

        # Идентификаторы, разрешённые из настоящих записей, проводятся через
        # настоящий матчер: три свои витрины дешевле любого конкурента, квота —
        # два продавца. Если исключение применяется после квоты, оба слота
        # достанутся нам самим, и рынка не останется.
        owned = sorted(owned_external_ids)
        candidates = [
            product(
                id=100 + index,
                name="Радиатор VW Touareg 2.5 TDI 710*549",
                price=price,
                urlText="radiator",
                company={"id": int(seller), "name": f"Магазин {seller}"},
            )
            for index, (price, seller) in enumerate(
                [
                    ("1000", owned[0]),
                    ("1010", owned[1]),
                    ("1020", owned[2]),
                    ("3000", "900001"),
                    ("3100", "900002"),
                    ("3200", "900003"),
                ]
            )
        ]
        seed = SeedInfo(
            product=product(
                id=1,
                name="Радиатор VW Touareg 2.5 TDI 710*549",
                price="5163",
                company={"id": int(owned[3]), "name": "KEMP"},
            ),
            seller_count=2,
            min_price=None,
            max_price=None,
        )
        comparison = build_comparison(
            seed,
            candidates,
            ComparisonParams(
                query="radiator",
                threshold=0.3,
                max_sellers=2,
                excluded_seller_ids=frozenset(resolved),
            ),
        )
        sellers = {str(offer.product.seller_id) for offer in comparison.offers}
        assert sellers.isdisjoint(owned_external_ids), (
            "свои витрины заняли слоты конкурентов: исключение применено "
            "после квоты, а не до неё"
        )
        assert len(comparison.offers) == 2, "квота обязана достаться конкурентам"
    finally:
        get_settings.cache_clear()
        async with async_session_factory() as session:
            store_ids = select(WorkspaceStore.store_id).where(
                WorkspaceStore.workspace_id == workspace_id
            )
            await session.execute(
                delete(MarketplaceStore).where(MarketplaceStore.id.in_(store_ids))
            )
            await session.execute(
                delete(WorkspaceStore).where(
                    WorkspaceStore.workspace_id == workspace_id
                )
            )
            await session.commit()
        await _cleanup(workspace_id)


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_persisted_source_assertion_cannot_exist_without_provenance() -> None:
    """Заявление источника нельзя сохранить в отрыве от его происхождения.

    Признак расширения раньше жил только в ``comparison_evidence``, а кодек
    повторного обогащения выбрасывает незнакомые ключи. Колонки первого класса
    (миграция 0034) хранят заявление вместе с захватом, на который оно
    опирается, и база не даёт записать одно без другого.
    """

    _require_disposable_database()

    async with async_session_factory() as session:
        # Миграция 0040 добавила ограничение родословной: способ извлечения без
        # источника/метода/запроса теперь тоже отвергается. Обе проверки —
        # правильный отказ, поэтому принимается любая из них.
        with pytest.raises(DBAPIError, match="source_assertion_(provenance|lineage)"):
            await session.execute(
                text(
                    "INSERT INTO market_observations "
                    "(id, pricing_run_item_id, catalog_item_id, raw_capture_id, "
                    " source, source_listing_id, seller_id, seller_name, url, "
                    " title, search_oe_norm, price, currency, match_confidence, "
                    " parser_version, observed_at, "
                    " source_assertion_retrieval_kind) "
                    "VALUES (gen_random_uuid(), gen_random_uuid(), "
                    " gen_random_uuid(), gen_random_uuid(), 'prom_public', 'l', "
                    " 's', 'n', 'u', 't', '1K0615301', 1, 'UAH', 1, 'v', now(), "
                    " 'prom_oe_page')"
                )
            )
        await session.rollback()

    async with async_session_factory() as session:
        with pytest.raises(DBAPIError, match="source_assertion_confidence"):
            await session.execute(
                text(
                    "INSERT INTO market_observations "
                    "(id, pricing_run_item_id, catalog_item_id, raw_capture_id, "
                    " source, source_listing_id, seller_id, seller_name, url, "
                    " title, search_oe_norm, price, currency, match_confidence, "
                    " parser_version, observed_at, "
                    " source_assertion_capture_sha256, source_assertion_confidence) "
                    "VALUES (gen_random_uuid(), gen_random_uuid(), "
                    " gen_random_uuid(), gen_random_uuid(), 'prom_public', 'l', "
                    " 's', 'n', 'u', 't', '1K0615301', 1, 'UAH', 1, 'v', now(), "
                    f" '{'a' * 64}', 9.0)"
                )
            )
        await session.rollback()


def _oe_page_records(*, oe: str, title: str, identity_source: str | None, seller: int):
    """Записи офферов ровно в том виде, в каком их отдаёт замороженная граница."""

    seed = SeedInfo(
        product=product(
            id=1,
            name="Радиатор VW Touareg",
            price="5163",
            company={"id": 111111, "name": "KEMP"},
        ),
        seller_count=2,
        min_price=None,
        max_price=None,
    )
    comparison = build_comparison(
        seed,
        [
            product(
                id=200,
                name=title,
                price="1100",
                urlText="radiator",
                company={"id": seller, "name": f"Магазин {seller}"},
            )
        ],
        ComparisonParams(
            query=oe,
            threshold=0.3,
            max_sellers=10,
            identity_source=identity_source,
        ),
    )
    scrape_input = ScrapeInput.build(
        "https://prom.ua/ua/p1153738393-radiator.html", oe
    )
    output = ScrapeOutput.from_comparison(scrape_input, comparison)
    return output.payload["output"]["records"]


async def _persist_through_pipeline(
    *, workspace_id: UUID, batch_id: UUID, item_id: UUID, records, oe: str
):
    """Прогнать записи через настоящий конвейер персистентности."""

    run_id, run_item_id, capture_id = uuid4(), uuid4(), uuid4()
    raw_evidence = [{"raw_content_sha256": "b" * 64, "url": "https://prom.ua/oe"}]
    async with async_session_factory() as session:
        # Свой батч на каждый прогон: ``uq_pricing_run_active_import_batch``
        # разрешает один активный прогон на батч, и это правильно.
        run_batch_id = uuid4()
        session.add(
            CatalogImportBatch(
                id=run_batch_id,
                workspace_id=workspace_id,
                filename=f"pipeline-{run_batch_id.hex}.xlsx",
                content_sha256=f"{run_batch_id.int % (16**64):064x}",
                content_size=1,
                status="completed",
                column_mapping={"sku": "SKU"},
                total_rows=1,
                imported_rows=1,
                rejected_rows=0,
                error_log=[],
            )
        )
        await session.flush()
        session.add(
            PricingRun(
                id=run_id,
                workspace_id=workspace_id,
                import_batch_id=run_batch_id,
                status="collecting",
                policy_version="integration-v1",
                policy_config={},
                parser_version=PROM_ADAPTER_VERSION,
                total_items=1,
            )
        )
        await session.flush()
        session.add(
            PricingRunItem(
                id=run_item_id,
                pricing_run_id=run_id,
                catalog_item_id=item_id,
                status="collecting",
                idempotency_key=f"pipeline:{run_item_id}",
            )
        )
        await session.flush()
        capture = RawMarketCapture(
            id=capture_id,
            pricing_run_item_id=run_item_id,
            source="prom_public",
            # Полноценная неизменяемая родословная: без неё
            # ``_candidate_raw_manifest`` отдаёт пустой хеш, и заявление
            # источника корректно отвергается — проверено отдельно.
            payload={
                "records": records,
                "raw_evidence": raw_evidence,
                "raw_manifest_sha256": canonical_sha256(raw_evidence),
            },
            content_sha256=f"{9:064x}",
            parser_version=PROM_ADAPTER_VERSION,
        )
        session.add(capture)
        await session.flush()
        run = await session.get(PricingRun, run_id)
        run_item = await session.get(PricingRunItem, run_item_id)
        catalog_item = await session.get(CatalogItem, item_id)
        await _persist_payload_observations(
            session,
            run=run,
            run_item=run_item,
            catalog_item=catalog_item,
            capture=capture,
            offers=list(records),
            owned_sellers=set(),
            brand_tiers={},
            brand_confidence={},
            observed_at=datetime.now(UTC),
            source_type="prom_public",
            acquisition_query=oe,
        )
        await session.commit()
    async with async_session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(MarketObservation).where(
                        MarketObservation.pricing_run_item_id == run_item_id
                    )
                )
            ).all()
        )


@pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)
@pytest.mark.asyncio
async def test_an_oe_page_offer_reaches_verified_identity_through_the_real_pipeline(
    monkeypatch,
) -> None:
    """Сквозная проверка: страница кода детали доводит предложение до цены.

    Модульные тесты доказывали логику заявления, ограничения базы — его
    хранение. Здесь предложение проходит настоящий конвейер персистентности:
    в заголовке номера нет, и без заявления источника оно осталось бы UNKNOWN.
    """

    _require_disposable_database()
    _environment(monkeypatch)
    workspace_id, batch_id, item_id = uuid4(), uuid4(), uuid4()
    oe = "1K0615999"

    try:
        await _seed(workspace_id=workspace_id, batch_id=batch_id, item_id=item_id)

        # 1. Положительный случай: рынок площадки, номер в карточке не повторён.
        observations = await _persist_through_pipeline(
            workspace_id=workspace_id,
            batch_id=batch_id,
            item_id=item_id,
            records=_oe_page_records(
                oe=oe,
                title="Радиатор VW Touareg 2.5 TDI",
                identity_source=MOTORS_IDENTITY_SOURCE,
                seller=700001,
            ),
            oe=oe,
        )
        assert observations, "конвейер обязан сохранить предложение"
        asserted = observations[0]
        assert asserted.oe_verification_status == "VERIFIED_EXACT", (
            "рынок, собранный площадкой под наш код, обязан подтверждать "
            f"идентичность; получено {asserted.oe_verification_status}"
        )
        assert asserted.verified_matched_oe_norm == oe
        assert asserted.source_assertion_retrieval_kind == RETRIEVAL_KIND_PROM_OE_PAGE
        assert asserted.source_assertion_capture_sha256
        assert asserted.source_assertion_confidence is not None

        # 2. Состязательный: обычный текстовый поиск не утверждает ничего.
        searched = await _persist_through_pipeline(
            workspace_id=workspace_id,
            batch_id=batch_id,
            item_id=item_id,
            records=_oe_page_records(
                oe=oe,
                title="Радиатор VW Touareg 2.5 TDI",
                identity_source=None,
                seller=700002,
            ),
            oe=oe,
        )
        assert searched
        assert searched[0].oe_verification_status != "VERIFIED_EXACT", (
            "выдача текстового поиска не является утверждением об идентичности"
        )
        assert searched[0].source_assertion_confidence is None

        # 3. Противоречие сильнее заявления: в карточке чужой номер.
        contradicted = await _persist_through_pipeline(
            workspace_id=workspace_id,
            batch_id=batch_id,
            item_id=item_id,
            records=_oe_page_records(
                oe=oe,
                title="Радиатор OE 9Z9999999 для другой машины",
                identity_source=MOTORS_IDENTITY_SOURCE,
                seller=700003,
            ),
            oe=oe,
        )
        assert contradicted
        # 4. Обычный поиск не хранит заявление вовсе: все четыре поля пусты.
        generic = searched[0]
        assert generic.source_assertion_retrieval_kind is None, (
            "выдача поиска сохранена как утверждение площадки, которого не было"
        )
        assert generic.source_assertion_capture_sha256 is None
        assert generic.source_assertion_confidence is None
        assert generic.via_oe_number is None

        # 5. Авторитетный случай хранит заявление целиком.
        assert asserted.source_assertion_retrieval_kind == RETRIEVAL_KIND_PROM_OE_PAGE
        assert asserted.source_assertion_capture_sha256

        assert contradicted[0].oe_verification_status != "VERIFIED_EXACT", (
            "чужой номер в карточке — факт о товаре, он сильнее группировки"
        )
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id)
