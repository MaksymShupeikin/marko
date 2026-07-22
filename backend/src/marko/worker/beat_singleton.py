"""Run Celery Beat only while this supervisor owns a renewable Redis lease."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import secrets
import signal
import subprocess
import time
from typing import Any, Protocol

from redis import Redis

from marko.core.config import Settings, get_settings


LOGGER = logging.getLogger("marko.scheduler")
_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class RedisLeaseClient(Protocol):
    def set(self, name: str, value: str, *, nx: bool, ex: int) -> object: ...

    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object: ...


class RedisHealthClient(Protocol):
    def get(self, name: str) -> object: ...

    def ttl(self, name: str) -> int: ...


class SchedulerShutdown(SystemExit):
    """Raised by the supervisor's signal handler for graceful cleanup."""


@dataclass(frozen=True, slots=True)
class SupervisorConfig:
    lock_key: str
    ttl_seconds: int
    refresh_seconds: int
    reacquire_initial_seconds: float
    reacquire_max_seconds: float
    health_state_path: Path

    @classmethod
    def from_settings(cls, settings: Settings) -> SupervisorConfig:
        lock_key = settings.scheduler_singleton_lock_key.strip()
        if not lock_key:
            raise RuntimeError("SCHEDULER_SINGLETON_LOCK_KEY must not be empty")
        if settings.scheduler_singleton_refresh_seconds * 2 >= (
            settings.scheduler_singleton_ttl_seconds
        ):
            raise RuntimeError("Scheduler lock refresh must be less than half the TTL")
        if (
            settings.scheduler_singleton_reacquire_max_seconds
            < settings.scheduler_singleton_reacquire_initial_seconds
        ):
            raise RuntimeError(
                "Scheduler reacquire maximum must not be less than its initial delay"
            )
        health_state_path = Path(settings.scheduler_health_state_path)
        if not health_state_path.is_absolute():
            raise RuntimeError("SCHEDULER_HEALTH_STATE_PATH must be absolute")
        return cls(
            lock_key=lock_key,
            ttl_seconds=settings.scheduler_singleton_ttl_seconds,
            refresh_seconds=settings.scheduler_singleton_refresh_seconds,
            reacquire_initial_seconds=(
                settings.scheduler_singleton_reacquire_initial_seconds
            ),
            reacquire_max_seconds=(
                settings.scheduler_singleton_reacquire_max_seconds
            ),
            health_state_path=health_state_path,
        )


def acquire_lease(
    client: RedisLeaseClient,
    *,
    key: str,
    token: str,
    ttl_seconds: int,
) -> bool:
    return bool(client.set(key, token, nx=True, ex=ttl_seconds))


def renew_lease(
    client: RedisLeaseClient,
    *,
    key: str,
    token: str,
    ttl_seconds: int,
) -> bool:
    return bool(client.eval(_RENEW_SCRIPT, 1, key, token, ttl_seconds))


def release_lease(client: RedisLeaseClient, *, key: str, token: str) -> bool:
    return bool(client.eval(_RELEASE_SCRIPT, 1, key, token))


def scheduler_command(token: str) -> list[str]:
    lease_suffix = token.rsplit("-", maxsplit=1)[-1]
    return [
        "celery",
        "--app",
        "marko.worker.celery_app:celery_app",
        "beat",
        "--loglevel=INFO",
        f"--pidfile=/tmp/marko-celerybeat-{lease_suffix}.pid",
        "--schedule=/tmp/marko-celerybeat-schedule",
    ]


def cleanup_beat_pidfile(token: str) -> None:
    lease_suffix = token.rsplit("-", maxsplit=1)[-1]
    Path(f"/tmp/marko-celerybeat-{lease_suffix}.pid").unlink(missing_ok=True)


def stop_process(process: subprocess.Popen[bytes]) -> None:
    """Stop the fenced Beat child before attempting to acquire another lease."""

    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def write_health_state(
    path: Path,
    *,
    state: str,
    config: SupervisorConfig,
    supervisor_pid: int,
    token: str | None = None,
    beat_pid: int | None = None,
    last_successful_renewal_at: float | None = None,
    detail: str | None = None,
) -> None:
    """Atomically publish scheduler ownership for the container healthcheck."""

    payload = {
        "schema_version": "marko-scheduler-health-v1",
        "state": state,
        "lock_key": config.lock_key,
        "ttl_seconds": config.ttl_seconds,
        "refresh_seconds": config.refresh_seconds,
        "supervisor_pid": supervisor_pid,
        "beat_pid": beat_pid,
        "token": token,
        "last_successful_renewal_at": last_successful_renewal_at,
        "updated_at": time.time(),
        "detail": detail,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{supervisor_pid}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def record_health_state(path: Path, **kwargs: Any) -> None:
    try:
        write_health_state(path, **kwargs)
    except Exception:
        LOGGER.exception("scheduler_health_state_write_failed path=%s", path)


def process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def scheduler_is_healthy(
    client: RedisHealthClient,
    *,
    config: SupervisorConfig,
    now: Callable[[], float] = time.time,
    pid_is_alive: Callable[[int], bool] = process_is_alive,
) -> bool:
    """Verify that this container owns a fresh lease and has a live Beat child."""

    try:
        payload = json.loads(config.health_state_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "marko-scheduler-health-v1":
            return False
        if payload.get("state") != "RUNNING":
            return False
        if payload.get("lock_key") != config.lock_key:
            return False
        token = payload.get("token")
        supervisor_pid = payload.get("supervisor_pid")
        beat_pid = payload.get("beat_pid")
        renewed_at = payload.get("last_successful_renewal_at")
        if not isinstance(token, str) or not token:
            return False
        if not isinstance(supervisor_pid, int) or not isinstance(beat_pid, int):
            return False
        if not isinstance(renewed_at, (int, float)):
            return False
        renewal_age = now() - float(renewed_at)
        if renewal_age < -5 or renewal_age > config.ttl_seconds:
            return False
        if not pid_is_alive(supervisor_pid) or not pid_is_alive(beat_pid):
            return False
        if client.get(config.lock_key) != token:
            return False
        return int(client.ttl(config.lock_key)) > 0
    except Exception:
        LOGGER.exception("scheduler_healthcheck_failed key=%s", config.lock_key)
        return False


def _release_without_masking_failure(
    client: RedisLeaseClient,
    *,
    config: SupervisorConfig,
    token: str,
) -> None:
    try:
        release_lease(client, key=config.lock_key, token=token)
    except Exception:
        LOGGER.exception("scheduler_singleton_lock_release_failed key=%s", config.lock_key)


def run_scheduler_supervisor(
    client: RedisLeaseClient,
    *,
    config: SupervisorConfig,
    process_factory: Callable[[Sequence[str]], subprocess.Popen[bytes]] = subprocess.Popen,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
    token_factory: Callable[[], str] | None = None,
) -> int:
    """Supervise a fenced Beat child and reacquire ownership without exiting."""

    supervisor_pid = os.getpid()
    new_token = token_factory or (
        lambda: f"{supervisor_pid}-{secrets.token_hex(16)}"
    )
    backoff = config.reacquire_initial_seconds
    while True:
        token = new_token()
        record_health_state(
            config.health_state_path,
            state="WAITING_FOR_LOCK",
            config=config,
            supervisor_pid=supervisor_pid,
            detail="acquiring_scheduler_lease",
        )
        try:
            acquired = acquire_lease(
                client,
                key=config.lock_key,
                token=token,
                ttl_seconds=config.ttl_seconds,
            )
        except Exception:
            acquired = False
            LOGGER.exception(
                "scheduler_singleton_lock_acquire_failed key=%s retry_in=%s",
                config.lock_key,
                backoff,
            )
        if not acquired:
            LOGGER.warning(
                "scheduler_singleton_lock_unavailable key=%s retry_in=%s",
                config.lock_key,
                backoff,
            )
            sleep(backoff)
            backoff = min(backoff * 2, config.reacquire_max_seconds)
            continue

        backoff = config.reacquire_initial_seconds
        acquired_at = now()
        try:
            process = process_factory(scheduler_command(token))
        except Exception:
            LOGGER.exception("scheduler_beat_start_failed key=%s", config.lock_key)
            _release_without_masking_failure(client, config=config, token=token)
            record_health_state(
                config.health_state_path,
                state="BEAT_START_FAILED",
                config=config,
                supervisor_pid=supervisor_pid,
                detail="celery_beat_process_failed_to_start",
            )
            return 1

        record_health_state(
            config.health_state_path,
            state="RUNNING",
            config=config,
            supervisor_pid=supervisor_pid,
            token=token,
            beat_pid=process.pid,
            last_successful_renewal_at=acquired_at,
        )
        lease_lost = False
        try:
            while process.poll() is None:
                sleep(config.refresh_seconds)
                if process.poll() is not None:
                    break
                try:
                    renewed = renew_lease(
                        client,
                        key=config.lock_key,
                        token=token,
                        ttl_seconds=config.ttl_seconds,
                    )
                except Exception:
                    renewed = False
                    LOGGER.exception(
                        "scheduler_singleton_lock_renew_failed key=%s",
                        config.lock_key,
                    )
                if renewed:
                    record_health_state(
                        config.health_state_path,
                        state="RUNNING",
                        config=config,
                        supervisor_pid=supervisor_pid,
                        token=token,
                        beat_pid=process.pid,
                        last_successful_renewal_at=now(),
                    )
                    continue

                lease_lost = True
                LOGGER.critical(
                    "scheduler_singleton_lock_lost key=%s; stopping fenced beat child",
                    config.lock_key,
                )
                record_health_state(
                    config.health_state_path,
                    state="LOCK_LOST",
                    config=config,
                    supervisor_pid=supervisor_pid,
                    token=token,
                    beat_pid=process.pid,
                    detail="beat_stopped_before_lease_reacquire",
                )
                stop_process(process)
                break
        finally:
            stop_process(process)
            cleanup_beat_pidfile(token)
            _release_without_masking_failure(client, config=config, token=token)

        if lease_lost:
            sleep(backoff)
            backoff = min(backoff * 2, config.reacquire_max_seconds)
            continue

        return_code = int(process.returncode or 0)
        record_health_state(
            config.health_state_path,
            state="BEAT_EXITED",
            config=config,
            supervisor_pid=supervisor_pid,
            detail=f"celery_beat_exit_code={return_code}",
        )
        return return_code


def run_healthcheck(settings: Settings) -> int:
    config = SupervisorConfig.from_settings(settings)
    client = Redis.from_url(settings.celery_broker_url, decode_responses=True)
    try:
        return 0 if scheduler_is_healthy(client, config=config) else 1
    finally:
        client.close()


def _raise_scheduler_shutdown(signum: int, _frame: object) -> None:
    raise SchedulerShutdown(signum)


def run_scheduler(settings: Settings) -> int:
    config = SupervisorConfig.from_settings(settings)
    client = Redis.from_url(settings.celery_broker_url, decode_responses=True)
    previous_sigterm = signal.signal(signal.SIGTERM, _raise_scheduler_shutdown)
    previous_sigint = signal.signal(signal.SIGINT, _raise_scheduler_shutdown)
    try:
        return run_scheduler_supervisor(client, config=config)
    except SchedulerShutdown:
        record_health_state(
            config.health_state_path,
            state="STOPPED",
            config=config,
            supervisor_pid=os.getpid(),
            detail="scheduler_supervisor_shutdown_requested",
        )
        return 0
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGINT, previous_sigint)
        client.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="verify this container's Beat child and Redis lease ownership",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    if args.healthcheck:
        return run_healthcheck(settings)
    return run_scheduler(settings)


if __name__ == "__main__":
    raise SystemExit(main())
