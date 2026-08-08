"""Build the customer-facing OE workbook from the files, without a database.

    python -m marko.oe_catalog_export_cli --out /path/OE_каталог.xlsx

Pure file computation: the same inputs give the same workbook, so what the
customer opens is exactly what the identity plan says and can be recomputed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from marko.services.catalog_identity_reparse import (
    ItemPlan,
    build_source_index,
    load_reference_edition,
    plan_identity,
)
from marko.services.catalog_identity_safety import (
    active_identity_graph_config,
    catalog_identity_tokens,
)
from marko.services.oe_catalog_export import (
    CODE_ONLY_HEADERS,
    IMPORT_HEADERS,
    CodeOnlyRow,
    ExportRow,
    candidate_numbers,
    code_only_values,
    import_values,
    oe_named_by_an_asserting_source,
    rests_only_on_our_own_label,
    resolve_import_row,
)
from marko.services.xlsx_catalog import ParsedCatalogRow, parse_catalog_xlsx
from metis.pricing.crosses import normalize_cross_oem
from metis.pricing.kemp_reference import load_article_brand_kinds

BACKEND_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CATALOG = "data/kemp_prom_catalog.xlsx"
#: The workbook carries a second sheet with the same headers and 16 rows, and
#: the parser refuses to choose between them on its own. Naming the sheet is the
#: whole fix; guessing is what it declines to do.
DEFAULT_CATALOG_SHEET = "Export Products Sheet"
DEFAULT_REFERENCES = ("data/kemp_reference_map.csv", "data/kemp_oe_map.csv")
DEFAULT_SITE = "data/kemp_site_numbers.csv"
DEFAULT_SPARETO = "data/spareto_oe_confirmations.csv"
DEFAULT_BRAND_KINDS = "config/article_brand_kinds.yaml"


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else BACKEND_ROOT / candidate


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value).strip()


def _availability(value: bool | None) -> str:
    """Availability in the form the importer reads back.

    ``stock_status`` is a different question — freshness of the stock — and the
    importer refuses its vocabulary in this column, so it is not what travels
    here.
    """

    if value is None:
        return ""
    return "+" if value else "-"


def _evidence_urls(path: Path) -> dict[str, tuple[str, str]]:
    """Internal code -> (confirmed number, the page that confirmed it)."""

    result: dict[str, tuple[str, str]] = {}
    if not path.is_file():
        return result
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = normalize_cross_oem(row.get("mpn") or "")
            url = (row.get("source_url") or "").strip()
            number = (row.get("number_raw") or "").strip()
            if code and url and code not in result:
                result[code] = (number, url)
    return result


def _card_urls(path: Path) -> dict[str, str]:
    """Internal code -> the kemp.ua card, for loading the picture and title."""

    result: dict[str, str] = {}
    if not path.is_file():
        return result
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = normalize_cross_oem(row.get("mpn") or "")
            url = (row.get("source_url") or "").strip()
            if code and url and code not in result:
                result[code] = url
    return result


def _reference_names(paths: Iterable[Path], *, config) -> dict[str, str]:
    """Internal code -> the name the customer's own book gives it.

    The newer edition wins, and the older one fills what it does not carry: 320
    codes shipped without a name once because only the second book named them.
    """

    names: dict[str, str] = {}
    for path in paths:
        _, edition = load_reference_edition(path, config=config)
        for row in edition.rows:
            code = normalize_cross_oem(row.mpn)
            if code and row.name.strip() and code not in names:
                names[code] = row.name.strip()
    return names


def _internal_code(plan: ItemPlan) -> str:
    return plan.internal_catalog_codes[0] if plan.internal_catalog_codes else ""


def _other_numbers(plan: ItemPlan, chosen: str = "") -> str:
    """Confirmed numbers beside the one in the OE column, for a wider search."""

    primary = chosen or plan.graph.canonical
    numbers = [plan.graph.canonical] if plan.graph.canonical != primary else []
    numbers += [
        link.extracted_oem_norm
        for link in plan.links
        if link.validation_status == "CONFIRMED"
        and link.extracted_oem_norm
        and link.extracted_oem_norm != primary
    ]
    return ", ".join(sorted(dict.fromkeys(numbers)))


def _blocked_reason(plan: ItemPlan) -> str:
    if plan.graph.canonical and plan.graph.canonical_anomalies:
        return "номер есть, но сомнение в самом номере: " + ", ".join(
            plan.graph.canonical_anomalies
        )
    if plan.graph.canonical:
        return "номер есть, но ни один источник не назвал его оригинальным"
    return "оригинальный номер не назван ни одним источником"


def _candidates(plan: ItemPlan, row: ParsedCatalogRow | None) -> str:
    numbers = [link.extracted_oem_norm for link in plan.links if link.extracted_oem_norm]
    if plan.graph.canonical:
        numbers.insert(0, plan.graph.canonical)
    if row is not None:
        numbers.extend(row.part_numbers_norm)
    return candidate_numbers(numbers)


def _oe_candidates(plan: ItemPlan, *, config) -> list[tuple[str, tuple[str, ...]]]:
    """Every confirmed number of this position, anchor first, then by trust."""

    candidates = [(plan.graph.canonical, tuple(plan.graph.canonical_sources))]
    links = [
        link
        for link in plan.links
        if link.validation_status == "CONFIRMED" and link.extracted_oem_norm
    ]
    links.sort(
        key=lambda link: min(
            (config.trust_index(source) for source in link.corroborating_sources),
            default=len(config.trust_order),
        )
    )
    candidates.extend(
        (link.extracted_oem_norm, tuple(link.corroborating_sources)) for link in links
    )
    return candidates


def _evidence_for(
    code: str,
    number: str,
    *,
    evidence: dict[str, tuple[str, str]],
    cards: dict[str, str],
) -> str:
    """The page that confirmed *this* number, or the card, but never a mix.

    A link whose page is about a different number is worse than no link: it
    reads as proof and is not.
    """

    confirmed_by, url = evidence.get(code, ("", ""))
    if confirmed_by and normalize_cross_oem(confirmed_by) == normalize_cross_oem(number):
        return url
    return cards.get(code, "")


def _export_row(
    row: ParsedCatalogRow,
    plan: ItemPlan,
    *,
    oe: str,
    sources: tuple[str, ...],
    reason: str,
    evidence: dict[str, tuple[str, str]],
    cards: dict[str, str],
) -> ExportRow:
    code = _internal_code(plan)
    return ExportRow(
        sku=_text(row.sku),
        oe=_text(oe),
        name=_text(row.name),
        category=_text(row.category),
        price=_text(row.current_price),
        currency=_text(row.currency),
        brand=_text(row.brand),
        mpn=_text(row.mpn_raw),
        available=_availability(row.is_available),
        stock=_text(row.stock_qty),
        url=_text(row.product_url),
        internal_code=code,
        sources=", ".join(sources),
        other_numbers=_other_numbers(plan, oe),
        anomalies=", ".join(plan.graph.anomalies),
        evidence_url=_evidence_for(code, oe, evidence=evidence, cards=cards),
        candidates="" if oe else _candidates(plan, row),
        no_oe_reason=reason,
    )


SELF_LABELLED_ONLY = (
    "оригинальным номер называет только карточка нашего же сайта, а её подписи "
    "полей ненадёжны"
)

NO_ASSERTED_NUMBER = (
    "номер есть, но оригинальным его не назвал ни один источник, который "
    "вообще утверждает оригинальность"
)


def _sheet(workbook: Workbook, title: str, headers: tuple[str, ...]) -> Any:
    sheet = workbook.create_sheet(title)
    sheet.append(list(headers))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(vertical="center")
    sheet.freeze_panes = "A2"
    for index, header in enumerate(headers, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = min(
            max(len(header) + 4, 14), 46
        )
    return sheet


def build(args: argparse.Namespace) -> dict[str, Any]:
    config = active_identity_graph_config()
    tokens = catalog_identity_tokens()
    kinds = load_article_brand_kinds(str(_resolve(args.brand_kinds)))
    references = [_resolve(path) for path in (args.references or DEFAULT_REFERENCES)]
    site = None if args.no_site else _resolve(args.site)
    spareto = [] if args.no_spareto else [_resolve(args.spareto)]

    index = build_source_index(
        config=config,
        kinds=kinds,
        tokens=tokens,
        reference_paths=references,
        site_path=site,
        spareto_paths=spareto,
    )
    evidence = _evidence_urls(_resolve(args.spareto)) if spareto else {}
    cards = _card_urls(_resolve(args.site)) if site else {}
    names = _reference_names(references, config=config)
    brands = frozenset(kinds.kinds)
    asserting = frozenset(
        name for name, rule in config.sources.items() if rule.asserts_oe
    )

    catalog_path = _resolve(args.catalog)
    catalog_bytes = catalog_path.read_bytes()
    parsed = parse_catalog_xlsx(catalog_bytes, sheet_name=args.catalog_sheet)

    rows: list[ExportRow] = []
    seen_codes: set[str] = set()
    for row in parsed.rows:
        plan = plan_identity(
            own_code=row.oe_norm or row.oe_raw,
            code_raw=row.oe_raw,
            part_numbers_raw=tuple(row.part_numbers_raw),
            current_oe_norm=row.oe_norm,
            index=index,
            config=config,
            tokens=tokens,
        )
        seen_codes.update(plan.internal_catalog_codes)
        number, sources, reason = "", (), ""
        if plan.identity_status != "OE_CONFIRMED" or not plan.graph.canonical:
            reason = _blocked_reason(plan)
        else:
            picked = oe_named_by_an_asserting_source(
                _oe_candidates(plan, config=config), asserting=asserting
            )
            if picked is None:
                # Confirmed by the graph, but the number it anchors on is a
                # supplier article nobody claimed as original: not a price key.
                reason = NO_ASSERTED_NUMBER
            elif rests_only_on_our_own_label(picked[1], asserting=asserting):
                reason = SELF_LABELLED_ONLY
            else:
                number, sources = picked
        rows.append(
            resolve_import_row(
                _export_row(
                    row,
                    plan,
                    oe=number,
                    sources=sources,
                    reason=reason,
                    evidence=evidence,
                    cards=cards,
                ),
                brands=brands,
            )
        )

    code_only: list[CodeOnlyRow] = []
    for code in sorted(index.reference_codes or index.by_code):
        if code in seen_codes:
            continue
        plan = plan_identity(
            own_code=code,
            part_numbers_raw=(),
            current_oe_norm="",
            index=index,
            config=config,
            tokens=tokens,
        )
        if plan.identity_status != "OE_CONFIRMED" or not plan.graph.canonical:
            continue
        picked = oe_named_by_an_asserting_source(
            _oe_candidates(plan, config=config), asserting=asserting
        )
        if picked is None or rests_only_on_our_own_label(
            picked[1], asserting=asserting
        ):
            continue
        number, sources = picked
        code_only.append(
            CodeOnlyRow(
                internal_code=code,
                oe=number,
                name=names.get(code, ""),
                sources=", ".join(sources),
                other_numbers=_other_numbers(plan, number),
                anomalies=", ".join(plan.graph.anomalies),
                evidence_url=_evidence_for(
                    code, number, evidence=evidence, cards=cards
                ),
            )
        )

    workbook = Workbook()
    workbook.remove(workbook.active)

    sheet = _sheet(workbook, "Импорт", IMPORT_HEADERS)
    for export_row in rows:
        sheet.append(import_values(export_row))

    sheet = _sheet(workbook, "Только код", CODE_ONLY_HEADERS)
    for code_row in code_only:
        sheet.append(code_only_values(code_row))

    with_oe = [export_row for export_row in rows if export_row.oe]
    without_oe = [export_row for export_row in rows if not export_row.oe]
    summary = {
        "catalog_rows": len(parsed.rows),
        "rows_with_oe": len(with_oe),
        "rows_without_oe": len(without_oe),
        "unique_oe": len({export_row.oe for export_row in with_oe}),
        "code_only_rows": len(code_only),
        "reasons": Counter(
            export_row.no_oe_reason for export_row in without_oe
        ).most_common(6),
        "catalog_sha256": hashlib.sha256(catalog_bytes).hexdigest(),
    }

    sheet = _sheet(workbook, "Справка", ("Показатель", "Значение"))
    for label, value in (
        ("Дата сборки", date.today().isoformat()),
        ("Строк в прайсе заказчика", summary["catalog_rows"]),
        ("Из них с оригинальным номером", summary["rows_with_oe"]),
        ("Разных оригинальных номеров", summary["unique_oe"]),
        ("Пока без номера", summary["rows_without_oe"]),
        ("Кодов с номером, но без строки в прайсе", summary["code_only_rows"]),
        ("Версия метода", config.method_version),
        ("Отпечаток конфигурации", config.source_sha256),
        ("Отпечаток прайса", summary["catalog_sha256"]),
    ):
        sheet.append([label, str(value)])
    sheet.append([])
    for line in (
        "На листе «Импорт» — весь прайс, все строки.",
        "«OE номер» заполнен только там, где номер подтверждён и назван "
        "источником, который утверждает оригинальность.",
        "Пусто в «OE номер» — позиция идёт в разбор, а не в цены; что смотреть, "
        "написано в «Кандидаты» и «Почему нет OE».",
        "Наш внутренний код 776… в колонку OE не попадает никогда.",
        "«Аномалии» — номер есть, но у позиции есть что посмотреть руками.",
    ):
        sheet.append([line])

    out = Path(args.out).expanduser()
    workbook.save(out)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="oe-catalog-export",
        description="Build the OE workbook the customer imports through the UI",
    )
    parser.add_argument("--out", required=True, help="Where to write the .xlsx")
    parser.add_argument("--catalog", default=DEFAULT_CATALOG)
    parser.add_argument("--catalog-sheet", default=DEFAULT_CATALOG_SHEET)
    parser.add_argument("--reference", action="append", dest="references")
    parser.add_argument("--site", default=DEFAULT_SITE)
    parser.add_argument("--no-site", action="store_true")
    parser.add_argument("--spareto", default=DEFAULT_SPARETO)
    parser.add_argument("--no-spareto", action="store_true")
    parser.add_argument("--brand-kinds", default=DEFAULT_BRAND_KINDS)
    args = parser.parse_args(argv)

    summary = build(args)
    for key, value in summary.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI entry
    raise SystemExit(main())
