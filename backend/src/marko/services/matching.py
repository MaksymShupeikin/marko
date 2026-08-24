"""Similarity scoring for product-name matching."""
from __future__ import annotations

import re

# Tokens carrying no discriminative value for product-name similarity.
_STOPWORDS: frozenset[str] = frozenset({
    "для", "від", "до", "та", "і", "в", "на", "з", "по", "the", "for", "and",
    "шт", "уп", "грн", "оригінал", "новий", "нова", "нове",
})
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_MIN_TOKEN_LENGTH = 2  # drop single-character noise tokens


def normalize_tokens(name: str | None) -> list[str]:
    """Lowercase word tokens with stopwords and single-char noise removed."""
    if not name:
        return []
    return [
        token
        for token in _WORD_RE.findall(name.lower())
        if len(token) >= _MIN_TOKEN_LENGTH and token not in _STOPWORDS
    ]


def token_similarity(tokens_a: set[str], tokens_b: set[str]) -> float:
    """Token-set similarity in [0, 1]: an equal blend of Jaccard and containment."""
    if not tokens_a or not tokens_b:
        return 0.0
    inter = len(tokens_a & tokens_b)
    jaccard = inter / len(tokens_a | tokens_b)
    containment = inter / min(len(tokens_a), len(tokens_b))
    return round(0.5 * jaccard + 0.5 * containment, 3)


# Antonym groups: parts differing only by one of these are NOT the same item.
# Each group lists mutually-exclusive "sides" as token prefixes (ua + ru forms).
_ANTONYM_GROUPS: tuple[tuple[frozenset[str], ...], ...] = (
    (frozenset({"лів", "лев"}), frozenset({"прав"})),   # лівий / правий (left / right)
    (frozenset({"перед"}), frozenset({"задн"})),        # передній / задній (front / rear)
    (frozenset({"верхн"}), frozenset({"нижн"})),        # верхній / нижній (upper / lower)
)


def _side_in_group(tokens: list[str], group: tuple[frozenset[str], ...]) -> int | None:
    """Index of the side whose prefix matches any token, or None if unspecified."""
    for idx, side in enumerate(group):
        if any(tok.startswith(pref) for tok in tokens for pref in side):
            return idx
    return None


def laterality_conflict(a_tokens: list[str], b_tokens: list[str]) -> bool:
    """True when both names explicitly name opposite sides (e.g. left vs right)."""
    for group in _ANTONYM_GROUPS:
        sa = _side_in_group(a_tokens, group)
        sb = _side_in_group(b_tokens, group)
        if sa is not None and sb is not None and sa != sb:
            return True
    return False


def _norm_brand(brand: str | None) -> str:
    return (brand or "").strip().lower()


def brands_compatible(seed: str | None, cand: str | None) -> bool:
    """Brands match, or at least one is unknown (do not reject on missing data)."""
    a, b = _norm_brand(seed), _norm_brand(cand)
    return not a or not b or a == b
