"""Exceptions shared across the scraper."""
from __future__ import annotations


class RequestFailed(RuntimeError):
    """Request failed after all retries."""


class ParseError(RuntimeError):
    """HTML does not contain the expected Apollo state."""
