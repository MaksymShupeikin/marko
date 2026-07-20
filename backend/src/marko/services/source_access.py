"""Fail-closed authorization boundary for live Prom marketplace collection.

Client-supplied exports and persisted raw-evidence replay do not cross this
boundary. Only a physical request to public marketplace pages requires a
permitted verdict backed by an auditable reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from marko.core.config import Settings, get_settings


PERMITTED_VERDICTS: Final[frozenset[str]] = frozenset(
    {"PERMITTED_OFFICIAL", "PERMITTED_LIMITED"}
)
SOURCE_ACCESS_ERROR_CODE: Final[str] = "SOURCE_ACCESS_BLOCKED"


class SourceAccessBlocked(RuntimeError):
    """Raised before an unapproved physical marketplace request is attempted."""

    code = SOURCE_ACCESS_ERROR_CODE
    retryable = False

    def __init__(self, status: SourceAccessStatus) -> None:
        self.verdict = status.verdict
        self.reference = status.reference
        super().__init__(
            "Live Prom marketplace collection is blocked "
            f"(verdict={status.verdict}). Use client-supplied exports or "
            "persisted evidence replay until an official feed or written "
            "authorization is recorded."
        )


@dataclass(frozen=True)
class SourceAccessStatus:
    source: str
    verdict: str
    reference: str | None
    live_collection_allowed: bool

    def as_dict(self) -> dict[str, str | bool | None]:
        return {
            "source": self.source,
            "verdict": self.verdict,
            "reference": self.reference,
            "live_collection_allowed": self.live_collection_allowed,
        }


def source_access_status(settings: Settings | None = None) -> SourceAccessStatus:
    resolved = settings or get_settings()
    reference = resolved.prom_marketplace_source_access_reference.strip() or None
    verdict = resolved.prom_marketplace_source_access_verdict
    return SourceAccessStatus(
        source="prom_public_marketplace",
        verdict=verdict,
        reference=reference,
        live_collection_allowed=(
            verdict in PERMITTED_VERDICTS and reference is not None
        ),
    )


def require_live_prom_marketplace_collection(
    settings: Settings | None = None,
) -> None:
    status = source_access_status(settings)
    if not status.live_collection_allowed:
        raise SourceAccessBlocked(status)


__all__ = [
    "PERMITTED_VERDICTS",
    "SOURCE_ACCESS_ERROR_CODE",
    "SourceAccessBlocked",
    "SourceAccessStatus",
    "require_live_prom_marketplace_collection",
    "source_access_status",
]
