import pytest
from httpx import ASGITransport, AsyncClient

from marko.api.dependencies import get_session
from marko.api.main import app
from marko.services.schema_state import code_schema_head


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


class _RevisionSession:
    """Session double answering ``SELECT 1`` and the alembic_version query."""

    def __init__(self, revision: str | None) -> None:
        self._revision = revision

    async def execute(self, _statement):
        return None

    async def scalar(self, _statement):
        if self._revision is None:
            raise RuntimeError('relation "alembic_version" does not exist')
        return self._revision


async def _ready_with_revision(revision: str | None):
    async def session_override():
        yield _RevisionSession(revision)

    app.dependency_overrides[get_session] = session_override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_readiness_passes_when_the_database_is_at_the_shipped_head():
    response = await _ready_with_revision(code_schema_head())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readiness_refuses_a_database_behind_the_shipped_head():
    """F2-0015: устаревший образ против старого тома больше не «healthy»."""
    response = await _ready_with_revision("20260728_0024")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "SCHEMA_REVISION_MISMATCH"
    assert detail["database_revision"] == "20260728_0024"
    assert detail["code_head"] == code_schema_head()
    assert detail["in_sync"] is False


@pytest.mark.asyncio
async def test_readiness_refuses_an_unmigrated_database():
    response = await _ready_with_revision(None)

    assert response.status_code == 503
    assert response.json()["detail"]["database_revision"] is None


@pytest.mark.asyncio
async def test_schema_revision_endpoint_reports_both_sides():
    async def session_override():
        yield _RevisionSession("20260728_0024")

    app.dependency_overrides[get_session] = session_override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/health/schema-revision")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    assert response.json() == {
        "code_head": code_schema_head(),
        "database_revision": "20260728_0024",
        "in_sync": False,
    }


def test_migration_graph_has_exactly_one_head():
    """Две head-ревизии сделали бы сравнение в readiness неопределённым."""
    assert code_schema_head() is not None
