"""Redis-backed fixed-window limits for costly or destructive operations."""

from __future__ import annotations

import logging
from functools import lru_cache
from hashlib import sha256
from uuid import UUID

from fastapi import HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from marko.core.config import get_settings

log = logging.getLogger(__name__)

_INCREMENT_WINDOW = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


class RateLimiter:
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: Redis | None = None

    @property
    def client(self) -> Redis:
        if self._client is None:
            self._client = Redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def check(
        self,
        *,
        policy: str,
        identity: str,
        limit: int,
        window_seconds: int,
    ) -> None:
        digest = sha256(identity.encode("utf-8")).hexdigest()[:24]
        key = f"rate-limit:v1:{policy}:{digest}"
        try:
            current, ttl = await self.client.eval(
                _INCREMENT_WINDOW,
                1,
                key,
                max(1, window_seconds),
            )
        except RedisError:
            # Redis also drives Celery. A transient cache failure must not turn
            # every authenticated API call into an outage; Cloudflare remains
            # the outer IP-level control while the problem is logged.
            log.exception("Rate limiter unavailable for policy %s", policy)
            return
        if int(current) <= limit:
            return
        retry_after = max(1, int(ttl))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests; try again later",
            headers={"Retry-After": str(retry_after)},
        )


@lru_cache(maxsize=4)
def _limiter(redis_url: str) -> RateLimiter:
    return RateLimiter(redis_url)


async def enforce_workspace_limit(
    workspace_id: UUID,
    *,
    policy: str,
    limit: int,
    window_seconds: int,
) -> None:
    settings = get_settings()
    if not settings.is_production or not settings.rate_limits_enabled:
        return
    await _limiter(settings.competitor_price_cache_url).check(
        policy=policy,
        identity=str(workspace_id),
        limit=limit,
        window_seconds=window_seconds,
    )


__all__ = ["RateLimiter", "enforce_workspace_limit"]
