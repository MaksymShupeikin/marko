from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

from marko.services.catalog_identity_coverage import (
    OE_CONFIRMED,
    REVIEW_OWNER_ASSERTED_OE,
    build_catalog_coverage_report,
    classify_plan,
    load_optkiev_catalog_review,
    load_owner_candidate_review,
)
from marko.services.catalog_identity_reparse import (
    OWN_STORE_LABELLED_OE_SOURCE,
    CatalogIdentityReparseError,
    SourceIndex,
    load_owner_store_source,
    plan_identity,
)
from marko.services.xlsx_catalog import ParsedCatalog, ParsedCatalogRow
from marko.services.parser_models import extract_labelled_original_oe_evidence
from metis.pricing.identity_graph import load_identity_graph_config
from metis.pricing.kemp_site import load_kemp_site_tokens


BACKEND = Path(__file__).resolve().parents[1]
CONFIG = load_identity_graph_config(BACKEND / "config/identity_graph.yaml")
TOKENS = load_kemp_site_tokens(BACKEND / "config/kemp_site_tokens.yaml")


def _owner_csv(path: Path, *, url: str = "https://prom.ua/ua/p1234-part.html") -> None:
    path.write_text(
        "код_kemp,номер,oem,блок,бренд_номера,ссылка,название,дата,скриншот\n"
        f"77649999,1K0413031BK,1K0413031BK,Оригінальні номери,KEMP,{url},"
        "Амортизатор VW,2026-08-08,\n"
        "77649999,1.10,1.10,Оригінальні номери,KEMP,"
        "https://prom.ua/ua/p1234-part.html,шум,2026-08-08,\n"
        "77649999,776416,776416,Оригінальні номери,KEMP,"
        "https://prom.ua/ua/p1234-part.html,internal,2026-08-08,\n"
        "77649999,27C06F,27C06F,Код запчастини,KEMP,"
        "https://prom.ua/ua/p1234-part.html,MPN,2026-08-08,\n",
        encoding="utf-8",
    )


def test_owner_loader_keeps_exact_label_card_provenance_and_rejects_noise(tmp_path):
    path = tmp_path / "owner.csv"
    _owner_csv(path)

    entries = load_owner_store_source(path)

    assert "77649999" in entries
    assert [entry.numbers for entry in entries["77649999"]] == [
        ("1K0413031BK",)
    ]
    context = entries["77649999"][0].raw_context
    assert "label=Оригінальні номери" in context
    assert "source_url=https://prom.ua/ua/p1234-part.html" in context
    assert "brand=KEMP" in context
    assert "captured_at=2026-08-08" in context
    assert "source_version=owner-card-export-v1" in context
    assert "source_file_sha256=" in context


def test_original_oe_extractor_supports_persisted_mapping_without_substring_match():
    evidence = extract_labelled_original_oe_evidence(
        {
            "Оригинальные номера": ["1K0413031BK"],
            "Оригинальный номер аналога": ["MUST_NOT_ENTER"],
            "Не оригінальний номер": ["ALSO_NOT"],
        }
    )

    assert [item["raw"] for item in evidence] == ["1K0413031BK"]


def test_owner_loader_refuses_a_non_card_url(tmp_path):
    path = tmp_path / "owner.csv"
    _owner_csv(path, url="https://prom.ua/ua/search/?q=77649999")

    with pytest.raises(CatalogIdentityReparseError, match="untrusted|unbound"):
        load_owner_store_source(path)


def test_bound_owner_card_is_review_evidence_and_does_not_fill_catalog_oe(tmp_path):
    path = tmp_path / "owner.csv"
    _owner_csv(path)
    entries = load_owner_store_source(path)
    index = SourceIndex(
        by_code={},
        shared_articles=frozenset(),
        loaded_sources=(OWN_STORE_LABELLED_OE_SOURCE,),
        owner_by_code=entries,
    )

    plan = plan_identity(
        own_code="77649999",
        code_raw="77649999",
        part_numbers_raw=(),
        current_oe_norm="77649999",
        index=index,
        config=CONFIG,
        tokens=TOKENS,
    )

    assert plan.identity_status != OE_CONFIRMED
    assert plan.fill_oe_norm == ""
    assert plan.graph.canonical == ""
    assert plan.owner_sources
    assert plan.owner_sources[0].extraction_method == OWN_STORE_LABELLED_OE_SOURCE
    assert classify_plan(plan) == REVIEW_OWNER_ASSERTED_OE
    assert "source_url=https://prom.ua/ua/p1234-part.html" in plan.source_contexts[
        "1K0413031BK"
    ][OWN_STORE_LABELLED_OE_SOURCE]


def _row() -> ParsedCatalogRow:
    return ParsedCatalogRow(
        source_row=1,
        sku="sku-1",
        oe_raw="77649999",
        oe_norm="77649999",
        mpn_raw="",
        mpn_norm="",
        internal_code_raw="",
        internal_code_norm="",
        name="Амортизатор VW",
        category="Амортизатори",
        brand="KEMP",
        description=None,
        product_url=None,
        current_price=Decimal("1"),
        currency="UAH",
        is_available=True,
        stock_status="fresh",
        stock_qty=None,
        stock_age_days=None,
        expected_units_sold=None,
        units_sold_30d=None,
        units_sold_60d=None,
        units_sold_90d=None,
        days_since_last_sale=None,
        historical_monthly_units=None,
        views_30d=None,
        conversion_rate_proxy=None,
        cost=None,
        manual_priority=Decimal("1"),
        raw_row={},
        part_numbers_raw=[],
        part_numbers_norm=[],
        applicability_brands=[],
        applicability_models=[],
        characteristics_raw={},
        identity_status="UNRESOLVED",
        identity_reason=None,
    )


def test_full_catalog_report_keeps_catalog_and_reference_denominators_separate():
    parsed = ParsedCatalog(
        rows=[_row()],
        issues=[],
        column_mapping={},
        total_rows=4901,
        sensitive_costs={},
        characteristics_report={},
    )
    report = build_catalog_coverage_report(
        parsed,
        index=SourceIndex(
            by_code={},
            shared_articles=frozenset(),
            loaded_sources=(),
            reference_codes=frozenset(),
        ),
        config=CONFIG,
        tokens=TOKENS,
    )

    assert report["catalog_scope"]["denominator"] == 4901
    assert report["catalog_scope"]["accepted_rows"] == 1
    assert report["reference_code_scope"]["denominator"] == 0
    assert report["catalog_scope"]["unique_confirmed_oe_count"] == 0
    assert report["catalog_scope"]["review_only_coverage_percent"] == 0.0
    matrix = {item["source"]: item for item in report["source_matrix"]}
    assert matrix["KEMP_REFERENCE_MAP_V2"]["source_role"] == (
        "REFERENCE_OE_ASSERTION"
    )
    assert matrix["OWN_STORE_LABELLED_OE"]["status"] == "REVIEW"


def test_owner_candidate_queue_is_review_only_and_keeps_exact_provenance(tmp_path):
    candidate_path = tmp_path / "owner-candidates.csv"
    candidate_path.write_text(
        "код_kemp,номер_кандидат,похоже_на_шум,ссылка,название_карточки,"
        "название_справочника\n"
        "77649999,1K0413031BK,нет,https://prom.ua/ua/p1234-part.html,"
        "Амортизатор VW,Амортизатор VW\n"
        "77649999,29.06.2025,да,https://prom.ua/ua/p1234-part.html,"
        "Амортизатор VW,Амортизатор VW\n",
        encoding="utf-8",
    )
    parsed = ParsedCatalog(
        rows=[_row()],
        issues=[],
        column_mapping={},
        total_rows=1,
        sensitive_costs={},
        characteristics_report={},
    )
    report = load_owner_candidate_review(
        candidate_path,
        parsed=parsed,
        index=SourceIndex(
            by_code={},
            shared_articles=frozenset(),
            loaded_sources=(),
            reference_codes=frozenset(),
        ),
        tokens=TOKENS,
    )

    assert report["source_role"] == "OWNER_PAGE_AREA_DISCOVERY_REVIEW"
    assert report["asserts_oe"] is False
    assert report["rows_read"] == 2
    assert report["noise_rows"] == 1
    assert report["clean_unique_numbers"] == 1
    assert report["flag_clean_codes"] == 1
    assert report["rows"][0]["card_url_bound"] is True
    assert "missing_structured_owner_oe_field" in report["rows"][0]["reasons"]


def test_optkiev_catalog_is_review_only_and_exact_card_overlap_is_reported(tmp_path):
    path = tmp_path / "optkiev.csv"
    path.write_text(
        "код_kemp,номер,oem,блок,бренд_номера,ссылка,название,дата,скриншот\n"
        "1K0413031BK,1K0413031BK,1K0413031BK,Оригінальні номери,VAG,"
        "https://avto.pro/part-1K0413031BK-VAG-531/,Амортизатор,2026-08-08,\n"
        "77649999,77649999,77649999,Аналоги,TRW,"
        "https://avto.pro/part-77649999-TRW-531/,Кросс,2026-08-08,\n",
        encoding="utf-8",
    )
    parsed = ParsedCatalog(
        rows=[_row()],
        issues=[],
        column_mapping={},
        total_rows=1,
        sensitive_costs={},
        characteristics_report={},
    )
    report = load_optkiev_catalog_review(
        path,
        parsed=parsed,
        index=SourceIndex(
            by_code={},
            shared_articles=frozenset(),
            loaded_sources=(),
            reference_codes=frozenset(),
        ),
        tokens=TOKENS,
    )

    assert report["source_role"] == "MARKETPLACE_SELLER_REVIEW"
    assert report["asserts_oe"] is False
    assert report["rows_read"] == 2
    assert report["self_reference_rows"] == 2
    assert report["unique_cards_or_urls"] == 2
    assert report["invalid_binding_rows"] == 0
    assert report["rows"][0]["card_url_bound"] is True
    assert "oem_equals_seller_number" in report["rows"][0]["reasons"]
