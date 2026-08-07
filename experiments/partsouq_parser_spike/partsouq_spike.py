"""Offline-only PartSouq parser and query-safety spike.

This module deliberately has no HTTP client.  It parses HTML that an operator
has lawfully saved and refuses to turn a product name into a PartSouq request:
the public PartSouq workflow is keyed by a part number or VIN/frame, while a
translated/catalogue-style name is not a unique automotive identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
import re
from typing import Iterable
from urllib.parse import quote_plus


PARTSOUQ_SEARCH_URL = "https://partsouq.com/en/search/all?q={}"
_PART_NUMBER = re.compile(
    r"\bpart\s*number\s*:\s*([A-Z0-9][A-Z0-9._/-]*)",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"\s+")
_IDENTIFIER = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{2,63}$")


class QueryKind(StrEnum):
    PART_NUMBER = "PART_NUMBER"
    VIN_OR_FRAME = "VIN_OR_FRAME"
    UNSUPPORTED_NAME_ONLY = "UNSUPPORTED_NAME_ONLY"


class ResultRole(StrEnum):
    QUERY_RESULT = "QUERY_RESULT"
    SUBSTITUTION = "SUBSTITUTION"


class IdentifierKind(StrEnum):
    OE = "OE"
    MPN = "MPN"
    CROSS = "CROSS"
    INTERNAL = "INTERNAL"
    UNKNOWN = "UNKNOWN"


class IdentifierSource(StrEnum):
    CUSTOMER_CATALOG = "CUSTOMER_CATALOG"
    PINNED_CAPTURE = "PINNED_CAPTURE"
    CONFIRMED_CROSSLINK = "CONFIRMED_CROSSLINK"
    MODEL_INFERRED = "MODEL_INFERRED"


_QUERYABLE_IDENTIFIER_KINDS = frozenset(
    {IdentifierKind.OE, IdentifierKind.MPN, IdentifierKind.CROSS}
)
_TRUSTED_IDENTIFIER_SOURCES = frozenset(
    {
        IdentifierSource.CUSTOMER_CATALOG,
        IdentifierSource.PINNED_CAPTURE,
        IdentifierSource.CONFIRMED_CROSSLINK,
    }
)


@dataclass(frozen=True, slots=True)
class KnownIdentifier:
    kind: IdentifierKind
    value: str
    source: IdentifierSource


@dataclass(frozen=True, slots=True)
class FormalPartQuery:
    """Small projection of the proposed Luna formal-part contract."""

    standardized_name: str
    part_type: str
    known_identifiers: tuple[KnownIdentifier, ...] = ()
    vin_or_frame: str | None = None
    vehicle_makes: tuple[str, ...] = ()
    vehicle_models: tuple[str, ...] = ()
    production_years: str | None = None
    engine_code: str | None = None
    position: str | None = None
    side: str | None = None


@dataclass(frozen=True, slots=True)
class PartSouqQueryPlan:
    kind: QueryKind
    query_value: str | None
    url: str | None
    reason_code: str


@dataclass(frozen=True, slots=True)
class CatalogPart:
    name: str
    part_number: str
    role: ResultRole
    compatibility: tuple[str, ...] = ()


def _text(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def _identifier(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def build_query_plan(query: FormalPartQuery) -> PartSouqQueryPlan:
    """Build only a source-supported lookup; never guess from a name."""

    for identifier in query.known_identifiers:
        if identifier.kind not in _QUERYABLE_IDENTIFIER_KINDS:
            continue
        if identifier.source not in _TRUSTED_IDENTIFIER_SOURCES:
            continue
        candidate = _identifier(identifier.value)
        if _IDENTIFIER.fullmatch(candidate):
            return PartSouqQueryPlan(
                kind=QueryKind.PART_NUMBER,
                query_value=candidate,
                url=PARTSOUQ_SEARCH_URL.format(quote_plus(candidate)),
                reason_code="TRUSTED_PART_NUMBER_AVAILABLE",
            )

    if query.vin_or_frame:
        candidate = _identifier(query.vin_or_frame)
        if 8 <= len(candidate) <= 32 and candidate.isalnum():
            return PartSouqQueryPlan(
                kind=QueryKind.VIN_OR_FRAME,
                query_value=candidate,
                url=PARTSOUQ_SEARCH_URL.format(quote_plus(candidate)),
                reason_code="VIN_OR_FRAME_AVAILABLE",
            )

    return PartSouqQueryPlan(
        kind=QueryKind.UNSUPPORTED_NAME_ONLY,
        query_value=None,
        url=None,
        reason_code="PARTSOUQ_REQUIRES_PART_NUMBER_OR_VIN_FRAME",
    )


class _RenderedBlocks(HTMLParser):
    """Collect rendered text from common block elements without CSS coupling."""

    _BLOCKS = frozenset({"h1", "h2", "h3", "h4", "p", "div", "li"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self._tag: str | None = None
        self._depth = 0
        self._chunks: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del attrs
        if self._tag is None and tag in self._BLOCKS:
            self._tag = tag
            self._depth = 1
            self._chunks = []
        elif self._tag is not None:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        del tag
        if self._tag is None:
            return
        self._depth -= 1
        if self._depth == 0:
            value = _text("".join(self._chunks))
            if value:
                self.blocks.append((self._tag, value))
            self._tag = None
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._tag is not None:
            self._chunks.append(data)


def parse_saved_search_html(html: str) -> tuple[CatalogPart, ...]:
    """Parse identity facts from operator-saved PartSouq search HTML.

    The parser ignores prices, availability and order controls.  Duplicate
    supplier offers collapse to one identity row, because they do not provide
    independent evidence for a part-number relationship.
    """

    rendered = _RenderedBlocks()
    rendered.feed(html)
    rendered.close()

    role = ResultRole.QUERY_RESULT
    pending_name: str | None = None
    current: dict[str, object] | None = None
    collecting_compatibility = False
    found: list[CatalogPart] = []

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        name = _text(str(current["name"]))
        number = _identifier(str(current["part_number"]))
        compatibility = tuple(
            dict.fromkeys(
                _text(str(value))
                for value in current.get("compatibility", ())
                if _text(str(value))
            )
        )
        if name and _IDENTIFIER.fullmatch(number):
            found.append(
                CatalogPart(
                    name=name,
                    part_number=number,
                    role=current["role"],  # type: ignore[arg-type]
                    compatibility=compatibility,
                )
            )
        current = None

    for tag, value in rendered.blocks:
        folded = value.casefold().rstrip(":")
        if folded == "substitutions":
            flush()
            role = ResultRole.SUBSTITUTION
            pending_name = None
            collecting_compatibility = False
            continue

        match = _PART_NUMBER.search(value)
        if match:
            flush()
            current = {
                "name": pending_name or "",
                "part_number": match.group(1),
                "role": role,
                "compatibility": [],
            }
            collecting_compatibility = False
            continue

        if folded == "compatibility":
            collecting_compatibility = current is not None
            continue

        if collecting_compatibility and tag == "li" and current is not None:
            values = current["compatibility"]
            assert isinstance(values, list)
            values.append(value)
            continue

        if tag in {"h1", "h2", "h3", "h4"}:
            if current is not None:
                flush()
            pending_name = value
            collecting_compatibility = False

    flush()

    unique: dict[tuple[str, str, ResultRole], CatalogPart] = {}
    for part in found:
        key = (part.name.casefold(), part.part_number, part.role)
        existing = unique.get(key)
        if existing is None:
            unique[key] = part
            continue
        unique[key] = CatalogPart(
            name=existing.name,
            part_number=existing.part_number,
            role=existing.role,
            compatibility=tuple(
                dict.fromkeys((*existing.compatibility, *part.compatibility))
            ),
        )
    return tuple(unique.values())


def substitution_numbers(parts: Iterable[CatalogPart]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            part.part_number
            for part in parts
            if part.role is ResultRole.SUBSTITUTION
        )
    )
