"""Cross-worker collection pacing and circuit breaking backed by Redis."""

from __future__ import annotations

import time

from redis import Redis

from marko.core.config import Settings
from marko.pricing.observability import pricing_event

_SLOT_SCRIPT = """
local next_at = tonumber(redis.call('GET', KEYS[1]) or '0')
local redis_time = redis.call('TIME')
local now = tonumber(redis_time[1]) * 1000 + math.floor(tonumber(redis_time[2]) / 1000)
local interval = tonumber(ARGV[1])
local wait = 0
if next_at > now then wait = next_at - now end
local base = now
if next_at > base then base = next_at end
local reserved_until = base + interval
local ttl = math.max((reserved_until - now) + interval * 2, 60000)
redis.call('SET', KEYS[1], reserved_until, 'PX', ttl)
return wait
"""


class CollectionCircuitOpen(RuntimeError):
    pass


class DistributedCollectionGuard:
    """One shared start-rate budget for all Celery collection workers."""

    def __init__(self, settings: Settings, *, namespace: str = "prom") -> None:
        self._redis = Redis.from_url(settings.celery_broker_url, decode_responses=True)
        self._slot_key = f"marko:collection:{namespace}:next_at"
        self._failure_key = f"marko:collection:{namespace}:failures"
        self._circuit_key = f"marko:collection:{namespace}:circuit"
        self._interval_ms = max(
            1, int(settings.pricing_collection_min_interval_seconds * 1000)
        )
        self._failure_threshold = max(1, settings.pricing_circuit_failure_threshold)
        self._open_seconds = max(1, settings.pricing_circuit_open_seconds)

    def wait_for_slot(self) -> float:
        """Acquire one globally coordinated physical request-start slot.

        Returns the actual coordination wait in seconds for latency
        decomposition and source-utilization telemetry.
        """
        ttl = self._redis.ttl(self._circuit_key)
        if ttl > 0:
            pricing_event("collection_circuit_open", source="prom", ttl_seconds=ttl)
            raise CollectionCircuitOpen(f"Prom collection circuit is open for {ttl}s")
        wait_ms = int(
            self._redis.eval(
                _SLOT_SCRIPT,
                1,
                self._slot_key,
                self._interval_ms,
            )
        )
        if wait_ms > 0:
            time.sleep(wait_ms / 1000)
        return wait_ms / 1000

    def record_success(self) -> None:
        self._redis.delete(self._failure_key)

    def record_failure(self) -> None:
        pipeline = self._redis.pipeline()
        pipeline.incr(self._failure_key)
        pipeline.expire(self._failure_key, self._open_seconds * 2)
        failures, _ = pipeline.execute()
        if int(failures) >= self._failure_threshold:
            self._redis.set(self._circuit_key, "open", ex=self._open_seconds)
            pricing_event(
                "collection_circuit_open",
                source="prom",
                failures=int(failures),
                ttl_seconds=self._open_seconds,
            )

    def close(self) -> None:
        self._redis.close()

    def __enter__(self) -> DistributedCollectionGuard:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


__all__ = ["CollectionCircuitOpen", "DistributedCollectionGuard"]
