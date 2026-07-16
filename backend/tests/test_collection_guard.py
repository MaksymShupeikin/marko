from marko.services.collection_guard import (
    DistributedCollectionGuard,
    _SLOT_SCRIPT,
)


def test_global_slot_uses_redis_clock_and_reservation_aware_ttl() -> None:
    assert "redis.call('TIME')" in _SLOT_SCRIPT
    assert "reserved_until - now" in _SLOT_SCRIPT

    class Redis:
        def __init__(self):
            self.eval_args = None

        def ttl(self, _key):
            return -2

        def eval(self, *args):
            self.eval_args = args
            return 0

    redis = Redis()
    guard = object.__new__(DistributedCollectionGuard)
    guard._redis = redis
    guard._slot_key = "slot"
    guard._circuit_key = "circuit"
    guard._interval_ms = 250

    assert guard.wait_for_slot() == 0
    assert redis.eval_args == (_SLOT_SCRIPT, 1, "slot", 250)
