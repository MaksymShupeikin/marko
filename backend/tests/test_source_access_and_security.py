from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from marko.api import main as api_main
from marko.api.dependencies import get_current_user
from marko.core.config import Settings
from marko.infrastructure.db.models import User, WorkspaceRole
from marko.services.auth import AuthContext
from marko.services.scrape_runtime import (
    ReplayEvidence,
    ScrapeExecutionTrace,
    request_fingerprint,
)
from marko.services.scraper_contract import (
    ScraperErrorCode,
    classify_scraper_exception,
)
from marko.services.source_access import (
    SourceAccessBlocked,
    require_live_prom_marketplace_collection,
    source_access_status,
)


def _auth_context(role: WorkspaceRole) -> AuthContext:
    return AuthContext(
        user=User(
            id=uuid4(),
            email=f"{role.value}@example.com",
            is_active=True,
        ),
        workspace_id=uuid4(),
        workspace_role=role,
    )


def test_source_access_is_fail_closed_by_default() -> None:
    settings = Settings()

    status = source_access_status(settings)

    assert status.verdict == "NOT_PERMITTED"
    assert status.live_collection_allowed is False
    with pytest.raises(SourceAccessBlocked) as blocked:
        require_live_prom_marketplace_collection(settings)
    assert blocked.value.retryable is False


def test_permitted_source_requires_an_auditable_reference() -> None:
    with pytest.raises(ValidationError, match="SOURCE_ACCESS_REFERENCE"):
        Settings(
            prom_marketplace_source_access_verdict="PERMITTED_OFFICIAL",
        )

    settings = Settings(
        prom_marketplace_source_access_verdict="PERMITTED_LIMITED",
        prom_marketplace_source_access_reference="authorization:prom:2026-07-16",
    )

    require_live_prom_marketplace_collection(settings)
    assert source_access_status(settings).live_collection_allowed is True


def test_source_access_has_terminal_scraper_error_taxonomy() -> None:
    settings = Settings()
    with pytest.raises(SourceAccessBlocked) as blocked:
        require_live_prom_marketplace_collection(settings)

    boundary = classify_scraper_exception(blocked.value)

    assert boundary.code == ScraperErrorCode.SOURCE_ACCESS_BLOCKED
    assert boundary.retryable is False


def test_replay_does_not_cross_the_live_request_gate() -> None:
    url = "https://prom.ua/ua/p1-example.html"
    request_key = request_fingerprint("product_page", url)
    gate_calls = 0

    def blocked_gate() -> None:
        nonlocal gate_calls
        gate_calls += 1
        require_live_prom_marketplace_collection(Settings())

    trace = ScrapeExecutionTrace(
        item_kind="comparison_job",
        execution_no=1,
        replay_cache={
            request_key: ReplayEvidence(
                request_key=request_key,
                body=b"<html>persisted evidence</html>",
            )
        },
        live_request_gate=blocked_gate,
    )
    request = trace.begin_request(url, None)

    replayed = trace.replay_for(request)

    assert replayed is not None
    assert replayed.content == b"<html>persisted evidence</html>"
    assert gate_calls == 0
    with pytest.raises(SourceAccessBlocked):
        trace.acquire_global_attempt_slot()
    assert gate_calls == 1


def test_production_security_configuration_is_fail_closed() -> None:
    with pytest.raises(ValidationError, match="DEBUG"):
        Settings(
            environment="production",
            debug=True,
            allowed_hosts="api.example.com",
            firebase_project_id="marko-production",
        )
    with pytest.raises(ValidationError, match="ALLOWED_HOSTS"):
        Settings(
            environment="production",
            allowed_hosts="*",
            firebase_project_id="marko-production",
        )


@pytest.mark.asyncio
async def test_production_app_disables_docs_and_sets_security_headers(
    monkeypatch,
) -> None:
    settings = Settings(
        environment="production",
        allowed_hosts="api.example.com",
        cors_origins="https://app.example.com",
        firebase_project_id="marko-production",
    )
    monkeypatch.setattr(api_main, "get_settings", lambda: settings)
    application = api_main.create_app()

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="https://api.example.com",
    ) as client:
        docs = await client.get("/docs")
        live = await client.get("/api/v1/health/live")

    assert docs.status_code == 404
    assert live.status_code == 200
    assert live.headers["x-content-type-options"] == "nosniff"
    assert live.headers["x-frame-options"] == "DENY"
    assert "max-age=31536000" in live.headers["strict-transport-security"]


@pytest.mark.asyncio
async def test_source_status_is_explicit_and_live_run_is_blocked() -> None:
    application = api_main.create_app()

    async def current_user_override() -> AuthContext:
        return _auth_context(WorkspaceRole.owner)

    application.dependency_overrides[get_current_user] = current_user_override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            source = await client.get("/api/v1/health/source-access")
            blocked = await client.post(
                "/api/v1/pricing/runs",
                json={"import_batch_id": str(uuid4())},
            )
    finally:
        application.dependency_overrides.clear()

    assert source.status_code == 200
    assert source.json()["live_collection_allowed"] is False
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "SOURCE_ACCESS_BLOCKED"


@pytest.mark.asyncio
async def test_member_cannot_start_admin_workflow() -> None:
    application = api_main.create_app()

    async def current_user_override() -> AuthContext:
        return _auth_context(WorkspaceRole.member)

    application.dependency_overrides[get_current_user] = current_user_override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/pricing/runs",
                json={"import_batch_id": str(uuid4())},
            )
    finally:
        application.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "INSUFFICIENT_WORKSPACE_ROLE"


@pytest.mark.asyncio
async def test_member_cannot_replay_dead_letter() -> None:
    application = api_main.create_app()

    async def current_user_override() -> AuthContext:
        return _auth_context(WorkspaceRole.member)

    application.dependency_overrides[get_current_user] = current_user_override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/operations/dead-letters/"
                f"pricing_target/{uuid4()}/replay"
            )
    finally:
        application.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "INSUFFICIENT_WORKSPACE_ROLE"
