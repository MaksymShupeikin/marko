"""Ownership and fencing semantics for the Celery Beat singleton lease."""

from marko.worker.beat_singleton import acquire_lease, release_lease, renew_lease


class FakeRedis:
    def __init__(self) -> None:
        self.value: str | None = None
        self.ttl: int | None = None

    def set(self, name: str, value: str, *, nx: bool, ex: int):
        del name
        if nx and self.value is not None:
            return False
        self.value = value
        self.ttl = ex
        return True

    def eval(self, script: str, numkeys: int, *keys_and_args: object):
        del numkeys
        token = str(keys_and_args[1])
        if self.value != token:
            return 0
        if "expire" in script:
            self.ttl = int(keys_and_args[2])
        else:
            self.value = None
        return 1


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
    assert redis.ttl == 40
    assert release_lease(redis, key="scheduler", token="owner-a")
    assert redis.value is None

