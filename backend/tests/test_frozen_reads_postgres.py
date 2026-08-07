"""F4/F6 на настоящей PostgreSQL: замороженные чтения и родословная приобретения.

Модульные наборы доказывают логику; здесь она проезжает через настоящую базу и
настоящие строки членства. Проверяется ровно то, что воспроизвёл независимый
валидатор:

* самоподписанный снимок, привязанный не к своей строке членства, не исполняется;
* повторное обогащение читает ЗАМОРОЖЕННУЮ позицию — правка каталога после
  старта не переписывает уже подтверждённую идентичность;
* повтор рекомендации подбирает коэффициенты по замороженной позиции;
* приобретение, противоречащее самому себе, не доезжает до ``VERIFIED_EXACT``.

Требуется одноразовая база, имя которой содержит ``p15017``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import os
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url

from factories import product
from marko.core.config import get_settings
from marko.infrastructure.db.models import (
    CatalogImportBatch,
    CatalogItem,
    MarketObservation,
    PricingRecommendation,
    PricingRun,
    PricingRunItem,
    RawMarketCapture,
    ScrapeTarget,
    Workspace,
)
from marko.infrastructure.db.session import async_session_factory
from marko.parsers.prom.gateway import MOTORS_IDENTITY_SOURCE
from marko.services import recommendation_replay
from marko.services.decision_fingerprint import canonical_sha256
from marko.services.market_collection import (
    FrozenBindingError,
    _calculate_and_persist,
    _persist_payload_observations,
    resolve_bound_execution_item,
)
from marko.services.matching import ComparisonParams, build_comparison
from marko.services.oe_reenrichment import re_enrich_retained_observations_in_session
from marko.services.offer_identity import OE_EXTRACTOR_VERSION
from marko.services.offer_processing import (
    ACQUISITION_METHOD_TEXT_SEARCH,
    ACQUISITION_SOURCE_SEARCH,
)
from marko.services.parser_models import SeedInfo
from marko.services.pricing_runs import (
    CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
    FULL_CATALOG_SCOPE,
    PROM_ADAPTER_VERSION,
    TrustedRunStart,
    create_pricing_run,
    preview_pricing_run,
    start_snapshot_fingerprint,
)
from marko.services.recommendation_replay import replay_recommendation
from marko.services.scraper_contract import (
    RETRIEVAL_KIND_PROM_OE_PAGE,
    ScrapeInput,
    ScrapeOutput,
)


pytestmark = pytest.mark.postgres
BACKEND_ROOT = Path(__file__).resolve().parents[1]

FROZEN_OE = "1K0615777"
FROZEN_CATEGORY = "brakes"
LIVE_DRIFT_OE = "9Z9999999"
LIVE_DRIFT_CATEGORY = "LIVE-DRIFT"
SEED_URL = "https://prom.ua/ua/p1153738393-radiator-folksvagen-tuareg.html"


def _postgres_enabled() -> bool:
    return os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") == "1"


def _require_disposable_database() -> None:
    database_name = make_url(os.environ.get("DATABASE_URL", "")).database or ""
    if "p15017" not in database_name.casefold():
        pytest.fail(
            "Refusing frozen-read test: DATABASE_URL must name a disposable "
            "database containing 'p15017'"
        )


requires_postgres = pytest.mark.skipif(
    not _postgres_enabled(),
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)


def _environment(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "e2e")
    monkeypatch.setenv("E2E_AUTH_BYPASS", "true")
    monkeypatch.setenv("E2E_AUTH_TOKEN", "p15017-frozen-reads-token-0000000000001")
    monkeypatch.setenv(
        "PRICING_BRAND_TIERS_PATH",
        str(BACKEND_ROOT / "src/marko/e2e/fixtures/brands.yaml"),
    )
    get_settings.cache_clear()


async def _seed(*, workspace_id: UUID, batch_id: UUID, item_ids: tuple[UUID, ...]):
    async with async_session_factory() as session:
        session.add(
            Workspace(
                id=workspace_id,
                name="P15017 frozen reads",
                slug=f"p15017-reads-{workspace_id.hex}",
            )
        )
        await session.flush()
        session.add(
            CatalogImportBatch(
                id=batch_id,
                workspace_id=workspace_id,
                filename=f"frozen-reads-{batch_id.hex}.xlsx",
                content_sha256=f"{batch_id.int % (16**64):064x}",
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
        for index, item_id in enumerate(item_ids):
            session.add(
                CatalogItem(
                    id=item_id,
                    workspace_id=workspace_id,
                    import_batch_id=batch_id,
                    source_row=2 + index,
                    sku=f"SKU-READS-{index}",
                    oe_raw=FROZEN_OE if index == 0 else f"{FROZEN_OE}{index}",
                    oe_norm=FROZEN_OE if index == 0 else f"{FROZEN_OE}{index}",
                    name=f"Позиция {index}",
                    category=FROZEN_CATEGORY,
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


async def _start_run(*, workspace_id: UUID, batch_id: UUID) -> UUID:
    celery = Mock()
    celery.send_task = Mock(return_value=Mock())
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
            celery_app=celery,
            source_mode="e2e_fixture_replay",
            scope_mode=FULL_CATALOG_SCOPE,
            start=TrustedRunStart(
                confirmation_source=CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
                reason="frozen-read integration proof",
                idempotency_key=f"frozen-reads-{batch_id.hex}",
                expected_scope_hash=preview.scope_hash,
                expected_catalog_snapshot_hash=preview.catalog_snapshot_hash,
                full_catalog_confirmed=True,
            ),
        )
        await session.commit()
        return run.id


async def _cleanup(workspace_id: UUID) -> None:
    guarded = (
        "pricing_recommendations",
        "offer_processing_outcomes",
        "market_observations",
        "raw_market_captures",
        "pricing_run_items",
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
        for table in reversed(guarded):
            await session.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER ALL"))
        await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
        await session.commit()


def _acquisition_payload(
    *,
    query: str = FROZEN_OE,
    identity_source: str | None = MOTORS_IDENTITY_SOURCE,
) -> dict:
    comparison = build_comparison(
        SeedInfo(
            product=product(
                id=1,
                name="Диск тормозной VW",
                price="5163",
                company={"id": 111, "name": "KEMP"},
            ),
            seller_count=2,
            min_price=None,
            max_price=None,
        ),
        [
            product(
                id=4242,
                name="Диск тормозной передний",
                price="640",
                urlText="disk",
                company={"id": 770001, "name": "Магазин 1"},
            )
        ],
        ComparisonParams(
            query=query,
            threshold=0.3,
            max_sellers=10,
            identity_source=identity_source,
        ),
    )
    return ScrapeOutput.from_comparison(
        ScrapeInput.build(SEED_URL, query), comparison
    ).payload


async def _collect_one_item(run_id: UUID, payload: dict) -> tuple[UUID, UUID]:
    """Довести первую позицию прогона до сохранённого наблюдения."""

    raw_evidence = [
        {"logical_request_id": str(uuid4()), "raw_content_sha256": "c" * 64}
    ]
    async with async_session_factory() as session:
        run = await session.get(PricingRun, run_id)
        run_item = await session.scalar(
            select(PricingRunItem)
            .where(PricingRunItem.pricing_run_id == run_id)
            .order_by(PricingRunItem.membership_position)
        )
        assert run is not None and run_item is not None
        target = await session.get(ScrapeTarget, run_item.scrape_target_id)
        assert target is not None
        target.payload = payload
        capture = RawMarketCapture(
            pricing_run_item_id=run_item.id,
            scrape_target_id=target.id,
            source="prom_public",
            capture_kind="parser_output_ref",
            payload={
                "raw_evidence": raw_evidence,
                "raw_manifest_sha256": canonical_sha256(raw_evidence),
            },
            content_sha256=f"{run_item.id.int % (16**64):064x}",
            parser_version=PROM_ADAPTER_VERSION,
        )
        session.add(capture)
        await session.flush()
        output = ScrapeOutput.from_payload(payload)
        frozen_item = resolve_bound_execution_item(run, run_item)
        await _persist_payload_observations(
            session,
            run=run,
            run_item=run_item,
            catalog_item=frozen_item,
            capture=capture,
            offers=list(output.candidate_records),
            owned_sellers=set(),
            brand_tiers={},
            brand_confidence={},
            observed_at=datetime.now(UTC),
            source_type="prom_public",
            prepared_url=output.prepared_url,
            acquisition_input_hash=output.input_hash,
            acquisition_query=output.acquisition_query,
        )
        await session.commit()
        return run_item.id, capture.id


async def _move_the_live_catalog_row(item_id: UUID) -> None:
    """Правка каталога уже ПОСЛЕ старта прогона."""

    async with async_session_factory() as session:
        item = await session.get(CatalogItem, item_id)
        assert item is not None
        item.oe_norm = LIVE_DRIFT_OE
        item.oe_raw = LIVE_DRIFT_OE
        item.category = LIVE_DRIFT_CATEGORY
        item.name = "LIVE-DRIFT"
        item.current_price = Decimal("4242")
        item.currency = "USD"
        await session.commit()


# ------------------------------------------------------------------ F4


@requires_postgres
@pytest.mark.asyncio
async def test_a_snapshot_hashed_over_another_membership_row_cannot_execute(
    monkeypatch,
) -> None:
    """Честный отпечаток поверх ЧУЖОГО снимка обязан быть отказом.

    ``verified_start_snapshot`` пересчитывает SHA-256 и на этом останавливается.
    Снимок позиции B, положенный в строку позиции A и корректно пере-хешированный,
    проходил эту проверку целиком: прогон считал не тот товар.
    """

    _require_disposable_database()
    _environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(), uuid4())
    try:
        await _seed(workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids)
        run_id = await _start_run(workspace_id=workspace_id, batch_id=batch_id)

        async with async_session_factory() as session:
            run = await session.get(PricingRun, run_id)
            items = list(
                (
                    await session.scalars(
                        select(PricingRunItem)
                        .where(PricingRunItem.pricing_run_id == run_id)
                        .order_by(PricingRunItem.membership_position)
                    )
                ).all()
            )
            assert run is not None and len(items) == 2
            first, second = items
            live_first = await session.get(CatalogItem, first.catalog_item_id)
            session.expunge_all()

        # Подмена в памяти: база такой UPDATE и так отвергает, здесь проверяется
        # путь ЧТЕНИЯ, то есть то, что доверять снимку нельзя без его связей.
        first.start_snapshot = dict(second.start_snapshot)
        first.start_snapshot_hash = start_snapshot_fingerprint(first.start_snapshot)

        with pytest.raises(FrozenBindingError, match="START_SNAPSHOT_MISBOUND"):
            resolve_bound_execution_item(run, first, live_first)
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id)


@requires_postgres
@pytest.mark.asyncio
async def test_re_enrichment_reads_the_frozen_position_after_the_catalog_moves(
    monkeypatch,
) -> None:
    """Повторное обогащение и заявление источника переживают правку каталога.

    Два дефекта в одном месте: запрос читал живой ``CatalogItem`` (F4), а
    проверяющий вызывался без восстановленного заявления (F6). Каждый по
    отдельности превращал подтверждённую идентичность в ``UNKNOWN`` после
    любой правки каталога.
    """

    _require_disposable_database()
    _environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    try:
        await _seed(workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids)
        run_id = await _start_run(workspace_id=workspace_id, batch_id=batch_id)
        run_item_id, _ = await _collect_one_item(run_id, _acquisition_payload())

        async with async_session_factory() as session:
            observation = await session.scalar(
                select(MarketObservation).where(
                    MarketObservation.pricing_run_item_id == run_item_id
                )
            )
            assert observation is not None
            assert observation.oe_verification_status == "VERIFIED_EXACT", (
                "рынок, собранный площадкой под наш код, обязан подтверждать "
                f"идентичность; получено {observation.oe_verification_status}"
            )
            assert (
                observation.source_assertion_retrieval_kind
                == RETRIEVAL_KIND_PROM_OE_PAGE
            )
            observation_id = observation.id
            # Пометить строку как требующую повторного обогащения.
            await session.execute(
                text(
                    "SELECT set_config('marko.identity_reenrichment', "
                    "'legacy-test-v0', true)"
                )
            )
            observation.oe_extractor_version = "legacy-test-v0"
            observation.oe_reenriched_at = datetime.now(UTC)
            await session.commit()

        await _move_the_live_catalog_row(item_ids[0])

        async with async_session_factory() as session:
            report = await re_enrich_retained_observations_in_session(
                session, batch_size=100, dry_run=False
            )
        assert report.failure_counts == {}, report.failure_counts
        assert report.updated == 1

        async with async_session_factory() as session:
            re_enriched = await session.get(MarketObservation, observation_id)
        assert re_enriched is not None
        assert re_enriched.oe_extractor_version == OE_EXTRACTOR_VERSION
        assert re_enriched.oe_verification_status == "VERIFIED_EXACT", (
            "повторное обогащение уронило подтверждённую идентичность: либо "
            "оно прочитало живой каталог, либо выбросило заявление источника"
        )
        assert re_enriched.verified_matched_oe_norm == FROZEN_OE
        assert re_enriched.comparison_evidence["retrieval_kind"] == (
            RETRIEVAL_KIND_PROM_OE_PAGE
        )
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id)


@requires_postgres
@pytest.mark.asyncio
async def test_replay_looks_up_coefficients_by_the_frozen_position(
    monkeypatch,
) -> None:
    """Повтор обязан подбирать коэффициенты по замороженным OE и категории.

    Иначе «повтор» считает по другому товару и объявляет расхождение дефектом
    расчёта, хотя изменилась только живая строка каталога.
    """

    _require_disposable_database()
    _environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    lookups: list[dict[str, object]] = []
    try:
        await _seed(workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids)
        run_id = await _start_run(workspace_id=workspace_id, batch_id=batch_id)
        run_item_id, _ = await _collect_one_item(run_id, _acquisition_payload())

        await _calculate_and_persist(run_item_id)

        async with async_session_factory() as session:
            recommendation = await session.scalar(
                select(PricingRecommendation).where(
                    PricingRecommendation.pricing_run_item_id == run_item_id
                )
            )
            assert recommendation is not None, "расчёт обязан оставить рекомендацию"
            recommendation_id = recommendation.id

        await _move_the_live_catalog_row(item_ids[0])

        original = recommendation_replay.load_target_tier_coefficients

        async def _recording(session, **kwargs):
            lookups.append(dict(kwargs))
            return await original(session, **kwargs)

        monkeypatch.setattr(
            recommendation_replay, "load_target_tier_coefficients", _recording
        )

        async with async_session_factory() as session:
            await replay_recommendation(
                session,
                workspace_id=workspace_id,
                recommendation_id=recommendation_id,
            )

        assert lookups, "повтор обязан подбирать коэффициенты"
        assert lookups[0]["category"] == FROZEN_CATEGORY, (
            "повтор прочитал живую категорию каталога вместо замороженной"
        )
        assert lookups[0]["oe_norm"] == FROZEN_OE, (
            "повтор прочитал живой номер каталога вместо замороженного"
        )
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id)


# ------------------------------------------------------------------ F6


@requires_postgres
@pytest.mark.asyncio
async def test_an_inconsistent_acquisition_never_reaches_verified_exact(
    monkeypatch,
) -> None:
    """``prom_oe_page`` + ``source=SEARCH`` не даёт подтверждённой идентичности.

    Такая запись раньше сохранялась как ``VERIFIED_EXACT``, потому что
    запрошенный номер заявления восстанавливался из ``CatalogItem.oe_norm``.
    """

    _require_disposable_database()
    _environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    try:
        await _seed(workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids)
        run_id = await _start_run(workspace_id=workspace_id, batch_id=batch_id)

        payload = _acquisition_payload()
        block = payload["output"]["records"][0]["acquisition"]
        block["source"] = ACQUISITION_SOURCE_SEARCH
        block["method"] = ACQUISITION_METHOD_TEXT_SEARCH

        raw_evidence = [
            {"logical_request_id": str(uuid4()), "raw_content_sha256": "c" * 64}
        ]
        async with async_session_factory() as session:
            run = await session.get(PricingRun, run_id)
            run_item = await session.scalar(
                select(PricingRunItem).where(PricingRunItem.pricing_run_id == run_id)
            )
            assert run is not None and run_item is not None
            capture = RawMarketCapture(
                pricing_run_item_id=run_item.id,
                scrape_target_id=run_item.scrape_target_id,
                source="prom_public",
                capture_kind="parser_output_ref",
                payload={
                    "raw_evidence": raw_evidence,
                    "raw_manifest_sha256": canonical_sha256(raw_evidence),
                },
                content_sha256=f"{run_item.id.int % (16**64):064x}",
                parser_version=PROM_ADAPTER_VERSION,
            )
            session.add(capture)
            await session.flush()
            frozen_item = resolve_bound_execution_item(run, run_item)
            # Записи скармливаются персистентности напрямую: граница такую
            # комбинацию уже не пропускает, а второй рубеж обязан держаться сам.
            await _persist_payload_observations(
                session,
                run=run,
                run_item=run_item,
                catalog_item=frozen_item,
                capture=capture,
                offers=list(payload["output"]["records"]),
                owned_sellers=set(),
                brand_tiers={},
                brand_confidence={},
                observed_at=datetime.now(UTC),
                source_type="prom_public",
                prepared_url=SEED_URL,
                acquisition_input_hash=ScrapeInput.build(
                    SEED_URL, FROZEN_OE
                ).input_hash,
                acquisition_query=FROZEN_OE,
            )
            await session.commit()
            run_item_id = run_item.id

        async with async_session_factory() as session:
            observation = await session.scalar(
                select(MarketObservation).where(
                    MarketObservation.pricing_run_item_id == run_item_id
                )
            )
        assert observation is not None, "рынок обязан сохраниться"
        assert observation.oe_verification_status != "VERIFIED_EXACT"
        assert observation.source_assertion_retrieval_kind is None
        assert observation.source_assertion_capture_sha256 is None
        assert observation.source_assertion_confidence is None
        assert observation.via_oe_number is None
        assert observation.automatic_eligible is False
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id)


@requires_postgres
@pytest.mark.asyncio
async def test_a_generic_search_persists_every_assertion_field_null(
    monkeypatch,
) -> None:
    _require_disposable_database()
    _environment(monkeypatch)
    workspace_id, batch_id = uuid4(), uuid4()
    item_ids = (uuid4(),)
    try:
        await _seed(workspace_id=workspace_id, batch_id=batch_id, item_ids=item_ids)
        run_id = await _start_run(workspace_id=workspace_id, batch_id=batch_id)
        run_item_id, _ = await _collect_one_item(
            run_id, _acquisition_payload(identity_source=None)
        )

        async with async_session_factory() as session:
            observation = await session.scalar(
                select(MarketObservation).where(
                    MarketObservation.pricing_run_item_id == run_item_id
                )
            )
        assert observation is not None
        assert observation.source_assertion_retrieval_kind is None
        assert observation.source_assertion_capture_sha256 is None
        assert observation.source_assertion_confidence is None
        assert observation.via_oe_number is None
        assert observation.oe_verification_status != "VERIFIED_EXACT"
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id)
