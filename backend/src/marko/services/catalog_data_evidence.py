"""Projection of customer catalog provenance for authenticated API consumers.

The XLSX importer intentionally keeps customer columns in ``CatalogItem.raw_row``.
This module turns those columns into a small, explicit contract for the current
UI. It is presentation metadata only: candidate numbers never become an OE and
the ``review_only`` flag stays true unless the persisted identity is a confirmed
OE with a non-empty normalized value.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import re
from typing import Any


_CELL_SEPARATOR = re.compile(r"[,;\n]+")
_EVIDENCE_URL_FIELDS = ("Ссылка на подтверждение", "evidence_url")
_SOURCE_FIELDS = ("Источники OE", "oe_sources")
_CANDIDATE_FIELDS = ("Кандидаты (не подтверждены)", "candidate_numbers")
_CONFIRMED_CROSS_FIELDS = (
    "Другие подтверждённые номера",
    "confirmed_cross_numbers",
)
_ANOMALY_FIELDS = ("Аномалии", "anomalies")
_NO_OE_REASON_FIELDS = ("Почему нет OE", "no_oe_reason")


@dataclass(frozen=True, slots=True)
class CatalogDataEvidence:
    """Safe, UI-facing provenance projection for one catalog row."""

    status: str
    review_only: bool
    internal_code: str | None
    oe_sources: tuple[str, ...]
    evidence_url: str | None
    confirmed_cross_numbers: tuple[str, ...]
    candidate_numbers: tuple[str, ...]
    anomalies: tuple[str, ...]
    no_oe_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "oe_sources",
            "confirmed_cross_numbers",
            "candidate_numbers",
            "anomalies",
        ):
            payload[key] = list(payload[key])
        return payload


def catalog_data_evidence(item: Any) -> CatalogDataEvidence:
    """Build provenance metadata without widening identity or pricing authority.

    A malformed or legacy row is deliberately represented as review-only. In
    particular, a URL or a candidate number cannot independently promote a row
    to ``OE_CONFIRMED``.
    """

    raw_row = getattr(item, "raw_row", None)
    raw = raw_row if isinstance(raw_row, Mapping) else {}
    identity_status = str(
        getattr(item, "identity_status", "UNRESOLVED") or "UNRESOLVED"
    ).strip().upper()
    oe_norm = str(getattr(item, "oe_norm", "") or "").strip()

    source_values = _values_for_fields(raw, _SOURCE_FIELDS)
    provenance = raw.get("identity_provenance")
    if isinstance(provenance, Mapping):
        source_values.extend(_split_values(provenance.get("canonical_sources")))
        source_values.extend(_split_values(provenance.get("canonical_source")))
    oe_sources = _dedupe(source_values)

    candidate_numbers = _dedupe(_values_for_fields(raw, _CANDIDATE_FIELDS))
    confirmed_cross_numbers = _dedupe(
        _values_for_fields(raw, _CONFIRMED_CROSS_FIELDS)
    )
    anomalies = _dedupe(_values_for_fields(raw, _ANOMALY_FIELDS))

    evidence_url = _first_http_url(_values_for_fields(raw, _EVIDENCE_URL_FIELDS))
    no_oe_reason = _first_text(_values_for_fields(raw, _NO_OE_REASON_FIELDS))
    if no_oe_reason is None and identity_status != "OE_CONFIRMED":
        no_oe_reason = _first_text([getattr(item, "identity_reason", None)])

    if identity_status == "OE_CONFIRMED" and oe_norm:
        status = "OE_CONFIRMED"
        review_only = False
    elif candidate_numbers:
        status = "CANDIDATE_REVIEW"
        review_only = True
    elif identity_status == "MPN_ONLY":
        status = "MPN_ONLY"
        review_only = True
    else:
        status = "NO_OE_REVIEW"
        review_only = True

    internal_code = _first_text(
        [
            getattr(item, "internal_code_norm", None),
            getattr(item, "internal_code_raw", None),
            raw.get("Внутренний код"),
            raw.get("internal_code"),
        ]
    )
    return CatalogDataEvidence(
        status=status,
        review_only=review_only,
        internal_code=internal_code,
        oe_sources=oe_sources,
        evidence_url=evidence_url,
        confirmed_cross_numbers=confirmed_cross_numbers,
        candidate_numbers=candidate_numbers,
        anomalies=anomalies,
        no_oe_reason=no_oe_reason,
    )


def _values_for_fields(raw: Mapping[str, Any], fields: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for field in fields:
        values.extend(_split_values(raw.get(field)))
    return values


def _split_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        values: list[str] = []
        for item in value:
            values.extend(_split_values(item))
        return values
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in _CELL_SEPARATOR.split(text) if part.strip()]


def _dedupe(values: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return tuple(result)


def _first_text(values: list[Any]) -> str | None:
    for value in values:
        text = str(value).strip() if value is not None else ""
        if text:
            return text
    return None


def _first_http_url(values: list[str]) -> str | None:
    for value in values:
        if value.casefold().startswith(("https://", "http://")):
            return value
    return None
