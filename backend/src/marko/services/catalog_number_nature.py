"""Fail-closed classification of catalog identifiers by their market nature.

The classifier answers a narrow planning question: is the catalog's primary
identifier a KEMP-internal number, a manufacturer/universal market number, or
still undetermined?  It does not prove part fitment and must never be used as a
substitute for exact candidate-level OE evidence.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
import csv
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any
import unicodedata

import yaml

from marko.services.xlsx_catalog import normalize_identifier


CATALOG_NUMBER_NATURE_SCHEMA_VERSION = "metis-catalog-number-nature-v1"


class CatalogNumberNature(StrEnum):
    KEMP_INTERNAL = "KEMP_INTERNAL"
    MANUFACTURER_OE = "MANUFACTURER_OE"
    UNKNOWN = "UNKNOWN"


class CatalogNumberNatureContractError(ValueError):
    """The client-specific number-nature policy is invalid."""


@dataclass(frozen=True, slots=True)
class ManufacturerOeRule:
    rule_id: str
    regex: str
    pattern: re.Pattern[str]
    context_any: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CatalogNumberNaturePolicy:
    catalog_id: str
    customer_scope: str
    source_catalog_sha256: str
    owned_seller_ids: frozenset[str]
    search_token_delimiter_regex: str
    search_token_delimiter: re.Pattern[str]
    internal_pattern_regexes: Mapping[str, str]
    internal_patterns: Mapping[str, re.Pattern[str]]
    manufacturer_oe_rules: tuple[ManufacturerOeRule, ...]
    source_path: str


@dataclass(frozen=True, slots=True)
class CatalogNumberRecord:
    source_row: int
    sku: str
    oe_raw: str
    title: str
    category: str = ""
    brand: str = ""
    mpn_raw: str = ""
    search_queries: str = ""
    product_url: str = ""


@dataclass(frozen=True, slots=True)
class CatalogNumberClassification:
    source_row: int
    sku: str
    oe_raw: str
    oe_norm: str
    nature: CatalogNumberNature
    reason_code: str
    rule_id: str | None
    live_independent_exact_count: int
    detected_internal_tokens: tuple[str, ...]


def load_catalog_number_nature_policy(
    path: str | Path,
) -> CatalogNumberNaturePolicy:
    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise CatalogNumberNatureContractError(
            f"Catalog number policy does not exist: {source_path}"
        )
    try:
        payload: Any = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CatalogNumberNatureContractError(
            "Catalog number policy is not valid YAML"
        ) from exc
    if not isinstance(payload, Mapping):
        raise CatalogNumberNatureContractError("Policy root must be a mapping")
    if payload.get("schema_version") != CATALOG_NUMBER_NATURE_SCHEMA_VERSION:
        raise CatalogNumberNatureContractError(
            f"Unsupported schema_version: {payload.get('schema_version')!r}"
        )

    catalog_id = _required_text(payload.get("catalog_id"), field="catalog_id")
    customer_scope = _required_text(
        payload.get("customer_scope"), field="customer_scope"
    )
    source_catalog_sha256 = _sha256_text(
        payload.get("source_catalog_sha256"), field="source_catalog_sha256"
    )
    owned_seller_ids = _text_set(
        payload.get("owned_seller_ids"), field="owned_seller_ids"
    )
    delimiter_regex = _required_text(
        payload.get("search_token_delimiter_regex"),
        field="search_token_delimiter_regex",
    )
    delimiter = _compile_regex(
        delimiter_regex,
        field="search_token_delimiter_regex",
        require_anchors=False,
    )

    raw_internal_patterns = payload.get("internal_number_patterns")
    if not isinstance(raw_internal_patterns, list) or not raw_internal_patterns:
        raise CatalogNumberNatureContractError(
            "internal_number_patterns must be a non-empty list"
        )
    internal_regexes: dict[str, str] = {}
    internal_patterns: dict[str, re.Pattern[str]] = {}
    for index, raw_rule in enumerate(raw_internal_patterns):
        prefix = f"internal_number_patterns[{index}]"
        if not isinstance(raw_rule, Mapping):
            raise CatalogNumberNatureContractError(f"{prefix} must be a mapping")
        rule_id = _unique_rule_id(
            raw_rule.get("id"), field=f"{prefix}.id", seen=internal_regexes
        )
        regex = _required_text(raw_rule.get("regex"), field=f"{prefix}.regex")
        internal_regexes[rule_id] = regex
        internal_patterns[rule_id] = _compile_regex(
            regex, field=f"{prefix}.regex", require_anchors=True
        )

    raw_manufacturer_rules = payload.get("manufacturer_oe_rules")
    if not isinstance(raw_manufacturer_rules, list):
        raise CatalogNumberNatureContractError(
            "manufacturer_oe_rules must be a list"
        )
    manufacturer_rules: list[ManufacturerOeRule] = []
    manufacturer_ids: dict[str, str] = {}
    for index, raw_rule in enumerate(raw_manufacturer_rules):
        prefix = f"manufacturer_oe_rules[{index}]"
        if not isinstance(raw_rule, Mapping):
            raise CatalogNumberNatureContractError(f"{prefix} must be a mapping")
        rule_id = _unique_rule_id(
            raw_rule.get("id"), field=f"{prefix}.id", seen=manufacturer_ids
        )
        regex = _required_text(raw_rule.get("regex"), field=f"{prefix}.regex")
        context_any = tuple(
            sorted(
                _text_set(raw_rule.get("context_any"), field=f"{prefix}.context_any")
            )
        )
        if not context_any:
            raise CatalogNumberNatureContractError(
                f"{prefix}.context_any must not be empty"
            )
        manufacturer_ids[rule_id] = regex
        manufacturer_rules.append(
            ManufacturerOeRule(
                rule_id=rule_id,
                regex=regex,
                pattern=_compile_regex(
                    regex, field=f"{prefix}.regex", require_anchors=True
                ),
                context_any=context_any,
            )
        )

    return CatalogNumberNaturePolicy(
        catalog_id=catalog_id,
        customer_scope=customer_scope,
        source_catalog_sha256=source_catalog_sha256,
        owned_seller_ids=frozenset(owned_seller_ids),
        search_token_delimiter_regex=delimiter_regex,
        search_token_delimiter=delimiter,
        internal_pattern_regexes=MappingProxyType(internal_regexes),
        internal_patterns=MappingProxyType(internal_patterns),
        manufacturer_oe_rules=tuple(manufacturer_rules),
        source_path=str(source_path.resolve()),
    )


def load_live_independent_exact_counts(
    path: str | Path | None,
    *,
    owned_seller_ids: Iterable[str],
) -> Mapping[str, int]:
    """Count exact, non-owned, non-KEMP and non-used observations by target OE."""

    if path is None:
        return MappingProxyType({})
    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise CatalogNumberNatureContractError(
            f"Live offer evidence does not exist: {source_path}"
        )
    owned = {str(value).strip() for value in owned_seller_ids if str(value).strip()}
    counts: Counter[str] = Counter()
    required = {
        "target_oe",
        "seller_id",
        "exact_oe_detected",
        "used_marker_detected",
        "kemp_detected",
    }
    with source_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = sorted(required - set(reader.fieldnames or ()))
        if missing:
            raise CatalogNumberNatureContractError(
                "Live evidence is missing columns: " + ", ".join(missing)
            )
        for row in reader:
            if not _csv_true(row.get("exact_oe_detected")):
                continue
            if _csv_true(row.get("used_marker_detected")):
                continue
            if _csv_true(row.get("kemp_detected")):
                continue
            if (row.get("seller_id") or "").strip() in owned:
                continue
            oe_norm = normalize_identifier(row.get("target_oe"))
            if oe_norm:
                counts[oe_norm] += 1
    return MappingProxyType(dict(counts))


def classify_catalog_number(
    record: CatalogNumberRecord,
    *,
    policy: CatalogNumberNaturePolicy,
    live_independent_exact_counts: Mapping[str, int] | None = None,
) -> CatalogNumberClassification:
    oe_norm = normalize_identifier(record.oe_raw)
    live_counts = live_independent_exact_counts or {}
    live_count = int(live_counts.get(oe_norm, 0)) if oe_norm else 0
    internal_tokens = _internal_search_tokens(record.search_queries, policy=policy)

    if len(oe_norm) < 3:
        return _classification(
            record,
            oe_norm=oe_norm,
            nature=CatalogNumberNature.UNKNOWN,
            reason_code="INVALID_OR_EMPTY_IDENTIFIER",
            rule_id=None,
            live_count=live_count,
            internal_tokens=internal_tokens,
        )

    # A non-owned exact listing is direct evidence that the number is used
    # outside Yuri's storefronts. It therefore outranks pattern heuristics.
    if live_count > 0:
        return _classification(
            record,
            oe_norm=oe_norm,
            nature=CatalogNumberNature.MANUFACTURER_OE,
            reason_code="LIVE_INDEPENDENT_EXACT",
            rule_id=None,
            live_count=live_count,
            internal_tokens=internal_tokens,
        )

    internal_rule = _first_full_match(oe_norm, policy.internal_patterns)
    if internal_rule is not None:
        conflicting_tokens = set(internal_tokens) - {oe_norm}
        if internal_tokens and oe_norm not in internal_tokens and conflicting_tokens:
            return _classification(
                record,
                oe_norm=oe_norm,
                nature=CatalogNumberNature.UNKNOWN,
                reason_code="CONFLICTING_KEMP_IDENTIFIERS",
                rule_id=internal_rule,
                live_count=live_count,
                internal_tokens=internal_tokens,
            )
        return _classification(
            record,
            oe_norm=oe_norm,
            nature=CatalogNumberNature.KEMP_INTERNAL,
            reason_code="KEMP_INTERNAL_PATTERN",
            rule_id=internal_rule,
            live_count=live_count,
            internal_tokens=internal_tokens,
        )

    if internal_tokens:
        return _classification(
            record,
            oe_norm=oe_norm,
            nature=CatalogNumberNature.MANUFACTURER_OE,
            reason_code="DISTINCT_KEMP_INTERNAL_TOKEN",
            rule_id=None,
            live_count=live_count,
            internal_tokens=internal_tokens,
        )

    context = _context_text(record)
    for rule in policy.manufacturer_oe_rules:
        if not rule.pattern.fullmatch(oe_norm):
            continue
        if any(_context_contains(context, token) for token in rule.context_any):
            return _classification(
                record,
                oe_norm=oe_norm,
                nature=CatalogNumberNature.MANUFACTURER_OE,
                reason_code="MANUFACTURER_PATTERN_AND_CONTEXT",
                rule_id=rule.rule_id,
                live_count=live_count,
                internal_tokens=internal_tokens,
            )

    return _classification(
        record,
        oe_norm=oe_norm,
        nature=CatalogNumberNature.UNKNOWN,
        reason_code="NO_SUFFICIENT_EVIDENCE",
        rule_id=None,
        live_count=live_count,
        internal_tokens=internal_tokens,
    )


def classify_catalog_numbers(
    records: Iterable[CatalogNumberRecord],
    *,
    policy: CatalogNumberNaturePolicy,
    live_independent_exact_counts: Mapping[str, int] | None = None,
) -> list[CatalogNumberClassification]:
    return [
        classify_catalog_number(
            record,
            policy=policy,
            live_independent_exact_counts=live_independent_exact_counts,
        )
        for record in records
    ]


def _classification(
    record: CatalogNumberRecord,
    *,
    oe_norm: str,
    nature: CatalogNumberNature,
    reason_code: str,
    rule_id: str | None,
    live_count: int,
    internal_tokens: tuple[str, ...],
) -> CatalogNumberClassification:
    return CatalogNumberClassification(
        source_row=record.source_row,
        sku=record.sku,
        oe_raw=record.oe_raw,
        oe_norm=oe_norm,
        nature=nature,
        reason_code=reason_code,
        rule_id=rule_id,
        live_independent_exact_count=live_count,
        detected_internal_tokens=internal_tokens,
    )


def _internal_search_tokens(
    search_queries: str,
    *,
    policy: CatalogNumberNaturePolicy,
) -> tuple[str, ...]:
    tokens: set[str] = set()
    for raw_token in policy.search_token_delimiter.split(search_queries or ""):
        token = normalize_identifier(raw_token)
        if token and _first_full_match(token, policy.internal_patterns) is not None:
            tokens.add(token)
    return tuple(sorted(tokens))


def _context_text(record: CatalogNumberRecord) -> str:
    value = " ".join((record.title, record.category, record.brand))
    return unicodedata.normalize("NFKC", value).casefold()


def _context_contains(context: str, token: str) -> bool:
    normalized = unicodedata.normalize("NFKC", token).casefold()
    if len(normalized) <= 3 and normalized.isalnum():
        return re.search(rf"(?<!\w){re.escape(normalized)}(?!\w)", context) is not None
    return normalized in context


def _first_full_match(
    value: str,
    patterns: Mapping[str, re.Pattern[str]],
) -> str | None:
    return next(
        (rule_id for rule_id, pattern in patterns.items() if pattern.fullmatch(value)),
        None,
    )


def _required_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogNumberNatureContractError(f"{field} must be a non-empty string")
    return value.strip()


def _sha256_text(value: Any, *, field: str) -> str:
    normalized = _required_text(value, field=field).lower()
    if re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
        raise CatalogNumberNatureContractError(f"{field} must be a SHA-256 digest")
    return normalized


def _text_set(value: Any, *, field: str) -> set[str]:
    if not isinstance(value, list):
        raise CatalogNumberNatureContractError(f"{field} must be a list")
    result: set[str] = set()
    for index, raw in enumerate(value):
        item = _required_text(raw, field=f"{field}[{index}]")
        if item in result:
            raise CatalogNumberNatureContractError(
                f"{field} contains duplicate value {item!r}"
            )
        result.add(item)
    return result


def _unique_rule_id(value: Any, *, field: str, seen: Mapping[str, Any]) -> str:
    rule_id = _required_text(value, field=field)
    if re.fullmatch(r"[a-z][a-z0-9_]*", rule_id) is None:
        raise CatalogNumberNatureContractError(
            f"{field} must use lowercase snake_case"
        )
    if rule_id in seen:
        raise CatalogNumberNatureContractError(f"Duplicate rule id: {rule_id}")
    return rule_id


def _compile_regex(
    value: str,
    *,
    field: str,
    require_anchors: bool,
) -> re.Pattern[str]:
    if require_anchors and not (value.startswith("^") and value.endswith("$")):
        raise CatalogNumberNatureContractError(
            f"{field} must be explicitly anchored with ^ and $"
        )
    try:
        return re.compile(value)
    except re.error as exc:
        raise CatalogNumberNatureContractError(f"{field} is invalid regex") from exc


def _csv_true(value: str | None) -> bool:
    return (value or "").strip().casefold() in {"1", "true", "yes"}


__all__ = [
    "CATALOG_NUMBER_NATURE_SCHEMA_VERSION",
    "CatalogNumberClassification",
    "CatalogNumberNature",
    "CatalogNumberNatureContractError",
    "CatalogNumberNaturePolicy",
    "CatalogNumberRecord",
    "ManufacturerOeRule",
    "classify_catalog_number",
    "classify_catalog_numbers",
    "load_catalog_number_nature_policy",
    "load_live_independent_exact_counts",
]
