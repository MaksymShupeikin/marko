from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import marko.services.exchange_rates as exchange_rates_module
from marko.services.exchange_rates import NbuExchangeRateProvider, NbuRate


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.ttls[key] = ex


async def test_nbu_rates_parse_usd_eur_and_preserve_exchange_date(monkeypatch):
    payload = [
        {"cc": "USD", "rate": 41.25, "exchangedate": "29.08.2026"},
        {"cc": "EUR", "rate": 48.20, "exchangedate": "29.08.2026"},
        {"cc": "PLN", "rate": 11.0, "exchangedate": "29.08.2026"},
    ]

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def get(self, url, params):
            assert url == exchange_rates_module.NBU_EXCHANGE_URL
            assert params == {"json": "", "date": "20260829"}
            return Response()

    monkeypatch.setattr(
        exchange_rates_module, "httpx", SimpleNamespace(AsyncClient=Client)
    )
    provider = NbuExchangeRateProvider("redis://unused", client=FakeRedis())

    rates = await provider.rates_for(
        {"USD", "EUR", "PLN"}, requested_date=date(2026, 8, 29)
    )

    assert rates == {
        "USD": NbuRate("USD", Decimal("41.25"), "29.08.2026"),
        "EUR": NbuRate("EUR", Decimal("48.2"), "29.08.2026"),
    }


async def test_nbu_current_day_response_is_cached(monkeypatch):
    redis = FakeRedis()
    provider = NbuExchangeRateProvider("redis://unused", client=redis)
    calls = 0

    async def fetch(day):
        nonlocal calls
        calls += 1
        assert day == date(2026, 8, 29)
        return {"USD": NbuRate("USD", Decimal("41.25"), "29.08.2026")}

    monkeypatch.setattr(provider, "_fetch", fetch)
    first = await provider.rates_for({"USD"}, requested_date=date(2026, 8, 29))
    second = await provider.rates_for({"USD"}, requested_date=date(2026, 8, 29))

    assert first == second
    assert calls == 1
    assert list(redis.values) == ["nbu-rates:v1:20260829"]


async def test_nbu_does_not_fall_back_to_previous_day(monkeypatch):
    redis = FakeRedis()
    redis.values["nbu-rates:v1:20260828"] = (
        '{"EUR":{"currency":"EUR","rate":"48.2",'
        '"exchange_date":"28.08.2026"}}'
    )
    provider = NbuExchangeRateProvider("redis://unused", client=redis)

    async def unavailable(_day):
        return {}

    monkeypatch.setattr(provider, "_fetch", unavailable)

    assert await provider.rates_for(
        {"EUR"}, requested_date=date(2026, 8, 29)
    ) == {}
