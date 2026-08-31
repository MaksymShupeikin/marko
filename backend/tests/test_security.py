from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from httpx import ASGITransport, AsyncClient

from marko.api import main as api_main
from marko.api.dependencies import get_workspace_manager
from marko.api.routers.v1.stores import _read_upload_limited
from marko.core.config import Settings, validate_production_settings
from marko.infrastructure.db.models import WorkspaceRole
from marko.services.auth import AuthContext
from marko.services.rate_limit import RateLimiter


def _production_settings(**overrides) -> Settings:
    values = {
        "environment": "production",
        "database_url": "postgresql+asyncpg://marko:strong-test-only@db:5432/marko",
        "firebase_project_id": "marko-test",
        "cors_origins": "https://markoprice.com",
        "trusted_hosts": "api.markoprice.com,testserver",
        "rate_limits_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_production_disables_docs_and_adds_security_headers(monkeypatch):
    monkeypatch.setattr(api_main, "get_settings", _production_settings)
    app = api_main.create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://api.markoprice.com",
    ) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            response = await client.get(path)
            assert response.status_code == 404

        response = await client.get("/api/v1/health/live")
        root = await client.get("/")

    assert response.status_code == 200
    assert response.headers["strict-transport-security"] == "max-age=31536000"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    assert len(response.headers["x-request-id"]) == 32
    assert root.json() == {"service": "Marko API"}


@pytest.mark.asyncio
async def test_security_headers_cover_invalid_host_rejection(monkeypatch):
    monkeypatch.setattr(api_main, "get_settings", _production_settings)
    app = api_main.create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://api.markoprice.com",
    ) as client:
        response = await client.get(
            "/api/v1/health/live",
            headers={"Host": "evil.example"},
        )

    assert response.status_code == 400
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize(
    "overrides",
    [
        {"debug": True},
        {"firebase_project_id": ""},
        {"rate_limits_enabled": False},
        {"hsts_max_age_seconds": 300},
        {"cors_origins": "*"},
        {"cors_origins": "http://markoprice.com"},
        {"trusted_hosts": "*"},
        {"database_url": "postgresql+asyncpg://marko:marko@db:5432/marko"},
    ],
)
def test_unsafe_production_configuration_fails_closed(overrides):
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        validate_production_settings(_production_settings(**overrides))


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [WorkspaceRole.owner, WorkspaceRole.admin])
async def test_workspace_managers_can_mutate(role):
    context = AuthContext(
        user=SimpleNamespace(),
        workspace_id=uuid4(),
        role=role,
    )
    assert await get_workspace_manager(context) is context


@pytest.mark.asyncio
async def test_workspace_member_cannot_mutate():
    context = AuthContext(
        user=SimpleNamespace(),
        workspace_id=uuid4(),
        role=WorkspaceRole.member,
    )
    with pytest.raises(HTTPException) as error:
        await get_workspace_manager(context)
    assert error.value.status_code == 403


class _FakeRedis:
    def __init__(self, result):
        self.result = result

    async def eval(self, *_args):
        return self.result


class _TrackedBytesIO(BytesIO):
    position_at_close: int | None = None

    def close(self) -> None:
        self.position_at_close = self.tell()
        super().close()


@pytest.mark.asyncio
async def test_rate_limit_returns_retry_after_without_exposing_identity():
    limiter = RateLimiter("redis://unused")
    limiter._client = _FakeRedis([13, 41])

    with pytest.raises(HTTPException) as error:
        await limiter.check(
            policy="competitor-search",
            identity="workspace-sensitive-id",
            limit=12,
            window_seconds=60,
        )

    assert error.value.status_code == 429
    assert error.value.headers == {"Retry-After": "41"}


@pytest.mark.asyncio
async def test_upload_limit_stops_reading_and_closes_file():
    source = _TrackedBytesIO(b"0123456789additional-data")
    upload = UploadFile(filename="catalog.xlsx", file=source)

    with pytest.raises(HTTPException) as error:
        await _read_upload_limited(upload, max_bytes=8)

    assert error.value.status_code == 413
    assert source.position_at_close == 9
    assert source.closed
