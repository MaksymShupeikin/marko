"""Exceptions shared across the scraper."""

from __future__ import annotations

from urllib.parse import parse_qsl, urljoin, urlsplit


class RequestFailed(RuntimeError):
    """Request failed after all retries.

    ``status_code`` lets callers branch on *why* a fetch failed without parsing
    the message. Prom answers a page past the end of a result set with a 301 to
    the canonical search URL, which is an end-of-pagination signal rather than
    an error, and only the status code distinguishes it from a real failure.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        request_url: str | None = None,
        redirect_location: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.request_url = request_url
        self.redirect_location = redirect_location
        super().__init__(message)

    @property
    def is_redirect(self) -> bool:
        return self.status_code is not None and 300 <= self.status_code < 400


def is_canonical_pagination_redirect(
    *,
    status_code: int | None,
    request_url: str | None,
    redirect_location: str | None,
    page_num: int,
) -> bool:
    """Recognize Prom's measured "page past the end" redirect fail-closed.

    The accepted signal is deliberately narrow: HTTP 301, page greater than
    one, same scheme/host/path, and the exact same query after removing only
    the requested ``page`` parameter. A challenge redirect, host change,
    different query, 302/307/308, or missing Location remains an error.
    """

    if status_code != 301 or page_num <= 1 or not request_url or not redirect_location:
        return False
    source = urlsplit(request_url)
    target = urlsplit(urljoin(request_url, redirect_location))
    if (
        source.scheme not in {"http", "https"}
        or target.scheme != source.scheme
        or target.netloc.casefold() != source.netloc.casefold()
        or target.path != source.path
        or target.fragment
    ):
        return False
    source_pairs = parse_qsl(source.query, keep_blank_values=True)
    target_pairs = parse_qsl(target.query, keep_blank_values=True)
    page_values = [value for key, value in source_pairs if key == "page"]
    if page_values != [str(page_num)]:
        return False
    if any(key == "page" for key, _value in target_pairs):
        return False
    source_without_page = sorted(
        (key, value) for key, value in source_pairs if key != "page"
    )
    return source_without_page == sorted(target_pairs)


class UnsafeResponse(RequestFailed):
    """Response violates the bounded fetch security contract."""


class ParseError(RuntimeError):
    """HTML does not contain the expected Apollo state."""


class ParserSchemaChanged(ParseError):
    """Apollo exists, but the recognized listing/search contract does not."""
