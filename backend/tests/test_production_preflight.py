"""PROMPT_15_015 P-001..P-025 strict preflight and canary matrix."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marko.governance.production_preflight import (
    render_human,
    render_json,
    run_preflight,
)


CANARY_DB = "CANARY_DB_PASSWORD_7f15a9"
CANARY_REDIS = "CANARY_REDIS_PASSWORD_9a51b7"


def _base() -> dict[str, str]:
    return {
        "ENVIRONMENT": "production",
        "DEBUG": "false",
        "API_DOCS_ENABLED": "false",
        "DATABASE_URL": f"postgresql+asyncpg://marko:{CANARY_DB}@db.prod.marko.internal:5432/marko",
        "CELERY_BROKER_URL": f"rediss://marko:{CANARY_REDIS}@redis.prod.marko.internal:6380/0",
        "CELERY_RESULT_BACKEND": f"rediss://marko:{CANARY_REDIS}@redis.prod.marko.internal:6380/1",
        "ALLOWED_HOSTS": "api.prod.marko.internal",
        "CORS_ORIGINS": "https://app.prod.marko.internal",
        "FIREBASE_PROJECT_ID": "marko-prod-8a7",
        "PUBLIC_API_BASE_URL": "https://api.prod.marko.internal",
        "APP_DOMAIN": "app.prod.marko.internal",
        "API_DOMAIN": "api.prod.marko.internal",
        "ACME_EMAIL": "ops@prod.marko.internal",
        "TRUSTED_PROXY_IPS": "*",
        "FIREBASE_API_KEY": "AIzaSyD-safe-public-id-8a7",
        "FIREBASE_AUTH_DOMAIN": "marko-prod-8a7.firebaseapp.com",
        "FIREBASE_MESSAGING_SENDER_ID": "4815162342",
        "FIREBASE_WEB_APP_ID": "1:4815162342:web:a1b2c3d4",
        "PROM_MARKETPLACE_SOURCE_ACCESS_VERDICT": "NOT_PERMITTED",
        "PROM_MARKETPLACE_SOURCE_ACCESS_REFERENCE": "",
        "PRICING_V3_ROBUST_DISPERSION_ENABLED": "false",
        "PRICING_COMPARABILITY_V1_AUTOMATIC_ENABLED": "false",
        "E2E_AUTH_BYPASS": "false",
        "E2E_AUTH_TOKEN": "",
    }


def _write(
    path: Path,
    values: dict[str, str],
    *,
    duplicate: tuple[str, str] | None = None,
    mode: int = 0o600,
) -> Path:
    lines = [f"{key}={value}" for key, value in values.items()]
    if duplicate:
        lines.append(f"{duplicate[0]}={duplicate[1]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(mode)
    return path


def _reason_codes(result) -> set[str]:
    return {reason for check in result.checks for reason in check.reason_codes}


def _static_variation(case_id: str, values: dict[str, str]):
    duplicate = None
    mode = 0o600
    if case_id == "P-001":
        values.pop("ENVIRONMENT")
    elif case_id == "P-002":
        values["ENVIRONMENT"] = "development"
    elif case_id == "P-003":
        values["DEBUG"] = "true"
    elif case_id == "P-004":
        values["API_DOCS_ENABLED"] = "true"
    elif case_id == "P-005":
        values["DATABASE_URL"] = (
            "postgresql+asyncpg://user:secret@db.example.com:5432/marko"
        )
    elif case_id == "P-006":
        values["DATABASE_URL"] = (
            "postgresql+asyncpg://USER:PASSWORD@db.prod.marko.internal:5432/marko"
        )
    elif case_id == "P-007":
        values["DATABASE_URL"] = (
            "postgresql+asyncpg://marko:secret@PRIVATE_POSTGRES_HOST:5432/marko"
        )
    elif case_id == "P-008":
        values["CELERY_BROKER_URL"] = "rediss://marko:secret@PRIVATE_REDIS_HOST:6380/0"
    elif case_id == "P-009":
        values["CELERY_BROKER_URL"] = (
            "redis://marko:secret@redis.prod.marko.internal:6379/0"
        )
    elif case_id == "P-010":
        values["ALLOWED_HOSTS"] = "api.example.com"
    elif case_id == "P-011":
        values["ALLOWED_HOSTS"] = "*"
    elif case_id == "P-012":
        values["CORS_ORIGINS"] = "https://app.example.com"
    elif case_id == "P-013":
        values["CORS_ORIGINS"] = "http://app.prod.marko.internal"
    elif case_id == "P-014":
        values["FIREBASE_PROJECT_ID"] = "your-firebase-project"
    elif case_id == "P-015":
        values["FIREBASE_API_KEY"] = "replace"
    elif case_id == "P-016":
        duplicate = ("DEBUG", "true")
    elif case_id == "P-017":
        values["DATABASE_URL"] = "://not-a-url"
    elif case_id == "P-023":
        values["E2E_AUTH_BYPASS"] = "true"
    elif case_id == "P-024":
        values["PRICING_V3_ROBUST_DISPERSION_ENABLED"] = "true"
    elif case_id == "P-025":
        mode = 0o644
    else:
        raise AssertionError(case_id)
    return values, duplicate, mode


@pytest.mark.parametrize(
    "case_id",
    (
        "P-001",
        "P-002",
        "P-003",
        "P-004",
        "P-005",
        "P-006",
        "P-007",
        "P-008",
        "P-009",
        "P-010",
        "P-011",
        "P-012",
        "P-013",
        "P-014",
        "P-015",
        "P-016",
        "P-017",
        "P-023",
        "P-024",
        "P-025",
    ),
)
def test_static_negative_matrix(case_id: str, tmp_path: Path) -> None:
    values, duplicate, mode = _static_variation(case_id, _base())
    path = _write(tmp_path / f"{case_id}.env", values, duplicate=duplicate, mode=mode)
    result = run_preflight(path, mode="static")
    assert not result.passed, case_id
    assert _reason_codes(result), case_id


def test_p018_unreachable_database_fails_connectivity(tmp_path: Path) -> None:
    values = _base()
    values["DATABASE_URL"] = "postgresql+asyncpg://marko:secret@203.0.113.1:5432/marko"
    path = _write(tmp_path / "P-018.env", values)
    result = run_preflight(path, mode="connectivity", connectivity_timeout=0.05)
    assert not result.passed
    assert any("DATABASE_URL_UNREACHABLE" in code for code in _reason_codes(result))


def _e2e_evidence(**overrides) -> dict:
    values = {
        "status": "PASS",
        "clean_migration_passed": True,
        "runtime_services_passed": True,
        "celery_workers_passed": True,
        "scheduler_singleton_passed": True,
        "frontend_served": True,
        "business_workflow_passed": True,
        "replay_exact": True,
        "duplicate_delivery_safe": True,
        "failure_matrix_passed": True,
        "cleanup_complete": True,
        "live_prom_requests": 0,
        "automatic_price_applications": 0,
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    ("case_id", "override", "expected_reason"),
    (
        (
            "P-019",
            {"clean_migration_passed": False},
            "PREFLIGHT_DATABASE_SCHEMA_FAILED",
        ),
        ("P-021", {"celery_workers_passed": False}, "PREFLIGHT_CELERY_WORKERS_FAILED"),
        (
            "P-022",
            {"scheduler_singleton_passed": False},
            "PREFLIGHT_SCHEDULER_SINGLETON_FAILED",
        ),
    ),
)
def test_full_evidence_negative_matrix(
    case_id: str,
    override: dict[str, bool],
    expected_reason: str,
    tmp_path: Path,
) -> None:
    env_path = _write(tmp_path / f"{case_id}.env", _base())
    evidence = tmp_path / f"{case_id}.json"
    evidence.write_text(json.dumps(_e2e_evidence(**override)), encoding="utf-8")
    result = run_preflight(
        env_path,
        mode="full",
        e2e_evidence=evidence,
        connectivity_timeout=0.01,
    )
    assert not result.passed
    assert expected_reason in _reason_codes(result)


def test_p020_redis_tls_or_auth_failure_is_secret_safe(tmp_path: Path) -> None:
    values = _base()
    values["CELERY_BROKER_URL"] = f"rediss://marko:{CANARY_REDIS}@203.0.113.2:6380/0"
    path = _write(tmp_path / "P-020.env", values)
    result = run_preflight(path, mode="connectivity", connectivity_timeout=0.05)
    rendered = render_json(result) + render_human(result)
    assert not result.passed
    assert CANARY_REDIS not in rendered


def test_valid_static_config_passes_without_emitting_canaries(tmp_path: Path) -> None:
    path = _write(tmp_path / "valid.env", _base())
    result = run_preflight(path, mode="static")
    rendered = render_json(result) + render_human(result)
    assert result.passed, result.blockers
    assert CANARY_DB not in rendered
    assert CANARY_REDIS not in rendered
    assert result.secrets_emitted is False


def test_edge_domain_mismatch_fails_static_preflight(tmp_path: Path) -> None:
    values = _base()
    values["PUBLIC_API_BASE_URL"] = "https://different.prod.marko.internal"
    path = _write(tmp_path / "edge-mismatch.env", values)

    result = run_preflight(path, mode="static")

    assert not result.passed
    assert "PREFLIGHT_EDGE_TOPOLOGY_MISMATCH" in _reason_codes(result)


def test_full_mode_cannot_pass_when_connectivity_and_workflow_are_skipped(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path / "full.env", _base())
    result = run_preflight(path, mode="full", connectivity_timeout=0.01)
    assert not result.passed
    statuses = {check.layer: check.status for check in result.checks}
    assert statuses["P5_DATABASE_SCHEMA"] == "BLOCKED"
    assert statuses["P7_WORKFLOW_SMOKE"] == "BLOCKED"


def test_blocked_e2e_status_cannot_be_reinterpreted_as_full_pass(
    tmp_path: Path,
) -> None:
    env_path = _write(tmp_path / "blocked.env", _base())
    evidence = tmp_path / "blocked.yaml"
    evidence.write_text(
        "e2e_evidence:\n"
        "  status: BLOCKED_ENVIRONMENT\n"
        "  clean_migration_passed: true\n"
        "  runtime_services_passed: true\n"
        "  celery_workers_passed: true\n"
        "  scheduler_singleton_passed: true\n"
        "  frontend_served: true\n"
        "  business_workflow_passed: true\n"
        "  replay_exact: true\n"
        "  duplicate_delivery_safe: true\n"
        "  failure_matrix_passed: true\n"
        "  cleanup_complete: true\n"
        "  live_prom_requests: 0\n"
        "  automatic_price_applications: 0\n",
        encoding="utf-8",
    )
    result = run_preflight(
        env_path,
        mode="full",
        e2e_evidence=evidence,
        connectivity_timeout=0.01,
    )
    assert not result.passed
    assert "PREFLIGHT_DATABASE_SCHEMA_FAILED" in _reason_codes(result)
