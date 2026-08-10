"""Миграция 0037 отказывается, а не чистит чужие доказательства."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.postgres
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _enabled() -> bool:
    return os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") == "1"


def _require_disposable() -> None:
    name = make_url(os.environ.get("DATABASE_URL", "")).database or ""
    if "p15017" not in name.casefold():
        pytest.fail("DATABASE_URL must name a disposable database containing 'p15017'")


def _alembic(*args: str, env: dict | None = None):
    return subprocess.run(
        ["uv", "run", "alembic", "-c", "alembic.ini", *args],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )


def _head_revision() -> str:
    """Head из самой цепочки: литерал делал бы набор ложно-красным на каждой миграции."""

    for line in _alembic("heads").stdout.splitlines():
        candidate = line.strip()
        if candidate and not candidate.startswith("INFO"):
            return candidate.split()[0]
    raise AssertionError("alembic heads printed no revision")


@pytest.mark.skipif(not _enabled(), reason="set MARKO_RUN_POSTGRES_INTEGRATION=1")
def test_the_unique_index_is_reached_on_a_clean_database() -> None:
    """На чистой базе индекс становится уникальным и дрейфа не остаётся."""

    _require_disposable()
    assert _alembic("upgrade", "head").returncode == 0
    current = _alembic("current")
    assert _head_revision() in current.stdout, current.stdout
    check = _alembic("check")
    assert check.returncode == 0, check.stdout + check.stderr


@pytest.mark.skipif(not _enabled(), reason="set MARKO_RUN_POSTGRES_INTEGRATION=1")
def test_the_cycle_is_reversible() -> None:
    _require_disposable()
    # Проверяем именно миграцию уникального request_key. От merge-head шаг
    # ``-1`` неоднозначен по определению Alembic и тестировал бы только форму
    # графа, а не обратимость 0037.
    assert _alembic("downgrade", "20260801_0036").returncode == 0
    assert _alembic("upgrade", "20260801_0037").returncode == 0
    assert _alembic("upgrade", "head").returncode == 0
