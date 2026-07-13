import pytest
from httpx import ASGITransport, AsyncClient

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
