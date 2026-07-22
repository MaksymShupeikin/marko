"""Ownership, fencing, recovery, and health semantics for Celery Beat."""

from pathlib import Path

import pytest

from marko.worker.beat_singleton import (
    SupervisorConfig,
    acquire_lease,
    release_lease,
    renew_lease,
    run_scheduler_supervisor,
    scheduler_command,
    scheduler_is_healthy,
    write_health_state,
)


class FakeRedis:
    def __init__(self, *, renew_failure: object | None = None) -> None:
        self.value: str | None = None
        self.ttl_seconds: int | None = None
        self.renew_failure = renew_failure

    def set(self, name: str, value: str, *, nx: bool, ex: int):
        del name
        if nx and self.value is not None:
            return False
        self.value = value
        self.ttl_seconds = ex
        return True

    def eval(self, script: str, numkeys: int, *keys_and_args: object):
        del numkeys
        token = str(keys_and_args[1])
        if self.value != token:
            return 0
        if "expire" in script:
            if self.renew_failure is not None:
                failure = self.renew_failure
                self.renew_failure = None
                self.value = None
                self.ttl_seconds = None
                if isinstance(failure, BaseException):
                    raise failure
                return failure
            self.ttl_seconds = int(keys_and_args[2])
        else:
            self.value = None
            self.ttl_seconds = None
        return 1

    def get(self, name: str):
        del name
        return self.value

    def ttl(self, name: str) -> int:
        del name
        return int(self.ttl_seconds if self.ttl_seconds is not None else -2)


class FakeProcess:
    _next_pid = 1000

    def __init__(self, poll_results: list[int | None]) -> None:
        self.poll_results = poll_results
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self.pid = FakeProcess._next_pid
        FakeProcess._next_pid += 1

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        if self.poll_results:
            result = self.poll_results.pop(0)
            if result is not None:
                self.returncode = result
            return result
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None):
        del timeout
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def config(path: Path) -> SupervisorConfig:
    return SupervisorConfig(
        lock_key="scheduler",
        ttl_seconds=90,
        refresh_seconds=20,
        reacquire_initial_seconds=1,
        reacquire_max_seconds=8,
        health_state_path=path,
    )


def test_second_scheduler_cannot_acquire_live_lease() -> None:
    redis = FakeRedis()

    assert acquire_lease(redis, key="scheduler", token="owner-a", ttl_seconds=30)
    assert not acquire_lease(
        redis,
        key="scheduler",
        token="owner-b",
        ttl_seconds=30,
    )


def test_only_owner_can_renew_or_release_scheduler_lease() -> None:
    redis = FakeRedis()
    assert acquire_lease(redis, key="scheduler", token="owner-a", ttl_seconds=30)

    assert not renew_lease(
        redis,
        key="scheduler",
        token="stale-owner",
        ttl_seconds=40,
    )
    assert not release_lease(redis, key="scheduler", token="stale-owner")
    assert redis.value == "owner-a"
    assert renew_lease(
        redis,
        key="scheduler",
        token="owner-a",
        ttl_seconds=40,
    )
    assert redis.ttl_seconds == 40
    assert release_lease(redis, key="scheduler", token="owner-a")
    assert redis.value is None


def test_reacquired_beat_keeps_schedule_state_but_uses_a_fresh_pidfile() -> None:
    first = scheduler_command("supervisor-owner-a")
    second = scheduler_command("supervisor-owner-b")

    assert "--schedule=/tmp/marko-celerybeat-schedule" in first
    assert "--schedule=/tmp/marko-celerybeat-schedule" in second
    assert next(item for item in first if item.startswith("--pidfile=")) != next(
        item for item in second if item.startswith("--pidfile=")
    )


@pytest.mark.parametrize("renew_failure", [False, RuntimeError("redis unavailable")])
def test_lock_loss_stops_beat_and_reacquires_without_exiting_supervisor(
    tmp_path: Path,
    renew_failure: object,
) -> None:
    redis = FakeRedis(renew_failure=renew_failure)
    first = FakeProcess([None, None])
    second = FakeProcess([0])
    processes = iter((first, second))
    sleeps: list[float] = []
    tokens = iter(("supervisor-owner-a", "supervisor-owner-b"))

    result = run_scheduler_supervisor(
        redis,
        config=config(tmp_path / "health.json"),
        process_factory=lambda _command: next(processes),
        sleep=sleeps.append,
        now=lambda: 100.0,
        token_factory=lambda: next(tokens),
    )

    assert result == 0
    assert first.terminated is True
    assert first.killed is False
    assert second.terminated is False
    assert sleeps == [20, 1]


def test_healthcheck_requires_fresh_owned_lease_and_live_processes(
    tmp_path: Path,
) -> None:
    health_path = tmp_path / "health.json"
    scheduler_config = config(health_path)
    redis = FakeRedis()
    redis.value = "supervisor-owner"
    redis.ttl_seconds = 75
    write_health_state(
        health_path,
        state="RUNNING",
        config=scheduler_config,
        supervisor_pid=10,
        token="supervisor-owner",
        beat_pid=11,
        last_successful_renewal_at=100.0,
    )

    assert scheduler_is_healthy(
        redis,
        config=scheduler_config,
        now=lambda: 120.0,
        pid_is_alive=lambda pid: pid in {10, 11},
    )

    redis.value = "different-owner"
    assert not scheduler_is_healthy(
        redis,
        config=scheduler_config,
        now=lambda: 120.0,
        pid_is_alive=lambda _pid: True,
    )


def test_healthcheck_rejects_stale_renewal(tmp_path: Path) -> None:
    health_path = tmp_path / "health.json"
    scheduler_config = config(health_path)
    redis = FakeRedis()
    redis.value = "supervisor-owner"
    redis.ttl_seconds = 1
    write_health_state(
        health_path,
        state="RUNNING",
        config=scheduler_config,
        supervisor_pid=10,
        token="supervisor-owner",
        beat_pid=11,
        last_successful_renewal_at=100.0,
    )

    assert not scheduler_is_healthy(
        redis,
        config=scheduler_config,
        now=lambda: 191.0,
        pid_is_alive=lambda _pid: True,
    )
