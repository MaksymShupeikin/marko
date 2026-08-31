"""Read a Prom.ua XLSX catalog export into Products.

Prom exports one row per offer with Ukrainian headers and a tail of repeating
``Назва_Характеристики`` / ``Значення_Характеристики`` column triplets. Part
numbers live in several of those places, so every candidate is collected: the
avto.pro price check tries them in order.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit, urlunsplit
from zipfile import BadZipFile, ZipFile

import openpyxl

from marko.services.parser_models import Product, Seller

PRODUCTS_SHEET = "Export Products Sheet"

# Headers holding a part number, in the order we prefer to search them.
_OEM_HEADERS = ("Код_товару", "Номер_пристрою_(MPN)")
_OEM_CHARACTERISTICS = ("Код запчастини", "Кросс-номери")
_CHARACTERISTIC_NAME = "Назва_Характеристики"
_CHARACTERISTIC_VALUE = "Значення_Характеристики"

_MIN_OEM_LENGTH = 4  # shorter tokens are truncation noise, not part numbers
_SELLER_HOST_RE = re.compile(
    r"^(?P<slug>[\w-]+?)-cs(?P<company_id>\d+)\.prom\.ua$", re.IGNORECASE
)
_PRODUCT_PATH_RE = re.compile(r"^/(?:[a-z]{2}/)?(?P<slug>p\d+-[^/]+)$", re.IGNORECASE)
_MARKETPLACE_PRODUCT_HOSTS = frozenset({"prom.ua", "www.prom.ua"})


class ExportFormatError(ValueError):
    """The workbook is not a Prom catalog export."""


def seller_from_export_url(url: str | None) -> Seller | None:
    """Seller behind a per-product export URL (``kemp-cs2847093.prom.ua/p...``)."""
    match = _SELLER_HOST_RE.fullmatch(urlsplit(url or "").hostname or "")
    if match is None:
        return None
    return Seller(
        company_id=match.group("company_id"),
        slug=match.group("slug").lower(),
        lang="ua",
    )


def is_export_url(url: str | None) -> bool:
    """True for the seller-subdomain link an XLSX export carries."""
    return seller_from_export_url(url) is not None


def canonical_product_url(url: str | None) -> str:
    """Marketplace link for a product, given either link shape.

    A seller's own shop page renders without ``window.ApolloCacheState``, so
    the parser cannot read it; the same product on prom.ua parses fine.
    """
    text = (url or "").strip()
    if not text:
        return ""
    parsed = urlsplit(text)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Некоректний порт у посиланні товару Prom") from exc
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
    ):
        raise ValueError("Дозволені лише звичайні HTTP(S)-посилання товарів Prom")

    match = _PRODUCT_PATH_RE.fullmatch(parsed.path)
    if match is None:
        raise ValueError("Некоректний шлях товару Prom")
    if is_export_url(text):
        return f"https://prom.ua/ua/{match.group('slug')}"
    if (parsed.hostname or "").casefold() not in _MARKETPLACE_PRODUCT_HOSTS:
        raise ValueError("Оновлення дозволене лише з prom.ua")
    return urlunsplit(("https", "prom.ua", parsed.path, "", ""))


_PRICE_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def parse_price(value: object) -> Decimal | None:
    """Число з цінового рядка ("1 234,56 грн") як Decimal, або None."""
    if value is None:
        return None
    normalized = str(value).replace("\u00a0", "").replace(" ", "").replace(",", ".")
    match = _PRICE_NUMBER_RE.search(normalized)
    if match is None:
        return None
    try:
        return Decimal(match.group()).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def normalize_oem(value: object) -> str | None:
    """Uppercase part number without separators, or None when unusable."""
    token = re.sub(r"[\s ]+", "", str(value or "")).upper()
    if len(token) < _MIN_OEM_LENGTH or not any(char.isalnum() for char in token):
        return None
    return token


def _split_oem_list(value: object) -> list[str]:
    return [str(part) for part in str(value or "").split(",")]


class _RowReader:
    """Maps header names to column indexes; headers repeat, so keep them all."""

    def __init__(self, headers: list[object]) -> None:
        self._columns: dict[str, list[int]] = {}
        for index, header in enumerate(headers):
            if header is not None:
                self._columns.setdefault(str(header).strip(), []).append(index)
        missing = [name for name in ("Код_товару", "Ціна") if name not in self._columns]
        if missing:
            raise ExportFormatError(
                f"Не схоже на експорт каталогу Prom: немає колонок {missing}"
            )

    def value(self, row: tuple, header: str) -> object:
        for index in self._columns.get(header, ()):
            if index < len(row) and row[index] not in (None, ""):
                return row[index]
        return None

    def characteristics(self, row: tuple) -> dict[str, object]:
        names = self._columns.get(_CHARACTERISTIC_NAME, ())
        values = self._columns.get(_CHARACTERISTIC_VALUE, ())
        found: dict[str, object] = {}
        for name_index, value_index in zip(names, values):
            if name_index >= len(row) or value_index >= len(row):
                continue
            name, value = row[name_index], row[value_index]
            if name and value:
                found.setdefault(str(name).strip(), value)
        return found


def _oem_numbers(
    reader: _RowReader, row: tuple, characteristics: dict
) -> tuple[str, ...]:
    raw: list[object] = [reader.value(row, header) for header in _OEM_HEADERS]
    for name in _OEM_CHARACTERISTICS:
        raw.extend(_split_oem_list(characteristics.get(name)))
    numbers = dict.fromkeys(filter(None, map(normalize_oem, raw)))
    return tuple(numbers)


def _product(reader: _RowReader, row: tuple) -> Product | None:
    external_id = reader.value(row, "Унікальний_ідентифікатор")
    name = reader.value(row, "Назва_позиції_укр") or reader.value(row, "Назва_позиції")
    url = reader.value(row, "Продукт_на_сайті")
    if external_id is None or not name or not url:
        return None
    try:
        product_id = int(str(external_id).strip())
    except ValueError:
        return None

    characteristics = reader.characteristics(row)
    available = str(reader.value(row, "Наявність") or "").strip() != "-"
    sku = reader.value(row, "Код_товару")
    return Product(
        id=product_id,
        name=str(name).strip(),
        sku=None if sku is None else str(sku).strip(),
        price=None if (price := reader.value(row, "Ціна")) is None else str(price),
        price_original=None,
        discounted_price=None,
        has_discount=None,
        currency=str(reader.value(row, "Валюта") or "UAH"),
        price_usd=None,
        presence="available" if available else "not_available",
        is_available=available,
        measure_unit=_text(reader.value(row, "Одиниця_виміру")),
        category_id=None,
        brand=_text(reader.value(row, "Виробник")),
        model_id=None,
        seller_id=None,
        seller_name=None,
        seller_slug=None,
        opinions_count=None,
        opinions_rating=None,
        image=_text(reader.value(row, "Посилання_зображення")),
        url_text=None,
        url=str(url).strip(),
        oem_numbers=_oem_numbers(reader, row, characteristics),
    )


def _text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def validate_export_archive(
    content: bytes,
    *,
    max_uncompressed_bytes: int,
    max_entries: int = 5_000,
) -> None:
    """Reject malformed, encrypted, or decompression-bomb XLSX containers."""
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > max_entries:
                raise ExportFormatError("У файлі .xlsx забагато внутрішніх частин")
            total = 0
            for entry in entries:
                if entry.flag_bits & 0x1:
                    raise ExportFormatError("Зашифровані .xlsx файли не підтримуються")
                total += entry.file_size
                if total > max_uncompressed_bytes:
                    raise ExportFormatError(
                        "Розпакований .xlsx перевищує безпечний ліміт"
                    )
            names = {entry.filename for entry in entries}
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                raise ExportFormatError("Файл не є коректною книгою .xlsx")
    except BadZipFile as exc:
        raise ExportFormatError("Файл не є коректним архівом .xlsx") from exc


def parse_export(
    source: str | Path | BinaryIO,
    *,
    max_rows: int | None = None,
) -> Iterator[Product]:
    """Yield products from a Prom XLSX export, skipping unusable rows."""
    try:
        workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises zipfile/XML errors for bad input
        raise ExportFormatError(f"Не вдалось прочитати файл .xlsx: {exc}") from exc
    try:
        sheet_name = (
            PRODUCTS_SHEET
            if PRODUCTS_SHEET in workbook.sheetnames
            else workbook.sheetnames[0]
        )
        rows = workbook[sheet_name].iter_rows(values_only=True)
        try:
            reader = _RowReader(list(next(rows)))
        except StopIteration:
            raise ExportFormatError("Порожній файл експорту") from None
        for row_number, row in enumerate(rows, start=2):
            if max_rows is not None and row_number - 1 > max_rows:
                raise ExportFormatError(
                    f"Файл містить більше {max_rows} рядків товарів"
                )
            if all(cell is None for cell in row):
                continue
            product = _product(reader, row)
            if product is not None:
                yield product
    finally:
        workbook.close()


def seller_of(products: list[Product]) -> Seller | None:
    """Seller the export belongs to, taken from the first parseable URL."""
    found: Seller | None = None
    for product in products:
        seller = seller_from_export_url(product.url)
        if seller is None:
            raise ExportFormatError(
                "Експорт містить посилання не з магазину продавця Prom"
            )
        if found is not None and seller.company_id != found.company_id:
            raise ExportFormatError("Експорт змішує товари різних магазинів Prom")
        found = seller
    return found


__all__ = [
    "ExportFormatError",
    "normalize_oem",
    "parse_export",
    "parse_price",
    "seller_from_export_url",
    "seller_of",
    "validate_export_archive",
]
