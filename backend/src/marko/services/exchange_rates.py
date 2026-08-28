"""Курси валют НБУ: перерахунок доларових і єврових цін у гривню.

Публічний API НБУ без ключа; курс живе добу, тому кешується в тому ж
Redis, що й звіти конкурентів. Недоступний НБУ — не привід валити звіт:
повертаємо порожній словник, і іновалютні пропозиції відкидаються, як
було до конвертації.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import httpx
from redis.asyncio import Redis

from marko.core.config import get_settings

log = logging.getLogger(__name__)

_NBU_URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json"
_WANTED = ("USD", "EUR")
_CACHE_TTL = 24 * 60 * 60
_TIMEOUT = 5.0

_client: Redis | None = None


def _redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(
            get_settings().competitor_price_cache_url, decode_responses=True
        )
    return _client


def _cache_key() -> str:
    return f"fx:v1:{datetime.now(UTC).date().isoformat()}"


async def uah_rates() -> dict[str, Decimal]:
    """Курс гривні за одиницю валюти, {"USD": 41.5, ...}; порожньо — без курсів."""
    try:
        cached = await _redis().get(_cache_key())
    except Exception as exc:  # Redis лежить — ідемо напряму в НБУ
        log.warning("Курси валют: кеш недоступний: %s", exc)
        cached = None
    if cached:
        try:
            return {code: Decimal(value) for code, value in json.loads(cached).items()}
        except (ValueError, InvalidOperation):
            pass  # зіпсований запис — перечитаємо з НБУ

    rates = await _fetch()
    if rates:
        try:
            await _redis().set(
                _cache_key(),
                json.dumps({code: str(value) for code, value in rates.items()}),
                ex=_CACHE_TTL,
            )
        except Exception as exc:
            log.warning("Курси валют: не вдалося закешувати: %s", exc)
    return rates


async def _fetch() -> dict[str, Decimal]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(_NBU_URL)
            response.raise_for_status()
            entries = response.json()
    except Exception as exc:
        log.warning("Курси валют: НБУ не відповів: %s", exc)
        return {}
    rates: dict[str, Decimal] = {}
    for entry in entries if isinstance(entries, list) else []:
        code = str(entry.get("cc") or "").upper()
        if code not in _WANTED:
            continue
        try:
            rate = Decimal(str(entry.get("rate")))
        except (InvalidOperation, TypeError):
            continue
        if rate > 0:
            rates[code] = rate
    if len(rates) < len(_WANTED):
        log.warning("Курси валют: НБУ віддав не всі валюти: %s", sorted(rates))
    return rates
