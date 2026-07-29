"""Config-driven extraction of the Prom characteristics block.

The importer historically read twelve columns of an eighty-seven column export.
Everything that identifies a part beyond its own code — the seller's own list of
cross numbers, the brands and models it fits — lives in the repeating
``Назва / Одиниця / Значення`` triples that were dropped.  This module turns
those triples into structured fields.

Two properties are deliberate.  Extraction is pure and deterministic, because
its output feeds the identity graph that pricing decisions are hashed against.
And nothing is discarded silently: a characteristic the configuration does not
recognize is still preserved verbatim and counted in the import report, so a
seller renaming a field surfaces as a number instead of as missing data.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field
import hashlib
from pathlib import Path
import re
from typing import Any

import yaml

from metis.pricing.crosses import normalize_cross_oem

CATALOG_CHARACTERISTICS_SCHEMA_VERSION = "marko-catalog-characteristics-v1"

FIELD_PART_NUMBERS = "part_numbers"
FIELD_APPLICABILITY_BRAND = "applicability_brand"
FIELD_APPLICABILITY_MODEL = "applicability_model"
KNOWN_FIELDS = frozenset(
    {
        FIELD_PART_NUMBERS,
        FIELD_APPLICABILITY_BRAND,
        FIELD_APPLICABILITY_MODEL,
        "condition",
        "part_kind",
    }
)

ANOMALY_UNBALANCED_COLUMNS = "CHARACTERISTIC_COLUMNS_UNBALANCED"
ANOMALY_NUMBER_TOO_SHORT = "PART_NUMBER_TOO_SHORT"
ANOMALY_NUMBER_TOO_LONG = "PART_NUMBER_TOO_LONG"
ANOMALY_PART_NUMBERS_TRUNCATED = "PART_NUMBERS_TRUNCATED"
ANOMALY_APPLICABILITY_TRUNCATED = "APPLICABILITY_TRUNCATED"
ANOMALY_VALUE_TOO_LONG = "CHARACTERISTIC_VALUE_TOO_LONG"

# Cyrillic letters that share a glyph with a Latin one.  Applied after
# upper-casing, which is why only the upper-case forms are listed.  Shared with
# ``xlsx_catalog`` so identifiers and characteristic names fold identically:
# the observed export contains both ``Модель`` and ``Мoдель`` with a Latin "o".
HOMOGLYPH_FOLDING = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "С": "C",
        "Е": "E",
        "Н": "H",
        "К": "K",
        "М": "M",
        "О": "O",
        "Р": "P",
        "Т": "T",
        "Х": "X",
        "І": "I",
    }
)

_NAME_CLEAN_RE = re.compile(r"[^a-zа-яёіїґєԁөү0-9]+", re.IGNORECASE)


class CharacteristicsContractError(ValueError):
    """The characteristics configuration cannot be trusted as written."""


@dataclass(frozen=True, slots=True)
class CharacteristicRule:
    field: str
    names: tuple[str, ...]
    separators: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CharacteristicsLimits:
    min_number_length: int
    max_number_length: int
    max_part_numbers: int
    max_applicability_values: int
    max_value_length: int


@dataclass(frozen=True, slots=True)
class CharacteristicsConfig:
    schema_version: str
    method_version: str
    name_prefixes: tuple[str, ...]
    value_prefixes: tuple[str, ...]
    limits: CharacteristicsLimits
    rules: tuple[CharacteristicRule, ...]
    rules_by_name: Mapping[str, CharacteristicRule]
    source_sha256: str | None


@dataclass(frozen=True, slots=True)
class CharacteristicColumns:
    """Where the characteristics block sits in one workbook."""

    pairs: tuple[tuple[int, int], ...]
    balanced: bool


@dataclass(frozen=True, slots=True)
class CharacteristicsExtraction:
    """Structured identity read out of one catalog row."""

    part_numbers_raw: tuple[str, ...] = ()
    part_numbers_norm: tuple[str, ...] = ()
    applicability_brands: tuple[str, ...] = ()
    applicability_models: tuple[str, ...] = ()
    characteristics_raw: dict[str, list[str]] = dataclass_field(default_factory=dict)
    unrecognized_names: tuple[str, ...] = ()
    anomalies: tuple[str, ...] = ()
    # Repeating the item's own code inside its cross list is the rule rather
    # than the exception in the observed export, so it is counted, not flagged.
    dropped_self_references: int = 0


def normalize_part_number(value: Any) -> str:
    """Normalize a declared part number the same way ``oe_norm`` is normalized.

    ``normalize_cross_oem`` keeps only ``[A-Z0-9]``, so a Cyrillic homoglyph is
    deleted rather than folded: ``06А 115-105 B`` would become ``06115105B``
    while the very same number in ``Код_товару`` becomes ``06A115105B`` via
    ``normalize_identifier``.  Two keys for one number means the row's own code
    is not recognized inside its own cross list, and the identity graph gains a
    number that matches nothing.  Folding first removes that divergence.
    """

    text = "" if value is None else str(value)
    return normalize_cross_oem(text.upper().translate(HOMOGLYPH_FOLDING))


def normalize_characteristic_name(value: Any) -> str:
    """Fold case, homoglyphs, underscores and punctuation into one key.

    ``Назва_Характеристики#2`` and ``назва характеристики 2`` collapse to the
    same string, and so do ``Модель`` and ``Мoдель``.
    """

    text = "" if value is None else str(value)
    folded = text.upper().translate(HOMOGLYPH_FOLDING).casefold()
    return _NAME_CLEAN_RE.sub(" ", folded.replace("_", " ")).strip()


def load_characteristics_config(path: str | Path) -> CharacteristicsConfig:
    """Load and validate the characteristics contract, hashing its bytes.

    Fail-closed: a malformed or unknown-schema file raises instead of silently
    degrading into "no characteristics recognized", which would look exactly
    like an export that stopped carrying them.
    """

    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise CharacteristicsContractError(
            f"Characteristics configuration does not exist: {source_path}"
        )
    raw = source_path.read_bytes()
    try:
        payload: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise CharacteristicsContractError(
            "Characteristics configuration is not valid YAML"
        ) from exc
    if not isinstance(payload, Mapping):
        raise CharacteristicsContractError(
            "Characteristics configuration root must be a mapping"
        )
    if payload.get("schema_version") != CATALOG_CHARACTERISTICS_SCHEMA_VERSION:
        raise CharacteristicsContractError(
            f"Unsupported characteristics schema: {payload.get('schema_version')!r}"
        )
    method_version = _required_text(payload.get("method_version"), "method_version")

    headers = payload.get("column_headers")
    if not isinstance(headers, Mapping):
        raise CharacteristicsContractError("column_headers must be a mapping")
    name_prefixes = _normalized_prefixes(headers.get("name_prefixes"), "name_prefixes")
    value_prefixes = _normalized_prefixes(
        headers.get("value_prefixes"), "value_prefixes"
    )

    limits = _load_limits(payload.get("limits"))

    records = payload.get("characteristics")
    if not isinstance(records, list) or not records:
        raise CharacteristicsContractError("characteristics must be a non-empty list")
    rules: list[CharacteristicRule] = []
    by_name: dict[str, CharacteristicRule] = {}
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise CharacteristicsContractError(
                f"characteristics[{index}] must be a mapping"
            )
        rule_field = _required_text(
            record.get("field"), f"characteristics[{index}].field"
        )
        if rule_field not in KNOWN_FIELDS:
            raise CharacteristicsContractError(
                f"characteristics[{index}].field is unknown: {rule_field!r}"
            )
        names = record.get("names")
        if not isinstance(names, list) or not names:
            raise CharacteristicsContractError(
                f"characteristics[{index}].names must be a non-empty list"
            )
        normalized_names: list[str] = []
        for name in names:
            key = normalize_characteristic_name(name)
            if not key:
                raise CharacteristicsContractError(
                    f"characteristics[{index}] contains an empty name"
                )
            if key in by_name:
                raise CharacteristicsContractError(
                    f"characteristic name is claimed twice: {name!r}"
                )
            normalized_names.append(key)
        separators = record.get("separators", [])
        if not isinstance(separators, list) or not all(
            isinstance(item, str) and item for item in separators
        ):
            raise CharacteristicsContractError(
                f"characteristics[{index}].separators must be a list of strings"
            )
        rule = CharacteristicRule(
            field=rule_field,
            names=tuple(normalized_names),
            separators=tuple(separators),
        )
        rules.append(rule)
        for key in normalized_names:
            by_name[key] = rule

    return CharacteristicsConfig(
        schema_version=CATALOG_CHARACTERISTICS_SCHEMA_VERSION,
        method_version=method_version,
        name_prefixes=name_prefixes,
        value_prefixes=value_prefixes,
        limits=limits,
        rules=tuple(rules),
        rules_by_name=by_name,
        source_sha256=hashlib.sha256(raw).hexdigest(),
    )


def characteristic_column_pairs(
    headers: Sequence[str], config: CharacteristicsConfig
) -> CharacteristicColumns:
    """Pair every name column with its value column, by header not by offset.

    Pairing is positional between the two ordered lists rather than
    ``name_index + 2``: the unit column is optional in some exports, and an
    offset assumption would silently read units as values.  A workbook whose
    name and value columns do not come in equal numbers is still usable, but it
    is reported rather than quietly truncated.
    """

    names = [
        index
        for index, header in enumerate(headers)
        if _has_prefix(normalize_characteristic_name(header), config.name_prefixes)
    ]
    values = [
        index
        for index, header in enumerate(headers)
        if _has_prefix(normalize_characteristic_name(header), config.value_prefixes)
    ]
    return CharacteristicColumns(
        pairs=tuple(zip(names, values, strict=False)),
        balanced=len(names) == len(values),
    )


def collect_characteristics(
    values: Sequence[Any],
    pairs: Sequence[tuple[int, int]],
) -> dict[str, list[str]]:
    """Read one row's characteristics, keeping the seller's original spelling."""

    collected: dict[str, list[str]] = {}
    for name_index, value_index in pairs:
        name = _text(values[name_index] if name_index < len(values) else None)
        value = _text(values[value_index] if value_index < len(values) else None)
        if not name:
            continue
        collected.setdefault(name, []).append(value)
    return collected


def extract_characteristics(
    collected: Mapping[str, Sequence[str]],
    config: CharacteristicsConfig,
    *,
    self_numbers: Iterable[str] = (),
    columns_balanced: bool = True,
) -> CharacteristicsExtraction:
    """Turn one row's raw characteristics into structured identity fields."""

    limits = config.limits
    own = {
        normalized
        for normalized in (normalize_part_number(value) for value in self_numbers)
        if normalized
    }

    numbers_raw: list[str] = []
    numbers_norm: list[str] = []
    seen_numbers: set[str] = set()
    brands: list[str] = []
    models: list[str] = []
    unrecognized: list[str] = []
    anomalies: list[str] = []
    self_references = 0
    if not columns_balanced:
        anomalies.append(ANOMALY_UNBALANCED_COLUMNS)

    for name, raw_values in collected.items():
        rule = config.rules_by_name.get(normalize_characteristic_name(name))
        if rule is None:
            unrecognized.append(name)
            continue
        if rule.field == FIELD_PART_NUMBERS:
            for token, normalized, anomaly in _iter_numbers(raw_values, rule, limits):
                if anomaly is not None:
                    _record(anomalies, anomaly)
                    continue
                if normalized in own:
                    self_references += 1
                    continue
                if normalized in seen_numbers:
                    continue
                if len(numbers_norm) >= limits.max_part_numbers:
                    _record(anomalies, ANOMALY_PART_NUMBERS_TRUNCATED)
                    break
                seen_numbers.add(normalized)
                numbers_raw.append(token)
                numbers_norm.append(normalized)
        elif rule.field in {FIELD_APPLICABILITY_BRAND, FIELD_APPLICABILITY_MODEL}:
            target = brands if rule.field == FIELD_APPLICABILITY_BRAND else models
            for value in _iter_applicability(raw_values, rule, limits):
                if value in target:
                    continue
                if len(target) >= limits.max_applicability_values:
                    _record(anomalies, ANOMALY_APPLICABILITY_TRUNCATED)
                    break
                target.append(value)

    return CharacteristicsExtraction(
        part_numbers_raw=tuple(numbers_raw),
        part_numbers_norm=tuple(numbers_norm),
        applicability_brands=tuple(brands),
        applicability_models=tuple(models),
        characteristics_raw={name: list(values) for name, values in collected.items()},
        unrecognized_names=tuple(dict.fromkeys(unrecognized)),
        anomalies=tuple(dict.fromkeys(anomalies)),
        dropped_self_references=self_references,
    )


def _iter_numbers(
    raw_values: Sequence[str],
    rule: CharacteristicRule,
    limits: CharacteristicsLimits,
) -> Iterable[tuple[str, str, str | None]]:
    for raw_value in raw_values:
        for token in _split(raw_value, rule.separators):
            token = token.strip()
            if not token:
                continue
            if len(token) > limits.max_value_length:
                yield token, "", ANOMALY_VALUE_TOO_LONG
                continue
            # Normalization drops inner spaces on purpose: the export writes the
            # same number as both "115 070" and "115070".
            normalized = normalize_part_number(token)
            if len(normalized) < limits.min_number_length:
                yield token, normalized, ANOMALY_NUMBER_TOO_SHORT
                continue
            if len(normalized) > limits.max_number_length:
                yield token, normalized, ANOMALY_NUMBER_TOO_LONG
                continue
            yield token, normalized, None


def _iter_applicability(
    raw_values: Sequence[str],
    rule: CharacteristicRule,
    limits: CharacteristicsLimits,
) -> Iterable[str]:
    for raw_value in raw_values:
        for token in _split(raw_value, rule.separators):
            token = token.strip()
            if token:
                yield token[: limits.max_value_length]


def _split(value: str, separators: Sequence[str]) -> list[str]:
    if not separators:
        return [value]
    pattern = "|".join(re.escape(separator) for separator in separators)
    return re.split(pattern, value)


def _record(anomalies: list[str], code: str) -> None:
    if code not in anomalies:
        anomalies.append(code)


def _has_prefix(value: str, prefixes: Sequence[str]) -> bool:
    return any(value.startswith(prefix) for prefix in prefixes)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, ".15g")
    return str(value).strip()


def _normalized_prefixes(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CharacteristicsContractError(f"{field} must be a non-empty list")
    prefixes: list[str] = []
    for item in value:
        normalized = normalize_characteristic_name(item)
        if not normalized:
            raise CharacteristicsContractError(f"{field} contains an empty prefix")
        prefixes.append(normalized)
    return tuple(prefixes)


def _load_limits(value: Any) -> CharacteristicsLimits:
    if not isinstance(value, Mapping):
        raise CharacteristicsContractError("limits must be a mapping")
    limits = CharacteristicsLimits(
        min_number_length=_positive_int(
            value.get("min_number_length"), "min_number_length"
        ),
        max_number_length=_positive_int(
            value.get("max_number_length"), "max_number_length"
        ),
        max_part_numbers=_positive_int(
            value.get("max_part_numbers"), "max_part_numbers"
        ),
        max_applicability_values=_positive_int(
            value.get("max_applicability_values"), "max_applicability_values"
        ),
        max_value_length=_positive_int(
            value.get("max_value_length"), "max_value_length"
        ),
    )
    if limits.min_number_length > limits.max_number_length:
        raise CharacteristicsContractError(
            "min_number_length must not exceed max_number_length"
        )
    return limits


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CharacteristicsContractError(f"{field} must be a positive integer")
    return value


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CharacteristicsContractError(f"{field} must be a non-empty string")
    return value.strip()


__all__ = [
    "CATALOG_CHARACTERISTICS_SCHEMA_VERSION",
    "CharacteristicColumns",
    "CharacteristicsConfig",
    "CharacteristicsContractError",
    "CharacteristicsExtraction",
    "HOMOGLYPH_FOLDING",
    "characteristic_column_pairs",
    "collect_characteristics",
    "extract_characteristics",
    "load_characteristics_config",
    "normalize_characteristic_name",
    "normalize_part_number",
]
