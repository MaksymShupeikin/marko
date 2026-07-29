#!/usr/bin/env python3
"""Deterministic, network-free WP-0 measurement of catalog identity coverage.

Answers one question with numbers instead of assumptions: which columns of the
Prom export actually carry product identity (cross numbers, applicability), how
much of it the importer currently drops, and how far the KEMP reference map
closes the remaining gap.

Normalization is reproduced literally from the repository so the measurement
cannot drift from production behaviour:

    _normalize_header / normalize_identifier
        backend/src/marko/services/xlsx_catalog.py:42-44, 258-262
    normalize_cross_oem
        backend/src/metis/pricing/crosses.py:457-463

Reading the ``.xls`` reference map requires ``xlrd``; the ``.xlsx`` export is
read with ``openpyxl``, already a backend dependency.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
from typing import Any
import unicodedata

import openpyxl

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

PROM_REQUIRED = {
    "sku": "унікальний ідентифікатор",
    "oe": "код товару",
    "name": "назва позиції",
    "category": "назва групи",
    "price": "ціна",
}
PROM_OPTIONAL = {
    "mpn": "номер пристрою mpn",
    "currency": "валюта",
    "available": "наявність",
    "brand": "виробник",
    "description": "опис",
    "product_url": "продукт на сайті",
    "stock_qty": "кількість",
}

# Colonne "фирма по артикулу" values that denote a vehicle manufacturer, i.e.
# an article that is a genuine OE number rather than an aftermarket article.
VEHICLE_MANUFACTURERS = frozenset(
    {
        "VAG",
        "General Motors",
        "Mercedes",
        "Ford",
        "Renault (RVI)",
        "Opel",
        "Peugeot/Citroen",
        "Fiat/Alfa/Lancia",
        "Chery",
        "BMW",
        "Nissan",
        "Mitsubishi",
        "Evobus/Setra",
    }
)

CROSS_CHARACTERISTICS = ("Код запчастини", "Кросс-номери")
BRAND_CHARACTERISTIC = "Сумісність з маркою"
MODEL_CHARACTERISTICS = ("Сумісність з моделлю",)


def cell_text(value: Any) -> str:
    """Mirror ``_cell_text`` so numeric cells never gain a spurious ``.0``."""

    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, ".15g")
    return str(value).strip()


def normalize_header(value: str) -> str:
    return _HEADER_CLEAN_RE.sub(" ", value.casefold().replace("_", " ")).strip()


def normalize_identifier(value: Any) -> str:
    raw = cell_text(value).upper().translate(_HOMOGLYPHS)
    primary = _IDENTIFIER_SPLIT_RE.split(raw, maxsplit=1)[0]
    return _IDENTIFIER_CLEAN_RE.sub("", primary)


def normalize_cross_oem(value: Any) -> str:
    if not value:
        return ""
    return re.sub(r"[^A-Z0-9]", "", unicodedata.normalize("NFKC", str(value)).upper())


def load_prom(path: str) -> tuple[list[str], list[list[Any]]]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.worksheets[0]
    stream = sheet.iter_rows(values_only=True)
    headers = [cell_text(value) for value in next(stream)]
    return headers, [list(row) for row in stream]


def load_kemp(path: str) -> list[list[str]]:
    import xlrd  # imported lazily: only this legacy .xls path needs it

    sheet = xlrd.open_workbook(path).sheet_by_index(0)
    return [
        [str(value).replace("\xa0", " ").strip() for value in sheet.row_values(row)]
        for row in range(1, sheet.nrows)
    ]


def characteristic_pairs(headers: list[str]) -> list[tuple[int, int]]:
    """Locate every ``Назва / Одиниця / Значення`` triple by header, not index."""

    names = [
        index
        for index, header in enumerate(headers)
        if normalize_header(header).startswith("назва характеристики")
    ]
    values = [
        index
        for index, header in enumerate(headers)
        if normalize_header(header).startswith("значення характеристики")
    ]
    return list(zip(names, values))


def row_characteristics(
    row: list[Any], pairs: list[tuple[int, int]]
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for name_index, value_index in pairs:
        name = cell_text(row[name_index]) if name_index < len(row) else ""
        value = cell_text(row[value_index]) if value_index < len(row) else ""
        if name:
            result.setdefault(name, []).append(value)
    return result


def measure(prom_path: str, kemp_path: str) -> dict[str, Any]:
    headers, rows = load_prom(prom_path)
    normalized: dict[str, list[int]] = {}
    for index, header in enumerate(headers):
        normalized.setdefault(normalize_header(header), []).append(index)

    missing = [key for key, header in PROM_REQUIRED.items() if header not in normalized]
    resolved: dict[str, int] = {}
    if not missing:
        resolved = {key: normalized[header][0] for key, header in PROM_REQUIRED.items()}
        resolved.update(
            {
                key: normalized[header][0]
                for key, header in PROM_OPTIONAL.items()
                if header in normalized
            }
        )

    pairs = characteristic_pairs(headers)
    kemp_rows = load_kemp(kemp_path)
    by_number = {normalize_cross_oem(row[1]): row for row in kemp_rows if row[1]}
    by_article: dict[str, list[list[str]]] = collections.defaultdict(list)
    for row in kemp_rows:
        if row[3]:
            by_article[normalize_cross_oem(row[3])].append(row)

    def field(row: list[Any], key: str) -> str:
        index = resolved.get(key)
        return cell_text(row[index]) if index is not None and index < len(row) else ""

    report: dict[str, Any] = {
        "prom_rows": len(rows),
        "prom_columns": len(headers),
        "prom_columns_read_by_importer": len(resolved),
        "prom_mapping_missing_required": missing,
        "prom_resolved_columns": {key: headers[i] for key, i in resolved.items()},
        "kemp_rows": len(kemp_rows),
        "kemp_unique_numbers": len(by_number),
    }

    names = collections.Counter()
    cross_extra_total = 0
    products_with_extra = 0
    brands = collections.Counter()
    models = collections.Counter()
    products_with_brand = 0
    products_with_model = 0
    article_kind = collections.Counter()
    code_shape = collections.Counter()
    internal_unresolved: list[str] = []
    description_with_table = 0

    for row in rows:
        chars = row_characteristics(row, pairs)
        for name in chars:
            names[name] += 1

        code = field(row, "oe")
        code_norm = normalize_cross_oem(code)
        code_shape[
            "internal_776"
            if code.startswith("776")
            else "digits"
            if code.isdigit()
            else "alphanumeric"
        ] += 1
        if code.startswith("776") and code_norm not in by_number:
            internal_unresolved.append(code)

        graph = {code_norm} if code_norm else set()
        for characteristic in CROSS_CHARACTERISTICS:
            for value in chars.get(characteristic, []):
                for token in re.split(r"[,;]", value):
                    token_norm = normalize_cross_oem(token)
                    if token_norm:
                        graph.add(token_norm)
        extra = len(graph - {code_norm})
        cross_extra_total += extra
        products_with_extra += 1 if extra else 0

        brand_values = chars.get(BRAND_CHARACTERISTIC, [])
        if any(value for value in brand_values):
            products_with_brand += 1
        for value in brand_values:
            for part in value.split("|"):
                if part.strip():
                    brands[part.strip()] += 1
        model_seen = False
        for characteristic in MODEL_CHARACTERISTICS:
            for value in chars.get(characteristic, []):
                if value:
                    model_seen = True
                for part in value.split("|"):
                    if part.strip():
                        models[part.strip()] += 1
        products_with_model += 1 if model_seen else 0

        matched = None
        for candidate in sorted(graph):
            if candidate in by_article:
                matched = by_article[candidate][0]
                break
            if candidate in by_number:
                matched = by_number[candidate]
                break
        if matched is None:
            article_kind["NO_KEMP_MATCH"] += 1
        else:
            article_kind[
                "OE" if matched[4] in VEHICLE_MANUFACTURERS else "AFTERMARKET"
            ] += 1

        if "<table" in field(row, "description").lower():
            description_with_table += 1

    shared_article = {
        article: len({row[1] for row in matches})
        for article, matches in by_article.items()
        if len({row[1] for row in matches}) > 1
    }

    report.update(
        {
            "characteristic_names": names.most_common(40),
            "cross_extra_numbers_total": cross_extra_total,
            "products_with_extra_number": products_with_extra,
            "products_with_applicability_brand": products_with_brand,
            "products_with_applicability_model": products_with_model,
            "distinct_brands": len(brands),
            "brands": brands.most_common(),
            "distinct_models": len(models),
            "models_top": models.most_common(25),
            "code_shape": code_shape.most_common(),
            "internal_776_unresolved_count": len(internal_unresolved),
            "internal_776_unresolved": sorted(internal_unresolved)[:40],
            "article_kind_via_kemp": article_kind.most_common(),
            "descriptions_with_table": description_with_table,
            "kemp_shared_article_fanout": len(shared_article),
            "kemp_shared_article_max": max(shared_article.values(), default=0),
        }
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prom", required=True, help="Prom catalog export .xlsx")
    parser.add_argument("--kemp", required=True, help="KEMP reference map .xls")
    parser.add_argument("--out", help="write JSON here instead of stdout")
    arguments = parser.parse_args()

    report = measure(arguments.prom, arguments.kemp)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if arguments.out:
        with open(arguments.out, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    else:
        print(payload)


if __name__ == "__main__":
    main()
