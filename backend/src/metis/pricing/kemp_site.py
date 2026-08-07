"""Classify numbers read off a kemp.ua product card (WP-1B).

The measurement of 2026-07-29 established the constraint this module exists to
honour: **the card's field labels are unreliable**.  Of 35 genuine vehicle OE
numbers found on aftermarket positions, 26 sat in the field labelled
``Артикул`` and only 9 in the field labelled ``ОЕ номер``; on positions whose
reference-map brand is a vehicle maker the ratio is the other way round.  So a
token's class is decided by its shape and by what we already know, never by
which field it came from.  The source field is carried along for audit only.

Deciding ``OE_CANDIDATE`` is not the same as deciding "this is an OE".  Links
built from this source are born ``REVIEW`` and cannot move a price until a
human or WP-2 confirms them, so the tokeniser errs toward the candidate bucket:
a wrong candidate costs one row in a review queue, a wrongly discarded token
loses a real OE for good.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml

from metis.pricing.crosses import normalize_cross_oem

KEMP_SITE_TOKENS_SCHEMA_VERSION = "metis-kemp-site-tokens-v1"

EXTRACTION_METHOD = "KEMP_SITE"


class KempSiteConfigError(ValueError):
    """The token configuration is absent, malformed or of an unknown schema."""


class TokenClass(str, Enum):
    """What a single token off the card turned out to be."""

    OE_CANDIDATE = "OE_CANDIDATE"
    AFTERMARKET_CROSS = "AFTERMARKET_CROSS"
    INTERNAL_CODE = "INTERNAL_CODE"
    KNOWN_ARTICLE = "KNOWN_ARTICLE"
    NOISE = "NOISE"


@dataclass(frozen=True)
class AftermarketPattern:
    name: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class KempSiteTokensConfig:
    method_version: str
    value_separators: tuple[str, ...]
    min_length: int
    max_length: int
    internal_code_pattern: re.Pattern[str]
    aftermarket_patterns: tuple[AftermarketPattern, ...]
    source_sha256: str | None = None


@dataclass(frozen=True)
class ClassifiedToken:
    """One number off the card, with everything needed to re-judge it by hand."""

    raw: str
    normalized: str
    token_class: TokenClass
    source_field: str
    matched_rule: str | None = None


@dataclass(frozen=True)
class KempSiteExtraction:
    tokens: tuple[ClassifiedToken, ...] = ()

    def of_class(self, token_class: TokenClass) -> tuple[ClassifiedToken, ...]:
        return tuple(token for token in self.tokens if token.token_class is token_class)

    @property
    def oe_candidates(self) -> tuple[ClassifiedToken, ...]:
        return self.of_class(TokenClass.OE_CANDIDATE)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KempSiteConfigError(f"{name} must be a non-empty string")
    return value.strip()


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise KempSiteConfigError(f"{name} must be a positive integer")
    return value


def _compile(pattern: Any, name: str) -> re.Pattern[str]:
    text = _text(pattern, name)
    try:
        return re.compile(text)
    except re.error as exc:
        raise KempSiteConfigError(f"{name} is not a valid regular expression") from exc


def load_kemp_site_tokens(path: str | Path) -> KempSiteTokensConfig:
    """Load and hash the token configuration, refusing anything unexpected."""

    source_path = Path(path).expanduser()
    if not source_path.is_file():
        raise KempSiteConfigError(f"Token config does not exist: {source_path}")
    raw = source_path.read_bytes()
    try:
        payload: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise KempSiteConfigError("Token config is not valid YAML") from exc
    if not isinstance(payload, dict):
        raise KempSiteConfigError("Token config root must be a mapping")
    if payload.get("schema_version") != KEMP_SITE_TOKENS_SCHEMA_VERSION:
        raise KempSiteConfigError(
            f"Unsupported token config schema: {payload.get('schema_version')!r}"
        )

    separators = payload.get("value_separators")
    if not isinstance(separators, list) or not separators:
        raise KempSiteConfigError("value_separators must be a non-empty list")
    for separator in separators:
        if not isinstance(separator, str) or len(separator) != 1:
            raise KempSiteConfigError("each value separator must be one character")

    limits = payload.get("limits")
    if not isinstance(limits, dict):
        raise KempSiteConfigError("limits must be a mapping")
    min_length = _positive_int(limits.get("min_length"), "min_length")
    max_length = _positive_int(limits.get("max_length"), "max_length")
    if min_length > max_length:
        raise KempSiteConfigError("min_length must not exceed max_length")

    patterns_payload = payload.get("aftermarket_patterns")
    if not isinstance(patterns_payload, list) or not patterns_payload:
        raise KempSiteConfigError("aftermarket_patterns must be a non-empty list")
    seen: set[str] = set()
    patterns: list[AftermarketPattern] = []
    for entry in patterns_payload:
        if not isinstance(entry, dict):
            raise KempSiteConfigError("each aftermarket pattern must be a mapping")
        name = _text(entry.get("name"), "aftermarket pattern name")
        if name in seen:
            raise KempSiteConfigError(f"Duplicate aftermarket pattern name: {name}")
        seen.add(name)
        patterns.append(
            AftermarketPattern(name=name, pattern=_compile(entry.get("pattern"), name))
        )

    return KempSiteTokensConfig(
        method_version=_text(payload.get("method_version"), "method_version"),
        value_separators=tuple(separators),
        min_length=min_length,
        max_length=max_length,
        internal_code_pattern=_compile(
            payload.get("internal_code_pattern"), "internal_code_pattern"
        ),
        aftermarket_patterns=tuple(patterns),
        source_sha256=hashlib.sha256(raw).hexdigest(),
    )


def split_tokens(value: str | None, config: KempSiteTokensConfig) -> list[str]:
    """Cut one field value into candidate tokens, keeping their raw form.

    Raw form matters: ``6455.EE`` and ``55310-4A500`` carry their punctuation as
    a signal of which marque they belong to, and ``normalize_cross_oem`` erases
    it.
    """

    if not value:
        return []
    pattern = "[" + re.escape("".join(config.value_separators)) + "]"
    return [chunk.strip() for chunk in re.split(pattern, value) if chunk.strip()]


def known_number_set(
    values: Iterable[str | None], config: KempSiteTokensConfig
) -> set[str]:
    """Normalized numbers we already hold, including parts of glued articles.

    The reference map stores ``55473/MG`` as one article; the site shows plain
    ``55473``.  Without splitting the known value the same number reads as new.
    """

    known: set[str] = set()
    for value in values:
        if not value:
            continue
        known.add(normalize_cross_oem(value))
        for token in split_tokens(value, config):
            known.add(normalize_cross_oem(token))
    known.discard("")
    return known


def classify_token(
    raw: str,
    *,
    config: KempSiteTokensConfig,
    known: set[str],
    source_field: str = "",
) -> ClassifiedToken:
    """Decide one token's class. Order of checks is the decision."""

    text = raw.strip().upper()
    normalized = normalize_cross_oem(text)

    def made(token_class: TokenClass, rule: str | None = None) -> ClassifiedToken:
        return ClassifiedToken(
            raw=raw.strip(),
            normalized=normalized,
            token_class=token_class,
            source_field=source_field,
            matched_rule=rule,
        )

    if not normalized:
        return made(TokenClass.NOISE, "EMPTY")
    if len(normalized) < config.min_length:
        return made(TokenClass.NOISE, "TOO_SHORT")
    if len(normalized) > config.max_length:
        return made(TokenClass.NOISE, "TOO_LONG")
    # Private shelf codes are an identity namespace, so formatting is not
    # semantic.  The customer files contain values such as ``7764 1257``;
    # checking the raw text lets that exact code escape as a public OE.  Keep
    # supplier-shape rules below on raw text, where hyphens do carry meaning.
    if config.internal_code_pattern.fullmatch(normalized):
        return made(TokenClass.INTERNAL_CODE, "INTERNAL_CODE_PATTERN")
    if normalized in known:
        return made(TokenClass.KNOWN_ARTICLE, "ALREADY_KNOWN")
    for pattern in config.aftermarket_patterns:
        if pattern.pattern.match(text):
            return made(TokenClass.AFTERMARKET_CROSS, pattern.name)
    return made(TokenClass.OE_CANDIDATE)


def extract_numbers(
    fields: Sequence[tuple[str, str | None]],
    *,
    config: KempSiteTokensConfig,
    known: set[str],
) -> KempSiteExtraction:
    """Classify every token of every field, in order, without deduplicating away
    the evidence.

    ``fields`` is a sequence of ``(field_name, value)`` pairs — typically
    ``[("oe", ...), ("sku", ...)]``.  Both are read; neither is trusted for what
    it is labelled (NO_9).  A number repeated across both fields is kept once,
    attributed to the field that showed it first.
    """

    tokens: list[ClassifiedToken] = []
    seen: set[str] = set()
    for source_field, value in fields:
        for raw in split_tokens(value, config):
            token = classify_token(
                raw, config=config, known=known, source_field=source_field
            )
            if token.token_class is not TokenClass.NOISE and token.normalized in seen:
                continue
            if token.token_class is not TokenClass.NOISE:
                seen.add(token.normalized)
            tokens.append(token)
    return KempSiteExtraction(tokens=tuple(tokens))
