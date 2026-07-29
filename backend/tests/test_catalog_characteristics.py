"""WP-1: the Prom characteristics block becomes structured catalog identity."""

from io import BytesIO

import pytest
from openpyxl import Workbook

from marko.core.config import backend_config_path
from marko.services.catalog_characteristics import (
    CharacteristicsContractError,
    characteristic_column_pairs,
    collect_characteristics,
    extract_characteristics,
    load_characteristics_config,
    normalize_characteristic_name,
)
from marko.services.xlsx_catalog import CatalogImportError, parse_catalog_xlsx


CONFIG = load_characteristics_config(
    backend_config_path("config/catalog_characteristics.yaml")
)

PROM_HEADERS = [
    "Унікальний_ідентифікатор",
    "Код_товару",
    "Назва_позиції",
    "Назва_групи",
    "Ціна",
    "Номер_пристрою_(MPN)",
    "Назва_Характеристики",
    "Одиниця_виміру_Характеристики",
    "Значення_Характеристики",
    "Назва_Характеристики",
    "Одиниця_виміру_Характеристики",
    "Значення_Характеристики",
    "Назва_Характеристики",
    "Одиниця_виміру_Характеристики",
    "Значення_Характеристики",
]


def prom_row(
    *,
    sku="U-1",
    code="056121113D",
    mpn="",
    part_numbers="056121113D, 050121113C, 776416",
    brand="Audi|Volkswagen",
    model="Passat|Golf",
):
    return [
        sku,
        code,
        "Термостат",
        "Система охолодження",
        "100",
        mpn,
        "Код запчастини",
        "",
        part_numbers,
        "Сумісність з маркою",
        "",
        brand,
        "Сумісність з моделлю",
        "",
        model,
    ]


def workbook_bytes(headers, rows, *, extra_sheets=()):
    stream = BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Export Products Sheet"
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    for title, sheet_headers, sheet_rows in extra_sheets:
        other = workbook.create_sheet(title)
        other.append(sheet_headers)
        for row in sheet_rows:
            other.append(row)
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def parse(collected, *, self_numbers=(), columns_balanced=True):
    return extract_characteristics(
        collected,
        CONFIG,
        self_numbers=self_numbers,
        columns_balanced=columns_balanced,
    )


# --------------------------------------------------------------- name folding


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Модель", "Мoдель"),  # second one carries a Latin "o"
        ("КОД ЗАПЧАСТИНИ", "код_запчастини"),
        ("Сумісність з маркою", "  сумісність   з  маркою  "),
    ],
)
def test_characteristic_names_fold_to_one_key(left, right):
    assert normalize_characteristic_name(left) == normalize_characteristic_name(right)


def test_homoglyph_variant_of_model_is_recognized_by_config():
    assert normalize_characteristic_name("Мoдель") in CONFIG.rules_by_name


def test_unknown_name_is_not_silently_claimed():
    key = normalize_characteristic_name("Гарантійний термін")

    assert key not in CONFIG.rules_by_name


# ------------------------------------------------------------ number extraction


def test_comma_separated_numbers_become_a_cross_list():
    result = parse({"Код запчастини": ["056121113D, 050121113C, 776416"]})

    assert result.part_numbers_norm == ("056121113D", "050121113C", "776416")
    assert result.part_numbers_raw == ("056121113D", "050121113C", "776416")


def test_inner_space_does_not_split_one_number_into_two():
    result = parse({"Код запчастини": ["776414, 115 070,"]})

    assert result.part_numbers_norm == ("776414", "115070")


def test_trailing_separator_produces_no_empty_number():
    result = parse({"Код запчастини": ["93818439, 77643,"]})

    assert result.part_numbers_norm == ("93818439", "77643")


def test_own_code_is_dropped_and_counted_not_flagged():
    result = parse(
        {"Код запчастини": ["056121113D, 050121113C"]},
        self_numbers=("056121113D",),
    )

    assert result.part_numbers_norm == ("050121113C",)
    assert result.dropped_self_references == 1
    assert result.anomalies == ()


def test_own_code_is_recognized_through_punctuation_and_case():
    result = parse(
        {"Код запчастини": ["06А 115-105 B, 050121113C"]},
        self_numbers=("06a115105b",),
    )

    assert result.part_numbers_norm == ("050121113C",)


def test_duplicate_numbers_collapse_once():
    result = parse({"Код запчастини": ["776416, 776416, 776 416"]})

    assert result.part_numbers_norm == ("776416",)


def test_cross_numbers_characteristic_joins_the_same_list():
    result = parse(
        {
            "Код запчастини": ["93818439"],
            "Кросс-номери": ["77643"],
        }
    )

    assert set(result.part_numbers_norm) == {"93818439", "77643"}


def test_too_short_number_is_rejected_with_a_code():
    result = parse({"Код запчастини": ["944, 050121113C"]})

    assert result.part_numbers_norm == ("050121113C",)
    assert "PART_NUMBER_TOO_SHORT" in result.anomalies


def test_too_long_number_is_rejected_with_a_code():
    result = parse({"Код запчастини": ["A" * 21]})

    assert result.part_numbers_norm == ()
    assert "PART_NUMBER_TOO_LONG" in result.anomalies


def test_number_list_is_capped_and_the_cap_is_reported():
    numbers = ", ".join(f"NUM{index:05d}" for index in range(80))

    result = parse({"Код запчастини": [numbers]})

    assert len(result.part_numbers_norm) == CONFIG.limits.max_part_numbers
    assert "PART_NUMBERS_TRUNCATED" in result.anomalies


def test_empty_value_yields_nothing_without_anomalies():
    result = parse({"Код запчастини": [""]})

    assert result.part_numbers_norm == ()
    assert result.anomalies == ()


# ------------------------------------------------------- applicability parsing


def test_brands_split_on_pipe_only():
    result = parse({"Сумісність з маркою": ["Peugeot|Citroen|Fiat"]})

    assert result.applicability_brands == ("Peugeot", "Citroen", "Fiat")


def test_model_name_containing_a_slash_stays_whole():
    result = parse({"Сумісність з моделлю": ["Transit Connect|LT/Crafter"]})

    assert result.applicability_models == ("Transit Connect", "LT/Crafter")


def test_single_brand_and_empty_applicability_are_both_fine():
    assert parse({"Сумісність з маркою": ["Audi"]}).applicability_brands == ("Audi",)
    assert parse({"Сумісність з маркою": [""]}).applicability_brands == ()


def test_five_brands_survive_intact():
    result = parse({"Сумісність з маркою": ["Volkswagen|Skoda|Daewoo|Mazda|Ford"]})

    assert len(result.applicability_brands) == 5


def test_repeated_brand_across_columns_appears_once():
    result = parse({"Сумісність з маркою": ["Audi|Volkswagen", "Audi"]})

    assert result.applicability_brands == ("Audi", "Volkswagen")


def test_short_form_marka_and_model_are_also_applicability():
    result = parse({"Марка": ["Opel"], "Модель": ["Astra"]})

    assert result.applicability_brands == ("Opel",)
    assert result.applicability_models == ("Astra",)


# ------------------------------------------------------------------ reporting


def test_unrecognized_characteristic_is_preserved_and_named():
    result = parse({"Гарантійний термін": ["12 місяців"]})

    assert result.unrecognized_names == ("Гарантійний термін",)
    assert result.characteristics_raw == {"Гарантійний термін": ["12 місяців"]}


def test_recognized_but_unmapped_characteristic_is_not_called_unrecognized():
    result = parse({"Стан": ["Нове"], "Тип запчастини": ["Оригінал"]})

    assert result.unrecognized_names == ()
    assert result.characteristics_raw["Стан"] == ["Нове"]


def test_unbalanced_columns_are_reported():
    result = parse({"Код запчастини": ["050121113C"]}, columns_balanced=False)

    assert "CHARACTERISTIC_COLUMNS_UNBALANCED" in result.anomalies


# --------------------------------------------------------------- column layout


def test_columns_pair_by_header_not_by_offset():
    headers = [
        "Назва_Характеристики",
        "Значення_Характеристики",
        "Назва_Характеристики#2",
        "Одиниця_виміру_Характеристики",
        "Значення_Характеристики#2",
    ]

    columns = characteristic_column_pairs(headers, CONFIG)

    assert columns.pairs == ((0, 1), (2, 4))
    assert columns.balanced is True


def test_missing_value_column_is_flagged_as_unbalanced():
    headers = [
        "Назва_Характеристики",
        "Значення_Характеристики",
        "Назва_Характеристики#2",
    ]

    columns = characteristic_column_pairs(headers, CONFIG)

    assert columns.balanced is False


def test_collect_keeps_every_occurrence_of_a_repeated_name():
    headers = [
        "Назва_Характеристики",
        "Значення_Характеристики",
        "Назва_Характеристики#2",
        "Значення_Характеристики#2",
    ]
    columns = characteristic_column_pairs(headers, CONFIG)

    collected = collect_characteristics(
        ("Код запчастини", "111111", "Код запчастини", "222222"), columns.pairs
    )

    assert collected == {"Код запчастини": ["111111", "222222"]}


def test_row_shorter_than_the_header_does_not_raise():
    headers = ["Назва_Характеристики", "Значення_Характеристики"]
    columns = characteristic_column_pairs(headers, CONFIG)

    assert collect_characteristics(("Код запчастини",), columns.pairs) == {
        "Код запчастини": [""]
    }


# ----------------------------------------------------------------- config load


def test_config_rejects_an_unknown_schema(tmp_path):
    path = tmp_path / "characteristics.yaml"
    path.write_text("schema_version: nope\n", encoding="utf-8")

    with pytest.raises(CharacteristicsContractError):
        load_characteristics_config(path)


def test_config_rejects_a_name_claimed_by_two_fields(tmp_path):
    path = tmp_path / "characteristics.yaml"
    path.write_text(
        "schema_version: marko-catalog-characteristics-v1\n"
        "method_version: test\n"
        "column_headers:\n"
        "  name_prefixes: ['назва характеристики']\n"
        "  value_prefixes: ['значення характеристики']\n"
        "limits:\n"
        "  min_number_length: 4\n"
        "  max_number_length: 20\n"
        "  max_part_numbers: 8\n"
        "  max_applicability_values: 8\n"
        "  max_value_length: 255\n"
        "characteristics:\n"
        "  - field: part_numbers\n"
        "    names: ['марка']\n"
        "    separators: [',']\n"
        "  - field: applicability_brand\n"
        "    names: ['марка']\n"
        "    separators: ['|']\n",
        encoding="utf-8",
    )

    with pytest.raises(CharacteristicsContractError):
        load_characteristics_config(path)


def test_config_rejects_inverted_length_limits(tmp_path):
    path = tmp_path / "characteristics.yaml"
    path.write_text(
        "schema_version: marko-catalog-characteristics-v1\n"
        "method_version: test\n"
        "column_headers:\n"
        "  name_prefixes: ['назва характеристики']\n"
        "  value_prefixes: ['значення характеристики']\n"
        "limits:\n"
        "  min_number_length: 20\n"
        "  max_number_length: 4\n"
        "  max_part_numbers: 8\n"
        "  max_applicability_values: 8\n"
        "  max_value_length: 255\n"
        "characteristics:\n"
        "  - field: part_numbers\n"
        "    names: ['код запчастини']\n"
        "    separators: [',']\n",
        encoding="utf-8",
    )

    with pytest.raises(CharacteristicsContractError):
        load_characteristics_config(path)


def test_missing_config_is_an_error_not_an_empty_contract(tmp_path):
    with pytest.raises(CharacteristicsContractError):
        load_characteristics_config(tmp_path / "absent.yaml")


def test_config_hash_is_recorded():
    assert CONFIG.source_sha256 is not None
    assert len(CONFIG.source_sha256) == 64


# ------------------------------------------------------------- importer wiring


def test_import_fills_identity_fields_from_characteristics():
    content = workbook_bytes(PROM_HEADERS, [prom_row()])

    parsed = parse_catalog_xlsx(content)
    row = parsed.rows[0]

    assert row.oe_norm == "056121113D"
    assert row.part_numbers_norm == ["050121113C", "776416"]
    assert row.applicability_brands == ["Audi", "Volkswagen"]
    assert row.applicability_models == ["Passat", "Golf"]
    assert row.characteristics_raw["Код запчастини"] == [
        "056121113D, 050121113C, 776416"
    ]


def test_import_report_counts_names_and_self_references():
    content = workbook_bytes(
        PROM_HEADERS,
        [
            prom_row(),
            prom_row(sku="U-2", code="3A0501541", part_numbers="3A0501541, FE03664"),
        ],
    )

    report = parse_catalog_xlsx(content).characteristics_report

    assert report["sheet"] == "Export Products Sheet"
    assert report["recognized"]["Код запчастини"] == 2
    assert report["unrecognized"] == {}
    assert report["self_references_dropped"] == 2
    assert report["rows_with_part_numbers"] == 2
    assert report["part_numbers_total"] == 3
    assert report["config_sha256"] == CONFIG.source_sha256


def test_unrecognized_name_reaches_the_batch_report():
    headers = PROM_HEADERS[:6] + [
        "Назва_Характеристики",
        "Одиниця_виміру_Характеристики",
        "Значення_Характеристики",
    ]
    row = ["U-1", "056121113D", "Термостат", "Група", "100", "", "Колір", "", "Чорний"]

    report = parse_catalog_xlsx(workbook_bytes(headers, [row])).characteristics_report

    assert report["unrecognized"] == {"Колір": 1}
    assert report["rows_with_part_numbers"] == 0


def test_workbook_without_characteristics_imports_with_empty_identity():
    headers = ["Артикул", "OEM номер", "Название", "Группа", "Цена"]
    content = workbook_bytes(headers, [["0007", "06А 115-105 B", "Фильтр", "Ф", "10"]])

    parsed = parse_catalog_xlsx(content)

    assert parsed.rows[0].part_numbers_norm == []
    assert parsed.characteristics_report["column_pairs"] == 0


def test_two_catalog_sheets_refuse_to_guess():
    content = workbook_bytes(
        PROM_HEADERS,
        [prom_row()],
        extra_sheets=(("Лист1", PROM_HEADERS, [prom_row(sku="U-9", code="AAA111")]),),
    )

    with pytest.raises(CatalogImportError, match="нескольких листах"):
        parse_catalog_xlsx(content)


def test_explicit_sheet_name_resolves_the_ambiguity():
    content = workbook_bytes(
        PROM_HEADERS,
        [prom_row()],
        extra_sheets=(("Лист1", PROM_HEADERS, [prom_row(sku="U-9", code="AAA111")]),),
    )

    parsed = parse_catalog_xlsx(content, sheet_name="Лист1")

    assert [row.oe_norm for row in parsed.rows] == ["AAA111"]


def test_non_catalog_second_sheet_does_not_block_import():
    content = workbook_bytes(
        PROM_HEADERS,
        [prom_row()],
        extra_sheets=(
            ("Export Groups Sheet", ["Номер_групи", "Назва_групи"], [[1, "Ф"]]),
        ),
    )

    parsed = parse_catalog_xlsx(content)

    assert len(parsed.rows) == 1
