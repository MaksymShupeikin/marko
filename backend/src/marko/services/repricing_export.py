"""The repricing run as an .xlsx sheet.

Вивантаження — не дамп таблиці, а документ: у шапці написано, коли прогін
зроблено і відносно якого каталогу, інакше через тиждень файл нічого не
доводить. Приховані рядки сюди не потрапляють — їх прибрали свідомо.
"""
from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from typing import Any, Sequence
from uuid import UUID

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font
from sqlalchemy.ext.asyncio import AsyncSession

import marko.repositories.repricing as repricing_repo
from marko.infrastructure.db.models import RepriceOutcome, RepriceRun

SHEET_TITLE = "Переоцінка"

_OUTCOME_LABELS = {
    RepriceOutcome.changed: "Змінено",
    RepriceOutcome.unchanged: "Без змін",
    RepriceOutcome.no_recommendation: "Не пораховано",
}

_SCOPE_LABELS = {"full": "весь каталог", "partial": "частина каталогу"}
_MODE_LABELS = {"fresh": "з початку", "resume": "продовження"}

_COLUMNS = (
    "Артикул",
    "Назва",
    "Бренд",
    "Магазин",
    "Стара ціна",
    "Нова ціна",
    "Різниця",
    "Різниця, %",
    "Валюта",
    "Результат",
    "Причина",
    "Зона",
    "Тир",
    "Впевненість",
    "Пропозицій",
    "Ціна змінилась після розрахунку",
    "Посилання",
)


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _effective(override: Any, listing: Any, field: str) -> Any:
    value = getattr(override, field, None) if override is not None else None
    return value if value is not None else getattr(listing, field, None)


def _drift_label(item: Any, listing: Any, override: Any) -> str:
    """Явні «так»/«ні», а не порожня клітинка.

    Порожнє в таблиці читається і як «ні», і як «не знаємо» — та сама
    двозначність, через яку «без змін» не можна плутати з «не пораховано».
    """
    if item.price_at_compute is None:
        return "невідомо"
    current = _effective(override, listing, "current_price")
    return "ні" if current == item.price_at_compute else "так"


def _header_rows(run: RepriceRun) -> list[list[Any]]:
    """Метадані прогону: без них файл не відповідає на «коли і по чому»."""
    stores = ", ".join(run.store_ids or []) or "усі власні магазини"
    return [
        ["Переоцінка каталогу"],
        ["Дата прогону", run.created_at.strftime("%Y-%m-%d %H:%M")],
        [
            "Охоплення",
            f"{_SCOPE_LABELS.get(run.scope.value, run.scope.value)}"
            f" · {_MODE_LABELS.get(run.mode.value, run.mode.value)}",
        ],
        ["Політика", run.policy.value],
        ["Рушій", run.engine],
        ["Каталог (підпис складу)", run.catalog_scope_signature],
        ["Товарів у каталозі на той момент", run.catalog_item_count],
        ["Магазини", stores],
        [
            "Підсумок",
            f"змінено {run.changed_count}"
            f" · без змін {run.unchanged_count}"
            f" · не пораховано {run.skipped_count}"
            f" · помилок {run.failed_count}",
        ],
        [],
    ]


def build_workbook(
    run: RepriceRun,
    rows: Sequence[tuple[Any, Any, Any, Any]],
) -> BytesIO:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(SHEET_TITLE)
    bold = Font(bold=True)

    for row in _header_rows(run):
        if row:
            first = WriteOnlyCell(sheet, value=row[0])
            first.font = bold
            sheet.append([first, *row[1:]])
        else:
            sheet.append([])

    header = []
    for title in _COLUMNS:
        cell = WriteOnlyCell(sheet, value=title)
        cell.font = bold
        header.append(cell)
    sheet.append(header)

    for item, listing, store, override in rows:
        sheet.append(
            [
                _effective(override, listing, "sku"),
                _effective(override, listing, "name"),
                _effective(override, listing, "brand"),
                store.name if store is not None else None,
                _number(item.old_price),
                _number(item.new_price),
                _number(item.delta_abs),
                _number(item.delta_pct),
                listing.currency,
                _OUTCOME_LABELS.get(item.outcome, ""),
                item.reason,
                item.zone,
                item.tier,
                _number(item.confidence),
                item.offers_total,
                _drift_label(item, listing, override),
                listing.url,
            ]
        )

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


async def export_run(
    session: AsyncSession, run: RepriceRun, workspace_id: UUID
) -> BytesIO:
    rows = await repricing_repo.items_for_export(session, run.id, workspace_id)
    return build_workbook(run, rows)


def export_filename(run: RepriceRun) -> str:
    return f"marko-reprice-{run.created_at.strftime('%Y%m%d-%H%M')}.xlsx"
