"""Run Celery Beat only while this process owns a renewable Redis lease."""

from __future__ import annotations

import logging
import os
import secrets
import subprocess
import time
from typing import Protocol

from redis import Redis

from marko.core.config import get_settings


LOGGER = logging.getLogger("marko.scheduler")
LOCK_UNAVAILABLE_EXIT = 75
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


def main() -> int:
    settings = get_settings()
    ttl = max(6, settings.scheduler_singleton_ttl_seconds)
    refresh = max(1, settings.scheduler_singleton_refresh_seconds)
    if refresh * 2 >= ttl:
        raise RuntimeError("Scheduler lock refresh must be less than half the TTL")
    key = settings.scheduler_singleton_lock_key.strip()
    if not key:
        raise RuntimeError("SCHEDULER_SINGLETON_LOCK_KEY must not be empty")
    token = f"{os.getpid()}-{secrets.token_hex(16)}"
    client = Redis.from_url(settings.celery_broker_url, decode_responses=True)
    if not acquire_lease(client, key=key, token=token, ttl_seconds=ttl):
        LOGGER.error("scheduler_singleton_lock_unavailable key=%s", key)
        return LOCK_UNAVAILABLE_EXIT

    command = [
        "celery",
        "--app",
        "marko.worker.celery_app:celery_app",
        "beat",
        "--loglevel=INFO",
        "--pidfile=/tmp/marko-celerybeat.pid",
        "--schedule=/tmp/marko-celerybeat-schedule",
    ]
    process = subprocess.Popen(command)
    try:
        while process.poll() is None:
            time.sleep(refresh)
            if not renew_lease(client, key=key, token=token, ttl_seconds=ttl):
                LOGGER.critical("scheduler_singleton_lock_lost key=%s", key)
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                return LOCK_UNAVAILABLE_EXIT
        return int(process.returncode or 0)
    finally:
        try:
            release_lease(client, key=key, token=token)
        except Exception:
            LOGGER.exception("scheduler_singleton_lock_release_failed key=%s", key)
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())

