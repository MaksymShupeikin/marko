from __future__ import annotations

import os

from marko.api.main import create_app
from marko.core.config import get_settings


_METHODS = {"get", "post", "put", "patch", "delete"}


def _full_surface_schema() -> dict:
    """OpenAPI for every operation the image contains, fitment included.

    Fitment is unmounted by default because it belongs to a later phase, but its
    error envelopes are still shipped code and are still part of this contract.
    """

    previous = os.environ.get("FITMENT_API_ENABLED")
    os.environ["FITMENT_API_ENABLED"] = "true"
    get_settings.cache_clear()
    try:
        return create_app().openapi()
    finally:
        if previous is None:
            os.environ.pop("FITMENT_API_ENABLED", None)
        else:
            os.environ["FITMENT_API_ENABLED"] = previous
        get_settings.cache_clear()


def test_every_v1_operation_declares_shared_runtime_error_envelope() -> None:
    schema = _full_surface_schema()
    checked = 0

    for path, path_item in schema["paths"].items():
        if not path.startswith("/api/v1/"):
            continue
        for method, operation in path_item.items():
            if method not in _METHODS:
                continue
            checked += 1
            responses = operation["responses"]
            assert "500" in responses, f"{method.upper()} {path} misses HTTP 500"
            body_schema = responses["500"]["content"]["application/json"]["schema"]
            assert body_schema["$ref"].endswith("/ErrorEnvelope")

    assert checked >= 66


def test_authenticated_router_groups_declare_auth_and_validation_failures() -> None:
    schema = _full_surface_schema()
    authenticated_prefixes = (
        "/api/v1/auth",
        "/api/v1/catalog",
        "/api/v1/stores",
        "/api/v1/jobs",
        "/api/v1/operations",
        "/api/v1/pricing",
        "/api/v1/fitment",
    )

    for path, path_item in schema["paths"].items():
        if not path.startswith(authenticated_prefixes):
            continue
        for method, operation in path_item.items():
            if method not in _METHODS:
                continue
            responses = operation["responses"]
            for status_code in ("401", "422", "503"):
                assert status_code in responses, (
                    f"{method.upper()} {path} misses HTTP {status_code}"
                )
