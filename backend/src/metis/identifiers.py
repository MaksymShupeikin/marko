"""Shared, conservative normalization for automotive identifiers.

NFKC deliberately does not collapse Cyrillic letters into Latin ones.  That
is correct for natural language, but inconvenient for OE/MPN values copied
under the wrong keyboard layout.  Folding every look-alike unconditionally is
also unsafe: a catalog value such as ``96182261 плоск`` would otherwise grow an
ASCII suffix from the Cyrillic annotation.

This module therefore folds only identifier-shaped occurrences:

* a token that mixes ASCII letters/digits with up to three foldable Cyrillic
  letters; or
* a one-to-three-letter Cyrillic prefix/suffix joined to a numeric token, such
  as ``КМ 533`` or ``ОЕ-123``.

Long Cyrillic words and tokens containing a non-confusable Cyrillic character
remain untouched and are removed by the final ASCII allow-list.
"""

from __future__ import annotations

from types import MappingProxyType
import re
import unicodedata


OEM_HOMOGLYPHS = MappingProxyType(
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
        "У": "Y",
        "І": "I",
        "Ј": "J",
        "Ѕ": "S",
    }
)

_OEM_HOMOGLYPH_FOLDING = str.maketrans(dict(OEM_HOMOGLYPHS))
_ALNUM_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_ASCII_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")
_OEM_JOINER_RE = re.compile(r"^[\s._/+\\\-–—]*$")
_MAX_CYRILLIC_IDENTIFIER_LETTERS = 3


def normalize_oem_identifier(value: str | None) -> str:
    """Return an uppercase ASCII OE/MPN key with conservative homoglyph folding."""

    normalized = unicodedata.normalize("NFKC", value or "").upper()
    tokens = tuple(_ALNUM_TOKEN_RE.finditer(normalized))
    if not tokens:
        return ""

    parts: list[str] = []
    cursor = 0
    for index, match in enumerate(tokens):
        parts.append(normalized[cursor : match.start()])
        token = match.group()
        if _should_fold_token(normalized, tokens, index, token):
            token = token.translate(_OEM_HOMOGLYPH_FOLDING)
        parts.append(token)
        cursor = match.end()
    parts.append(normalized[cursor:])
    return _ASCII_NON_ALNUM_RE.sub("", "".join(parts))


def _should_fold_token(
    value: str,
    tokens: tuple[re.Match[str], ...],
    index: int,
    token: str,
) -> bool:
    cyrillic = tuple(character for character in token if _is_cyrillic(character))
    if not cyrillic or any(character not in OEM_HOMOGLYPHS for character in cyrillic):
        return False

    has_ascii_latin = any("A" <= character <= "Z" for character in token)
    has_digit = any(character.isascii() and character.isdigit() for character in token)
    if has_ascii_latin:
        return True
    if has_digit:
        return len(cyrillic) <= _MAX_CYRILLIC_IDENTIFIER_LETTERS

    return (
        len(cyrillic) <= _MAX_CYRILLIC_IDENTIFIER_LETTERS
        and len(cyrillic) == len(token)
        and _has_numeric_neighbor(value, tokens, index)
    )


def _has_numeric_neighbor(
    value: str,
    tokens: tuple[re.Match[str], ...],
    index: int,
) -> bool:
    current = tokens[index]
    for neighbor_index in (index - 1, index + 1):
        if not 0 <= neighbor_index < len(tokens):
            continue
        neighbor = tokens[neighbor_index]
        if not any(
            character.isascii() and character.isdigit()
            for character in neighbor.group()
        ):
            continue
        separator = (
            value[neighbor.end() : current.start()]
            if neighbor_index < index
            else value[current.end() : neighbor.start()]
        )
        if _OEM_JOINER_RE.fullmatch(separator):
            return True
    return False


def _is_cyrillic(character: str) -> bool:
    return "CYRILLIC" in unicodedata.name(character, "")


__all__ = ["OEM_HOMOGLYPHS", "normalize_oem_identifier"]
