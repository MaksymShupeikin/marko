"""Strict, deterministic and secret-safe production preflight contract."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
import hashlib
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import subprocess
from typing import Any, Literal, Mapping
from urllib.parse import unquote, urlsplit

import yaml

from marko.core.config import Settings
from marko.services.comparability_activation import (
    comparability_activation_artifact_verified,
)


PREFLIGHT_SCHEMA_VERSION = "1.0.0"
PreflightMode = Literal["static", "connectivity", "full"]


@dataclass(frozen=True, slots=True)
class FieldPolicy:
    required: bool = True
    secret: bool = False
    parser: str = "text"
    allowed_schemes: tuple[str, ...] = ()
    https_required: bool = False
    placeholder_forbidden: bool = True
    local_endpoint_forbidden: bool = False


FIELD_POLICIES: Mapping[str, FieldPolicy] = {
    "ENVIRONMENT": FieldPolicy(),
    "DATABASE_URL": FieldPolicy(
        secret=True,
        parser="url",
        allowed_schemes=("postgresql+asyncpg",),
        local_endpoint_forbidden=True,
    ),
    "CELERY_BROKER_URL": FieldPolicy(
        secret=True,
        parser="url",
        allowed_schemes=("rediss",),
        local_endpoint_forbidden=True,
    ),
    "CELERY_RESULT_BACKEND": FieldPolicy(
        secret=True,
        parser="url",
        allowed_schemes=("rediss",),
        local_endpoint_forbidden=True,
    ),
    "ALLOWED_HOSTS": FieldPolicy(),
    "CORS_ORIGINS": FieldPolicy(parser="origins", https_required=True),
    "FIREBASE_PROJECT_ID": FieldPolicy(),
    "PUBLIC_API_BASE_URL": FieldPolicy(
        parser="url", allowed_schemes=("https",), https_required=True
    ),
    "APP_DOMAIN": FieldPolicy(parser="hostname", local_endpoint_forbidden=True),
    "API_DOMAIN": FieldPolicy(parser="hostname", local_endpoint_forbidden=True),
    "ACME_EMAIL": FieldPolicy(parser="email"),
    "TRUSTED_PROXY_IPS": FieldPolicy(parser="trusted_proxies"),
    "FIREBASE_API_KEY": FieldPolicy(secret=True),
    "FIREBASE_AUTH_DOMAIN": FieldPolicy(),
    "FIREBASE_MESSAGING_SENDER_ID": FieldPolicy(),
    "FIREBASE_WEB_APP_ID": FieldPolicy(),
}

_SENTINEL_EXACT = frozenset(
    {
        "",
        "null",
        "none",
        "replace",
        "changeme",
        "change-me",
        "todo",
        "tbd",
        "user",
        "password",
        "example",
    }
)
_SENTINEL_FRAGMENTS = (
    "example.com",
    "private_postgres_host",
    "private_redis_host",
    "your-firebase",
    "your_",
    "<",
    ">${",
    "${",
)
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    id: str
    layer: str
    status: str
    reason_codes: tuple[str, ...] = ()
    secret_safe: bool = True


@dataclass(frozen=True, slots=True)
class PreflightResult:
    schema_version: str
    requested_mode: PreflightMode
    environment: str
    config_source: str
    config_sha256: str
    git_commit: str
    checks: tuple[PreflightCheck, ...]
    passed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    secrets_emitted: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["checks"] = [asdict(check) for check in self.checks]
        return payload


@dataclass(slots=True)
class _Collector:
    checks: list[PreflightCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(
        self,
        check_id: str,
        layer: str,
        passed: bool,
        *reason_codes: str,
        blocked: bool = False,
    ) -> None:
        self.checks.append(
            PreflightCheck(
                id=check_id,
                layer=layer,
                status="PASS" if passed else ("BLOCKED" if blocked else "FAIL"),
                reason_codes=tuple(dict.fromkeys(reason_codes)) if not passed else (),
            )
        )


class EnvFileError(ValueError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def parse_env_file(path: Path) -> tuple[dict[str, str], tuple[str, ...]]:
    """Parse a strict KEY=VALUE file without shell expansion or interpolation."""

    if not path.is_file():
        raise EnvFileError("PREFLIGHT_ENV_FILE_UNREADABLE")
    values: dict[str, str] = {}
    duplicates: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise EnvFileError("PREFLIGHT_ENV_FILE_UNREADABLE") from exc
    for line_number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise EnvFileError(f"PREFLIGHT_ENV_SYNTAX_LINE_{line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "A").isalnum() or not key[0].isalpha():
            raise EnvFileError(f"PREFLIGHT_ENV_KEY_LINE_{line_number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key in values:
            duplicates.append(key)
        values[key] = value
    return values, tuple(sorted(set(duplicates)))


def run_preflight(
    env_file: Path,
    *,
    mode: PreflightMode,
    e2e_evidence: Path | None = None,
    connectivity_timeout: float = 3.0,
) -> PreflightResult:
    """Run exactly the requested layers; full mode cannot pass with skips."""

    resolved = env_file.expanduser().resolve()
    raw = resolved.read_bytes() if resolved.is_file() else b""
    config_hash = hashlib.sha256(raw).hexdigest()
    collector = _Collector()
    try:
        values, duplicates = parse_env_file(resolved)
    except EnvFileError as exc:
        values, duplicates = {}, ()
        collector.add(
            "PREFLIGHT_INPUT_SOURCE", "P0_INPUT_SOURCE", False, exc.reason_code
        )
    else:
        collector.add("PREFLIGHT_INPUT_SOURCE", "P0_INPUT_SOURCE", True)
        collector.add(
            "PREFLIGHT_DUPLICATE_KEYS",
            "P0_INPUT_SOURCE",
            not duplicates,
            "PREFLIGHT_DUPLICATE_ENV_KEY",
        )
        _check_file_permissions(resolved, values, collector)
        _validate_static(values, collector)
        _check_git_tracking(resolved, collector)

    if mode in {"connectivity", "full"}:
        _validate_connectivity(values, collector, timeout=connectivity_timeout)
    if mode == "full":
        _validate_full_evidence(e2e_evidence, collector)

    blockers = tuple(
        reason
        for check in collector.checks
        if check.status != "PASS"
        for reason in check.reason_codes
    )
    passed = bool(collector.checks) and all(
        check.status == "PASS" for check in collector.checks
    )
    return PreflightResult(
        schema_version=PREFLIGHT_SCHEMA_VERSION,
        requested_mode=mode,
        environment=values.get("ENVIRONMENT", "NOT_SET"),
        config_source=resolved.name,
        config_sha256=config_hash,
        git_commit=_git_commit(resolved.parent),
        checks=tuple(collector.checks),
        passed=passed,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(collector.warnings)),
    )


def _validate_static(values: Mapping[str, str], collector: _Collector) -> None:
    environment = values.get("ENVIRONMENT", "").strip().casefold()
    collector.add(
        "PREFLIGHT_ENVIRONMENT",
        "P1_STATIC_SCHEMA",
        environment == "production",
        "PREFLIGHT_ENVIRONMENT_REQUIRED"
        if not environment
        else "PREFLIGHT_ENVIRONMENT_NOT_PRODUCTION",
    )
    collector.add(
        "PREFLIGHT_DEBUG_DISABLED",
        "P1_STATIC_SCHEMA",
        not _truthy(values.get("DEBUG", "false")),
        "PREFLIGHT_DEBUG_ENABLED",
    )
    collector.add(
        "PREFLIGHT_API_DOCS_DISABLED",
        "P1_STATIC_SCHEMA",
        not _truthy(values.get("API_DOCS_ENABLED", "false")),
        "PREFLIGHT_API_DOCS_ENABLED",
    )

    for name, policy in FIELD_POLICIES.items():
        raw = values.get(name)
        collector.add(
            f"PREFLIGHT_FIELD_{name}",
            "P2_PLACEHOLDER_AND_SECRET_HYGIENE",
            _valid_field(name, raw, policy),
            _field_reason(name, raw, policy),
        )

    hosts = _split_csv(values.get("ALLOWED_HOSTS"))
    collector.add(
        "PREFLIGHT_ALLOWED_HOSTS",
        "P3_TOPOLOGY_AND_SECURITY",
        bool(hosts)
        and "*" not in hosts
        and all(not _is_placeholder(host) for host in hosts),
        "PREFLIGHT_ALLOWED_HOSTS_UNSAFE",
    )
    origins = _split_csv(values.get("CORS_ORIGINS"))
    collector.add(
        "PREFLIGHT_CORS",
        "P3_TOPOLOGY_AND_SECURITY",
        bool(origins)
        and "*" not in origins
        and all(_valid_https_origin(origin) for origin in origins),
        "PREFLIGHT_CORS_UNSAFE",
    )
    app_domain = values.get("APP_DOMAIN", "").strip().casefold()
    api_domain = values.get("API_DOMAIN", "").strip().casefold()
    public_api = urlsplit(values.get("PUBLIC_API_BASE_URL", ""))
    origin_hosts = {
        (urlsplit(origin).hostname or "").casefold() for origin in origins
    }
    collector.add(
        "PREFLIGHT_EDGE_TOPOLOGY",
        "P3_TOPOLOGY_AND_SECURITY",
        bool(app_domain and api_domain)
        and app_domain != api_domain
        and app_domain in origin_hosts
        and (public_api.hostname or "").casefold() == api_domain
        and api_domain in {host.casefold() for host in hosts},
        "PREFLIGHT_EDGE_TOPOLOGY_MISMATCH",
    )
    collector.add(
        "PREFLIGHT_E2E_AUTH_BYPASS",
        "P3_TOPOLOGY_AND_SECURITY",
        not _truthy(values.get("E2E_AUTH_BYPASS", "false")),
        "PREFLIGHT_E2E_AUTH_BYPASS_IN_PRODUCTION",
    )
    collector.add(
        "PREFLIGHT_E2E_AUTH_TOKEN",
        "P3_TOPOLOGY_AND_SECURITY",
        not bool(values.get("E2E_AUTH_TOKEN", "").strip()),
        "PREFLIGHT_E2E_AUTH_TOKEN_IN_PRODUCTION",
    )
    v3_enabled = _truthy(values.get("PRICING_V3_ROBUST_DISPERSION_ENABLED", "false"))
    activation_ok = _valid_activation_artifact(
        values.get("PRICING_V3_ACTIVATION_ARTIFACT"),
        values.get("PRICING_V3_ACTIVATION_SHA256"),
    )
    collector.add(
        "PREFLIGHT_ROBUST_V3_ACTIVATION",
        "P3_TOPOLOGY_AND_SECURITY",
        not v3_enabled or activation_ok,
        "PREFLIGHT_ROBUST_V3_ACTIVATION_ARTIFACT_MISSING",
    )
    matching_enabled = _truthy(
        values.get("PRICING_COMPARABILITY_V1_AUTOMATIC_ENABLED", "false")
    )
    matching_activation_ok = comparability_activation_artifact_verified(
        values.get("PRICING_COMPARABILITY_ACTIVATION_ARTIFACT"),
        values.get("PRICING_COMPARABILITY_ACTIVATION_SHA256"),
    )
    collector.add(
        "PREFLIGHT_COMPARABILITY_ACTIVATION",
        "P3_TOPOLOGY_AND_SECURITY",
        not matching_enabled or matching_activation_ok,
        "PREFLIGHT_COMPARABILITY_ACTIVATION_ARTIFACT_MISSING",
    )
    verdict = values.get("PROM_MARKETPLACE_SOURCE_ACCESS_VERDICT", "NOT_PERMITTED")
    source_reference_ok = not verdict.startswith("PERMITTED_") or bool(
        values.get("PROM_MARKETPLACE_SOURCE_ACCESS_REFERENCE", "").strip()
    )
    collector.add(
        "PREFLIGHT_SOURCE_ACCESS_REFERENCE",
        "P3_TOPOLOGY_AND_SECURITY",
        source_reference_ok,
        "PREFLIGHT_SOURCE_ACCESS_REFERENCE_MISSING",
    )
    try:
        Settings(
            _env_file=None,
            **{key.casefold(): value for key, value in values.items()},
        )
    except Exception:
        collector.add(
            "PREFLIGHT_SETTINGS_SCHEMA",
            "P1_STATIC_SCHEMA",
            False,
            "PREFLIGHT_SETTINGS_SCHEMA_INVALID",
        )
    else:
        collector.add("PREFLIGHT_SETTINGS_SCHEMA", "P1_STATIC_SCHEMA", True)


def _valid_field(name: str, raw: str | None, policy: FieldPolicy) -> bool:
    if raw is None or (policy.required and not raw.strip()):
        return False
    if policy.placeholder_forbidden and _is_placeholder(raw):
        return False
    if policy.parser == "url":
        try:
            parsed = urlsplit(raw)
            hostname = parsed.hostname or ""
            port = parsed.port
            del port
        except ValueError:
            return False
        if parsed.scheme not in policy.allowed_schemes or not hostname:
            return False
        if policy.local_endpoint_forbidden and _is_local(hostname):
            return False
        if (
            parsed.username is not None and _is_placeholder(unquote(parsed.username))
        ) or (
            parsed.password is not None and _is_placeholder(unquote(parsed.password))
        ):
            return False
    if policy.parser == "origins":
        return all(_valid_https_origin(value) for value in _split_csv(raw))
    if policy.parser == "hostname":
        return _valid_public_hostname(raw)
    if policy.parser == "email":
        local, separator, domain = raw.rpartition("@")
        return bool(local and separator and _valid_public_hostname(domain))
    if policy.parser == "trusted_proxies":
        proxies = _split_csv(raw)
        if not proxies:
            return False
        if proxies == ("*",):
            return True
        try:
            return all(bool(ipaddress.ip_network(value, strict=False)) for value in proxies)
        except ValueError:
            return False
    return True


def _field_reason(name: str, raw: str | None, policy: FieldPolicy) -> str:
    if raw is None or not raw.strip():
        return f"PREFLIGHT_{name}_MISSING"
    if _is_placeholder(raw):
        return f"PREFLIGHT_{name}_PLACEHOLDER"
    if policy.parser == "url":
        return f"PREFLIGHT_{name}_URL_UNSAFE"
    return f"PREFLIGHT_{name}_INVALID"


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in _SENTINEL_EXACT:
        return True
    if normalized.startswith(("your-", "your_")):
        return True
    return any(fragment in normalized for fragment in _SENTINEL_FRAGMENTS)


def _is_local(hostname: str) -> bool:
    normalized = hostname.strip("[]").casefold()
    if normalized in _LOCAL_HOSTS or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _valid_https_origin(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and not _is_placeholder(parsed.hostname)
        and not _is_local(parsed.hostname)
    )


def _valid_public_hostname(value: str) -> bool:
    normalized = value.strip().rstrip(".").casefold()
    if not normalized or _is_placeholder(normalized) or _is_local(normalized):
        return False
    if "://" in normalized or "/" in normalized or "@" in normalized:
        return False
    try:
        ascii_hostname = normalized.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    labels = ascii_hostname.split(".")
    return len(labels) >= 2 and all(
        label
        and len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
        for label in labels
    )


def _check_file_permissions(
    path: Path, values: Mapping[str, str], collector: _Collector
) -> None:
    has_secret_fields = any(
        values.get(name) for name, policy in FIELD_POLICIES.items() if policy.secret
    )
    mode = path.stat().st_mode & 0o777
    secure = not has_secret_fields or mode & 0o077 == 0
    collector.add(
        "PREFLIGHT_CONFIG_PERMISSIONS",
        "P2_PLACEHOLDER_AND_SECRET_HYGIENE",
        secure,
        "PREFLIGHT_SECRET_FILE_PERMISSIONS_UNSAFE",
    )


def _check_git_tracking(path: Path, collector: _Collector) -> None:
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path)],
            cwd=path.parent,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        collector.warnings.append("PREFLIGHT_GIT_TRACKING_NOT_AVAILABLE")
        return
    tracked = completed.returncode == 0
    collector.add(
        "PREFLIGHT_CONFIG_NOT_TRACKED",
        "P2_PLACEHOLDER_AND_SECRET_HYGIENE",
        not tracked,
        "PREFLIGHT_PRODUCTION_CONFIG_TRACKED",
    )


def _validate_connectivity(
    values: Mapping[str, str], collector: _Collector, *, timeout: float
) -> None:
    for name in ("DATABASE_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"):
        raw = values.get(name, "")
        try:
            parsed = urlsplit(raw)
            hostname = parsed.hostname
            port = parsed.port or (5432 if name == "DATABASE_URL" else 6380)
            if not hostname:
                raise ValueError
            socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
            with socket.create_connection(
                (hostname, port), timeout=timeout
            ) as connection:
                if parsed.scheme == "rediss":
                    context = ssl.create_default_context()
                    with context.wrap_socket(connection, server_hostname=hostname):
                        pass
        except Exception as exc:
            collector.add(
                f"PREFLIGHT_CONNECTIVITY_{name}",
                "P4_DEPENDENCY_CONNECTIVITY",
                False,
                f"PREFLIGHT_{name}_UNREACHABLE_{type(exc).__name__.upper()}",
            )
        else:
            collector.add(
                f"PREFLIGHT_CONNECTIVITY_{name}",
                "P4_DEPENDENCY_CONNECTIVITY",
                True,
            )
    _application_dependency_probes(values, collector, timeout=timeout)


def _application_dependency_probes(
    values: Mapping[str, str], collector: _Collector, *, timeout: float
) -> None:
    async def probes() -> tuple[bool, bool, bool]:
        db_ok = False
        broker_ok = False
        backend_ok = False
        try:
            import asyncpg

            dsn = values.get("DATABASE_URL", "").replace(
                "postgresql+asyncpg://", "postgresql://", 1
            )
            connection = await asyncio.wait_for(asyncpg.connect(dsn), timeout)
            try:
                db_ok = await connection.fetchval("SELECT 1") == 1
            finally:
                await connection.close()
        except Exception:
            db_ok = False
        try:
            from redis.asyncio import Redis

            broker = Redis.from_url(values.get("CELERY_BROKER_URL", ""))
            try:
                broker_ok = bool(await asyncio.wait_for(broker.ping(), timeout))
            finally:
                await broker.aclose()
        except Exception:
            broker_ok = False
        try:
            from redis.asyncio import Redis

            backend = Redis.from_url(values.get("CELERY_RESULT_BACKEND", ""))
            try:
                backend_ok = bool(await asyncio.wait_for(backend.ping(), timeout))
            finally:
                await backend.aclose()
        except Exception:
            backend_ok = False
        return db_ok, broker_ok, backend_ok

    try:
        db_ok, broker_ok, backend_ok = asyncio.run(probes())
    except RuntimeError:
        db_ok = broker_ok = backend_ok = False
    for check_id, passed, reason in (
        ("PREFLIGHT_POSTGRES_SELECT_1", db_ok, "PREFLIGHT_POSTGRES_QUERY_FAILED"),
        (
            "PREFLIGHT_REDIS_BROKER_PING",
            broker_ok,
            "PREFLIGHT_REDIS_BROKER_PING_FAILED",
        ),
        (
            "PREFLIGHT_REDIS_BACKEND_PING",
            backend_ok,
            "PREFLIGHT_REDIS_BACKEND_PING_FAILED",
        ),
    ):
        collector.add(check_id, "P4_DEPENDENCY_CONNECTIVITY", passed, reason)


def _validate_full_evidence(path: Path | None, collector: _Collector) -> None:
    if path is None or not path.is_file():
        for check_id, layer, reason in (
            (
                "PREFLIGHT_DATABASE_SCHEMA",
                "P5_DATABASE_SCHEMA",
                "PREFLIGHT_SCHEMA_EVIDENCE_MISSING",
            ),
            (
                "PREFLIGHT_RUNTIME_SERVICES",
                "P6_RUNTIME_SERVICES",
                "PREFLIGHT_RUNTIME_EVIDENCE_MISSING",
            ),
            (
                "PREFLIGHT_WORKFLOW_SMOKE",
                "P7_WORKFLOW_SMOKE",
                "PREFLIGHT_WORKFLOW_EVIDENCE_MISSING",
            ),
        ):
            collector.add(check_id, layer, False, reason, blocked=True)
        return
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(payload, Mapping) and isinstance(
            payload.get("e2e_evidence"), Mapping
        ):
            payload = payload["e2e_evidence"]
        if not isinstance(payload, Mapping):
            raise ValueError("E2E evidence root must be an object")
    except (OSError, UnicodeError, ValueError, yaml.YAMLError):
        collector.add(
            "PREFLIGHT_E2E_EVIDENCE",
            "P5_DATABASE_SCHEMA",
            False,
            "PREFLIGHT_E2E_EVIDENCE_INVALID",
        )
        return
    evidence_passed = payload.get("status") == "PASS"
    checks = {
        "PREFLIGHT_DATABASE_SCHEMA": evidence_passed
        and bool(payload.get("clean_migration_passed")),
        "PREFLIGHT_RUNTIME_SERVICES": evidence_passed
        and bool(payload.get("runtime_services_passed")),
        "PREFLIGHT_CELERY_WORKERS": evidence_passed
        and bool(payload.get("celery_workers_passed")),
        "PREFLIGHT_SCHEDULER_SINGLETON": bool(
            evidence_passed and payload.get("scheduler_singleton_passed")
        ),
        "PREFLIGHT_FRONTEND_RUNTIME": evidence_passed
        and bool(payload.get("frontend_served")),
        "PREFLIGHT_WORKFLOW_SMOKE": bool(
            evidence_passed
            and payload.get("business_workflow_passed")
            and payload.get("replay_exact")
            and payload.get("duplicate_delivery_safe")
            and payload.get("failure_matrix_passed")
            and payload.get("cleanup_complete")
            and payload.get("live_prom_requests", 1) == 0
            and payload.get("automatic_price_applications", 1) == 0
        ),
        "PREFLIGHT_DUPLICATE_DELIVERY": bool(
            evidence_passed and payload.get("duplicate_delivery_safe")
        ),
        "PREFLIGHT_FAILURE_MATRIX": bool(
            evidence_passed and payload.get("failure_matrix_passed")
        ),
        "PREFLIGHT_E2E_CLEANUP": bool(
            evidence_passed and payload.get("cleanup_complete")
        ),
    }
    layers = {
        "PREFLIGHT_DATABASE_SCHEMA": "P5_DATABASE_SCHEMA",
        "PREFLIGHT_RUNTIME_SERVICES": "P6_RUNTIME_SERVICES",
        "PREFLIGHT_CELERY_WORKERS": "P6_RUNTIME_SERVICES",
        "PREFLIGHT_SCHEDULER_SINGLETON": "P6_RUNTIME_SERVICES",
        "PREFLIGHT_FRONTEND_RUNTIME": "P6_RUNTIME_SERVICES",
        "PREFLIGHT_WORKFLOW_SMOKE": "P7_WORKFLOW_SMOKE",
        "PREFLIGHT_DUPLICATE_DELIVERY": "P7_WORKFLOW_SMOKE",
        "PREFLIGHT_FAILURE_MATRIX": "P7_WORKFLOW_SMOKE",
        "PREFLIGHT_E2E_CLEANUP": "P7_WORKFLOW_SMOKE",
    }
    for check_id, passed in checks.items():
        collector.add(
            check_id,
            layers[check_id],
            passed,
            f"{check_id}_FAILED",
        )


def _valid_activation_artifact(
    path_value: str | None, expected_hash: str | None
) -> bool:
    if not path_value or not expected_hash or len(expected_hash) != 64:
        return False
    path = Path(path_value).expanduser()
    if not path.is_file():
        return False
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    return actual == expected_hash.casefold()


def _git_commit(cwd: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "NOT_AVAILABLE"
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and len(value) >= 7 else "NOT_AVAILABLE"


def _truthy(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _split_csv(value: str | None) -> tuple[str, ...]:
    return tuple(item.strip() for item in (value or "").split(",") if item.strip())


def render_json(result: PreflightResult) -> str:
    return json.dumps(result.as_dict(), indent=2, sort_keys=True) + "\n"


def render_human(result: PreflightResult) -> str:
    lines = [
        f"PRODUCTION_PREFLIGHT={'PASS' if result.passed else 'FAIL'}",
        f"mode={result.requested_mode}",
        f"config={result.config_source}",
    ]
    lines.extend(
        f"{check.id}={check.status}"
        + (f" ({','.join(check.reason_codes)})" if check.reason_codes else "")
        for check in result.checks
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "EnvFileError",
    "FIELD_POLICIES",
    "PREFLIGHT_SCHEMA_VERSION",
    "PreflightCheck",
    "PreflightResult",
    "parse_env_file",
    "render_human",
    "render_json",
    "run_preflight",
]
