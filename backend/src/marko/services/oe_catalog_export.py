"""One workbook the customer can import, holding every confirmed OE.

The identity work lives in files and JSON reports; this turns it into the one
artefact somebody can actually open, import through the UI and work against.

Two rules shape it. The OE column may only carry a number the graph confirmed —
a candidate is discovery material and travels on its own sheet, never beside a
price. And an internal ``776`` shelf code in that column is not a bad row but a
broken export: it would leave for Prom as an original number and match nothing,
so it stops the run instead of being skipped quietly.

The headers are the importer's own aliases (``xlsx_catalog.FIELD_ALIASES``), so
the file reads without an explicit column mapping. Everything the importer does
not know — the internal code, the sources behind the number, the anomalies still
open — travels in columns whose names match no alias, and is carried through the
round trip for the human rather than for the machine.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields, replace

from marko.services.catalog_identity_safety import is_internal_catalog_code


class OeCatalogExportError(RuntimeError):
    """The export cannot be trusted and must not be written."""


#: Below this an "original number" is almost always a filter or bearing article
#: (``KL228``, ``HIS25``): brand part numbers, not what a vehicle maker prints.
MIN_OE_LENGTH = 6

#: A brand shorter than this is too easy to hit by accident inside a number.
MIN_GLUED_BRAND_LENGTH = 4


@dataclass(frozen=True)
class ExportRow:
    """A catalogue row whose OE the graph confirmed."""

    sku: str
    oe: str
    name: str
    category: str
    price: str
    currency: str
    brand: str
    mpn: str
    available: str
    stock: str
    url: str
    internal_code: str
    sources: str
    other_numbers: str
    anomalies: str
    evidence_url: str
    #: Numbers a human may look at, none of them confirmed as original.
    candidates: str = ""
    #: Why the OE cell is empty, or what the importer will refuse the row for.
    no_oe_reason: str = ""


@dataclass(frozen=True)
class BlockedRow:
    """A catalogue row still without a confirmed original number."""

    sku: str
    name: str
    category: str
    price: str
    currency: str
    url: str
    internal_code: str
    candidates: str
    reason: str
    anomalies: str


@dataclass(frozen=True)
class CodeOnlyRow:
    """A confirmed OE for a code that has no row in the price catalogue."""

    internal_code: str
    oe: str
    name: str
    sources: str
    other_numbers: str
    anomalies: str
    evidence_url: str


IMPORT_HEADERS: tuple[str, ...] = (
    "Артикул",
    "OE номер",
    "Название",
    "Категория",
    "Цена",
    "Валюта",
    "Бренд",
    "MPN",
    "Наличие",
    "Количество",
    "Ссылка",
    "Внутренний код",
    "Источники OE",
    "Другие подтверждённые номера",
    "Аномалии",
    "Ссылка на подтверждение",
    "Кандидаты (не подтверждены)",
    "Почему нет OE",
)

REVIEW_HEADERS: tuple[str, ...] = IMPORT_HEADERS + ("Почему не в импорте",)

BLOCKED_HEADERS: tuple[str, ...] = (
    "Идентификатор",
    "Название позиции",
    "Группа",
    "Цена товара",
    "Валюта цены",
    "Адрес карточки",
    "Внутренний код",
    "Кандидаты (не подтверждены)",
    "Почему нет OE",
    "Аномалии",
)

CODE_ONLY_HEADERS: tuple[str, ...] = (
    "Внутренний код",
    "Оригинальный номер",
    "Название по справочнику",
    "Источники OE",
    "Другие подтверждённые номера",
    "Аномалии",
    "Ссылка на подтверждение",
)


def _values(row: object, headers: Sequence[str]) -> list[str]:
    return [str(getattr(row, field.name) or "") for field in fields(row)][
        : len(headers)
    ]


def import_values(row: ExportRow) -> list[str]:
    return _values(row, IMPORT_HEADERS)


def review_values(row: ExportRow, reason: str) -> list[str]:
    return import_values(row) + [reason]


def blocked_values(row: BlockedRow) -> list[str]:
    return _values(row, BLOCKED_HEADERS)


def code_only_values(row: CodeOnlyRow) -> list[str]:
    return _values(row, CODE_ONLY_HEADERS)


def glued_brand(number: str, brands: Iterable[str]) -> str | None:
    """The brand name stuck to the tail of ``number``, if there is one.

    ``191906090PIERBURG`` is one number in the reference book and two facts run
    together. Splitting it is out of the question — a number is what names the
    part — so the row is handed to a human intact.
    """

    upper = number.upper()
    for brand in brands:
        token = brand.strip().upper()
        if len(token) < MIN_GLUED_BRAND_LENGTH or not token.isalpha():
            continue
        if upper.endswith(token) and len(upper) - len(token) >= MIN_OE_LENGTH:
            return token
    return None


def oe_needs_a_human(number: str, *, brands: Iterable[str]) -> str | None:
    """Why this confirmed number should not travel beside a price, or ``None``.

    The graph says the number is confirmed; this asks a narrower question — is
    it *shaped* like an original number. A filter article and a brand glued to a
    tail are both confirmed and both useless in the OE column.
    """

    value = number.strip()
    if len(value) < MIN_OE_LENGTH:
        return f"короткий номер ({len(value)} знаков): обычно это артикул бренда"
    if not any(character.isdigit() for character in value):
        return "в номере нет ни одной цифры"
    brand = glued_brand(value, brands)
    if brand is not None:
        return f"к номеру приклеен бренд {brand}"
    return None


def oe_named_by_an_asserting_source(
    candidates: Sequence[tuple[str, Sequence[str]]], *, asserting: Iterable[str]
) -> tuple[str, tuple[str, ...]] | None:
    """The first number here that a source claiming OE-ness actually named.

    The graph's anchor is not always that number. On a catalogue row the
    customer's own «Код товару» outranks the reference book by design — it is
    the number they sell under — and for 158 rows of 3283 it is a supplier
    article while the book and the independent catalogue named a real original
    number beside it. In the price column that difference is the whole job: a
    search for ``AUTC7163`` finds our own shelf, a search for ``441407151C``
    finds the market.

    ``candidates`` arrives in preference order, anchor first.
    """

    wanted = frozenset(asserting)
    for number, sources in candidates:
        value = (number or "").strip()
        if value and wanted.intersection(sources):
            return value, tuple(sources)
    return None


#: Our own product card. Its field labels are unreliable by declaration, so a
#: number whose only OE claim comes from there is not one we hand to pricing.
SELF_LABELLED_SOURCE = "KEMP_SITE"


def rests_only_on_our_own_label(
    sources: Iterable[str], *, asserting: Iterable[str]
) -> bool:
    """Whether the sole claim of originality is our own site's field label."""

    claims = frozenset(asserting).intersection(sources)
    return claims == {SELF_LABELLED_SOURCE}


def candidate_numbers(numbers: Iterable[str], *, limit: int = 12) -> str:
    """Unconfirmed numbers for a human to look at, without our shelf codes.

    A ``776`` code is what the position is called on our own shelf. It is not a
    cross, nothing outside this company knows it, and a person copying it out of
    a candidate cell into a search would get an empty page — so it never travels
    even here.
    """

    seen: list[str] = []
    for number in numbers:
        value = (number or "").strip()
        if not value or value in seen or is_internal_catalog_code(value):
            continue
        seen.append(value)
    return ", ".join(sorted(seen)[:limit])


def _import_blocker(row: ExportRow) -> str | None:
    """What the importer itself would refuse this row for."""

    if not row.name.strip():
        return "нет названия — импорт откажет"
    if not row.category.strip():
        return "нет категории — импорт откажет"
    if not row.price.strip():
        return "нет цены — импорт откажет"
    return None


def resolve_import_row(row: ExportRow, *, brands: Iterable[str]) -> ExportRow:
    """Decide what this row's OE cell may hold, keeping the row either way.

    The customer wants the whole catalogue in one table, so a position without a
    confirmed original number still travels — with an empty OE cell and the
    reason beside it. The importer reads that as MPN-only material, which is
    exactly what it is: discovery, not a price key.

    Raises only for the one thing that must never leave: our own shelf code in
    the OE column.
    """

    if is_internal_catalog_code(row.oe):
        raise OeCatalogExportError(
            f"строка {row.sku or row.internal_code}: в колонке OE наш внутренний "
            f"код {row.oe}; в Prom он уйдёт как оригинальный номер и не найдёт "
            "ничего"
        )
    if not row.oe.strip():
        return row
    reason = oe_needs_a_human(row.oe, brands=brands)
    if reason is not None:
        return replace(
            row,
            oe="",
            candidates=candidate_numbers([row.oe, *row.candidates.split(", ")]),
            no_oe_reason=reason,
        )
    blocker = _import_blocker(row)
    if blocker is not None:
        return replace(row, no_oe_reason=blocker)
    return row
