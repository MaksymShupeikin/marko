"""Catalog repricing: plan a run, walk it, and record why each price moved.

Прогін нічого не змінює в каталозі. Він рахує пропозицію для кожного товару
і складає її в ``reprice_run_items`` разом із доказами — застосовує ціни
людина, і лише за межами Marko.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession

import marko.repositories.listings as listings_repo
import marko.repositories.repricing as repricing_repo
import marko.repositories.stores as stores_repo
from marko.infrastructure.db.models import (
    RepriceItemStatus,
    RepriceMode,
    RepriceOutcome,
    RepricePolicy,
    RepriceRun,
    RepriceScope,
    SyncRun,
    SyncStatus,
)
from marko.infrastructure.db.session import async_session_factory
from marko.services import billing
from marko.services.bulk_products import CatalogFilter
from marko.services.competitor_prices import (
    cached_report_for_query,
    competitor_prices_for_query,
    listing_search_query,
)
from marko.services.pricing import DEFAULT_ENGINE, get_engine

log = logging.getLogger(__name__)

REPRICE_TASK = "marko.worker.reprice_catalog"
REPRICE_KIND = "catalog_reprice"

_PROGRESS_EVERY = 25

# Запобіжник каталогу: якщо прогін пропонує зрушити більшу частку товарів,
# це радше зламаний рушій або зіпсовані дані, ніж ринок. Зупиняємось і
# кажемо про це, замість тихо віддати тисячі нових цін.
MAX_CHANGED_SHARE = 0.2
# На маленькому зрізі частка нічого не означає: три товари з трьох — це 100%.
MIN_PLAN_FOR_SHARE_GUARD = 20

_LIMIT_REACHED = "Вичерпано ліміт перевірок цін"
_GONE = "Товар зник з каталогу або став недоступним для редагування"


class RepriceDispatchError(RuntimeError):
    """The repricing run could not be queued."""


@dataclass(frozen=True)
class CatalogSignature:
    """Which catalog a run was measured against — by composition, not by price.

    Підпис навмисно не включає ціни. Інакше будь-яке оновлення каталогу
    скидало б покриття, і кнопка «продовжити» не працювала б майже ніколи.
    Застарівання окремої ціни відстежує ``price_at_compute`` у рядку прогону.
    """

    value: str
    item_count: int
    store_ids: tuple[str, ...]


@dataclass(frozen=True)
class RepricePreview:
    """What a run would cost and cover, before anything is queued."""

    catalog: CatalogSignature
    matching: int
    covered: int
    remaining: int
    checks_left: int | None
    last_run_signature: str | None
    signature_changed: bool


async def catalog_signature(
    session: AsyncSession, workspace_id: UUID
) -> CatalogSignature:
    """SHA-1 over the sorted ids of every own-store product, filters ignored.

    Фільтр сюди не входить навмисно: підпис описує каталог, а не зріз. Інакше
    зміна фільтра в інтерфейсі виглядала б як зміна каталогу й обнуляла б
    покриття.
    """
    ids = await listings_repo.manageable_workspace_listing_ids(session, workspace_id)
    ordered = sorted(str(value) for value in ids)
    digest = hashlib.sha1("|".join(ordered).encode("utf-8")).hexdigest()
    store_ids = await stores_repo.owned_store_ids(session, workspace_id)
    return CatalogSignature(
        value=digest,
        item_count=len(ordered),
        store_ids=tuple(str(value) for value in store_ids),
    )


async def preview(
    session: AsyncSession,
    workspace_id: UUID,
    catalog_filter: CatalogFilter,
    *,
    mode: RepriceMode = RepriceMode.fresh,
) -> RepricePreview:
    signature = await catalog_signature(session, workspace_id)
    matching = len(
        await listings_repo.manageable_workspace_listing_ids(
            session,
            workspace_id,
            query=catalog_filter.query,
            price_min=catalog_filter.price_min,
            price_max=catalog_filter.price_max,
            source=catalog_filter.source,
            available=catalog_filter.available,
            store_ids=catalog_filter.store_uuids,
        )
    )
    covered_ids = await repricing_repo.covered_listing_ids(
        session, workspace_id, signature.value
    )
    # Покриття рахуємо по всьому каталогу, а лишок — по зрізу фільтра.
    covered = len(covered_ids)
    remaining = matching if mode is RepriceMode.fresh else max(matching - covered, 0)
    runs = await repricing_repo.list_runs(session, workspace_id, limit=1)
    last_signature = runs[0][0].catalog_scope_signature if runs else None
    return RepricePreview(
        catalog=signature,
        matching=matching,
        covered=covered,
        remaining=remaining,
        checks_left=await billing.checks_remaining(session, workspace_id),
        last_run_signature=last_signature,
        signature_changed=(
            last_signature is not None and last_signature != signature.value
        ),
    )


@dataclass(frozen=True)
class Reconciliation:
    """How a changed catalog lines up with what was already priced."""

    signature_changed: bool
    previous_signature: str | None
    # Пораховані товари, які вижили в новому каталозі.
    kept: int
    # Пораховані товари, яких у каталозі більше немає.
    gone: int
    # Товари каталогу, яких ще не рахували.
    fresh: int


async def reconciliation(
    session: AsyncSession, workspace_id: UUID
) -> Reconciliation:
    """Compare the catalog as it is now with what past runs already priced.

    Порівнюємо не два склади каталогу, а покриття з нинішнім складом: повний
    список id минулого каталогу довелося б зберігати цілком (47 тисяч UUID на
    кожен прогін), а відповідь від цього не стала б кориснішою — людину
    цікавить саме те, що доведеться рахувати заново.
    """
    signature = await catalog_signature(session, workspace_id)
    runs = await repricing_repo.list_runs(session, workspace_id, limit=1)
    if not runs:
        return Reconciliation(
            signature_changed=False,
            previous_signature=None,
            kept=0,
            gone=0,
            fresh=signature.item_count,
        )

    previous = runs[0][0].catalog_scope_signature
    current_ids = set(
        await listings_repo.manageable_workspace_listing_ids(session, workspace_id)
    )
    covered = await repricing_repo.covered_listing_ids(
        session, workspace_id, previous
    )
    return Reconciliation(
        signature_changed=previous != signature.value,
        previous_signature=previous,
        kept=len(covered & current_ids),
        gone=len(covered - current_ids),
        fresh=len(current_ids - covered),
    )


async def carry_over_coverage(
    session: AsyncSession, workspace_id: UUID
) -> RepriceRun | None:
    """Count surviving products as already priced under the new catalog.

    Це і є відповідь на «щоб не повторюватися і не робити з самого початку»:
    після зміни складу каталогу підпис інший, і покриття формально порожнє,
    хоча більшість товарів ті самі. Перенесення нічого не рахує — воно
    переписує вже отримані результати під новий підпис, а рядки, чия ціна
    відтоді поїхала, позначає як такі, що потребують перерахунку.
    """
    signature = await catalog_signature(session, workspace_id)
    runs = await repricing_repo.list_runs(session, workspace_id, limit=1)
    if not runs:
        return None
    previous = runs[0][0].catalog_scope_signature
    if previous == signature.value:
        return None

    current_ids = set(
        await listings_repo.manageable_workspace_listing_ids(session, workspace_id)
    )
    items = [
        item
        for item in await repricing_repo.latest_done_items(
            session, workspace_id, previous
        )
        if item.listing_id in current_ids
    ]
    if not items:
        return None

    run = RepriceRun(
        id=uuid4(),
        workspace_id=workspace_id,
        scope=RepriceScope.full,
        mode=RepriceMode.carry_over,
        policy=RepricePolicy.balanced,
        engine="carry_over",
        catalog_scope_signature=signature.value,
        catalog_item_count=signature.item_count,
        store_ids=list(signature.store_ids),
        changed_count=sum(
            1 for item in items if item.outcome is RepriceOutcome.changed
        ),
        unchanged_count=sum(
            1 for item in items if item.outcome is RepriceOutcome.unchanged
        ),
        skipped_count=sum(
            1 for item in items if item.outcome is RepriceOutcome.no_recommendation
        ),
    )
    await repricing_repo.create_run(session, run)
    await session.flush()
    await repricing_repo.insert_items(
        session,
        [
            {
                "run_id": run.id,
                "listing_id": item.listing_id,
                "position": position,
                "group_key": item.group_key,
                "status": RepriceItemStatus.done,
                "outcome": item.outcome,
                "reason": item.reason,
                "old_price": item.old_price,
                "new_price": item.new_price,
                "delta_abs": item.delta_abs,
                "delta_pct": item.delta_pct,
                "price_at_compute": item.price_at_compute,
                "zone": item.zone,
                "tier": item.tier,
                "method": item.method,
                "confidence": item.confidence,
                "offers_total": item.offers_total,
                "evidence": item.evidence,
                "computed_at": item.computed_at,
            }
            for position, item in enumerate(items)
        ],
    )
    await session.commit()
    return run


async def queue_reprice(
    session: AsyncSession,
    workspace_id: UUID,
    catalog_filter: CatalogFilter,
    *,
    scope: RepriceScope,
    mode: RepriceMode,
    policy: RepricePolicy,
    requested_count: int | None,
    celery_app: Celery,
    engine_name: str = DEFAULT_ENGINE,
) -> RepriceRun:
    """Materialise the plan, then hand it to the worker.

    План матеріалізується тут, а не у воркері: «продовжити» має продовжувати
    рівно там, де зупинилися, а порядок, порахований двічі в різний час,
    цього не гарантує.
    """
    signature = await catalog_signature(session, workspace_id)
    rows = await listings_repo.reprice_plan_rows(
        session,
        workspace_id,
        query=catalog_filter.query,
        price_min=catalog_filter.price_min,
        price_max=catalog_filter.price_max,
        source=catalog_filter.source,
        available=catalog_filter.available,
        store_ids=catalog_filter.store_uuids,
    )
    if mode is RepriceMode.resume:
        covered = await repricing_repo.covered_listing_ids(
            session, workspace_id, signature.value
        )
        rows = [row for row in rows if row[0] not in covered]
    if scope is RepriceScope.partial and requested_count is not None:
        rows = rows[: max(requested_count, 0)]

    sync_run = await stores_repo.create_sync_run(
        session,
        workspace_id=workspace_id,
        store_id=None,
        kind=REPRICE_KIND,
        status=SyncStatus.queued,
    )
    sync_run.progress_total = len(rows)
    await session.flush()

    run = RepriceRun(
        # Ідентифікатор ставимо тут, а не покладаємось на default колонки:
        # рядки плану посилаються на нього ще до commit.
        id=uuid4(),
        workspace_id=workspace_id,
        sync_run_id=sync_run.id,
        scope=scope,
        mode=mode,
        policy=policy,
        requested_count=requested_count,
        engine=engine_name,
        catalog_scope_signature=signature.value,
        catalog_item_count=signature.item_count,
        store_ids=list(signature.store_ids),
        filter_json=catalog_filter.as_json(),
    )
    await repricing_repo.create_run(session, run)
    await session.flush()

    await repricing_repo.insert_items(
        session,
        [
            {
                "run_id": run.id,
                "listing_id": listing_id,
                "position": position,
                "group_key": group_key,
                "status": RepriceItemStatus.pending,
                "old_price": price,
            }
            for position, (listing_id, group_key, price) in enumerate(rows)
        ],
    )
    await session.commit()

    try:
        result = await asyncio.to_thread(
            celery_app.send_task, REPRICE_TASK, args=[str(sync_run.id)]
        )
    except Exception as exc:
        sync_run.status = SyncStatus.failed
        sync_run.error = f"Не вдалося поставити переоцінку в чергу: {exc}"[:4000]
        sync_run.finished_at = datetime.now(UTC)
        await session.commit()
        raise RepriceDispatchError(sync_run.error) from exc

    sync_run.task_id = result.id
    await session.commit()
    return run


async def run_reprice(sync_run_id: UUID) -> int:
    """Worker side: walk the materialised plan, one product at a time."""
    async with async_session_factory() as session:
        sync_run = await session.get(SyncRun, sync_run_id)
        if sync_run is None or sync_run.workspace_id is None:
            raise LookupError(f"Sync run {sync_run_id} does not exist")
        run = await repricing_repo.get_run_by_sync_run(session, sync_run_id)
        if run is None:
            raise LookupError(f"Reprice run for sync run {sync_run_id} does not exist")

        sync_run.status = SyncStatus.running
        sync_run.started_at = datetime.now(UTC)
        sync_run.progress_current = 0
        sync_run.error = None
        await session.commit()

        engine = get_engine(run.engine)
        plan_size = sync_run.progress_total or 0
        done = 0
        budget_spent = False
        stopped: str | None = None

        while True:
            await session.refresh(sync_run)
            if sync_run.status is SyncStatus.cancelled:
                stopped = "Переоцінку зупинено на вашу вимогу"
                break

            batch = await repricing_repo.next_pending_items(
                session, run.id, limit=_PROGRESS_EVERY
            )
            if not batch:
                break

            for item in batch:
                # Один зламаний товар не має валити прогін по каталогу — і не
                # має лишатися pending, інакше наступний цикл візьме ту саму
                # партію і крутитиметься на ній вічно.
                try:
                    budget_spent = await _process_item(
                        session, run, item, engine=engine, budget_spent=budget_spent
                    )
                except Exception as exc:  # noqa: BLE001 — рядок, а не прогін
                    log.exception("Товар %s не переоцінено", item.listing_id)
                    _mark_skipped(
                        run,
                        item,
                        f"Помилка розрахунку: {exc}"[:255],
                        status=RepriceItemStatus.failed,
                    )
                    run.failed_count += 1
                done += 1

            sync_run.progress_current = done
            await session.commit()

            if _share_guard_tripped(run, plan_size):
                stopped = (
                    f"Зупинено запобіжником: прогін пропонує змінити ціну більш ніж "
                    f"у {int(MAX_CHANGED_SHARE * 100)}% товарів "
                    f"({run.changed_count} з {plan_size}). Перевірте дані ринку."
                )
                break

        sync_run.status = (
            SyncStatus.cancelled
            if sync_run.status is SyncStatus.cancelled
            else SyncStatus.completed
        )
        sync_run.finished_at = datetime.now(UTC)
        sync_run.error = stopped or (
            f"Не вдалося порахувати {run.failed_count} з {plan_size} товарів"
            if run.failed_count
            else None
        )
        await session.commit()
        return done


def _share_guard_tripped(run: RepriceRun, plan_size: int) -> bool:
    if plan_size < MIN_PLAN_FOR_SHARE_GUARD:
        return False
    return run.changed_count > plan_size * MAX_CHANGED_SHARE


async def _process_item(
    session: AsyncSession,
    run: RepriceRun,
    item: Any,
    *,
    engine: Any,
    budget_spent: bool,
) -> bool:
    """Fill one plan row. Returns whether the check budget is now exhausted."""
    item.computed_at = datetime.now(UTC)
    row = await listings_repo.get_manageable_workspace_listing(
        session, run.workspace_id, item.listing_id
    )
    if row is None:
        _mark_skipped(run, item, _GONE, status=RepriceItemStatus.failed)
        run.failed_count += 1
        return budget_spent

    listing, _store, override = row
    current_price = (
        override.current_price
        if override is not None and override.current_price is not None
        else listing.current_price
    )
    item.old_price = current_price
    item.price_at_compute = current_price

    try:
        query = await listing_search_query(session, run.workspace_id, item.listing_id)
    except LookupError:
        _mark_skipped(run, item, _GONE, status=RepriceItemStatus.failed)
        run.failed_count += 1
        return budget_spent

    report = await cached_report_for_query(query)
    if report is None:
        if budget_spent:
            _mark_skipped(run, item, _LIMIT_REACHED)
            run.skipped_count += 1
            return True
        # Перевірку списуємо перед живим запитом, а не після: інакше ліміт
        # дізнавався б про витрату вже після того, як гроші пішли.
        if not await billing.try_consume_check(session, run.workspace_id):
            _mark_skipped(run, item, _LIMIT_REACHED)
            run.skipped_count += 1
            return True
        try:
            report = await competitor_prices_for_query(query)
        except Exception as exc:  # мережа, джерело, парсер — рядок, не прогін
            log.info("Товар %s не переоцінено: %s", item.listing_id, exc)
            _mark_skipped(
                run, item, f"Не вдалося зібрати ринок: {exc}"[:255],
                status=RepriceItemStatus.failed,
            )
            run.failed_count += 1
            return budget_spent

    suggestion = engine.suggest(
        current_price=current_price,
        report=report,
        policy=run.policy.value,
    )
    _apply_suggestion(run, item, suggestion)
    return budget_spent


def _mark_skipped(
    run: RepriceRun,
    item: Any,
    reason: str,
    *,
    status: RepriceItemStatus = RepriceItemStatus.done,
) -> None:
    item.status = status
    item.outcome = RepriceOutcome.no_recommendation
    item.reason = reason


def _apply_suggestion(run: RepriceRun, item: Any, suggestion: Any) -> None:
    item.status = RepriceItemStatus.done
    item.outcome = RepriceOutcome(suggestion.outcome)
    item.reason = suggestion.reason
    item.new_price = suggestion.new_price
    item.zone = suggestion.zone
    item.tier = suggestion.tier
    item.method = suggestion.method
    item.confidence = suggestion.confidence
    item.offers_total = suggestion.offers_total
    item.evidence = suggestion.evidence

    old = item.old_price
    new = suggestion.new_price
    if old is not None and new is not None and old > 0:
        item.delta_abs = new - old
        item.delta_pct = ((new - old) / old * Decimal("100")).quantize(Decimal("0.01"))

    if item.outcome is RepriceOutcome.changed:
        run.changed_count += 1
    elif item.outcome is RepriceOutcome.unchanged:
        run.unchanged_count += 1
    else:
        run.skipped_count += 1
