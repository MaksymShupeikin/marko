"""Make tests independent from the developer's uncommitted root ``.env``."""

import os

import pytest


os.environ["API_DOCS_ENABLED"] = "false"
os.environ["FIREBASE_PROJECT_ID"] = ""
os.environ["PROM_MARKETPLACE_SOURCE_ACCESS_VERDICT"] = "NOT_PERMITTED"
os.environ["PROM_MARKETPLACE_SOURCE_ACCESS_REFERENCE"] = ""
os.environ["E2E_AUTH_BYPASS"] = "false"
os.environ["E2E_AUTH_TOKEN"] = ""
os.environ["E2E_TASK_HOLD_SECONDS"] = "0"
os.environ["COST_PRIVACY_MODE"] = "UNDECIDED"
os.environ["COST_ENCRYPTION_ACTIVE_KEY_ID"] = ""
os.environ["COST_ENCRYPTION_KEYS_JSON"] = ""


_SCHEMA_READY = False


def _ensure_schema_at_head() -> None:
    """Migrate the disposable database once before the first ``postgres`` test.

    Only ``test_verified_identity_postgres`` drives Alembic itself, so any other
    opt-in suite passed or failed purely by collection order. Bringing the
    schema to head up front makes each of them runnable on its own.
    """

    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    import pathlib
    import subprocess

    backend_root = pathlib.Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        ["uv", "run", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=backend_root,
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _SCHEMA_READY = True


@pytest.fixture(autouse=True)
async def _isolate_database_engine_per_event_loop(request):
    """Give every ``postgres`` test a connection pool bound to its own loop.

    ``marko.infrastructure.db.session.engine`` is created once at import time.
    Under ``asyncio_mode = "auto"`` each test runs in a fresh event loop, so a
    pool populated by an earlier test hands out connections attached to a loop
    that is already closed. Alone the opt-in suites pass; in a full run they
    fail with "attached to a different loop". Disposing around each such test
    keeps them runnable both ways.
    """

    if request.node.get_closest_marker("postgres") is None:
        yield
        return

    _ensure_schema_at_head()

    from marko.infrastructure.db.session import engine

    await engine.dispose()
    try:
        yield
    finally:
        await engine.dispose()
