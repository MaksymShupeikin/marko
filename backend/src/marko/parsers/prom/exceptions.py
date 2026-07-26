"""Exceptions shared across the scraper."""

from __future__ import annotations


class RequestFailed(RuntimeError):
    """Request failed after all retries.

    ``status_code`` lets callers branch on *why* a fetch failed without parsing
    the message. Prom answers a page past the end of a result set with a 301 to
    the canonical search URL, which is an end-of-pagination signal rather than
    an error, and only the status code distinguishes it from a real failure.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)

    @property
    def is_redirect(self) -> bool:
        return self.status_code is not None and 300 <= self.status_code < 400


class UnsafeResponse(RequestFailed):
    """Response violates the bounded fetch security contract."""


class ParseError(RuntimeError):
    """HTML does not contain the expected Apollo state."""


class ParserSchemaChanged(ParseError):
    """Apollo exists, but the recognized listing/search contract does not."""
