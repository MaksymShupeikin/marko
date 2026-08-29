"""Official NBU exchange rates used to normalize competitor prices to UAH."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx
from redis.asyncio import Redis


log = logging.getLogger(__name__)

NBU_EXCHANGE_URL = (
    "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchangenew"
)
KYIV = ZoneInfo("Europe/Kyiv")
SUPPORTED_FOREIGN_CURRENCIES = frozenset({"USD", "EUR"})
_CACHE_TTL_SECONDS = 90_000


class _RedisClient(Protocol):
    async def get(self, key: str) -> bytes | str | None:
        ...

    async def set(self, key: str, value: str, *, ex: int) -> Any:
        ...


@dataclass(frozen=True)
class NbuRate:
    currency: str
    rate: Decimal
    exchange_date: str

    def as_json(self) -> dict[str, str]:
        return {
            "currency": self.currency,
            "rate": str(self.rate),
            "exchange_date": self.exchange_date,
        }


class NbuExchangeRateProvider:
    """Fetch and cache the official rate applicable to one Kyiv calendar day."""

    def __init__(
        self,
        redis_url: str,
        *,
        client: _RedisClient | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._redis_url = redis_url
        self._client = client
        self._timeout = timeout

    def _redis(self) -> _RedisClient:
        if self._client is None:
            self._client = Redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def rates_for(
        self,
        currencies: set[str],
        *,
        requested_date: date | None = None,
    ) -> dict[str, NbuRate]:
        wanted = {
            value.strip().upper()
            for value in currencies
            if value.strip().upper() in SUPPORTED_FOREIGN_CURRENCIES
        }
        if not wanted:
            return {}

        day = requested_date or datetime.now(KYIV).date()
        cache_key = f"nbu-rates:v1:{day:%Y%m%d}"
        cached = await self._cached(cache_key)
        if wanted.issubset(cached):
            return {currency: cached[currency] for currency in wanted}

        fetched = await self._fetch(day)
        if fetched:
            try:
                await self._redis().set(
                    cache_key,
                    json.dumps(
                        {key: value.as_json() for key, value in fetched.items()},
                        separators=(",", ":"),
                    ),
                    ex=_CACHE_TTL_SECONDS,
                )
            except Exception as exc:
                log.warning("Could not cache NBU rates for %s: %s", day, exc)
        return {currency: fetched[currency] for currency in wanted if currency in fetched}

    async def _cached(self, key: str) -> dict[str, NbuRate]:
        try:
            raw = await self._redis().get(key)
        except Exception as exc:
            log.warning("Could not read NBU rate cache: %s", exc)
            return {}
        if raw is None:
            return {}
        try:
            payload = json.loads(raw)
            return {
                currency: NbuRate(
                    currency=currency,
                    rate=Decimal(str(item["rate"])),
                    exchange_date=str(item["exchange_date"]),
                )
                for currency, item in payload.items()
                if currency in SUPPORTED_FOREIGN_CURRENCIES
                and isinstance(item, dict)
            }
        except (KeyError, TypeError, ValueError, InvalidOperation):
            log.warning("Invalid NBU rate cache payload for %s", key)
            return {}

    async def _fetch(self, day: date) -> dict[str, NbuRate]:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers={"Accept": "application/json"},
            ) as client:
                response = await client.get(
                    NBU_EXCHANGE_URL,
                    params={"json": "", "date": day.strftime("%Y%m%d")},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            log.warning("NBU exchange-rate request for %s failed: %s", day, exc)
            return {}

        rates: dict[str, NbuRate] = {}
        for item in payload if isinstance(payload, list) else ():
            if not isinstance(item, dict):
                continue
            currency = str(item.get("cc") or "").strip().upper()
            if currency not in SUPPORTED_FOREIGN_CURRENCIES:
                continue
            try:
                rate = Decimal(str(item["rate"]))
            except (KeyError, InvalidOperation, ValueError):
                continue
            if rate <= 0:
                continue
            exchange_date = str(item.get("exchangedate") or "").strip()
            if not exchange_date:
                continue
            rates[currency] = NbuRate(
                currency=currency,
                rate=rate,
                exchange_date=exchange_date,
            )
        return rates


__all__ = [
    "KYIV",
    "NBU_EXCHANGE_URL",
    "NbuExchangeRateProvider",
    "NbuRate",
    "SUPPORTED_FOREIGN_CURRENCIES",
]
