"""Regression proof that the complete Alembic chain renders without a DB."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_complete_offline_upgrade_sql_keeps_the_active_run_guard() -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = (
        "postgresql+asyncpg://offline:offline@localhost/marko_offline_sql"
    )
    alembic = Path(sys.executable).with_name("alembic")

    completed = subprocess.run(
        [str(alembic), "-c", "alembic.ini", "upgrade", "head", "--sql"],
        cwd=BACKEND_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "DO $marko_scope_guard$" in completed.stdout
    assert "BLOCKED_MIGRATION_20260801_0032" in completed.stdout
    assert "DO $marko_frozen_guard$" in completed.stdout
    assert "BLOCKED_MIGRATION_20260801_0035" in completed.stdout
    assert "DO $marko_review_key_guard$" in completed.stdout
    assert "BLOCKED_MIGRATION_20260801_0037" in completed.stdout
    assert "DO $marko_membership_guard$" in completed.stdout
    assert "BLOCKED_MIGRATION_20260802_0039" in completed.stdout
    assert "DO $marko_ai_cache_guard$" in completed.stdout
    assert "AI_EVIDENCE_CACHE_SOURCE_INVALID" in completed.stdout
    assert "20260805_0047" in completed.stdout
    assert "STALE_AFTER_REPARSE" in completed.stdout
    assert "SOURCE_SEMANTIC_CONFLICT" in completed.stdout
    assert "PUBLIC_NUMBER_SEMANTIC_FANOUT" in completed.stdout
    assert "20260805_0048" in completed.stdout
    assert "BLOCKED_MIGRATION_20260805_0048" in completed.stdout
    assert "ck_market_observation_sale_not_above_reference" in completed.stdout
    assert "ck_catalog_discovery_offer_sale_not_above_reference" in completed.stdout
