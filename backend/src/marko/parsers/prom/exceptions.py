"""Exceptions shared across the scraper."""

from __future__ import annotations


class RequestFailed(RuntimeError):
    """Request failed after all retries."""


class UnsafeResponse(RequestFailed):
    """Response violates the bounded fetch security contract."""


class ParseError(RuntimeError):
    """HTML does not contain the expected Apollo state."""


class ParserSchemaChanged(ParseError):
    """Apollo exists, but the recognized listing/search contract does not."""
