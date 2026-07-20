import base64
from io import BytesIO
import json
from uuid import uuid4

import pytest
from openpyxl import Workbook

from marko.core.config import Settings
from marko.infrastructure.db.models import CatalogItem, CatalogItemCostRecord
from marko.services.xlsx_catalog import (
    CatalogImportError,
    SensitiveCatalogImportBlocked,
    import_catalog_xlsx,
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


def test_cost_fails_closed_without_encryption_and_never_enters_raw_row():
    blank_content = workbook_bytes(
        ["OE", "Name", "Category", "Price", "Себестоимость"],
        [["A001", "Part", "Filters", 850, None]],
    )
    automatic = parse_catalog_xlsx(blank_content)

    assert automatic.rows[0].cost is None
    assert automatic.sensitive_costs == {}
    assert "Себестоимость" not in automatic.rows[0].raw_row

    content = workbook_bytes(
        ["OE", "Name", "Category", "Price", "Себестоимость"],
        [["A001", "Part", "Filters", 850, 600]],
    )

    with pytest.raises(SensitiveCatalogImportBlocked) as error:
        parse_catalog_xlsx(content)
    assert "600" not in str(error.value)

    encrypted = parse_catalog_xlsx(content, allow_encrypted_cost_input=True)
    assert encrypted.rows[0].cost is None
    assert encrypted.sensitive_costs == {2: 600}
    assert encrypted.column_mapping["cost"] == "Себестоимость"
    assert "Себестоимость" not in encrypted.rows[0].raw_row
    with pytest.raises(CatalogImportError, match="privacy mode"):
        parse_catalog_xlsx(
            content,
            explicit_mapping={"cost": "Себестоимость"},
            allow_encrypted_cost_input=True,
        )


def test_canonical_prom_export_uses_unique_product_id_as_sku_and_code_as_oe():
    content = workbook_bytes(
        [
            "Код_товару",
            "Назва_позиції",
            "Ціна",
            "Валюта",
            "Наявність",
            "Кількість",
            "Назва_групи",
            "Унікальний_ідентифікатор",
            "Виробник",
            "Опис",
            "Продукт_на_сайті",
            "Номер_пристрою_(MPN)",
        ],
        [
            [
                "056121113D",
                "Термостат",
                175,
                "UAH",
                "!",
                22,
                "Охлаждение",
                "1153724211",
                "KEMP",
                "Описание",
                "https://example.test/p1153724211.html",
                "056121113D",
            ]
        ],
    )

    parsed = parse_catalog_xlsx(content)

    assert parsed.issues == []
    row = parsed.rows[0]
    assert row.sku == "1153724211"
    assert row.oe_raw == "056121113D"
    assert row.mpn_raw == "056121113D"
    assert row.is_available is True
    assert row.stock_qty == 22
    assert row.product_url == "https://example.test/p1153724211.html"


def test_parses_bulk_manual_sales_context_columns():
    content = workbook_bytes(
        [
            "SKU",
            "OE",
            "Name",
            "Category",
            "Price",
            "Продажи за 30 дней",
            "Продажи за 60 дней",
            "Продажи за 90 дней",
            "Дней с последней продажи",
            "Средние продажи в месяц",
            "План продаж в месяц",
            "Просмотры за 30 дней",
            "Конверсия",
        ],
        [["S-1", "OE-1", "Part", "Parts", 100, 3, 7, 11, 9, 4, 5, 80, 0.05]],
    )

    row = parse_catalog_xlsx(content).rows[0]

    assert row.units_sold_30d == 3
    assert row.units_sold_60d == 7
    assert row.units_sold_90d == 11
    assert row.days_since_last_sale == 9
    assert row.historical_monthly_units == 4
    assert row.expected_units_sold == 5
    assert row.views_30d == 80
    assert str(row.conversion_rate_proxy) == "0.05"


class _ImportSession:
    def __init__(self) -> None:
        self.added = []
        self.committed = False

    def add(self, value) -> None:
        self.added.append(value)

    def add_all(self, values) -> None:
        self.added.extend(values)

    async def flush(self) -> None:
        for value in self.added:
            if hasattr(value, "id") and value.id is None:
                value.id = uuid4()

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, _value) -> None:
        return None


@pytest.mark.asyncio
async def test_bulk_cost_is_encrypted_before_persistence() -> None:
    content = workbook_bytes(
        ["SKU", "OE", "Name", "Category", "Price", "Себестоимость"],
        [["S-1", "OE-1", "Part", "Parts", 850, "600.00"]],
    )
    encoded = base64.urlsafe_b64encode(bytes([7]) * 32).decode().rstrip("=")
    settings = Settings(
        cost_privacy_mode="SERVER_SIDE_ENCRYPTED",
        cost_encryption_active_key_id="cost-v1",
        cost_encryption_keys_json=json.dumps({"cost-v1": encoded}),
    )
    session = _ImportSession()
    workspace_id = uuid4()
    user_id = uuid4()

    batch = await import_catalog_xlsx(
        session,  # type: ignore[arg-type]
        workspace_id=workspace_id,
        user_id=user_id,
        filename="catalog.xlsx",
        content=content,
        settings=settings,
    )

    item = next(value for value in session.added if isinstance(value, CatalogItem))
    record = next(
        value for value in session.added if isinstance(value, CatalogItemCostRecord)
    )
    assert batch.status == "completed"
    assert session.committed is True
    assert item.cost is None
    assert "Себестоимость" not in item.raw_row
    assert record.workspace_id == workspace_id
    assert record.catalog_item_id == item.id
    assert record.user_id == user_id
    assert record.action == "SET"
    assert record.ciphertext is not None
    assert b"600.00" not in record.ciphertext


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


def test_normalized_oe_collision_is_removed_for_manual_review() -> None:
    content = workbook_bytes(
        ["SKU", "OE", "Name", "Category", "Price"],
        [
            ["one", "1K0 698 151 E", "One", "Brakes", 100],
            ["two", "1K0-698-151-E", "Two", "Brakes", 110],
        ],
    )

    parsed = parse_catalog_xlsx(content)

    assert parsed.rows == []
    assert [issue.row for issue in parsed.issues] == [2, 3]
    assert {issue.code for issue in parsed.issues} == {"NORMALIZED_OE_COLLISION"}


def test_identifier_and_mapping_json_validation():
    assert normalize_identifier("  000-АХ  ") == "000AX"
    assert parse_mapping_json('{"oe":"Custom OE"}') == {"oe": "Custom OE"}
    with pytest.raises(CatalogImportError):
        parse_mapping_json("[]")
