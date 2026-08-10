"""Реальные доказательства двух отказов миграций.

Оба отказа были заявлены, но не проверены. Попытки засеять данные молча падали
на NOT NULL, таблица оставалась пустой, и «миграция дошла до head» читалось как
успех. Пустая выборка доказательством не является, поэтому здесь строится вся
цепочка родительских строк, наличие данных подтверждается счётчиком ДО
миграции, и только после этого проверяется отказ.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import uuid

import asyncpg
import pytest
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.postgres
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _enabled() -> bool:
    return os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") == "1"


def _dsn(database: str) -> str:
    url = make_url(os.environ["DATABASE_URL"])
    return (
        f"postgresql://{url.username}:{url.password}@{url.host}:{url.port}/{database}"
    )


def _async_url(database: str) -> str:
    url = make_url(os.environ["DATABASE_URL"])
    return (
        f"postgresql+asyncpg://{url.username}:{url.password}"
        f"@{url.host}:{url.port}/{database}"
    )


def _require_disposable() -> None:
    name = make_url(os.environ.get("DATABASE_URL", "")).database or ""
    if "p15017" not in name.casefold():
        pytest.fail("DATABASE_URL must name a disposable database containing 'p15017'")


def _alembic(database: str, *args: str):
    return subprocess.run(
        ["uv", "run", "alembic", "-c", "alembic.ini", *args],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": _async_url(database)},
    )


def _revision(database: str) -> str:
    return _alembic(database, "current").stdout.strip()


def _head_revision(database: str) -> str:
    """Head берётся из самой цепочки, а не из литерала.

    Литерал делает набор ложно-красным на каждой следующей миграции, и тогда
    его чинят правкой числа — то есть перестают читать. Здесь проверяется
    утверждение «чистый путь доходит до головы», а не «голова называется так».
    """

    for line in _alembic(database, "heads").stdout.splitlines():
        candidate = line.strip()
        if candidate and not candidate.startswith("INFO"):
            return candidate.split()[0]
    raise AssertionError("alembic heads printed no revision")


async def _admin(sql: str) -> None:
    connection = await asyncpg.connect(_dsn("postgres"))
    try:
        await connection.execute(sql)
    finally:
        await connection.close()


async def _fresh_database(name: str) -> str:
    await _admin(f'DROP DATABASE IF EXISTS "{name}"')
    await _admin(f'CREATE DATABASE "{name}" OWNER marko')
    return name


async def _seed_chain(connection) -> dict[str, uuid.UUID]:
    """Полная цепочка родительских строк. Ошибку SQL не глотаем."""

    ids = {
        key: uuid.uuid4()
        for key in ("ws", "batch", "item", "run", "run_item", "capture", "obs")
    }
    await connection.execute(
        "INSERT INTO workspaces (id, name, slug) VALUES ($1, $2, $3)",
        ids["ws"],
        "refusal",
        f"refusal-{ids['ws'].hex}",
    )
    await connection.execute(
        "INSERT INTO catalog_import_batches "
        "(id, workspace_id, filename, content_sha256, content_size, column_mapping, "
        " error_log) VALUES ($1, $2, $3, $4, $5, $6::json, $7::json)",
        ids["batch"],
        ids["ws"],
        "r.xlsx",
        "a" * 64,
        1,
        "{}",
        "[]",
    )
    await connection.execute(
        "INSERT INTO catalog_items "
        "(id, workspace_id, import_batch_id, source_row, sku, oe_raw, oe_norm, name, "
        " category, current_price, raw_row) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::json)",
        ids["item"],
        ids["ws"],
        ids["batch"],
        2,
        "SKU-R",
        "1K0 1",
        "1K01",
        "Позиция",
        "brakes",
        800,
        "{}",
    )
    return ids


async def _seed_run(connection, ids, *, bounded: bool, status: str) -> None:
    if bounded:
        await connection.execute(
            "INSERT INTO pricing_runs "
            "(id, workspace_id, import_batch_id, status, policy_version, policy_config, "
            " parser_version, classifier_version, coefficient_model, "
            " calibration_accounting, total_items, scope_contract_version, scope_mode, "
            " scope_confirmation_source, full_catalog_confirmed, scope_manifest, "
            " scope_hash, catalog_snapshot_hash, scope_frozen_at) "
            "VALUES ($1,$2,$3,$4,$5,$6::json,$7,$8,$9,$10::json,$11,$12,$13,$14,$15,"
            "$16::json,$17,$18, now())",
            ids["run"],
            ids["ws"],
            ids["batch"],
            status,
            "v1",
            "{}",
            "p",
            "c",
            "reference",
            "{}",
            1,
            "pricing-run-scope-v2",
            "FULL_CATALOG",
            "OPERATOR",
            True,
            "{}",
            "b" * 64,
            "c" * 64,
        )
        return
    await connection.execute(
        "INSERT INTO pricing_runs "
        "(id, workspace_id, import_batch_id, status, policy_version, policy_config, "
        " parser_version, classifier_version, coefficient_model, "
        " calibration_accounting, total_items) "
        "VALUES ($1,$2,$3,$4,$5,$6::json,$7,$8,$9,$10::json,$11)",
        ids["run"],
        ids["ws"],
        ids["batch"],
        status,
        "v1",
        "{}",
        "p",
        "c",
        "reference",
        "{}",
        1,
    )


async def _seed_observation(connection, ids) -> None:
    await connection.execute(
        "INSERT INTO pricing_run_items "
        "(id, pricing_run_id, catalog_item_id, idempotency_key) VALUES ($1,$2,$3,$4)",
        ids["run_item"],
        ids["run"],
        ids["item"],
        f"idem-{ids['run_item'].hex}",
    )
    await connection.execute(
        "INSERT INTO raw_market_captures "
        "(id, pricing_run_item_id, source, payload, content_sha256, parser_version) "
        "VALUES ($1,$2,$3,$4::json,$5,$6)",
        ids["capture"],
        ids["run_item"],
        "prom_public",
        "{}",
        "d" * 64,
        "p",
    )
    await connection.execute(
        "INSERT INTO market_observations "
        "(id, pricing_run_item_id, catalog_item_id, raw_capture_id, source, "
        " source_listing_id, seller_id, seller_name, url, title, price, currency, "
        " match_confidence, parser_version, observed_at, search_oe_norm) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14, now(), $15)",
        ids["obs"],
        ids["run_item"],
        ids["item"],
        ids["capture"],
        "prom_public",
        "L1",
        "S1",
        "Shop",
        "https://prom.ua/x",
        "Товар",
        100,
        "UAH",
        1,
        "p",
        "1K01",
    )


async def _insert_review(connection, ids, request_key: str) -> uuid.UUID:
    review_id = uuid.uuid4()
    await connection.execute(
        "INSERT INTO candidate_comparability_reviews "
        "(id, workspace_id, market_observation_id, catalog_item_id, request_key, "
        " input_hash, attempt_no, prompt_version, schema_version, provider, model_id, "
        " decision_source, status, verdict, match_level, confidence, rationale, "
        " dimension_findings, hard_stop_conflicts, input_snapshot, image_urls, usage, "
        " latency_ms, reviewed_at) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,"
        "$18::json,$19::json,$20::json,$21::json,$22::json,$23, now())",
        review_id,
        ids["ws"],
        ids["obs"],
        ids["item"],
        request_key,
        "e" * 64,
        1,
        "v1",
        "1",
        "openai_responses",
        "m",
        "LLM",
        "FAILED",
        "INSUFFICIENT_DATA",
        "NOT_APPLICABLE",
        0,
        "r",
        "[]",
        "[]",
        "{}",
        "[]",
        "{}",
        1,
    )
    return review_id


@pytest.mark.skipif(not _enabled(), reason="set MARKO_RUN_POSTGRES_INTEGRATION=1")
@pytest.mark.asyncio
async def test_duplicate_request_keys_are_impossible_before_0037() -> None:
    """Дубликат ``request_key`` создать нельзя, и это сильнее преflight-а.

    Проверка дубликатов в 0037 писалась как страховка, но выполнить её ветку
    настоящими строками невозможно: на ревизии 0034 уже стоит
    ``uq_candidate_comparability_review_request_key UNIQUE (request_key)``.
    Расхождение с моделью касалось только **индекса**
    ``ix_candidate_comparability_reviews_request_key``, который был создан
    неуникальным, тогда как уникальность и так гарантировалась ограничением.

    Поэтому здесь доказывается настоящий инвариант: вторая строка с тем же
    ключом отвергается базой. Преflight в 0037 остаётся защитой в глубину на
    случай, если ограничение когда-нибудь снимут; ветка недостижима, пока оно
    на месте, и выдавать её за проверенную нельзя.
    """

    _require_disposable()
    database = await _fresh_database("marko_dupfail_p15017")
    try:
        assert _alembic(database, "upgrade", "20260801_0036").returncode == 0
        connection = await asyncpg.connect(_dsn(database))
        try:
            constraint = await connection.fetchval(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'uq_candidate_comparability_review_request_key'"
            )
            assert constraint == "UNIQUE (request_key)", constraint

            ids = await _seed_chain(connection)
            await _seed_run(connection, ids, bounded=False, status="collecting")
            await _seed_observation(connection, ids)
            await _insert_review(connection, ids, "DUPLICATE-KEY")
            with pytest.raises(asyncpg.exceptions.UniqueViolationError):
                await _insert_review(connection, ids, "DUPLICATE-KEY")

            surviving = await connection.fetchval(
                "SELECT count(*) FROM candidate_comparability_reviews "
                "WHERE request_key = 'DUPLICATE-KEY'"
            )
            assert surviving == 1
        finally:
            await connection.close()

        # Раз дубликатов быть не может, чистый путь обязан дойти до head.
        assert _alembic(database, "upgrade", "head").returncode == 0
        assert _head_revision(database) in _revision(database)
    finally:
        await _admin(f'DROP DATABASE IF EXISTS "{database}"')


@pytest.mark.skipif(not _enabled(), reason="set MARKO_RUN_POSTGRES_INTEGRATION=1")
@pytest.mark.asyncio
async def test_0037_reaches_head_and_is_unique_on_a_clean_database() -> None:
    _require_disposable()
    database = await _fresh_database("marko_dupok_p15017")
    try:
        assert _alembic(database, "upgrade", "head").returncode == 0
        assert _head_revision(database) in _revision(database)
        connection = await asyncpg.connect(_dsn(database))
        try:
            unique = await connection.fetchval(
                "SELECT indisunique FROM pg_index WHERE indexrelid = "
                "'ix_candidate_comparability_reviews_request_key'::regclass"
            )
            assert unique is True
        finally:
            await connection.close()
        assert _alembic(database, "downgrade", "20260801_0036").returncode == 0
        assert _alembic(database, "upgrade", "head").returncode == 0
        assert _alembic(database, "check").returncode == 0
    finally:
        await _admin(f'DROP DATABASE IF EXISTS "{database}"')


@pytest.mark.skipif(not _enabled(), reason="set MARKO_RUN_POSTGRES_INTEGRATION=1")
@pytest.mark.asyncio
async def test_0035_refuses_while_a_pre_0035_bounded_run_is_active() -> None:
    """Прогоны, начатые до заморозки состава, нельзя дооформить задним числом."""

    _require_disposable()
    database = await _fresh_database("marko_runfail_p15017")
    try:
        assert _alembic(database, "upgrade", "20260801_0034").returncode == 0
        connection = await asyncpg.connect(_dsn(database))
        try:
            ids = await _seed_chain(connection)
            await _seed_run(connection, ids, bounded=True, status="collecting")
            matching = await connection.fetchval(
                "SELECT count(*) FROM pricing_runs WHERE id = $1 "
                "AND scope_contract_version IS NOT NULL "
                "AND status NOT IN ('completed','partial','failed','cancelled')",
                ids["run"],
            )
            assert matching == 1, "строка не соответствует предикату отказа"
        finally:
            await connection.close()

        result = _alembic(database, "upgrade", "20260801_0035")
        assert result.returncode != 0, (
            "миграция обязана отказаться при активном прогоне"
        )
        assert "BLOCKED_MIGRATION_20260801_0035" in (result.stdout + result.stderr)
        assert "20260801_0034" in _revision(database)

        connection = await asyncpg.connect(_dsn(database))
        try:
            preserved = await connection.fetchval("SELECT count(*) FROM pricing_runs")
            assert preserved == 1, "миграция тронула данные при отказе"
        finally:
            await connection.close()
    finally:
        await _admin(f'DROP DATABASE IF EXISTS "{database}"')


@pytest.mark.skipif(not _enabled(), reason="set MARKO_RUN_POSTGRES_INTEGRATION=1")
@pytest.mark.asyncio
async def test_0035_proceeds_once_the_run_is_terminal() -> None:
    """Чистый путь: завершённый прогон миграции не мешает."""

    _require_disposable()
    database = await _fresh_database("marko_runok_p15017")
    try:
        assert _alembic(database, "upgrade", "20260801_0034").returncode == 0
        connection = await asyncpg.connect(_dsn(database))
        try:
            ids = await _seed_chain(connection)
            await _seed_run(connection, ids, bounded=True, status="completed")
        finally:
            await connection.close()
        assert _alembic(database, "upgrade", "head").returncode == 0
        assert _head_revision(database) in _revision(database)
    finally:
        await _admin(f'DROP DATABASE IF EXISTS "{database}"')


@pytest.mark.skipif(not _enabled(), reason="set MARKO_RUN_POSTGRES_INTEGRATION=1")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "anomaly",
    ("SOURCE_SEMANTIC_CONFLICT", "PUBLIC_NUMBER_SEMANTIC_FANOUT"),
)
async def test_0047_downgrade_refuses_to_erase_semantic_conflict(
    anomaly: str,
) -> None:
    """The newer CHECK cannot be removed while a quarantined edge uses it."""

    _require_disposable()
    database = await _fresh_database("marko_semantic_identity_p15017")
    try:
        assert _alembic(database, "upgrade", "head").returncode == 0
        connection = await asyncpg.connect(_dsn(database))
        try:
            ids = await _seed_chain(connection)
            await connection.execute(
                "INSERT INTO catalog_identity_links "
                "(id, workspace_id, catalog_item_id, our_oem_norm, "
                " extracted_oem_norm, extracted_raw, raw_context, "
                " extraction_method, validation_status, anomaly, "
                " method_version, config_sha256) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'REVIEW',$9,$10,$11)",
                uuid.uuid4(),
                ids["ws"],
                ids["item"],
                "312783",
                "8E0513033",
                "8E0 513 033",
                "rear in v1; front in v2",
                "KEMP_REFERENCE_MAP_V2",
                anomaly,
                "identity-graph-v3",
                "b" * 64,
            )
        finally:
            await connection.close()

        refused = _alembic(database, "downgrade", "20260804_0046")
        assert refused.returncode != 0
        assert anomaly in (refused.stdout + refused.stderr)
        # A failed transactional downgrade from a mergepoint leaves the
        # database at the single shipped head; it no longer reports each
        # ancestor revision separately.
        assert _head_revision(database) in _revision(database)

        connection = await asyncpg.connect(_dsn(database))
        try:
            await connection.execute(
                "DELETE FROM catalog_identity_links "
                "WHERE anomaly = $1",
                anomaly,
            )
        finally:
            await connection.close()
        assert _alembic(database, "downgrade", "20260804_0046").returncode == 0
        assert "20260804_0046" in _revision(database)
    finally:
        await _admin(f'DROP DATABASE IF EXISTS "{database}"')


@pytest.mark.skipif(not _enabled(), reason="set MARKO_RUN_POSTGRES_INTEGRATION=1")
@pytest.mark.asyncio
async def test_0046_downgrade_refuses_to_erase_stale_quarantine_semantics() -> None:
    """A downgrade must not strand a value forbidden by the older CHECK."""

    _require_disposable()
    database = await _fresh_database("marko_stale_identity_p15017")
    try:
        assert _alembic(database, "upgrade", "head").returncode == 0
        connection = await asyncpg.connect(_dsn(database))
        try:
            ids = await _seed_chain(connection)
            await connection.execute(
                "INSERT INTO catalog_identity_links "
                "(id, workspace_id, catalog_item_id, our_oem_norm, "
                " extracted_oem_norm, extracted_raw, raw_context, "
                " extraction_method, validation_status, anomaly, "
                " method_version, config_sha256) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'REVIEW',"
                "'STALE_AFTER_REPARSE',$9,$10)",
                uuid.uuid4(),
                ids["ws"],
                ids["item"],
                "1K01",
                "7L6121253C",
                "7L6 121 253 C",
                "obsolete source row",
                "KEMP_REFERENCE_MAP_V2",
                "identity-graph-v2",
                "a" * 64,
            )
        finally:
            await connection.close()

        refused = _alembic(database, "downgrade", "20260804_0045")
        assert refused.returncode != 0
        assert "STALE_AFTER_REPARSE" in (refused.stdout + refused.stderr)
        assert _head_revision(database) in _revision(database)

        connection = await asyncpg.connect(_dsn(database))
        try:
            await connection.execute(
                "DELETE FROM catalog_identity_links "
                "WHERE anomaly = 'STALE_AFTER_REPARSE'"
            )
        finally:
            await connection.close()
        assert _alembic(database, "downgrade", "20260804_0045").returncode == 0
        assert "20260804_0045" in _revision(database)
    finally:
        await _admin(f'DROP DATABASE IF EXISTS "{database}"')


@pytest.mark.skipif(not _enabled(), reason="set MARKO_RUN_POSTGRES_INTEGRATION=1")
@pytest.mark.asyncio
async def test_0037_preflight_refuses_when_the_unique_constraint_is_absent() -> None:
    """Искусственная проверка: преflight 0037 несущий, а не декоративный.

    Ветку нельзя вызвать на настоящей схеме — ``UNIQUE (request_key)`` стоит
    ещё с 0034, и второй строки с тем же ключом просто не существует. Поэтому
    ограничение снимается **только внутри одноразовой базы**, чтобы
    воспроизвести состояние, ради которого преflight и написан: ограничение
    когда-то сняли, дубликаты завелись, и миграция обязана отказаться, а не
    молча выбрать, какую улику оставить.

    Схема продукта здесь не меняется: ни модель, ни миграции не трогаются, а
    база уничтожается в ``finally``.
    """

    _require_disposable()
    database = await _fresh_database("marko_dupforce_p15017")
    try:
        assert _alembic(database, "upgrade", "20260801_0036").returncode == 0
        connection = await asyncpg.connect(_dsn(database))
        try:
            # Снятие ограничения — единственная искусственная часть теста.
            await connection.execute(
                "ALTER TABLE candidate_comparability_reviews "
                "DROP CONSTRAINT uq_candidate_comparability_review_request_key"
            )
            ids = await _seed_chain(connection)
            await _seed_run(connection, ids, bounded=False, status="collecting")
            await _seed_observation(connection, ids)
            first = await _insert_review(connection, ids, "DUPLICATE-KEY")
            second = await _insert_review(connection, ids, "DUPLICATE-KEY")
            assert first != second

            seeded = await connection.fetchval(
                "SELECT count(*) FROM candidate_comparability_reviews "
                "WHERE request_key = 'DUPLICATE-KEY'"
            )
            # Данные существуют — только теперь отказ что-то доказывает.
            assert seeded == 2
        finally:
            await connection.close()

        result = _alembic(database, "upgrade", "head")
        assert result.returncode != 0, "миграция обязана отказаться при дубликатах"
        combined = result.stdout + result.stderr
        assert "BLOCKED_MIGRATION_20260801_0037" in combined
        assert "DUPLICATE-KEY" in combined, "отказ обязан назвать конкретные ключи"
        assert "20260801_0036" in _revision(database)

        connection = await asyncpg.connect(_dsn(database))
        try:
            surviving = await connection.fetchval(
                "SELECT count(*) FROM candidate_comparability_reviews "
                "WHERE request_key = 'DUPLICATE-KEY'"
            )
            assert surviving == 2, "миграция удалила чужие улики вместо отказа"
            unique = await connection.fetchval(
                "SELECT indisunique FROM pg_index WHERE indexrelid = "
                "'ix_candidate_comparability_reviews_request_key'::regclass"
            )
            assert unique is False, "индекс подменён несмотря на отказ"
        finally:
            await connection.close()
    finally:
        await _admin(f'DROP DATABASE IF EXISTS "{database}"')
