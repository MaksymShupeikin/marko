"""Parsing checks for the Prom XLSX catalog export."""
from io import BytesIO

import openpyxl
import pytest

from marko.parsers.prom_export import (
    ExportFormatError,
    normalize_oem,
    parse_export,
    seller_from_export_url,
    seller_of,
)

_HEADERS = [
    "Код_товару", "Назва_позиції", "Назва_позиції_укр", "Пошукові_запити",
    "Ціна", "Валюта",
    "Одиниця_виміру", "Посилання_зображення", "Наявність", "Кількість",
    "Унікальний_ідентифікатор", "Виробник", "Продукт_на_сайті",
    "Номер_пристрою_(MPN)",
    "Назва_Характеристики", "Значення_Характеристики",
    "Назва_Характеристики", "Значення_Характеристики",
]

_ROW = [
    "93818439", "Радиатор Iveco", "Радіатор Iveco (Івеко)",
    "93818439, Радіатор Iveco, радиатор Ивеко",
    "3297", "UAH",
    "шт.", "https://images.prom.ua/1.jpg", "!", 5,
    1153724202, "KEMP", "https://kemp-cs2847093.prom.ua/p1153724202-radiator.html",
    "93818439",
    "Код запчастини", "93818439, 77643",
    "Кросс-номери", "115 070, 12",
]


def _workbook(rows: list[list], sheet_name: str = "Export Products Sheet") -> BytesIO:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append(_HEADERS)
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def test_parses_a_row_into_a_product_with_every_oem_candidate():
    product = next(iter(parse_export(_workbook([_ROW]))))

    assert product.id == 1153724202
    assert product.name == "Радіатор Iveco (Івеко)"  # Ukrainian name wins
    assert product.sku == "93818439"
    assert product.price == "3297"
    assert product.currency == "UAH"
    assert product.brand == "KEMP"
    assert product.is_available is True
    assert product.image == "https://images.prom.ua/1.jpg"
    # Deduplicated, spaces stripped, "12" dropped as too short to be a part number.
    assert product.oem_numbers == ("93818439", "77643", "115070")


def test_takes_the_manufacturer_number_from_the_search_queries():
    """Справжній випадок: у «Код_товару» артикул магазину, номер Audi — поруч.

    За «312783» конкурентів не знаходилось узагалі; за «8E0513033» знаходиться
    ринок, тож саме він має стояти першим — пошукових термінів беруть два.
    """
    row = [
        "312783", "Амортизатор задний Audi A4", "Амортизатор задний Audi (Ауді) A4 (В6)",
        "312783, 312 783, 8E0 513 033, 8E0513033, 77648805, 7764 8805,"
        " задний, Амортизатор Audi A4, 1.6-1.8-2.0, 00-04",
        "1383", "UAH", "шт.", "https://images.prom.ua/2.jpg", "!", 3,
        2749852485, "KEMP", "https://kemp-cs2847093.prom.ua/p2749852485-amortyzator.html",
        "312783",
        "Код запчастини", "312783, 77648805",
        "Стан", "Новий",
    ]

    product = next(iter(parse_export(_workbook([row]))))

    assert product.oem_numbers[0] == "8E0513033"
    assert set(product.oem_numbers) == {"8E0513033", "312783", "77648805"}


def test_search_queries_drop_words_engine_sizes_and_short_tokens():
    """Поле змішує номери з фразами — у номери має пройти лише номер."""
    row = [
        "776414", "Амортизатор передний", "Амортизатор передній Mercedes 124",
        "776414, 115 070, Амортизатор передний Mercedes 124, Ford, Sierra,"
        " 1.6-1.8-2.0, 94-06, 6 pin, 2.0",
        "1769", "UAH", "шт.", "https://images.prom.ua/3.jpg", "!", 1,
        2766554583, "KEMP", "https://kemp-cs2847093.prom.ua/p2766554583-amort.html",
        None,
        "Стан", "Новий",
        "Тип", "Газомасляний",
    ]

    product = next(iter(parse_export(_workbook([row]))))

    assert product.oem_numbers == ("776414", "115070")


def test_marks_minus_availability_as_out_of_stock():
    row = list(_ROW)
    row[_HEADERS.index("Наявність")] = "-"

    product = next(iter(parse_export(_workbook([row]))))

    assert product.is_available is False


def test_skips_rows_without_identifier_name_or_url():
    broken = list(_ROW)
    broken[_HEADERS.index("Унікальний_ідентифікатор")] = None

    products = list(parse_export(_workbook([broken, _ROW])))

    assert [product.id for product in products] == [1153724202]


def test_rejects_a_workbook_that_is_not_a_prom_export():
    workbook = openpyxl.Workbook()
    workbook.active.append(["Article", "Price"])
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    with pytest.raises(ExportFormatError):
        list(parse_export(buffer))


def test_reads_the_seller_from_product_urls():
    seller = seller_from_export_url(
        "https://kemp-cs2847093.prom.ua/p1153724202-radiator.html"
    )

    assert seller is not None
    assert seller.company_id == "2847093"
    assert seller.slug == "kemp"
    assert seller.listing_url == "https://prom.ua/ua/c2847093-kemp.html"
    assert seller_from_export_url("https://example.com/p1.html") is None
    assert seller_of(list(parse_export(_workbook([_ROW])))) == seller


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("062 121 350", "062121350"),
        (" w914/2 ", "W914/2"),
        ("12", None),
        ("---", None),
        (None, None),
    ],
)
def test_normalize_oem(raw, expected):
    assert normalize_oem(raw) == expected


def test_export_url_is_rewritten_to_the_marketplace_link():
    """Сторінка магазину рендериться без ApolloCacheState — парсер її не читає."""
    from marko.parsers.prom_export import canonical_product_url, is_export_url

    export_url = "https://kemp-cs2847093.prom.ua/p1153725504-bendiks-audi-100.html"
    assert is_export_url(export_url)
    assert canonical_product_url(export_url) == (
        "https://prom.ua/ua/p1153725504-bendiks-audi-100.html"
    )

    marketplace_url = "https://prom.ua/ua/p2749847098-knopka.html"
    assert not is_export_url(marketplace_url)
    assert canonical_product_url(marketplace_url) == marketplace_url
    assert canonical_product_url(None) == ""
