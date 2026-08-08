"""Full-catalog OE/OEM coverage measurement.

The identity reparse CLI historically reported the 7,193-code reference
universe.  That is useful for diagnosing the graph, but it is not the answer to
"how much of the 4,901-row catalog is covered?"  This module keeps the two
denominators side by side and emits one auditable result per parsed catalog row.

The report is pure: it reads the workbook and declared source files, plans the
same graph used by the database reparse, and writes no database rows or price
inputs.  Review classes are intentionally not collapsed into confirmed OE.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
import csv
import hashlib
import io
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from marko.services.catalog_identity_reparse import (
    AVTOPRO_CROSS_SOURCE,
    AVTOPRO_OE_SOURCE,
    KEMP_SITE_INTERNAL_CODE_RE,
    OWN_STORE_LABELLED_OE_SOURCE,
    SourceIndex,
    CatalogIdentityReparseError,
    _owner_card_url_is_safe,
    _owner_code_aliases,
    _owner_number_is_obvious_noise,
    _asserted_numbers,
    plan_identity,
)
from marko.services.parser_models import extract_labelled_original_oe_evidence
from marko.services.xlsx_catalog import ParsedCatalog, ParsedCatalogRow
from metis.pricing.identity_graph import Anomaly, IdentityGraphConfig
from metis.pricing.kemp_site import KempSiteTokensConfig
from metis.pricing.crosses import normalize_cross_oem


OE_CONFIRMED = "OE_CONFIRMED"
REVIEW_OWNER_ASSERTED_OE = "REVIEW_OWNER_ASSERTED_OE"
REVIEW_REFERENCE_ONLY = "REVIEW_REFERENCE_ONLY"
MPN_ONLY = "MPN_ONLY"
UNRESOLVED = "UNRESOLVED"
REJECTED_NOISE = "REJECTED_NOISE"
CONFLICT = "CONFLICT"

CLASSIFICATION_ORDER: tuple[str, ...] = (
    OE_CONFIRMED,
    REVIEW_OWNER_ASSERTED_OE,
    REVIEW_REFERENCE_ONLY,
    MPN_ONLY,
    UNRESOLVED,
    REJECTED_NOISE,
    CONFLICT,
)

_REFERENCE_OE_SOURCES = frozenset(
    {"KEMP_REFERENCE_MAP_V1", "KEMP_REFERENCE_MAP_V2"}
)


def _source_role(source: str) -> str:
    """Stable human-readable role used by the source matrix."""

    if source in _REFERENCE_OE_SOURCES:
        return "REFERENCE_OE_ASSERTION"
    if source == "KEMP_REFERENCE_ARTICLE":
        return "REFERENCE_CROSS"
    if source == OWN_STORE_LABELLED_OE_SOURCE:
        return "OWNER_ASSERTED_REVIEW"
    if source == AVTOPRO_OE_SOURCE:
        return "MARKETPLACE_REVIEW_OE"
    if source == AVTOPRO_CROSS_SOURCE:
        return "MARKETPLACE_REVIEW_CROSS"
    if source == "KEMP_SITE":
        return "SITE_REVIEW_OE"
    if source == "OWN_EXPORT_CODE":
        return "OWN_EXPORT_CROSS_OR_CODE"
    if source == "OWN_EXPORT_CHARACTERISTIC":
        return "OWN_EXPORT_CROSS"
    return "UNCLASSIFIED_REVIEW_SOURCE"


_SOURCE_URL_CONTEXT_RE = re.compile(r"(?:^| \| )source_url=(?P<url>[^|]+)")
_SOURCE_CODE_CONTEXT_RE = re.compile(r"(?:^| \| )code=(?P<code>[^|]+)")
_AVTOPRO_GENERIC_CARD_RE = re.compile(r"^/part-[^/?#]+-[^/?#]+-[^/?#]+/?$", re.IGNORECASE)


def _context_url(context: str) -> str | None:
    match = _SOURCE_URL_CONTEXT_RE.search(context or "")
    if match is None:
        return None
    return match.group("url").strip() or None


def _source_entries(index: SourceIndex, source: str):
    """Yield exact ``(code, SourceNumbers)`` entries for a source."""

    for code, entries in index.by_code.items():
        for entry in entries:
            if entry.extraction_method == source:
                yield code, entry
    for code, entries in index.owner_by_code.items():
        for entry in entries:
            if entry.extraction_method == source:
                yield code, entry


def _source_number_overlap(index: SourceIndex, source: str) -> dict[str, Any]:
    """Measure exact number reuse inside one source, without fuzzy joins."""

    by_number: defaultdict[str, set[str]] = defaultdict(set)
    cards: set[str] = set()
    codes: set[str] = set()
    raw_values = 0
    seen_entries: set[tuple[str, tuple[str, ...]]] = set()
    for code, entry in _source_entries(index, source):
        entry_key = (entry.raw_context, tuple(entry.numbers))
        if entry_key in seen_entries:
            continue
        seen_entries.add(entry_key)
        code_match = _SOURCE_CODE_CONTEXT_RE.search(entry.raw_context or "")
        canonical_code = code_match.group("code").strip() if code_match else code
        codes.add(canonical_code)
        url = _context_url(entry.raw_context)
        if url:
            cards.add(url)
        for raw in entry.numbers:
            normalized = normalize_cross_oem(raw)
            if not normalized:
                continue
            raw_values += 1
            by_number[normalized].add(canonical_code)
    duplicated_numbers = {
        number for number, owners in by_number.items() if len(owners) > 1
    }
    unique_numbers = set(by_number)
    return {
        "unique_codes": len(codes),
        "unique_cards": len(cards),
        "unique_numbers": len(unique_numbers),
        "raw_number_values": raw_values,
        "duplicated_numbers": len(duplicated_numbers),
        "duplicate_rate_percent": _percent(
            len(duplicated_numbers), len(unique_numbers)
        ),
    }


def _review_reasons(
    plan,
    classification: str,
    *,
    owner_candidates: Sequence[Mapping[str, Any]] = (),
) -> list[str]:
    """Return explicit operator-facing reasons for every non-confirmed result."""

    reasons: list[str] = []
    anomalies = set(plan.graph.anomalies)
    if "SHARED_ARTICLE_FANOUT" in anomalies:
        reasons.append("shared_code_or_multiple_catalog_rows")
    if "PUBLIC_NUMBER_SEMANTIC_FANOUT" in anomalies:
        reasons.append("variant_side_assembly_or_shared_public_number")
    if "SOURCE_SEMANTIC_CONFLICT" in anomalies:
        reasons.append("source_semantic_conflict")
    if "OE_SOURCE_CONFLICT" in anomalies:
        reasons.append("conflicting_oe_assertions")
    if "OE_SUPERSEDED_BY_NEWER_REFERENCE" in anomalies:
        reasons.append("supersession")
    if classification == REVIEW_OWNER_ASSERTED_OE:
        reasons.append("missing_independent_assertion")
        if owner_candidates:
            contexts = " ".join(
                str(candidate.get("raw_context") or "")
                for candidate in owner_candidates
            )
            if "source_url=" not in contexts:
                reasons.append("missing_detail_card")
            if (
                "content_sha256=" not in contexts
                and "source_file_sha256=" not in contexts
            ):
                reasons.append("missing_card_content_hash")
            if "source_version=" not in contexts and "parser_version=" not in contexts:
                reasons.append("missing_extractor_version")
            owner_urls = {
                _context_url(str(candidate.get("raw_context") or ""))
                for candidate in owner_candidates
            }
            owner_urls.discard(None)
            if len(owner_urls) > 1:
                reasons.append("multiple_owner_cards_for_code")
    elif classification == REVIEW_REFERENCE_ONLY:
        reasons.append("reference_only_cross_or_supplier_number")
        reasons.append("missing_independent_assertion")
    elif classification == MPN_ONLY:
        reasons.append("supplier_number_or_cross_not_oe")
    elif classification == REJECTED_NOISE:
        reasons.append("page_wide_boilerplate_or_noise_value")
    elif classification == UNRESOLVED:
        reasons.append("no_usable_identity_source")
    if not reasons:
        reasons.append("manual_review_required")
    return list(dict.fromkeys(reasons))


def _owner_evidence_for_row(row: ParsedCatalogRow) -> tuple[dict[str, Any], ...]:
    """Expose owner labels only when the row carries a bound Prom card URL."""

    url = (row.product_url or "").strip()
    return tuple(
        {
            **evidence,
            "source_url": url,
            "bound": bool(url),
        }
        for evidence in extract_labelled_original_oe_evidence(
            row.characteristics_raw
        )
    )


def _source_names(plan) -> set[str]:
    names = set(plan.graph.canonical_sources)
    names.update(link.extraction_method for link in plan.graph.links)
    names.update(source.extraction_method for source in plan.owner_sources)
    return names


def _owner_candidates(plan) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for source in plan.owner_sources:
        for raw in source.numbers:
            normalized = normalize_cross_oem(raw)
            key = (source.extraction_method, normalized, source.raw_context)
            if not normalized or key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "raw": raw,
                    "normalized": normalized,
                    "source": source.extraction_method,
                    "raw_context": source.raw_context,
                }
            )
    return candidates


def classify_plan(
    plan,
    *,
    owner_evidence: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Map the graph's persistence status to the review taxonomy."""

    if plan.graph.anomalies:
        return CONFLICT
    if plan.identity_status == OE_CONFIRMED:
        return OE_CONFIRMED
    if OWN_STORE_LABELLED_OE_SOURCE in _source_names(plan) or owner_evidence:
        return REVIEW_OWNER_ASSERTED_OE
    if plan.graph.canonical and any(
        source == "KEMP_REFERENCE_ARTICLE" for source in _source_names(plan)
    ):
        return REVIEW_REFERENCE_ONLY
    if plan.identity_status == MPN_ONLY:
        return MPN_ONLY
    if plan.graph.discarded and not plan.graph.canonical:
        return REJECTED_NOISE
    return UNRESOLVED


def _percent(numerator: int, denominator: int) -> float:
    return round((numerator / denominator) * 100, 4) if denominator else 0.0


def _count_status(counter: Counter[str]) -> dict[str, int]:
    return {
        key: int(counter.get(key, 0))
        for key in CLASSIFICATION_ORDER
    }


def _catalog_internal_code_rows(
    parsed: ParsedCatalog,
    *,
    tokens: KempSiteTokensConfig,
) -> dict[str, set[int]]:
    """Exact internal-code → workbook-row index, used only for queue audit."""

    by_code: defaultdict[str, set[int]] = defaultdict(set)
    for row in parsed.rows:
        for value in (row.oe_norm, *row.part_numbers_norm):
            normalized = normalize_cross_oem(value)
            if normalized and tokens.internal_code_pattern.fullmatch(normalized):
                by_code[normalized].add(row.source_row)
    return dict(by_code)


def _reference_map_numbers(index: SourceIndex) -> set[str]:
    return {
        normalize_cross_oem(raw)
        for entries in index.by_code.values()
        for source in entries
        if source.extraction_method in _REFERENCE_OE_SOURCES
        for raw in source.numbers
        if normalize_cross_oem(raw)
    }


def _owner_structured_numbers(index: SourceIndex) -> dict[str, set[str]]:
    """Exact owner-card candidates by exact normalized code alias."""

    result: defaultdict[str, set[str]] = defaultdict(set)
    for code, entries in index.owner_by_code.items():
        for entry in entries:
            for raw in entry.numbers:
                normalized = normalize_cross_oem(raw)
                if normalized:
                    result[code].add(normalized)
    return dict(result)


def _optkiev_card_url_is_safe(source_url: str) -> bool:
    """Validate an Avto.pro product-card URL without claiming KEMP binding.

    The supplied OPTKiev export contains seller/article cards, not a KEMP
    internal-code export.  We retain the exact card provenance but deliberately
    do not reuse ``avtopro_card_url_binds_code``: that stricter helper is for a
    KEMP-branded card whose path article is an internal KEMP code.
    """

    try:
        parsed = urlsplit(source_url)
    except ValueError:
        return False
    return bool(
        parsed.scheme.casefold() == "https"
        and (parsed.hostname or "").casefold() in {"avto.pro", "www.avto.pro"}
        and not parsed.query
        and not parsed.fragment
        and _AVTOPRO_GENERIC_CARD_RE.fullmatch(parsed.path) is not None
    )


def load_optkiev_catalog_review(
    path: str | Path,
    *,
    parsed: ParsedCatalog,
    index: SourceIndex,
    tokens: KempSiteTokensConfig,
    detail_limit: int = 1000,
) -> dict[str, Any]:
    """Audit the supplied OPTKiev/Avto.pro CSV as review-only evidence.

    Its ``код_kemp``/``номер`` columns are self-referential seller-card
    values (the current export has ``oem == номер`` on every row), and most
    codes are not internal KEMP codes.  The file can therefore discover exact
    number overlaps, but it cannot assert an OE or bind a KEMP catalog row by
    itself.  Every row remains available with its exact card URL, field label,
    title, brand and source hash.
    """

    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise CatalogIdentityReparseError(
            f"OPTKiev catalog artifact does not exist: {source_path}"
        )
    raw_file = source_path.read_bytes()
    digest = hashlib.sha256(raw_file).hexdigest()
    try:
        text = raw_file.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CatalogIdentityReparseError(
            f"OPTKiev catalog artifact is not UTF-8: {source_path}"
        ) from exc
    rows = list(csv.DictReader(io.StringIO(text)))
    required = {
        "код_kemp",
        "номер",
        "oem",
        "блок",
        "бренд_номера",
        "ссылка",
        "название",
    }
    headers = set(rows[0]) if rows else set()
    missing = sorted(required - headers)
    if missing:
        raise CatalogIdentityReparseError(
            f"OPTKiev catalog artifact is missing columns: {', '.join(missing)}"
        )

    catalog_rows_by_number: defaultdict[str, set[int]] = defaultdict(set)
    for catalog_row in parsed.rows:
        for value in (catalog_row.oe_norm, *catalog_row.part_numbers_norm):
            normalized = normalize_cross_oem(value)
            if normalized:
                catalog_rows_by_number[normalized].add(catalog_row.source_row)
    reference_numbers = _reference_map_numbers(index)
    seen_numbers: Counter[str] = Counter()
    seen_codes: set[str] = set()
    seen_urls: set[str] = set()
    block_counts: Counter[str] = Counter()
    review_rows: list[dict[str, Any]] = []
    invalid_binding_rows = 0
    self_reference_rows = 0
    internal_code_rows = 0
    rows_with_catalog_number = 0
    rows_with_multiple_catalog_rows = 0
    rows_in_reference_maps = 0
    unique_catalog_matches: set[str] = set()
    unique_reference_matches: set[str] = set()

    for row_number, row in enumerate(rows, start=2):
        raw_code = str(row.get("код_kemp") or "").strip()
        raw_number = str(row.get("номер") or "").strip()
        raw_oem = str(row.get("oem") or "").strip()
        block = str(row.get("блок") or "").strip()
        source_url = str(row.get("ссылка") or "").strip()
        title = str(row.get("название") or "").strip()
        number_brand = str(row.get("бренд_номера") or "").strip()
        normalized_code = normalize_cross_oem(raw_code)
        normalized_number = normalize_cross_oem(raw_number)
        if normalized_code:
            seen_codes.add(normalized_code)
        if source_url:
            seen_urls.add(source_url)
        if normalized_number:
            seen_numbers[normalized_number] += 1
        block_counts[block or "<empty>"] += 1
        url_bound = _optkiev_card_url_is_safe(source_url)
        if not url_bound:
            invalid_binding_rows += 1
        is_internal_code = bool(
            normalized_code and tokens.internal_code_pattern.fullmatch(normalized_code)
        )
        if is_internal_code:
            internal_code_rows += 1
        self_reference = bool(
            normalized_code and normalized_number and normalized_code == normalized_number
        )
        if self_reference:
            self_reference_rows += 1
        catalog_matches = sorted(catalog_rows_by_number.get(normalized_number, ()))
        if catalog_matches:
            rows_with_catalog_number += 1
            unique_catalog_matches.add(normalized_number)
        if len(catalog_matches) > 1:
            rows_with_multiple_catalog_rows += 1
        in_reference = normalized_number in reference_numbers if normalized_number else False
        if in_reference:
            rows_in_reference_maps += 1
            unique_reference_matches.add(normalized_number)
        if len(review_rows) >= max(0, detail_limit):
            continue
        reasons = ["seller_card_review_only"]
        if self_reference:
            reasons.append("oem_equals_seller_number")
        if not is_internal_code:
            reasons.append("not_bound_to_internal_kemp_code")
        if block.casefold() == "аналоги":
            reasons.append("analog_or_supplier_field")
        elif "оригин" in block.casefold() or "oe" in block.casefold():
            reasons.append("oe_label_not_independently_accepted")
        if in_reference:
            reasons.append("already_in_reference_maps")
        else:
            reasons.append("absent_from_reference_maps")
        if not catalog_matches:
            reasons.append("number_not_in_catalog_fields")
        elif len(catalog_matches) > 1:
            reasons.append("multiple_catalog_rows_for_number")
        review_rows.append(
            {
                "artifact_row": row_number,
                "code_raw": raw_code,
                "code_normalized": normalized_code,
                "number_raw": raw_number,
                "number_normalized": normalized_number,
                "oem_raw": raw_oem,
                "field_label": block,
                "number_brand": number_brand,
                "card_url": source_url,
                "card_url_bound": url_bound,
                "card_title": title,
                "catalog_source_rows": catalog_matches,
                "in_reference_maps": in_reference,
                "reasons": list(dict.fromkeys(reasons)),
                "source_file_sha256": digest,
                "source_version": "optkiev-export-v1",
            }
        )

    unique_numbers = set(seen_numbers)
    duplicated_numbers = {number for number, count in seen_numbers.items() if count > 1}
    return {
        "source": "OPTKIEV_NUMBERS_CATALOG_REVIEW",
        "source_role": "MARKETPLACE_SELLER_REVIEW",
        "publisher": "avtopro_optkiev",
        "status": "REVIEW",
        "asserts_oe": False,
        "source_version": "optkiev-export-v1",
        "path": str(source_path),
        "content_sha256": digest,
        "rows_read": len(rows),
        "unique_cards_or_urls": len(seen_urls),
        "unique_codes": len(seen_codes),
        "unique_numbers": len(unique_numbers),
        "duplicate_numbers": len(duplicated_numbers),
        "duplicate_rate_percent": _percent(len(duplicated_numbers), len(unique_numbers)),
        "block_counts": dict(sorted(block_counts.items())),
        "self_reference_rows": self_reference_rows,
        "internal_code_rows": internal_code_rows,
        "invalid_binding_rows": invalid_binding_rows,
        "rows_with_exact_catalog_number": rows_with_catalog_number,
        "unique_numbers_with_catalog_match": len(unique_catalog_matches),
        "rows_with_multiple_catalog_rows": rows_with_multiple_catalog_rows,
        "rows_in_reference_maps": rows_in_reference_maps,
        "unique_numbers_in_reference_maps": len(unique_reference_matches),
        "rows": review_rows,
    }


def load_owner_candidate_review(
    path: str | Path,
    *,
    parsed: ParsedCatalog,
    index: SourceIndex,
    tokens: KempSiteTokensConfig,
    detail_limit: int = 1000,
) -> dict[str, Any]:
    """Audit the derived 135-code owner queue without admitting it to identity.

    ``prom_own_store_oe_candidates.csv`` is a page-area discovery artifact, not
    a structured OE field.  It is therefore deliberately kept outside the
    graph.  Every row retains its own card URL/title and file hash, and the
    report says whether a later exact detail-card read can corroborate it.
    """

    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise CatalogIdentityReparseError(
            f"Owner candidate artifact does not exist: {source_path}"
        )
    raw_file = source_path.read_bytes()
    digest = hashlib.sha256(raw_file).hexdigest()
    try:
        text = raw_file.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CatalogIdentityReparseError(
            f"Owner candidate artifact is not UTF-8: {source_path}"
        ) from exc
    rows = list(csv.DictReader(io.StringIO(text)))
    required = {
        "код_kemp",
        "номер_кандидат",
        "похоже_на_шум",
        "ссылка",
        "название_карточки",
        "название_справочника",
    }
    headers = set(rows[0]) if rows else set()
    missing = sorted(required - headers)
    if missing:
        raise CatalogIdentityReparseError(
            f"Owner candidate artifact is missing columns: {', '.join(missing)}"
        )

    catalog_rows_by_code = _catalog_internal_code_rows(parsed, tokens=tokens)
    reference_numbers = _reference_map_numbers(index)
    owner_numbers = _owner_structured_numbers(index)
    seen_pairs: set[tuple[str, str, str]] = set()
    unique_numbers: set[str] = set()
    clean_numbers: set[str] = set()
    noisy_numbers: set[str] = set()
    codes: set[str] = set()
    clean_codes: set[str] = set()
    flag_clean_codes: set[str] = set()
    urls: set[str] = set()
    duplicate_rows = 0
    noise_rows = 0
    flag_noise_rows = 0
    invalid_binding_rows = 0
    rows_in_catalog = 0
    rows_multiple_catalog = 0
    numbers_in_reference = set()
    numbers_absent_reference = set()
    numbers_structured_confirmable = set()
    review_rows: list[dict[str, Any]] = []

    for row_number, row in enumerate(rows, start=2):
        raw_code = str(row.get("код_kemp") or "").strip()
        raw_number = str(row.get("номер_кандидат") or "").strip()
        source_url = str(row.get("ссылка") or "").strip()
        normalized_code = normalize_cross_oem(raw_code)
        normalized_number = normalize_cross_oem(raw_number)
        noise_flag = str(row.get("похоже_на_шум") or "").strip().casefold()
        if not normalized_code or not normalized_number:
            noise_rows += 1
            continue
        codes.add(normalized_code)
        urls.add(source_url)
        unique_numbers.add(normalized_number)
        safe_url = _owner_card_url_is_safe(source_url)
        obvious_noise = _owner_number_is_obvious_noise(raw_number, normalized_number)
        internal_code = bool(KEMP_SITE_INTERNAL_CODE_RE.fullmatch(normalized_number))
        flagged_noise = noise_flag in {"да", "yes", "true", "1"}
        if flagged_noise:
            flag_noise_rows += 1
        else:
            flag_clean_codes.add(normalized_code)
        is_noise = flagged_noise or obvious_noise or internal_code
        if is_noise:
            noise_rows += 1
            noisy_numbers.add(normalized_number)
        else:
            clean_codes.add(normalized_code)
            clean_numbers.add(normalized_number)
        if not safe_url:
            invalid_binding_rows += 1
        aliases = _owner_code_aliases(raw_code)
        row_catalog_matches = sorted(
            {
                source_row
                for alias in aliases
                for source_row in catalog_rows_by_code.get(alias, ())
            }
        )
        if row_catalog_matches:
            rows_in_catalog += 1
        if len(row_catalog_matches) > 1:
            rows_multiple_catalog += 1
        in_reference = normalized_number in reference_numbers
        if in_reference:
            numbers_in_reference.add(normalized_number)
        elif not is_noise:
            numbers_absent_reference.add(normalized_number)
        structured_match = any(
            normalized_number in owner_numbers.get(alias, set()) for alias in aliases
        )
        if structured_match:
            numbers_structured_confirmable.add(normalized_number)
        key = (normalized_code, normalized_number, source_url)
        if key in seen_pairs:
            duplicate_rows += 1
        seen_pairs.add(key)
        if len(review_rows) >= max(0, detail_limit):
            continue
        reasons: list[str] = []
        if flagged_noise:
            reasons.append("explicit_noise_flag")
        if obvious_noise:
            reasons.append("date_dimension_or_page_noise")
        if internal_code:
            reasons.append("internal_kemp_code")
        if not safe_url:
            reasons.append("unbound_or_untrusted_card_url")
        if not is_noise and not in_reference:
            reasons.append("absent_from_reference_maps")
        if not is_noise and in_reference:
            reasons.append("already_in_reference_maps")
        if not structured_match and not is_noise:
            reasons.append("missing_structured_owner_oe_field")
        if len(row_catalog_matches) > 1:
            reasons.append("multiple_catalog_rows_for_code")
        if not row_catalog_matches:
            reasons.append("code_not_in_catalog_rows")
        review_rows.append(
            {
                "artifact_row": row_number,
                "code_raw": raw_code,
                "code_normalized": normalized_code,
                "candidate_raw": raw_number,
                "candidate_normalized": normalized_number,
                "noise_flag": noise_flag,
                "is_noise": is_noise,
                "card_url": source_url,
                "card_url_bound": safe_url,
                "card_title": str(row.get("название_карточки") or "").strip(),
                "reference_title": str(row.get("название_справочника") or "").strip(),
                "catalog_source_rows": row_catalog_matches,
                "in_reference_maps": in_reference,
                "structured_owner_field_match": structured_match,
                "reasons": list(dict.fromkeys(reasons or ["manual_detail_card_review"])),
                "source_file_sha256": digest,
                "source_version": "owner-candidate-export-v1",
            }
        )

    clean_duplicate_rate = _percent(
        max(0, duplicate_rows), len(seen_pairs)
    )
    return {
        "source": "OWN_STORE_CANDIDATE_REVIEW",
        "source_role": "OWNER_PAGE_AREA_DISCOVERY_REVIEW",
        "publisher": "kemp_owned_store",
        "status": "REVIEW",
        "asserts_oe": False,
        "source_version": "owner-candidate-export-v1",
        "path": str(source_path),
        "content_sha256": digest,
        "rows_read": len(rows),
        "clean_rows": len(rows) - noise_rows,
        "flag_clean_rows": len(rows) - flag_noise_rows,
        "noise_rows": noise_rows,
        "flag_noise_rows": flag_noise_rows,
        "invalid_binding_rows": invalid_binding_rows,
        "duplicate_rows": duplicate_rows,
        "duplicate_rate_percent": clean_duplicate_rate,
        "unique_codes": len(codes),
        "clean_codes": len(clean_codes),
        "flag_clean_codes": len(flag_clean_codes),
        "codes_with_only_noise_after_validation": len(
            flag_clean_codes - clean_codes
        ),
        "unique_numbers": len(unique_numbers),
        "clean_unique_numbers": len(clean_numbers),
        "noise_unique_numbers": len(noisy_numbers),
        "unique_card_urls": len(urls),
        "rows_with_exact_catalog_code": rows_in_catalog,
        "rows_with_multiple_catalog_rows": rows_multiple_catalog,
        "clean_numbers_in_reference_maps": len(numbers_in_reference),
        "clean_numbers_absent_from_reference_maps": len(numbers_absent_reference),
        "clean_numbers_with_structured_owner_match": len(
            numbers_structured_confirmable
        ),
        "rows": review_rows,
    }


def _plan_catalog_row(
    row: ParsedCatalogRow,
    *,
    index: SourceIndex,
    config: IdentityGraphConfig,
    tokens: KempSiteTokensConfig,
):
    owner_evidence = _owner_evidence_for_row(row)
    plan = plan_identity(
        own_code=row.oe_norm or row.oe_raw,
        code_raw=row.oe_raw,
        part_numbers_raw=tuple(row.part_numbers_raw),
        current_oe_norm=row.oe_norm,
        index=index,
        config=config,
        tokens=tokens,
        owner_oe_evidence=owner_evidence,
    )
    return plan, owner_evidence


def _reference_scope_report(
    index: SourceIndex,
    *,
    config: IdentityGraphConfig,
    tokens: KempSiteTokensConfig,
) -> dict[str, Any]:
    statuses: Counter[str] = Counter()
    anomalies: Counter[str] = Counter()
    links: Counter[str] = Counter()
    source_codes: Counter[str] = Counter()
    no_assertion = 0
    quarantine = 0
    clean_anchor_held = 0
    shared_ambiguity = 0
    blocked_graph_quarantine = 0
    blocked_other = 0
    blocked_anomalies: Counter[str] = Counter()
    # A mutually exclusive operator queue for the blocked reference universe.
    # The legacy counters below are intentionally retained as diagnostic
    # projections (for example, anomaly counts can overlap the no-assertion
    # bucket), while this counter is the acceptance/reporting split.
    blocked_reason_counts: Counter[str] = Counter()
    codes = tuple(sorted(index.reference_codes or index.by_code))
    for code in codes:
        plan = plan_identity(
            own_code=code,
            part_numbers_raw=(),
            current_oe_norm="",
            index=index,
            config=config,
            tokens=tokens,
        )
        statuses[plan.identity_status] += 1
        for anomaly in plan.graph.anomalies:
            anomalies[anomaly] += 1
        for link in plan.links:
            links[link.validation_status] += 1
            for source in link.corroborating_sources:
                source_codes[source] += 1
        for source in plan.graph.canonical_sources:
            source_codes[source] += 1
        has_oe_source = any(
            config.sources[source].asserts_oe
            for source in _source_names(plan)
            if source in config.sources
        )
        blocked = not _asserted_numbers(plan.graph, config)
        if not has_oe_source:
            no_assertion += 1
        if plan.graph.anomalies:
            quarantine += 1
            if blocked:
                for anomaly in plan.graph.anomalies:
                    blocked_anomalies[anomaly] += 1
            if blocked and has_oe_source:
                blocked_graph_quarantine += 1
        elif blocked and plan.graph.canonical and has_oe_source:
            clean_anchor_held += 1
        elif blocked:
            blocked_other += 1
        if blocked:
            if not has_oe_source:
                blocked_reason_counts["NO_OE_ASSERTION"] += 1
            elif plan.graph.anomalies:
                blocked_reason_counts["GRAPH_QUARANTINE"] += 1
            elif plan.graph.canonical:
                blocked_reason_counts["CLEAN_ANCHOR_NOT_ELIGIBLE"] += 1
            else:
                blocked_reason_counts["OTHER"] += 1
        if any(
            anomaly
            in {
                Anomaly.SHARED_ARTICLE_FANOUT.value,
                Anomaly.PUBLIC_NUMBER_SEMANTIC_FANOUT.value,
            }
            for anomaly in plan.graph.anomalies
        ):
            shared_ambiguity += 1
    return {
        "denominator": len(codes),
        "identity_status_counts": dict(sorted(statuses.items())),
        "anomaly_counts": dict(sorted(anomalies.items())),
        "link_status_counts": dict(sorted(links.items())),
        "codes_with_confirmed_oe": statuses.get(OE_CONFIRMED, 0),
        "coverage_percent": _percent(statuses.get(OE_CONFIRMED, 0), len(codes)),
        "blocked_codes_total": len(codes) - statuses.get(OE_CONFIRMED, 0),
        "codes_with_no_oe_assertion": no_assertion,
        "codes_graph_quarantined": quarantine,
        "blocked_codes_with_oe_assertion_graph_quarantine": blocked_graph_quarantine,
        "codes_clean_anchor_held_without_oe": clean_anchor_held,
        # ``blocked_codes_other`` is the disjoint bucket.  Keep the former
        # projection under an explicit name because it overlaps the
        # no-assertion/anomaly diagnostics and must not be summed as a queue.
        "blocked_codes_other": blocked_reason_counts.get("OTHER", 0),
        "blocked_codes_other_overlapping_diagnostic": blocked_other,
        "blocked_reason_counts": dict(sorted(blocked_reason_counts.items())),
        "blocked_reason_total": sum(blocked_reason_counts.values()),
        "blocked_anomaly_counts": dict(sorted(blocked_anomalies.items())),
        "codes_shared_or_public_ambiguity": shared_ambiguity,
        "source_code_mentions": dict(sorted(source_codes.items())),
    }


def build_catalog_coverage_report(
    parsed: ParsedCatalog,
    *,
    index: SourceIndex,
    config: IdentityGraphConfig,
    tokens: KempSiteTokensConfig,
    detail_limit: int = 1000,
) -> dict[str, Any]:
    """Plan every workbook row and return full + reference-scope metrics."""

    classifications: Counter[str] = Counter()
    baseline_statuses: Counter[str] = Counter()
    anomalies: Counter[str] = Counter()
    links: Counter[str] = Counter()
    source_rows: Counter[str] = Counter()
    source_confirmed_rows: Counter[str] = Counter()
    source_numbers: defaultdict[str, set[str]] = defaultdict(set)
    accepted_new: list[dict[str, Any]] = []
    review_queue: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    row_results: list[dict[str, Any]] = []
    owner_candidate_rows: list[dict[str, Any]] = []
    owner_candidate_numbers: set[str] = set()
    owner_numbers_on_catalog_rows: set[str] = set()
    owner_numbers_in_reference_graph: set[str] = set()
    owner_rows_with_confirmed_graph = 0
    owner_rows_requiring_review = 0
    reference_numbers = {
        normalize_cross_oem(raw_number)
        for entries in index.by_code.values()
        for source in entries
        for raw_number in source.numbers
        if normalize_cross_oem(raw_number)
    }
    confirmed_numbers: set[str] = set()
    review_only_rows = 0
    rows_without_usable_source = 0
    rows_changed_by_evidence = 0
    identity_status_changed_rows = 0
    oe_value_changed_rows = 0
    source_review_rows: Counter[str] = Counter()
    source_conflict_rows: Counter[str] = Counter()
    source_catalog_rows: Counter[str] = Counter()
    source_catalog_asserted_rows: Counter[str] = Counter()
    source_catalog_confirmed_rows: Counter[str] = Counter()
    source_catalog_numbers: defaultdict[str, set[str]] = defaultdict(set)
    source_unique_attribution: Counter[str] = Counter()
    review_reason_counts: Counter[str] = Counter()

    for row in parsed.rows:
        baseline_statuses[row.identity_status or UNRESOLVED] += 1
        plan, owner_evidence = _plan_catalog_row(
            row, index=index, config=config, tokens=tokens
        )
        classification = classify_plan(plan, owner_evidence=owner_evidence)
        classifications[classification] += 1
        names = _source_names(plan)
        owner_candidates = _owner_candidates(plan)
        asserted = _asserted_numbers(plan.graph, config)
        if classification in {REVIEW_OWNER_ASSERTED_OE, REVIEW_REFERENCE_ONLY}:
            review_only_rows += 1
        if not plan.graph.canonical and not owner_candidates:
            rows_without_usable_source += 1
        if plan.identity_status != (row.identity_status or UNRESOLVED):
            identity_status_changed_rows += 1
        if plan.fill_oe_norm and plan.fill_oe_norm != normalize_cross_oem(row.oe_norm or ""):
            oe_value_changed_rows += 1
        if (
            plan.identity_status != (row.identity_status or UNRESOLVED)
            or plan.fill_oe_norm
            or owner_candidates
        ):
            rows_changed_by_evidence += 1
        asserted_source_names: set[str] = set()
        if asserted:
            asserted_source_names.update(
                source
                for source in plan.graph.canonical_sources
                if source in config.sources and config.sources[source].asserts_oe
            )
            for link in plan.graph.links:
                if link.validation_status == "CONFIRMED":
                    asserted_source_names.update(
                        source
                        for source in link.corroborating_sources
                        if source in config.sources and config.sources[source].asserts_oe
                    )
        if asserted_source_names:
            confirmed_numbers.update(number for number, _raw in _asserted_numbers(plan.graph, config))
            if len(asserted_source_names) == 1:
                source_unique_attribution[next(iter(asserted_source_names))] += 1
        for source in names:
            source_catalog_rows[source] += 1
            if classification != OE_CONFIRMED:
                source_review_rows[source] += 1
            if plan.graph.anomalies:
                source_conflict_rows[source] += 1
            if source in asserted_source_names:
                source_catalog_asserted_rows[source] += 1
                if classification == OE_CONFIRMED:
                    source_catalog_confirmed_rows[source] += 1
        if owner_candidates:
            if classification == OE_CONFIRMED:
                owner_rows_with_confirmed_graph += 1
            else:
                owner_rows_requiring_review += 1
            row_numbers = {
                normalize_cross_oem(value)
                for value in (row.oe_norm, *row.part_numbers_norm)
                if normalize_cross_oem(value)
            }
            for candidate in owner_candidates:
                normalized = candidate["normalized"]
                owner_candidate_numbers.add(normalized)
                if normalized in row_numbers:
                    owner_numbers_on_catalog_rows.add(normalized)
                if normalized in reference_numbers:
                    owner_numbers_in_reference_graph.add(normalized)
            if len(owner_candidate_rows) < max(0, detail_limit):
                owner_candidate_rows.append(
                    {
                        "source_row": row.source_row,
                        "sku": row.sku,
                        "classification": classification,
                        "identity_status": plan.identity_status,
                        "current_oe": row.oe_raw,
                        "candidates": owner_candidates,
                        "candidate_numbers_in_reference_graph": sorted(
                            {
                                candidate["normalized"]
                                for candidate in owner_candidates
                                if candidate["normalized"] in reference_numbers
                            }
                        ),
                    }
                )
        for source in names:
            source_rows[source] += 1
        if asserted:
            for source in names:
                if (
                    source != OWN_STORE_LABELLED_OE_SOURCE
                    and config.sources.get(source)
                    and config.sources[source].asserts_oe
                ):
                    source_confirmed_rows[source] += 1
        for link in plan.links:
            links[link.validation_status] += 1
            for source in link.corroborating_sources:
                source_numbers[source].add(link.extracted_oem_norm)
                source_catalog_numbers[source].add(link.extracted_oem_norm)
        if plan.graph.canonical:
            for source in plan.graph.canonical_sources:
                source_numbers[source].add(plan.graph.canonical)
                source_catalog_numbers[source].add(plan.graph.canonical)
        for owner in _owner_candidates(plan):
            source_numbers[owner["source"]].add(owner["normalized"])
            source_catalog_numbers[owner["source"]].add(owner["normalized"])
        for anomaly in plan.graph.anomalies:
            anomalies[anomaly] += 1
        new_numbers = [
            {"raw": raw, "normalized": normalized}
            for normalized, raw in asserted
            if normalized != normalize_cross_oem(row.oe_norm or "")
        ]
        if new_numbers:
            accepted_new.append(
                {
                    "source_row": row.source_row,
                    "sku": row.sku,
                    "current_oe": row.oe_raw,
                    "new_oe_numbers": new_numbers,
                    "sources": sorted(names),
                }
            )
        if classification != OE_CONFIRMED:
            review_reason_counts.update(
                _review_reasons(
                    plan,
                    classification,
                    owner_candidates=owner_candidates,
                )
            )
            queue_item = {
                "source_row": row.source_row,
                "sku": row.sku,
                "oe": row.oe_raw,
                "classification": classification,
                "identity_status": plan.identity_status,
                "identity_reason": plan.identity_reason,
                "anomalies": list(plan.graph.anomalies),
                "sources": sorted(names),
                "discarded": dict(plan.graph.discarded),
                "review_reasons": _review_reasons(
                    plan,
                    classification,
                    owner_candidates=owner_candidates,
                ),
            }
            if owner_candidates:
                queue_item["owner_candidates"] = owner_candidates
            if len(review_queue) < max(0, detail_limit):
                review_queue.append(queue_item)
        if plan.graph.anomalies and len(contradictions) < max(0, detail_limit):
            contradictions.append(
                {
                    "source_row": row.source_row,
                    "sku": row.sku,
                    "anomalies": list(plan.graph.anomalies),
                    "sources": sorted(names),
                    "identity_reason": plan.identity_reason,
                    "review_reasons": _review_reasons(
                        plan,
                        classification,
                        owner_candidates=owner_candidates,
                    ),
                }
            )
        if len(row_results) < max(0, detail_limit):
            row_results.append(
                {
                    "source_row": row.source_row,
                    "sku": row.sku,
                    "classification": classification,
                    "identity_status": plan.identity_status,
                    "identity_reason": plan.identity_reason,
                    "canonical": plan.graph.canonical,
                    "sources": sorted(names),
                    "anomalies": list(plan.graph.anomalies),
                    "owner_candidates": _owner_candidates(plan),
                    "review_reasons": _review_reasons(
                        plan,
                        classification,
                        owner_candidates=owner_candidates,
                    )
                    if classification != OE_CONFIRMED
                    else [],
                }
            )

    denominator = int(parsed.total_rows or len(parsed.rows))
    source_report = {
        source: {
            "rows_with_evidence": source_rows[source],
            "rows_with_asserted_oe": source_confirmed_rows[source],
            "rows_with_confirmed_oe": source_catalog_confirmed_rows[source],
            "unique_numbers": len(source_numbers[source]),
        }
        for source in sorted(source_rows)
    }
    source_matrix: list[dict[str, Any]] = []
    for source, rule in config.sources.items():
        overlap = _source_number_overlap(index, source)
        dataset_hashes = sorted(
            digest for digest, source_name in config.datasets.items() if source_name == source
        )
        source_matrix.append(
            {
                "source": source,
                "publisher": rule.publisher,
                "source_role": _source_role(source),
                "asserts_oe": rule.asserts_oe,
                "status": rule.status.value,
                "vintage": rule.vintage,
                "loaded": source in index.loaded_sources,
                "dataset_sha256s": dataset_hashes,
                "unique_cards_or_urls": overlap["unique_cards"],
                "ingested_cards": (
                    index.owner_cards_bound
                    if source == OWN_STORE_LABELLED_OE_SOURCE
                    else overlap["unique_cards"]
                ),
                "unique_codes": overlap["unique_codes"],
                "source_unique_numbers": overlap["unique_numbers"],
                "source_duplicate_numbers": overlap["duplicated_numbers"],
                "source_duplicate_rate_percent": overlap["duplicate_rate_percent"],
                "catalog_rows_with_evidence": source_catalog_rows[source],
                "catalog_rows_with_asserted_oe": source_catalog_asserted_rows[source],
                "catalog_rows_with_confirmed_oe": source_catalog_confirmed_rows[source],
                "catalog_review_only_candidates": source_review_rows[source],
                "catalog_conflict_rows": source_conflict_rows[source],
                "catalog_unique_numbers": len(source_catalog_numbers[source]),
                "incremental_unique_confirmed_rows": source_unique_attribution[source],
                "discarded_or_noise_values": (
                    index.owner_noise_rows
                    if source == OWN_STORE_LABELLED_OE_SOURCE
                    else 0
                ),
            }
        )
    source_matrix.sort(key=lambda item: item["source"])
    number_sources: defaultdict[str, set[str]] = defaultdict(set)
    for source, numbers in source_catalog_numbers.items():
        for number in numbers:
            number_sources[number].add(source)
    multi_source_numbers = {
        number for number, sources in number_sources.items() if len(sources) > 1
    }
    catalog_number_union = set(number_sources)
    overlap_metrics = {
        "unique_number_union": len(catalog_number_union),
        "numbers_present_in_multiple_sources": len(multi_source_numbers),
        "multi_source_overlap_percent": _percent(
            len(multi_source_numbers), len(catalog_number_union)
        ),
        "source_number_duplicate_rate_definition": (
            "number of normalized catalog-evidence numbers seen in two or more "
            "source roles divided by the union of normalized source numbers"
        ),
    }
    reference = _reference_scope_report(index, config=config, tokens=tokens)
    return {
        "schema_version": "metis-catalog-identity-coverage-v1",
        "catalog_scope": {
            "denominator": denominator,
            "accepted_rows": len(parsed.rows),
            "parse_issues": len(parsed.issues),
            "baseline_identity_status_counts": dict(sorted(baseline_statuses.items())),
            "classification_counts": _count_status(classifications),
            "oe_confirmed_rows": classifications.get(OE_CONFIRMED, 0),
            "oe_coverage_percent": _percent(
                classifications.get(OE_CONFIRMED, 0), denominator
            ),
            "review_or_unresolved_rows": denominator
            - classifications.get(OE_CONFIRMED, 0),
            "link_status_counts": dict(sorted(links.items())),
            "anomaly_counts": dict(sorted(anomalies.items())),
            "source_coverage": source_report,
            "unique_confirmed_oe_count": len(confirmed_numbers),
            "review_only_rows": review_only_rows,
            "review_only_coverage_percent": _percent(review_only_rows, denominator),
            "rows_without_usable_identity_source": rows_without_usable_source,
            "rows_changed_by_new_evidence": rows_changed_by_evidence,
            "identity_status_changed_rows": identity_status_changed_rows,
            "oe_value_changed_rows": oe_value_changed_rows,
            "review_reason_counts": dict(sorted(review_reason_counts.items())),
            "overlap_and_duplicate_metrics": overlap_metrics,
        },
        "owner_source_ingest": {
            "owner_rows_read": index.owner_rows_read,
            "owner_rows_bound": index.owner_rows_bound,
            "owner_cards_bound": index.owner_cards_bound,
            "owner_card_ambiguity_codes": index.owner_card_ambiguity_codes,
            "owner_noise_rows_rejected": index.owner_noise_rows,
            "owner_code_aliases": len(index.owner_by_code),
        },
        "owner_review": {
            "rows_with_owner_evidence": owner_rows_with_confirmed_graph
            + owner_rows_requiring_review,
            "rows_with_owner_and_confirmed_graph": owner_rows_with_confirmed_graph,
            "rows_requiring_owner_review": owner_rows_requiring_review,
            "owner_card_ambiguity_codes": index.owner_card_ambiguity_codes,
            "unique_candidate_numbers": len(owner_candidate_numbers),
            "candidate_numbers_already_on_catalog_rows": len(
                owner_numbers_on_catalog_rows
            ),
            "candidate_numbers_in_reference_graph": len(
                owner_numbers_in_reference_graph
            ),
            "candidate_numbers_absent_reference_graph": len(
                owner_candidate_numbers - owner_numbers_in_reference_graph
            ),
            "candidate_rows_sample": owner_candidate_rows,
        },
        "source_matrix": source_matrix,
        "source_incremental_lift_definition": (
            "incremental_unique_confirmed_rows counts catalog rows whose final "
            "confirmed assertion set contains only this source; sources from "
            "the same publisher are not treated as independent votes"
        ),
        "reference_code_scope": reference,
        "deltas": {
            "accepted_new_oe_rows": len(accepted_new),
            "accepted_new_oe_numbers": len(
                {
                    value["normalized"]
                    for row in accepted_new
                    for value in row["new_oe_numbers"]
                }
            ),
            "accepted_new_oe_sample": accepted_new[:detail_limit],
        },
        "review_queue": review_queue,
        "contradictions": contradictions,
        "row_results": row_results,
    }


__all__ = [
    "CONFLICT",
    "MPN_ONLY",
    "OE_CONFIRMED",
    "REJECTED_NOISE",
    "REVIEW_OWNER_ASSERTED_OE",
    "REVIEW_REFERENCE_ONLY",
    "UNRESOLVED",
    "build_catalog_coverage_report",
    "classify_plan",
    "load_optkiev_catalog_review",
    "load_owner_candidate_review",
]
