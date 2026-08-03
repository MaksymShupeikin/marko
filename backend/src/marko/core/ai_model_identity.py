"""Fail-closed identity rules for paid AI model snapshots.

Most model aliases are mutable and therefore cannot define an evidence cache.
The provider also publishes a small number of stable snapshot identifiers that
do not carry an ISO-date suffix.  Only those explicitly documented identifiers,
or a bounded dated snapshot, are accepted here.  A newly introduced alias must
be reviewed and added deliberately; arbitrary ``latest`` names stay rejected.
"""

from __future__ import annotations

from datetime import date
import re
from typing import Final


AI_MODEL_IDENTIFIER_MAX_LENGTH: Final[int] = 160
DOCUMENTED_STABLE_MODEL_IDS: Final[frozenset[str]] = frozenset({"gpt-5.6-luna"})
_MODEL_IDENTIFIER = re.compile(
    rf"[A-Za-z0-9][A-Za-z0-9._:/-]{{0,{AI_MODEL_IDENTIFIER_MAX_LENGTH - 1}}}",
    re.ASCII,
)
_SNAPSHOT_DATE_SUFFIX = re.compile(r"-(\d{4}-\d{2}-\d{2})$", re.ASCII)


def validated_model_identifier(value: object) -> str | None:
    """Return a storage-safe provider model id, or ``None``.

    Provider strings are untrusted metadata.  Whitespace, control characters,
    Unicode confusables and truncation are all rejected rather than normalized,
    because normalization could make two distinct provider values look equal.
    """

    if not isinstance(value, str) or value != value.strip():
        return None
    if not value or len(value) > AI_MODEL_IDENTIFIER_MAX_LENGTH or not value.isascii():
        return None
    return value if _MODEL_IDENTIFIER.fullmatch(value) else None


def is_immutable_model_snapshot(value: object) -> bool:
    """Whether ``value`` is a documented stable id or an ISO-dated snapshot."""

    identifier = validated_model_identifier(value)
    if identifier is None:
        return False
    if identifier in DOCUMENTED_STABLE_MODEL_IDS:
        return True
    matched = _SNAPSHOT_DATE_SUFFIX.search(identifier)
    if matched is None:
        return False
    try:
        date.fromisoformat(matched.group(1))
    except ValueError:
        return False
    return True


__all__ = [
    "AI_MODEL_IDENTIFIER_MAX_LENGTH",
    "DOCUMENTED_STABLE_MODEL_IDS",
    "is_immutable_model_snapshot",
    "validated_model_identifier",
]
