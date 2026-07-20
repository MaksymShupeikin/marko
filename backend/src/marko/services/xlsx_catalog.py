"""Validated XLSX ingestion for Prom catalog exports.

The parser keeps the original row next to normalized pricing inputs.  It does
not execute workbook formulas and never converts article numbers to integers,
so leading zeroes remain intact when they are present in the workbook.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any
from uuid import UUID
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.core.config import Settings, get_settings
from marko.infrastructure.db.models import CatalogImportBatch, CatalogItem
from marko.services.catalog_costs import add_encrypted_cost_record
from marko.services.cost_privacy import (
    CostPrivacyMode,
    is_raw_cost_label,
    require_server_cost_input_allowed,
)

MAX_XLSX_BYTES = 25 * 1024 * 1024
MAX_UNCOMPRESSED_XLSX_BYTES = 250 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 256
MAX_ERROR_LOG = 2_000

_HEADER_CLEAN_RE = re.compile(r"[^a-zа-яёіїґєԁөү0-9]+", re.IGNORECASE)
_IDENTIFIER_SPLIT_RE = re.compile(r"[,;|\n\r]+")
_IDENTIFIER_CLEAN_RE = re.compile(r"[^A-Z0-9]+")
_HOMOGLYPHS = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "С": "C",
        "Е": "E",
        "Н": "H",
        "К": "K",
        "М": "M",
        "О": "O",
        "Р": "P",
        "Т": "T",
        "Х": "X",
        "І": "I",
    }
)

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "sku": (
        "sku",
        "артикул",
        "артикул продавца",
        "артикул продавця",
        "код товара",
        "код товару",
        "код позиции",
    ),
    "oe": (
        "oe",
        "oem",
        "oe oem",
        "oem номер",
        "oe номер",
        "номер oe",
        "номер oem",
        "ое номер",
        "оригинальный номер",
        "оригінальний номер",
        "номер запчасти",
        "номер запчастини",
    ),
    "mpn": ("mpn", "manufacturer part number", "номер производителя"),
    "name": (
        "name",
        "title",
        "название",
        "назва",
        "наименование",
        "название позиции",
        "назва позиції",
    ),
    "category": (
        "category",
        "категория",
        "категорія",
        "группа",
        "група",
        "название группы",
        "назва групи",
    ),
    "price": ("price", "цена", "ціна", "цена розничная", "ціна роздрібна"),
    "currency": ("currency", "валюта"),
    "available": (
        "available",
        "availability",
        "наличие",
        "наявність",
        "статус наличия",
    ),
    "brand": ("brand", "manufacturer", "бренд", "производитель", "виробник"),
    "description": ("description", "описание", "опис"),
    "product_url": (
        "url",
        "product url",
        "ссылка",
        "посилання",
        "ссылка на товар",
        "посилання на товар",
    ),
    "stock_status": (
        "stock status",
        "статус товара",
        "статус товару",
        "статус запасаса",
    ),
    "stock_qty": (
        "stock qty",
        "quantity",
        "остаток",
        "залишок",
        "количество",
        "кількість",
    ),
    "stock_age_days": (
        "stock age days",
        "age days",
        "возраст запаса",
        "вік запасу",
        "дней на складе",
    ),
    "expected_units_sold": (
        "expected units sold",
        "monthly sales",
        "продажи в месяц",
        "продажі на місяць",
        "план продаж в месяц",
        "план продажів на місяць",
    ),
    "units_sold_30d": (
        "units sold 30d",
        "sales 30d",
        "продажи за 30 дней",
        "продажі за 30 днів",
    ),
    "units_sold_60d": (
        "units sold 60d",
        "sales 60d",
        "продажи за 60 дней",
        "продажі за 60 днів",
    ),
    "units_sold_90d": (
        "units sold 90d",
        "sales 90d",
        "продажи за 90 дней",
        "продажі за 90 днів",
    ),
    "days_since_last_sale": (
        "days since last sale",
        "дней с последней продажи",
        "днів з останнього продажу",
    ),
    "historical_monthly_units": (
        "historical monthly units",
        "historical monthly sales",
        "средние продажи в месяц",
        "середні продажі на місяць",
    ),
    "views_30d": (
        "views 30d",
        "просмотры за 30 дней",
        "перегляди за 30 днів",
    ),
    "conversion_rate_proxy": (
        "conversion rate proxy",
        "conversion",
        "конверсия",
        "конверсія",
    ),
    # Raw cost is never ingested through a generic workbook boundary.  The
    # privacy mode must be decided before a dedicated path can exist.
    "cost": (),
    "manual_priority": ("manual priority", "приоритет", "пріоритет"),
}

REQUIRED_FIELDS = frozenset({"oe", "name", "category", "price"})


class CatalogImportError(ValueError):
    """The workbook as a whole cannot be imported."""


class SensitiveCatalogImportBlocked(CatalogImportError):
    """A workbook contains raw cost but encrypted ingestion is unavailable."""


@dataclass(frozen=True)
class ImportIssue:
    row: int
    code: str
    message: str


@dataclass(frozen=True)
class ParsedCatalogRow:
    source_row: int
    sku: str
    oe_raw: str
    oe_norm: str
    mpn_raw: str
    mpn_norm: str
    name: str
    category: str
    brand: str | None
    description: str | None
    product_url: str | None
    current_price: Decimal
    currency: str
    is_available: bool | None
    stock_status: str
    stock_qty: Decimal | None
    stock_age_days: Decimal | None
    expected_units_sold: Decimal | None
    units_sold_30d: Decimal | None
    units_sold_60d: Decimal | None
    units_sold_90d: Decimal | None
    days_since_last_sale: Decimal | None
    historical_monthly_units: Decimal | None
    views_30d: Decimal | None
    conversion_rate_proxy: Decimal | None
    cost: Decimal | None
    manual_priority: Decimal
    raw_row: dict[str, Any]


@dataclass(frozen=True)
class ParsedCatalog:
    rows: list[ParsedCatalogRow]
    issues: list[ImportIssue]
    column_mapping: dict[str, str]
    total_rows: int
    sensitive_costs: dict[int, Decimal]


def normalize_identifier(value: Any) -> str:
    """Normalize an OE/MPN without ever coercing it to a number."""
    raw = _cell_text(value).upper().translate(_HOMOGLYPHS)
    primary = _IDENTIFIER_SPLIT_RE.split(raw, maxsplit=1)[0]
    return _IDENTIFIER_CLEAN_RE.sub("", primary)


def parse_catalog_xlsx(
    content: bytes,
    *,
    explicit_mapping: dict[str, str] | None = None,
    sheet_name: str | None = None,
    allow_encrypted_cost_input: bool = False,
) -> ParsedCatalog:
    if not content:
        raise CatalogImportError("Файл пуст")
    if len(content) > MAX_XLSX_BYTES:
        raise CatalogImportError(f"Файл больше {MAX_XLSX_BYTES // 1024 // 1024} MB")
    try:
        with ZipFile(BytesIO(content)) as archive:
            uncompressed_size = sum(entry.file_size for entry in archive.infolist())
    except (BadZipFile, OSError) as exc:
        raise CatalogImportError("Файл не является валидным XLSX") from exc
    if uncompressed_size > MAX_UNCOMPRESSED_XLSX_BYTES:
        raise CatalogImportError("Распакованный XLSX слишком велик")
    try:
        workbook = load_workbook(
            BytesIO(content),
            read_only=True,
            data_only=True,
            keep_links=False,
        )
    except (InvalidFileException, OSError, ValueError, KeyError) as exc:
        raise CatalogImportError("Файл не является валидным XLSX") from exc

    try:
        if sheet_name is not None:
            if sheet_name not in workbook.sheetnames:
                raise CatalogImportError(f"Лист {sheet_name!r} не найден")
            sheet = workbook[sheet_name]
        else:
            sheet = workbook.active
        iterator = sheet.iter_rows(values_only=True)
        try:
            header_values = next(iterator)
        except StopIteration as exc:
            raise CatalogImportError("В XLSX нет строк") from exc
        if len(header_values) > MAX_COLUMNS:
            raise CatalogImportError(
                f"Слишком много колонок: {len(header_values)} > {MAX_COLUMNS}"
            )
        headers = _unique_headers(header_values)
        resolved = resolve_column_mapping(headers, explicit_mapping)
        cost_indexes = [
            index for index, header in enumerate(headers) if is_raw_cost_label(header)
        ]
        if len(cost_indexes) > 1:
            raise CatalogImportError(
                "Найдено несколько колонок себестоимости; оставьте одну"
            )
        cost_index = cost_indexes[0] if cost_indexes else None

        rows: list[ParsedCatalogRow] = []
        issues: list[ImportIssue] = []
        sensitive_costs: dict[int, Decimal] = {}
        seen_skus: set[str] = set()
        seen_oe_rows: dict[str, ParsedCatalogRow] = {}
        blocked_oe_collisions: set[str] = set()
        total_rows = 0
        for source_row, values in enumerate(iterator, start=2):
            if source_row - 1 > MAX_ROWS:
                raise CatalogImportError(f"В XLSX больше {MAX_ROWS} строк")
            if not any(value not in (None, "") for value in values):
                continue
            total_rows += 1
            raw_row = {
                header: _json_safe(values[index] if index < len(values) else None)
                for index, header in enumerate(headers)
                if not is_raw_cost_label(header)
            }
            try:
                raw_cost = (
                    values[cost_index]
                    if cost_index is not None and cost_index < len(values)
                    else None
                )
                parsed_cost = _optional_unit_cost(raw_cost)
                if parsed_cost is not None and not allow_encrypted_cost_input:
                    raise SensitiveCatalogImportBlocked(
                        "Себестоимость заполнена, но защищённый серверный импорт не включён"
                    )
                parsed = _parse_row(source_row, values, resolved, raw_row)
                if parsed.sku in seen_skus:
                    raise CatalogImportError(f"Дублирующийся SKU: {parsed.sku}")
                seen_skus.add(parsed.sku)
                if parsed.oe_norm in blocked_oe_collisions:
                    issues.append(
                        ImportIssue(
                            source_row,
                            "NORMALIZED_OE_COLLISION",
                            "OE normalization collision requires manual review",
                        )
                    )
                    continue
                previous = seen_oe_rows.get(parsed.oe_norm)
                if previous is not None:
                    rows.remove(previous)
                    seen_oe_rows.pop(parsed.oe_norm, None)
                    blocked_oe_collisions.add(parsed.oe_norm)
                    issues.extend(
                        (
                            ImportIssue(
                                previous.source_row,
                                "NORMALIZED_OE_COLLISION",
                                "OE normalization collision requires manual review",
                            ),
                            ImportIssue(
                                source_row,
                                "NORMALIZED_OE_COLLISION",
                                "OE normalization collision requires manual review",
                            ),
                        )
                    )
                    continue
                seen_oe_rows[parsed.oe_norm] = parsed
                rows.append(parsed)
                if parsed_cost is not None:
                    sensitive_costs[source_row] = parsed_cost
            except SensitiveCatalogImportBlocked:
                raise
            except CatalogImportError as exc:
                issues.append(ImportIssue(source_row, "INVALID_ROW", str(exc)))
    finally:
        workbook.close()

    if total_rows == 0:
        raise CatalogImportError("В XLSX нет товарных строк")
    accepted_source_rows = {row.source_row for row in rows}
    column_mapping = {field: headers[index] for field, index in resolved.items()}
    if cost_index is not None:
        column_mapping["cost"] = headers[cost_index]
    return ParsedCatalog(
        rows=rows,
        issues=issues,
        column_mapping=column_mapping,
        total_rows=total_rows,
        sensitive_costs={
            row: value
            for row, value in sensitive_costs.items()
            if row in accepted_source_rows
        },
    )


def resolve_column_mapping(
    headers: list[str], explicit_mapping: dict[str, str] | None = None
) -> dict[str, int]:
    normalized_headers: dict[str, list[int]] = {}
    for index, header in enumerate(headers):
        normalized_headers.setdefault(_normalize_header(header), []).append(index)

    explicit = explicit_mapping or {}
    unknown_fields = set(explicit) - set(FIELD_ALIASES)
    if unknown_fields:
        raise CatalogImportError(
            "Неизвестные поля mapping: " + ", ".join(sorted(unknown_fields))
        )
    if "cost" in explicit:
        raise CatalogImportError(
            "Raw cost import is disabled until cost privacy mode is approved"
        )

    result = _prom_export_mapping(headers) if not explicit else {}
    for field, aliases in FIELD_ALIASES.items():
        if field in result:
            continue
        candidates = (explicit[field],) if field in explicit else aliases
        matched: list[int] = []
        for candidate in candidates:
            matched.extend(normalized_headers.get(_normalize_header(candidate), []))
        matched = sorted(set(matched))
        if len(matched) > 1:
            raise CatalogImportError(
                f"Колонка {field!r} определилась неоднозначно; передайте mapping явно"
            )
        if matched:
            result[field] = matched[0]
        elif field in explicit:
            raise CatalogImportError(
                f"Колонка {explicit[field]!r} для поля {field!r} не найдена"
            )

    missing = REQUIRED_FIELDS - set(result)
    if missing:
        raise CatalogImportError(
            "Не найдены обязательные колонки: " + ", ".join(sorted(missing))
        )
    return result


async def import_catalog_xlsx(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    filename: str,
    content: bytes,
    explicit_mapping: dict[str, str] | None = None,
    sheet_name: str | None = None,
    store_id: UUID | None = None,
    user_id: UUID,
    settings: Settings | None = None,
) -> CatalogImportBatch:
    """Parse and atomically persist one immutable catalog snapshot."""
    selected = settings or get_settings()
    allow_encrypted_cost_input = False
    if (
        CostPrivacyMode(selected.cost_privacy_mode)
        == CostPrivacyMode.SERVER_SIDE_ENCRYPTED
    ):
        try:
            selected.cost_keyring
        except ValueError:
            pass
        else:
            allow_encrypted_cost_input = True
    parsed = await asyncio.to_thread(
        parse_catalog_xlsx,
        content,
        explicit_mapping=explicit_mapping,
        sheet_name=sheet_name,
        allow_encrypted_cost_input=allow_encrypted_cost_input,
    )
    if parsed.sensitive_costs:
        try:
            require_server_cost_input_allowed(
                next(iter(parsed.sensitive_costs.values())), settings=selected
            )
        except RuntimeError as exc:
            raise CatalogImportError(
                "Защищённый импорт себестоимости недоступен"
            ) from exc
    now = datetime.now(UTC)
    batch = CatalogImportBatch(
        workspace_id=workspace_id,
        filename=filename[:255] or "catalog.xlsx",
        content_sha256=hashlib.sha256(content).hexdigest(),
        content_size=len(content),
        status="running",
        column_mapping=parsed.column_mapping,
        total_rows=parsed.total_rows,
        imported_rows=len(parsed.rows),
        rejected_rows=len(parsed.issues),
        error_log=[asdict(issue) for issue in parsed.issues[:MAX_ERROR_LOG]],
        started_at=now,
    )
    session.add(batch)
    await session.flush()
    items = [
        CatalogItem(
            workspace_id=workspace_id,
            import_batch_id=batch.id,
            store_id=store_id,
            **asdict(row),
        )
        for row in parsed.rows
    ]
    session.add_all(items)
    await session.flush()
    for item, row in zip(items, parsed.rows, strict=True):
        cost = parsed.sensitive_costs.get(row.source_row)
        if cost is not None:
            add_encrypted_cost_record(
                session,
                workspace_id=workspace_id,
                catalog_item_id=item.id,
                user_id=user_id,
                cost=cost,
                reason=f"encrypted XLSX import row {row.source_row}",
                settings=selected,
            )
    batch.status = (
        "failed" if not parsed.rows else "partial" if parsed.issues else "completed"
    )
    batch.finished_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(batch)
    return batch


async def get_import_batch(
    session: AsyncSession, *, workspace_id: UUID, batch_id: UUID
) -> CatalogImportBatch | None:
    return await session.scalar(
        select(CatalogImportBatch).where(
            CatalogImportBatch.id == batch_id,
            CatalogImportBatch.workspace_id == workspace_id,
        )
    )


async def list_import_batches(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    limit: int,
    offset: int,
) -> tuple[list[CatalogImportBatch], int]:
    where = CatalogImportBatch.workspace_id == workspace_id
    total = int(
        await session.scalar(select(func.count(CatalogImportBatch.id)).where(where))
        or 0
    )
    batches = list(
        (
            await session.scalars(
                select(CatalogImportBatch)
                .where(where)
                .order_by(
                    CatalogImportBatch.created_at.desc(), CatalogImportBatch.id.desc()
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return batches, total


async def list_catalog_items(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    batch_id: UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[CatalogItem], int]:
    conditions = [CatalogItem.workspace_id == workspace_id]
    if batch_id is not None:
        conditions.append(CatalogItem.import_batch_id == batch_id)
    total = int(
        await session.scalar(select(func.count(CatalogItem.id)).where(*conditions)) or 0
    )
    items = list(
        (
            await session.scalars(
                select(CatalogItem)
                .where(*conditions)
                .order_by(CatalogItem.source_row, CatalogItem.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return items, total


def parse_mapping_json(value: str | None) -> dict[str, str] | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CatalogImportError("mapping должен быть JSON-объектом") from exc
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in parsed.items()
    ):
        raise CatalogImportError("mapping должен содержать пары строка-строка")
    return parsed


def _parse_row(
    source_row: int,
    values: tuple[Any, ...],
    mapping: dict[str, int],
    raw_row: dict[str, Any],
) -> ParsedCatalogRow:
    def get(field: str) -> Any:
        index = mapping.get(field)
        return values[index] if index is not None and index < len(values) else None

    oe_raw = _cell_text(get("oe"))
    oe_norm = normalize_identifier(oe_raw)
    if len(oe_norm) < 3:
        raise CatalogImportError("пустой или невалидный OE/OEM")
    if len(oe_norm) > 255:
        raise CatalogImportError("OE/OEM длиннее 255 символов")
    name = _required_text(get("name"), "название")
    category = _required_text(get("category"), "категория")[:255]
    price = _positive_decimal(get("price"), "цена")
    sku = _cell_text(get("sku")) or f"OE-{oe_norm}-{source_row}"
    if len(sku) > 255:
        raise CatalogImportError("SKU длиннее 255 символов")
    mpn_raw = _cell_text(get("mpn"))
    currency = _normalize_currency(get("currency"))
    stock_qty = _optional_nonnegative_decimal(get("stock_qty"), "остаток")
    stock_age = _optional_nonnegative_decimal(get("stock_age_days"), "возраст запаса")
    expected = _optional_nonnegative_decimal(get("expected_units_sold"), "продажи")
    units_sold_30d = _optional_nonnegative_decimal(
        get("units_sold_30d"), "продажи за 30 дней"
    )
    units_sold_60d = _optional_nonnegative_decimal(
        get("units_sold_60d"), "продажи за 60 дней"
    )
    units_sold_90d = _optional_nonnegative_decimal(
        get("units_sold_90d"), "продажи за 90 дней"
    )
    days_since_last_sale = _optional_nonnegative_decimal(
        get("days_since_last_sale"), "дней с последней продажи"
    )
    historical_monthly_units = _optional_nonnegative_decimal(
        get("historical_monthly_units"), "средние продажи в месяц"
    )
    views_30d = _optional_nonnegative_decimal(get("views_30d"), "просмотры за 30 дней")
    conversion_rate_proxy = _optional_ratio(get("conversion_rate_proxy"), "конверсия")
    priority = _optional_positive_decimal(
        get("manual_priority"), "приоритет"
    ) or Decimal("1")
    product_url = _optional_text(get("product_url"))
    if product_url and not product_url.casefold().startswith(("https://", "http://")):
        raise CatalogImportError(
            "ссылка на товар должна начинаться с http:// или https://"
        )
    return ParsedCatalogRow(
        source_row=source_row,
        sku=sku,
        oe_raw=oe_raw,
        oe_norm=oe_norm,
        mpn_raw=mpn_raw,
        mpn_norm=normalize_identifier(mpn_raw),
        name=name,
        category=category,
        brand=_optional_text(get("brand"), max_length=255),
        description=_optional_text(get("description")),
        product_url=product_url,
        current_price=price,
        currency=currency,
        is_available=_optional_bool(get("available")),
        stock_status=_stock_status(get("stock_status")),
        stock_qty=stock_qty,
        stock_age_days=stock_age,
        expected_units_sold=expected,
        units_sold_30d=units_sold_30d,
        units_sold_60d=units_sold_60d,
        units_sold_90d=units_sold_90d,
        days_since_last_sale=days_since_last_sale,
        historical_monthly_units=historical_monthly_units,
        views_30d=views_30d,
        conversion_rate_proxy=conversion_rate_proxy,
        cost=None,
        manual_priority=priority,
        raw_row=raw_row,
    )


def _prom_export_mapping(headers: list[str]) -> dict[str, int]:
    """Recognize Yuri's canonical Prom.ua export without an explicit JSON map."""
    exact = {_normalize_header(header): index for index, header in enumerate(headers)}
    required = {
        "sku": "унікальний ідентифікатор",
        "oe": "код товару",
        "name": "назва позиції",
        "category": "назва групи",
        "price": "ціна",
    }
    if not all(header in exact for header in required.values()):
        return {}
    optional = {
        "mpn": "номер пристрою mpn",
        "currency": "валюта",
        "available": "наявність",
        "brand": "виробник",
        "description": "опис",
        "product_url": "продукт на сайті",
        "stock_qty": "кількість",
    }
    result = {field: exact[header] for field, header in required.items()}
    result.update(
        {field: exact[header] for field, header in optional.items() if header in exact}
    )
    return result


def _unique_headers(values: tuple[Any, ...]) -> list[str]:
    result: list[str] = []
    seen: dict[str, int] = {}
    for index, value in enumerate(values, start=1):
        base = _cell_text(value) or f"column_{index}"
        count = seen.get(base, 0) + 1
        seen[base] = count
        result.append(base if count == 1 else f"{base}#{count}")
    return result


def _normalize_header(value: str) -> str:
    return _HEADER_CLEAN_RE.sub(" ", value.casefold().replace("_", " ")).strip()


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, ".15g")
    return str(value).strip()


def _required_text(value: Any, label: str) -> str:
    normalized = _cell_text(value)
    if not normalized:
        raise CatalogImportError(f"пустое поле: {label}")
    return normalized


def _optional_text(value: Any, *, max_length: int | None = None) -> str | None:
    normalized = _cell_text(value)
    if not normalized:
        return None
    return normalized[:max_length] if max_length else normalized


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise CatalogImportError(f"невалидное число: {label}")
    if isinstance(value, (int, float, Decimal)):
        raw = str(value)
    else:
        raw = _cell_text(value).replace("\u00a0", "").replace(" ", "")
        raw = re.sub(r"(?i)(uah|грн|гривен|гривня|₴)", "", raw)
        if "," in raw and "." in raw:
            if raw.rfind(",") > raw.rfind("."):
                raw = raw.replace(".", "").replace(",", ".")
            else:
                raw = raw.replace(",", "")
        elif "," in raw:
            raw = raw.replace(",", ".")
    try:
        result = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise CatalogImportError(f"невалидное число: {label}") from exc
    if not result.is_finite():
        raise CatalogImportError(f"невалидное число: {label}")
    return result


def _positive_decimal(value: Any, label: str) -> Decimal:
    result = _decimal(value, label)
    if result <= 0:
        raise CatalogImportError(f"{label} должна быть > 0")
    return result.quantize(Decimal("0.01"))


def _optional_positive_decimal(value: Any, label: str) -> Decimal | None:
    if value is None or not _cell_text(value):
        return None
    return _positive_decimal(value, label)


def _optional_nonnegative_decimal(value: Any, label: str) -> Decimal | None:
    if value is None or not _cell_text(value):
        return None
    result = _decimal(value, label)
    if result < 0:
        raise CatalogImportError(f"{label} не может быть отрицательным")
    return result


def _optional_ratio(value: Any, label: str) -> Decimal | None:
    result = _optional_nonnegative_decimal(value, label)
    if result is not None and result > 1:
        raise CatalogImportError(f"{label} должна быть от 0 до 1")
    return result


def _optional_unit_cost(value: Any) -> Decimal | None:
    if value is None or not _cell_text(value):
        return None
    result = _decimal(value, "себестоимость")
    if result <= 0:
        raise CatalogImportError("себестоимость должна быть > 0")
    if result.as_tuple().exponent < -2:
        raise CatalogImportError("себестоимость поддерживает не более 2 знаков")
    if result >= Decimal("1000000000000"):
        raise CatalogImportError("себестоимость выше допустимого диапазона")
    return result.quantize(Decimal("0.01"))


def _normalize_currency(value: Any) -> str:
    raw = _cell_text(value).casefold()
    if not raw or raw in {"uah", "грн", "₴", "гривня", "гривень"}:
        return "UAH"
    normalized = raw.upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise CatalogImportError("валюта должна быть ISO-4217 кодом")
    return normalized


def _optional_bool(value: Any) -> bool | None:
    if value is None or not _cell_text(value):
        return None
    if isinstance(value, bool):
        return value
    raw = _cell_text(value).casefold()
    if raw in {
        "1",
        "true",
        "yes",
        "y",
        "да",
        "так",
        "есть",
        "в наличии",
        "в наявності",
        "available",
        "+",
        "!",
    }:
        return True
    if raw in {
        "0",
        "false",
        "no",
        "n",
        "нет",
        "ні",
        "нет в наличии",
        "немає",
        "unavailable",
        "-",
    }:
        return False
    raise CatalogImportError("неизвестное значение наличия")


def _stock_status(value: Any) -> str:
    raw = _cell_text(value).casefold().replace("-", "_").replace(" ", "_")
    if not raw:
        return "unknown"
    aliases = {
        "fresh": "fresh",
        "свежий": "fresh",
        "свіжий": "fresh",
        "ходовой": "fresh",
        "stale": "stale",
        "лежалый": "stale",
        "залежалый": "stale",
        "залежалий": "stale",
        "dead_stock": "dead_stock",
        "deadstock": "dead_stock",
        "неликвид": "dead_stock",
        "неліквід": "dead_stock",
        "unknown": "unknown",
        "неизвестно": "unknown",
    }
    try:
        return aliases[raw]
    except KeyError as exc:
        raise CatalogImportError(
            "статус должен быть fresh/stale/dead_stock/unknown"
        ) from exc


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


__all__ = [
    "CatalogImportError",
    "ImportIssue",
    "ParsedCatalog",
    "ParsedCatalogRow",
    "SensitiveCatalogImportBlocked",
    "get_import_batch",
    "import_catalog_xlsx",
    "list_catalog_items",
    "list_import_batches",
    "normalize_identifier",
    "parse_catalog_xlsx",
    "parse_mapping_json",
    "resolve_column_mapping",
]
