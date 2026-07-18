#!/usr/bin/env python3
"""Run a disposable, secret-safe full-mode PROMPT 15.015 preflight proof."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from marko.governance.production_preflight import (  # noqa: E402
    render_json,
    run_preflight,
)


POSTGRES_IMAGE = "postgres:17-alpine"
REDIS_IMAGE = "redis:8-alpine"


class ProofError(RuntimeError):
    """Bounded proof failure whose message is never emitted."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _run(
    command: list[str],
    *,
    timeout: float = 60,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    operation = (
        "_".join(Path(part).name for part in command[:2]).upper().replace("-", "_")
    )
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProofError(f"{operation}_TIMEOUT") from exc
    if check and completed.returncode != 0:
        raise ProofError(f"{operation}_FAILED")
    return completed


def _free_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _write_tls_material(directory: Path, hostname: str) -> Path:
    ca_key = directory / "ca.key"
    ca_cert = directory / "ca.crt"
    server_key = directory / "server.key"
    server_csr = directory / "server.csr"
    server_cert = directory / "server.crt"
    extensions = directory / "server-ext.cnf"
    extensions.write_text(
        "[v3_server]\n"
        f"subjectAltName=DNS:{hostname}\n"
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n",
        encoding="utf-8",
    )
    _run(
        [
            "openssl",
            "req",
            "-x509",
            "-nodes",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_cert),
            "-days",
            "1",
            "-subj",
            "/CN=Marko-Preflight-CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
        ]
    )
    _run(
        [
            "openssl",
            "req",
            "-nodes",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(server_key),
            "-out",
            str(server_csr),
            "-subj",
            f"/CN={hostname}",
        ]
    )
    _run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(server_csr),
            "-CA",
            str(ca_cert),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(server_cert),
            "-days",
            "1",
            "-extfile",
            str(extensions),
            "-extensions",
            "v3_server",
        ]
    )
    server_key.chmod(0o644)
    return ca_cert


def _write_env(
    path: Path,
    *,
    hostname: str,
    postgres_port: int,
    redis_port: int,
    postgres_password: str,
    redis_password: str,
) -> None:
    values = {
        "ENVIRONMENT": "production",
        "DEBUG": "false",
        "API_DOCS_ENABLED": "false",
        "DATABASE_URL": (
            "postgresql+asyncpg://marko:"
            f"{postgres_password}@{hostname}:{postgres_port}/marko"
        ),
        "CELERY_BROKER_URL": (
            f"rediss://default:{redis_password}@{hostname}:{redis_port}/0"
        ),
        "CELERY_RESULT_BACKEND": (
            f"rediss://default:{redis_password}@{hostname}:{redis_port}/1"
        ),
        "ALLOWED_HOSTS": "api.prod.marko.internal",
        "CORS_ORIGINS": "https://app.prod.marko.internal",
        "FIREBASE_PROJECT_ID": "marko-prod-8a7",
        "PUBLIC_API_BASE_URL": "https://api.prod.marko.internal",
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
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )
    path.chmod(0o600)


def _wait_postgres(container: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = _run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", container],
            check=False,
        ).stdout.strip()
        if status == "healthy":
            return
        time.sleep(0.25)
    raise ProofError("POSTGRES_NOT_HEALTHY")


def _wait_redis_tls(
    hostname: str,
    port: int,
    ca_cert: Path,
    timeout: float = 60,
) -> None:
    context = ssl.create_default_context(cafile=str(ca_cert))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((hostname, port), timeout=1) as connection:
                with context.wrap_socket(connection, server_hostname=hostname):
                    return
        except OSError:
            time.sleep(0.25)
    raise ProofError("REDIS_TLS_NOT_HEALTHY")


def _cleanup(containers: tuple[str, ...]) -> None:
    for container in containers:
        _run(["docker", "rm", "--force", container], timeout=30, check=False)


def run_proof(e2e_evidence: Path, output: Path) -> bool:
    if shutil.which("docker") is None or shutil.which("openssl") is None:
        raise ProofError("REQUIRED_BINARY_MISSING")
    if not e2e_evidence.is_file():
        raise ProofError("E2E_EVIDENCE_MISSING")
    _run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=15)

    hostname = "lvh.me"
    if socket.gethostbyname(hostname) != "127.0.0.1":
        raise ProofError("LOOPBACK_ALIAS_UNAVAILABLE")
    suffix = secrets.token_hex(4)
    postgres_container = f"marko-preflight-db-{suffix}"
    redis_container = f"marko-preflight-redis-{suffix}"
    containers = (postgres_container, redis_container)
    postgres_password = "db-" + secrets.token_urlsafe(24)
    redis_password = "redis-" + secrets.token_urlsafe(24)
    postgres_port = _free_port()
    redis_port = _free_port()
    artifact_root = ROOT / ".artifacts" / "prompt_15_015_preflight"
    artifact_root.mkdir(parents=True, exist_ok=True)

    try:
        with tempfile.TemporaryDirectory(prefix="proof-", dir=artifact_root) as raw_dir:
            directory = Path(raw_dir)
            ca_cert = _write_tls_material(directory, hostname)
            env_file = directory / "runtime.env"
            _write_env(
                env_file,
                hostname=hostname,
                postgres_port=postgres_port,
                redis_port=redis_port,
                postgres_password=postgres_password,
                redis_password=redis_password,
            )
            _run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    postgres_container,
                    "-e",
                    "POSTGRES_USER=marko",
                    "-e",
                    f"POSTGRES_PASSWORD={postgres_password}",
                    "-e",
                    "POSTGRES_DB=marko",
                    "-p",
                    f"127.0.0.1:{postgres_port}:5432",
                    "--health-cmd=pg_isready -U marko -d marko",
                    "--health-interval=1s",
                    "--health-timeout=3s",
                    "--health-retries=60",
                    POSTGRES_IMAGE,
                ],
                timeout=120,
            )
            _run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    redis_container,
                    "-p",
                    f"127.0.0.1:{redis_port}:6379",
                    "-v",
                    f"{directory}:/tls:ro",
                    REDIS_IMAGE,
                    "redis-server",
                    "--port",
                    "0",
                    "--tls-port",
                    "6379",
                    "--tls-cert-file",
                    "/tls/server.crt",
                    "--tls-key-file",
                    "/tls/server.key",
                    "--tls-ca-cert-file",
                    "/tls/ca.crt",
                    "--tls-auth-clients",
                    "no",
                    "--requirepass",
                    redis_password,
                ],
                timeout=120,
            )
            _wait_postgres(postgres_container)
            _wait_redis_tls(hostname, redis_port, ca_cert)
            previous_ca = os.environ.get("SSL_CERT_FILE")
            os.environ["SSL_CERT_FILE"] = str(ca_cert)
            try:
                result = run_preflight(
                    env_file,
                    mode="full",
                    e2e_evidence=e2e_evidence,
                    connectivity_timeout=5,
                )
            finally:
                if previous_ca is None:
                    os.environ.pop("SSL_CERT_FILE", None)
                else:
                    os.environ["SSL_CERT_FILE"] = previous_ca
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(render_json(result), encoding="utf-8")
            return result.passed
    finally:
        _cleanup(containers)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--e2e-evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        passed = run_proof(args.e2e_evidence.resolve(), args.output.resolve())
    except Exception as exc:
        reason_code = exc.code if isinstance(exc, ProofError) else type(exc).__name__
        sys.stderr.write(
            json.dumps(
                {
                    "status": "FAIL",
                    "reason_code": reason_code,
                    "secrets_emitted": False,
                },
                sort_keys=True,
            )
            + "\n"
        )
        return 3
    sys.stdout.write(
        json.dumps(
            {
                "status": "PASS" if passed else "FAIL",
                "output": str(args.output),
                "secrets_emitted": False,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
