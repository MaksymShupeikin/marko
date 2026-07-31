"""Fitment is a later phase, and the boundary is enforced rather than asserted.

The customer's 2026-07-30 reply defines this delivery: recommend a raise or a
cut per position against the cheapest comparable offer.  Fitment appears nowhere
in it.  Its 25 endpoints are nevertheless implemented and tested, which is a
liability rather than a bonus at handover: an endpoint that answers is a
promise, and a half-delivered feature reachable by anyone poking at the API
invites exactly the "so it works, why is it not on screen" conversation.

So the split is expressed the way the repository already expresses undelivered
capability — ``pricing_comparability_v1_automatic_enabled`` is the precedent —
as a setting that is off unless a deployment opts in.  These tests pin both
halves of the boundary, because prose in a scope document drifts and a test
does not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from marko.api.main import create_app
from marko.core.config import Settings, get_settings


FITMENT_PREFIX = "/api/v1/fitment"
FRONTEND_ROUTER = (
    Path(__file__).resolve().parents[2] / "frontend/lib/core/app_router.dart"
)


@pytest.fixture(autouse=True)
def _isolate_settings_cache():
    """``get_settings`` is ``lru_cache``d, so a flag change is invisible without this.

    Cleared on the way in and on the way out: a stale entry left behind would
    leak this module's opt-in into whatever runs next.
    """

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_the_shipped_default_keeps_fitment_out_of_this_delivery() -> None:
    assert Settings().fitment_api_enabled is False


def test_no_fitment_path_is_published_by_default() -> None:
    paths = create_app().openapi()["paths"]

    assert not [path for path in paths if path.startswith(FITMENT_PREFIX)]


def test_every_fitment_path_returns_when_a_deployment_opts_in(monkeypatch) -> None:
    """The feature is deferred, not deleted: opting in restores all 25 routes."""

    monkeypatch.setenv("FITMENT_API_ENABLED", "true")
    paths = create_app().openapi()["paths"]
    fitment_paths = [path for path in paths if path.startswith(FITMENT_PREFIX)]

    assert fitment_paths, "opting in must republish the fitment surface"
    operations = sum(
        1
        for path in fitment_paths
        for method in paths[path]
        if method in {"get", "post", "put", "patch", "delete"}
    )
    assert operations == 25


def test_the_frontend_has_no_route_to_fitment() -> None:
    """The other half of the boundary: no way in through the UI either.

    The widgets under ``lib/features/fitment`` are kept, so the next phase starts
    from working code rather than a rewrite; what is absent is any route that
    would let a customer reach them during this delivery.
    """

    router_source = FRONTEND_ROUTER.read_text(encoding="utf-8")

    assert "fitment" not in router_source.casefold()
