import pytest
from httpx import ASGITransport, AsyncClient

from marko.api.dependencies import get_session
from marko.api.main import app


@pytest.mark.asyncio
async def test_live_healthcheck():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readiness_maps_driver_network_failure_to_503():
    class UnavailableSession:
        async def execute(self, _statement):
            raise OSError("database DNS is unavailable")

    async def unavailable_session():
        yield UnavailableSession()

    app.dependency_overrides[get_session] = unavailable_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}
