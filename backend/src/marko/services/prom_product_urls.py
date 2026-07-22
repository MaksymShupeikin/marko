"""Validation helpers for canonical Prom product URLs."""

from __future__ import annotations

import re
from urllib.parse import urlsplit


_PRODUCT_PATH_RE = re.compile(
    r"^/(?:[a-z]{2}/)?p(?P<id>\d+)-[\w-]+\.html$",
    re.IGNORECASE,
)


def validate_product_url(url: str) -> int:
    """Return the product ID for an HTTPS Prom product URL.

    Reject credentials, non-default ports, query strings, fragments, and
    lookalike hosts before a caller performs any network request.
    """

    parsed = urlsplit(url)
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() not in {"prom.ua", "www.prom.ua"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"unsafe or unsupported Prom product URL: {url!r}")
    match = _PRODUCT_PATH_RE.fullmatch(parsed.path)
    if match is None:
        raise ValueError(f"unsupported Prom product path: {parsed.path!r}")
    return int(match.group("id"))


__all__ = ["validate_product_url"]
