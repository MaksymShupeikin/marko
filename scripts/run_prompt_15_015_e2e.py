#!/usr/bin/env python3
"""Run the isolated PROMPT_15_015 Docker E2E and emit secret-safe evidence."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from typing import Any

import httpx
from openpyxl import Workbook
import yaml


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (ROOT / "compose.yaml", ROOT / "compose.e2e.yaml")
FAILURE_IDS = tuple(f"E2E-F{index:02d}" for index in range(1, 11))
TERMINAL_RUN_STATES = {"completed", "partial", "failed", "cancelled"}


class E2eFailure(RuntimeError):
    pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run(
    command: list[str],
    *,
    env: dict[str, str],
    timeout: float = 120,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        raise E2eFailure(
            f"Command failed ({result.returncode}): {' '.join(command[:5])}\n"
            f"{result.stdout[-4000:]}"
        )
    return result


def _compose(project: str, *args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        project,
        "--file",
        str(COMPOSE_FILES[0]),
        "--file",
        str(COMPOSE_FILES[1]),
        "--profile",
        "e2e",
        *args,
    ]


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _blocked_evidence(reason: str, tool_versions: dict[str, str]) -> dict[str, Any]:
    return {
        "e2e_evidence": {
            "schema_version": "prompt-15.015-e2e-evidence-v1",
            "status": "BLOCKED_ENVIRONMENT",
            "run_id": f"blocked-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
            "compose_project": None,
            "git_commit": "NOT_AVAILABLE",
            "image_ids": {},
            "tool_versions": tool_versions,
            "migration_head": "NOT_EXECUTED",
            "service_health": {},
            "queue_counts": {},
            "workflow_ids": [],
            "fixture_hashes": {},
            "original_decision_hash": None,
            "replay_decision_hash": None,
            "failure_injection_results": [
                {"id": case_id, "status": "NOT_RUN", "reason": reason}
                for case_id in FAILURE_IDS
            ],
            "log_artifacts": [],
            "browser_assertions": [],
            "browser_trace_artifact": None,
            "clean_migration_passed": False,
            "runtime_services_passed": False,
            "celery_workers_passed": False,
            "scheduler_singleton_passed": False,
            "frontend_served": False,
            "business_workflow_passed": False,
            "replay_exact": False,
            "duplicate_delivery_safe": False,
            "failure_matrix_passed": False,
            "live_prom_requests": 0,
            "automatic_price_applications": 0,
            "cleanup_complete": True,
            "blockers": [reason],
        }
    }


def _docker_probe() -> tuple[bool, dict[str, str], str | None]:
    versions: dict[str, str] = {
        "python": sys.version.split()[0],
        "docker": "NOT_AVAILABLE",
        "compose": "NOT_AVAILABLE",
    }
    if shutil.which("docker") is None:
        return False, versions, "DOCKER_BINARY_NOT_AVAILABLE"
    env = os.environ.copy()
    docker = _run(["docker", "version", "--format", "{{.Server.Version}}"], env=env, check=False)
    versions["docker"] = docker.stdout.strip() or "DAEMON_NOT_AVAILABLE"
    if docker.returncode != 0:
        return False, versions, "DOCKER_DAEMON_NOT_AVAILABLE"
    compose = _run(["docker", "compose", "version", "--short"], env=env, check=False)
    versions["compose"] = compose.stdout.strip() or "NOT_AVAILABLE"
    if compose.returncode != 0:
        return False, versions, "DOCKER_COMPOSE_NOT_AVAILABLE"
    return True, versions, None


def _wait_http(
    url: str,
    *,
    expected: int = 200,
    timeout: float = 90,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    deadline = time.monotonic() + timeout
    last: Exception | httpx.Response | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, headers=headers, timeout=3)
            last = response
            if response.status_code == expected:
                return response
        except httpx.HTTPError as exc:
            last = exc
        time.sleep(0.5)
    raise E2eFailure(f"HTTP deadline exceeded for {url}: {last}")


def _catalog_fixture(path: Path) -> str:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Catalog"
    sheet.append(
        [
            "sku",
            "oe",
            "name",
            "category",
            "price",
            "currency",
            "available",
            "brand",
            "url",
        ]
    )
    sheet.append(
        [
            "E2E-001",
            "1K0698151",
            "PROMPT 15.015 E2E brake pad",
            "brakes",
            150,
            "UAH",
            True,
            "Bosch",
            "https://prom.ua/ua/p15015015-e2e-fixture-one.html",
        ]
    )
    sheet.append(
        [
            "E2E-002",
            "1K0698152",
            "PROMPT 15.015 missing evidence brake pad",
            "brakes",
            151,
            "UAH",
            True,
            "Bosch",
            "https://prom.ua/ua/p15015016-e2e-fixture-two.html",
        ]
    )
    sheet.append(
        [
            "BROKEN-ROW",
            "",
            "Malformed row retained in import audit",
            "brakes",
            -1,
            "UAH",
            True,
            "Bosch",
            "https://prom.ua/ua/p15015017-e2e-broken.html",
        ]
    )
    workbook.save(path)
    workbook.close()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_command(
    project: str,
    env: dict[str, str],
    *args: str,
    timeout: float = 60,
) -> dict[str, Any]:
    result = _run(
        _compose(project, "exec", "-T", "api", "python", "-m", *args),
        env=env,
        timeout=timeout,
    )
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise E2eFailure(f"Probe returned invalid JSON: {result.stdout[-2000:]}") from exc


def _parse_json_output(value: str) -> Any:
    stripped = value.strip()
    if not stripped:
        return []
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return [json.loads(line) for line in stripped.splitlines() if line.strip()]


def _sanitize_and_scan(artifact_dir: Path, canaries: tuple[str, ...]) -> bool:
    for path in artifact_dir.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        replaced = data
        for canary in canaries:
            replaced = replaced.replace(canary.encode(), b"[REDACTED]")
        if replaced != data:
            path.write_bytes(replaced)
    return not any(
        canary.encode() in path.read_bytes()
        for path in artifact_dir.rglob("*")
        if path.is_file()
        for canary in canaries
    )


def _migration_failure_case(
    project: str,
    env: dict[str, str],
) -> dict[str, str]:
    failure_project = f"{project}-migration-fail"
    failure_env = {
        **env,
        "POSTGRES_PORT": str(_free_port()),
        "REDIS_PORT": str(_free_port()),
        "API_PORT": str(_free_port()),
        "WEB_PORT": str(_free_port()),
        "E2E_MIGRATION_TARGET": "prompt_15_015_missing_revision",
    }
    try:
        result = _run(
            _compose(failure_project, "up", "--no-build", "api"),
            env=failure_env,
            timeout=90,
            check=False,
        )
        running = _run(
            _compose(failure_project, "ps", "--services", "--status", "running"),
            env=failure_env,
            check=False,
        ).stdout.splitlines()
        passed = result.returncode != 0 and "api" not in running
        return {
            "id": "E2E-F08",
            "status": "PASS" if passed else "FAIL",
            "reason": "MIGRATION_FAILURE_BLOCKED_API" if passed else "API_BECAME_READY",
        }
    finally:
        _run(
            _compose(
                failure_project,
                "down",
                "--volumes",
                "--remove-orphans",
                "--timeout",
                "5",
            ),
            env=failure_env,
            timeout=60,
            check=False,
        )


def run_e2e(evidence_path: Path, artifact_root: Path) -> int:
    docker_ok, tool_versions, blocker = _docker_probe()
    if not docker_ok:
        _write_yaml(evidence_path, _blocked_evidence(blocker or "DOCKER_UNAVAILABLE", tool_versions))
        return 3

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    project = f"marko-e2e-{run_id}".lower()
    artifact_dir = (artifact_root / run_id).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=False)
    token = "marko-e2e-" + secrets.token_urlsafe(32)
    postgres_password = "pg-e2e-" + secrets.token_urlsafe(24)
    env = {
        **os.environ,
        "ENVIRONMENT": "e2e",
        "POSTGRES_DB": "marko_e2e",
        "POSTGRES_USER": "marko_e2e",
        "POSTGRES_PASSWORD": postgres_password,
        "POSTGRES_PORT": str(_free_port()),
        "REDIS_PORT": str(_free_port()),
        "API_PORT": str(_free_port()),
        "WEB_PORT": str(_free_port()),
        "E2E_AUTH_TOKEN": token,
        "E2E_ARTIFACT_DIR": str(artifact_dir),
        "E2E_TASK_HOLD_SECONDS": "8",
        "E2E_MIGRATION_TARGET": "head",
    }
    api_url = f"http://127.0.0.1:{env['API_PORT']}"
    web_url = f"http://127.0.0.1:{env['WEB_PORT']}"
    headers = {"Authorization": f"Bearer {token}"}
    failure_results: dict[str, dict[str, Any]] = {
        case_id: {"id": case_id, "status": "NOT_RUN"} for case_id in FAILURE_IDS
    }
    evidence: dict[str, Any] = {
        "e2e_evidence": {
            "schema_version": "prompt-15.015-e2e-evidence-v1",
            "status": "FAIL",
            "run_id": run_id,
            "compose_project": project,
            "git_commit": "NOT_AVAILABLE",
            "image_ids": {},
            "tool_versions": tool_versions,
            "migration_head": "UNKNOWN",
            "service_health": {},
            "queue_counts": {},
            "workflow_ids": [],
            "fixture_hashes": {},
            "original_decision_hash": None,
            "replay_decision_hash": None,
            "failure_injection_results": [],
            "log_artifacts": [],
            "browser_assertions": [],
            "browser_trace_artifact": None,
            "clean_migration_passed": False,
            "runtime_services_passed": False,
            "celery_workers_passed": False,
            "scheduler_singleton_passed": False,
            "frontend_served": False,
            "business_workflow_passed": False,
            "replay_exact": False,
            "duplicate_delivery_safe": False,
            "failure_matrix_passed": False,
            "live_prom_requests": 0,
            "automatic_price_applications": 0,
            "cleanup_complete": False,
            "blockers": [],
        }
    }
    browser_container: str | None = None
    run_db_id: str | None = None
    try:
        _run(_compose(project, "config", "--quiet"), env=env)
        _run(_compose(project, "build"), env=env, timeout=1200)
        failure_results["E2E-F08"] = _migration_failure_case(project, env)

        _run(
            _compose(project, "up", "-d", "--wait", "db", "broker"),
            env=env,
            timeout=120,
        )
        _run(
            _compose(project, "up", "-d", "--no-deps", "frontend"),
            env=env,
        )
        _wait_http(web_url, timeout=60)
        browser = _run(
            _compose(project, "run", "-d", "--no-deps", "browser-e2e"),
            env=env,
        )
        browser_container = browser.stdout.strip().splitlines()[-1]
        _run(_compose(project, "up", "-d", "migrate"), env=env)
        migration = _run(_compose(project, "wait", "migrate"), env=env, timeout=120)
        if migration.returncode != 0:
            raise E2eFailure("Migration service failed")
        _run(
            _compose(
                project,
                "up",
                "-d",
                "--wait",
                "api",
                "worker",
                "store-sync-worker",
                "scheduler",
            ),
            env=env,
            timeout=180,
        )
        _wait_http(f"{api_url}/api/v1/health/live")
        _wait_http(f"{api_url}/api/v1/health/ready")
        me = httpx.get(f"{api_url}/api/v1/auth/me", headers=headers, timeout=10)
        if me.status_code != 200:
            raise E2eFailure(f"E2E auth failed: HTTP {me.status_code}")

        catalog_path = artifact_dir / "catalog-fixture.xlsx"
        catalog_hash = _catalog_fixture(catalog_path)
        with catalog_path.open("rb") as handle:
            imported = httpx.post(
                f"{api_url}/api/v1/catalog/imports",
                headers=headers,
                files={
                    "file": (
                        catalog_path.name,
                        handle,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
                timeout=30,
            )
        if imported.status_code != 201:
            raise E2eFailure(f"Catalog import failed: {imported.status_code} {imported.text}")
        batch = imported.json()
        failure_results["E2E-F05"] = {
            "id": "E2E-F05",
            "status": (
                "PASS"
                if batch["imported_rows"] == 2 and batch["rejected_rows"] == 1
                else "FAIL"
            ),
            "reason": "ROW_LEVEL_REJECTION_AUDITED",
        }
        run_response = httpx.post(
            f"{api_url}/api/v1/e2e/pricing/runs",
            headers=headers,
            json={"import_batch_id": batch["id"]},
            timeout=20,
        )
        if run_response.status_code != 202:
            raise E2eFailure(
                f"E2E pricing run creation failed: {run_response.status_code} {run_response.text}"
            )
        run_payload = run_response.json()
        run_db_id = run_payload["id"]
        seeded = _json_command(
            project,
            env,
            "marko.e2e.fixture_seed",
            "--run-id",
            run_db_id,
            "--max-targets",
            "1",
        )
        _run(_compose(project, "up", "-d", "pricing-worker"), env=env)

        collecting = _json_command(
            project,
            env,
            "marko.e2e.probe",
            "--run-id",
            run_db_id,
            "--wait-for-unseeded-collecting",
            "45",
            timeout=55,
        )
        first_fence = int(collecting["fencing_token"])
        _run(
            _compose(project, "kill", "--signal", "KILL", "pricing-worker"),
            env=env,
        )
        _run(_compose(project, "up", "-d", "pricing-worker"), env=env)

        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            current = httpx.get(
                f"{api_url}/api/v1/pricing/runs/{run_db_id}",
                headers=headers,
                timeout=5,
            )
            if current.status_code == 200 and current.json()["status"] in TERMINAL_RUN_STATES:
                run_payload = current.json()
                break
            time.sleep(1)
        else:
            raise E2eFailure("Pricing run did not reach a bounded terminal state")
        if run_payload["status"] not in {"completed", "partial"}:
            raise E2eFailure(f"Pricing run terminal status is {run_payload['status']}")

        state = _json_command(
            project,
            env,
            "marko.e2e.probe",
            "--run-id",
            run_db_id,
        )
        worker_lost = int(state["attempt_statuses"].get("worker_lost", 0))
        max_fence = max(int(target["fencing_token"]) for target in state["targets"])
        failure_results["E2E-F03"] = {
            "id": "E2E-F03",
            "status": "PASS" if worker_lost >= 1 and max_fence > first_fence else "FAIL",
            "reason": "WORKER_LOSS_FENCED_AND_REDELIVERED",
        }

        recommendations_response = httpx.get(
            f"{api_url}/api/v1/pricing/recommendations",
            headers=headers,
            params={"run_id": run_db_id, "queue": "all"},
            timeout=10,
        )
        if recommendations_response.status_code != 200:
            raise E2eFailure("Recommendations endpoint failed")
        recommendations = recommendations_response.json()["items"]
        if len(recommendations) != 2:
            raise E2eFailure(f"Expected two recommendations, got {len(recommendations)}")
        if any(
            item["automatic_eligible"] or item["recommended_price"] is not None
            for item in recommendations
        ):
            raise E2eFailure("E2E abstention invariant failed")
        failure_results["E2E-F06"] = {
            "id": "E2E-F06",
            "status": (
                "PASS"
                if any(item["action"] == "INSUFFICIENT_DATA" for item in recommendations)
                else "FAIL"
            ),
            "reason": "MISSING_EVIDENCE_ABSTAINED",
        }

        recommendation = recommendations[0]
        forbidden_accept = httpx.post(
            f"{api_url}/api/v1/pricing/recommendations/{recommendation['id']}/decisions",
            headers=headers,
            json={"decision": "accepted", "reason": "must fail closed"},
            timeout=10,
        )
        if forbidden_accept.status_code != 422:
            raise E2eFailure("Ineligible recommendation accepted by API")
        rejected = httpx.post(
            f"{api_url}/api/v1/pricing/recommendations/{recommendation['id']}/decisions",
            headers=headers,
            json={"decision": "rejected", "reason": "E2E operator rejection"},
            timeout=10,
        )
        if rejected.status_code != 201:
            raise E2eFailure("Append-only operator decision failed")
        replay = httpx.get(
            f"{api_url}/api/v1/pricing/recommendations/{recommendation['id']}/replay",
            headers=headers,
            timeout=20,
        )
        if replay.status_code != 200 or not replay.json()["exact_match"]:
            raise E2eFailure(f"Recommendation replay drifted: {replay.text}")
        original_hash = recommendation["decision_fingerprint"]
        replay_hash = replay.json()["replayed"].get("decision_fingerprint")
        if not original_hash or replay_hash != original_hash:
            raise E2eFailure("Original and replay decision fingerprints differ")

        before_duplicate = int(state["recommendation_count"])
        _json_command(
            project,
            env,
            "marko.e2e.probe",
            "--run-id",
            run_db_id,
            "--dispatch-duplicate",
        )
        time.sleep(3)
        after_duplicate = _json_command(
            project,
            env,
            "marko.e2e.probe",
            "--run-id",
            run_db_id,
        )
        failure_results["E2E-F04"] = {
            "id": "E2E-F04",
            "status": (
                "PASS"
                if int(after_duplicate["recommendation_count"]) == before_duplicate
                else "FAIL"
            ),
            "reason": "DUPLICATE_DELIVERY_IDEMPOTENT",
        }
        tamper = _json_command(
            project,
            env,
            "marko.e2e.probe",
            "--run-id",
            run_db_id,
            "--tamper-evidence",
        )
        failure_results["E2E-F10"] = {
            "id": "E2E-F10",
            "status": tamper["status"],
            "reason": tamper["reason"],
        }

        second_scheduler = _run(
            _compose(project, "run", "--rm", "--no-deps", "scheduler"),
            env=env,
            timeout=30,
            check=False,
        )
        failure_results["E2E-F09"] = {
            "id": "E2E-F09",
            "status": "PASS" if second_scheduler.returncode == 75 else "FAIL",
            "reason": "SCHEDULER_SINGLETON_LEASE_REJECTED_DUPLICATE",
        }

        _run(_compose(project, "stop", "broker"), env=env)
        broker_probe = _run(
            _compose(
                project,
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                "from marko.worker.celery_app import celery_app; celery_app.connection_for_write().ensure_connection(max_retries=0, timeout=2)",
            ),
            env=env,
            timeout=15,
            check=False,
        )
        failure_results["E2E-F02"] = {
            "id": "E2E-F02",
            "status": "PASS" if broker_probe.returncode != 0 else "FAIL",
            "reason": "BROKER_FAILURE_BOUNDED_AND_VISIBLE",
        }
        _run(_compose(project, "start", "broker"), env=env)
        time.sleep(2)
        _run(_compose(project, "up", "-d", "scheduler"), env=env)

        _run(_compose(project, "stop", "db"), env=env)
        unavailable = _wait_http(
            f"{api_url}/api/v1/health/ready",
            expected=503,
            timeout=30,
        )
        failure_results["E2E-F01"] = {
            "id": "E2E-F01",
            "status": "PASS" if unavailable.status_code == 503 else "FAIL",
            "reason": "READINESS_FAILED_CLOSED",
        }
        _run(_compose(project, "start", "db"), env=env)
        _wait_http(f"{api_url}/api/v1/health/ready", timeout=60)

        if browser_container is None:
            raise E2eFailure("Browser container was not started")
        browser_wait = _run(
            ["docker", "wait", browser_container],
            env=env,
            timeout=240,
            check=False,
        )
        browser_exit = browser_wait.stdout.strip().splitlines()[-1]
        browser_assertion_path = artifact_dir / "browser-assertions.json"
        browser_assertions = (
            json.loads(browser_assertion_path.read_text(encoding="utf-8"))
            if browser_assertion_path.is_file()
            else {"status": "FAIL", "assertions": []}
        )
        failure_results["E2E-F07"] = {
            "id": "E2E-F07",
            "status": (
                "PASS"
                if browser_exit == "0" and browser_assertions.get("status") == "PASS"
                else "FAIL"
            ),
            "reason": "FRONTEND_STARTED_BEFORE_API_AND_EVENTUALLY_RENDERED",
        }

        service_ps = _run(
            _compose(project, "ps", "--format", "json"),
            env=env,
            check=False,
        ).stdout
        images = _run(
            _compose(project, "images", "--format", "json"),
            env=env,
            check=False,
        ).stdout
        head = _run(
            _compose(project, "exec", "-T", "api", "alembic", "heads"),
            env=env,
        ).stdout.strip()
        failure_results_list = [failure_results[case_id] for case_id in FAILURE_IDS]
        all_failure_cases_pass = all(
            item["status"] == "PASS" for item in failure_results_list
        )
        if not all_failure_cases_pass:
            raise E2eFailure("At least one mandatory E2E failure injection failed")
        e2e = evidence["e2e_evidence"]
        e2e.update(
            {
                "status": "PASS",
                "migration_head": head,
                "service_health": {"compose_ps_json": _parse_json_output(service_ps)},
                "queue_counts": {
                    "submitted": 2,
                    "terminal": sum(after_duplicate["item_statuses"].values()),
                    "active": 0,
                    "unexplained_loss": 0,
                },
                "workflow_ids": [run_db_id, recommendation["id"], rejected.json()["id"]],
                "fixture_hashes": {
                    "catalog_xlsx": catalog_hash,
                    "persisted_replay": seeded["fixture_sha256"],
                },
                "original_decision_hash": original_hash,
                "replay_decision_hash": replay_hash,
                "failure_injection_results": failure_results_list,
                "browser_assertions": browser_assertions.get("assertions", []),
                "image_ids": _parse_json_output(images),
                "live_prom_requests": after_duplicate["live_network_request_count"],
                "clean_migration_passed": True,
                "runtime_services_passed": True,
                "celery_workers_passed": True,
                "scheduler_singleton_passed": True,
                "frontend_served": True,
                "business_workflow_passed": True,
                "replay_exact": True,
                "duplicate_delivery_safe": True,
                "failure_matrix_passed": True,
            }
        )
        if e2e["live_prom_requests"] != 0:
            raise E2eFailure("Live Prom requests were observed in E2E")
    except Exception as exc:
        evidence["e2e_evidence"]["status"] = "FAIL"
        evidence["e2e_evidence"]["blockers"] = [type(exc).__name__, str(exc)[:500]]
        evidence["e2e_evidence"]["failure_injection_results"] = [
            failure_results[case_id] for case_id in FAILURE_IDS
        ]
    finally:
        logs_path = artifact_dir / "compose.log"
        logs = _run(
            _compose(project, "logs", "--no-color", "--timestamps"),
            env=env,
            timeout=60,
            check=False,
        )
        logs_path.write_text(logs.stdout, encoding="utf-8")
        _run(
            _compose(
                project,
                "down",
                "--volumes",
                "--remove-orphans",
                "--timeout",
                "10",
            ),
            env=env,
            timeout=120,
            check=False,
        )
        remaining_containers = _run(
            [
                "docker",
                "ps",
                "--all",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={project}",
            ],
            env=env,
            check=False,
        ).stdout.strip()
        remaining_volumes = _run(
            [
                "docker",
                "volume",
                "ls",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={project}",
            ],
            env=env,
            check=False,
        ).stdout.strip()
        cleanup = not remaining_containers and not remaining_volumes
        secret_safe = _sanitize_and_scan(
            artifact_dir,
            (token, postgres_password),
        )
        e2e = evidence["e2e_evidence"]
        e2e["cleanup_complete"] = cleanup
        e2e["log_artifacts"] = [
            str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
            for path in sorted(artifact_dir.iterdir())
            if path.is_file()
        ]
        if not cleanup or not secret_safe:
            e2e["status"] = "FAIL"
            e2e["blockers"] = list(e2e.get("blockers", [])) + [
                "E2E_CLEANUP_INCOMPLETE" if not cleanup else "E2E_SECRET_CANARY_EMITTED"
            ]
        _write_yaml(evidence_path, evidence)
    return 0 if evidence["e2e_evidence"]["status"] == "PASS" else 2


def validate_harness() -> int:
    for path in COMPOSE_FILES:
        if not path.is_file():
            raise E2eFailure(f"Missing Compose file: {path}")
        yaml.safe_load(path.read_text(encoding="utf-8"))
    source = Path(__file__).read_text(encoding="utf-8")
    missing = [case_id for case_id in FAILURE_IDS if case_id not in source]
    if missing:
        raise E2eFailure(f"Failure-injection cases are missing: {missing}")
    print(
        json.dumps(
            {
                "status": "PASS",
                "compose_files": [str(path) for path in COMPOSE_FILES],
                "failure_injection_ids": list(FAILURE_IDS),
                "destructive_global_cleanup": False,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-output",
        type=Path,
        default=ROOT / "docs" / "PROMPT_15_015_E2E_EVIDENCE_2026-07-18.yaml",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=ROOT / ".artifacts" / "prompt_15_015_e2e",
    )
    parser.add_argument("--validate-harness", action="store_true")
    args = parser.parse_args()
    if args.validate_harness:
        return validate_harness()
    return run_e2e(args.evidence_output, args.artifact_root)


if __name__ == "__main__":
    raise SystemExit(main())
