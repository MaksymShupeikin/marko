from io import BytesIO

import pytest
from openpyxl import Workbook

from marko.services.xlsx_catalog import (
    CatalogImportError,
    normalize_identifier,
    parse_catalog_xlsx,
    parse_mapping_json,
)


def workbook_bytes(headers, rows):
    stream = BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def test_parses_prom_headers_and_preserves_raw_row():
    content = workbook_bytes(
        [
            "Артикул",
            "OEM номер",
            "Название_позиции",
            "Название_группы",
            "Цена",
            "Наличие",
            "Статус товара",
            "Ссылка",
        ],
        [
            [
                "0007",
                "06А 115-105 B",
                "Фильтр",
                "Фильтры",
                "1 234,50 грн",
                "В наличии",
                "лежалый",
                "https://prom.ua/ua/p1-x.html",
            ]
        ],
    )

    parsed = parse_catalog_xlsx(content)

    assert parsed.total_rows == 1
    assert parsed.issues == []
    row = parsed.rows[0]
    assert row.sku == "0007"
    assert row.oe_raw == "06А 115-105 B"
    assert row.oe_norm == "06A115105B"
    assert str(row.current_price) == "1234.50"
    assert row.currency == "UAH"
    assert row.is_available is True
    assert row.stock_status == "stale"
    assert row.raw_row["OEM номер"] == "06А 115-105 B"


def test_rejects_bad_rows_without_losing_valid_rows():
    content = workbook_bytes(
        ["OE", "Name", "Category", "Price"],
        [
            ["ABC-001", "Good", "Filters", 100],
            [None, "No OE", "Filters", 100],
            ["ABC-003", "Zero", "Filters", 0],
        ],
    )

    parsed = parse_catalog_xlsx(content)

    assert [row.oe_norm for row in parsed.rows] == ["ABC001"]
    assert [issue.row for issue in parsed.issues] == [3, 4]


def test_explicit_mapping_supports_nonstandard_export():
    content = workbook_bytes(
        ["A", "B", "C", "D"],
        [["0123", "Part", "Brakes", "850,00"]],
    )

    parsed = parse_catalog_xlsx(
        content,
        explicit_mapping={"oe": "A", "name": "B", "category": "C", "price": "D"},
    )

    assert parsed.rows[0].oe_norm == "0123"
    assert parsed.rows[0].sku == "OE-0123-2"


def test_cost_is_manual_by_default_but_can_be_mapped_explicitly():
    content = workbook_bytes(
        ["OE", "Name", "Category", "Price", "Себестоимость"],
        [["A001", "Part", "Filters", 850, 600]],
    )

    automatic = parse_catalog_xlsx(content)
    explicit = parse_catalog_xlsx(
        content,
        explicit_mapping={"cost": "Себестоимость"},
    )

    assert automatic.rows[0].cost is None
    assert "cost" not in automatic.column_mapping
    assert explicit.rows[0].cost == 600


def test_missing_required_columns_is_a_workbook_error():
    content = workbook_bytes(["Name", "Price"], [["Part", 100]])

    with pytest.raises(CatalogImportError, match="category, oe"):
        parse_catalog_xlsx(content)


def test_duplicate_sku_is_rejected_as_a_row_error():
    content = workbook_bytes(
        ["SKU", "OE", "Name", "Category", "Price"],
        [["same", "A001", "One", "X", 10], ["same", "A002", "Two", "X", 20]],
    )

    parsed = parse_catalog_xlsx(content)

    assert len(parsed.rows) == 1
    assert parsed.issues[0].row == 3
    assert "SKU" in parsed.issues[0].message


def test_identifier_and_mapping_json_validation():
    assert normalize_identifier("  000-АХ  ") == "000AX"
    assert parse_mapping_json('{"oe":"Custom OE"}') == {"oe": "Custom OE"}
    with pytest.raises(CatalogImportError):
        parse_mapping_json("[]")
