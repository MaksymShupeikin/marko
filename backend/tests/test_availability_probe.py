import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_probe():
    test_path = Path(__file__).resolve()
    candidates = (
        test_path.parents[2] / "scripts" / "availability_probe.py",
        test_path.parents[1] / "scripts" / "availability_probe.py",
    )
    path = next(candidate for candidate in candidates if candidate.is_file())
    spec = importlib.util.spec_from_file_location("availability_probe_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _SettingsProvider:
    def __init__(self, *, configured: bool) -> None:
        self.settings = SimpleNamespace(
            serper_api_key="configured" if configured else "",
            openai_api_key="configured" if configured else "",
        )
        self.cache_clears = 0

    def __call__(self):
        return self.settings

    def cache_clear(self) -> None:
        self.cache_clears += 1


async def test_probe_runs_two_queries_with_both_flag_values_offline(
    monkeypatch, capsys
):
    probe = _load_probe()
    settings = _SettingsProvider(configured=True)
    calls: list[tuple[str, str | None]] = []

    async def fake_report(query, *, refresh):
        assert refresh is True
        calls.append((query.listing_id, os.getenv(probe._FLAG)))
        return {
            "stats": {"recommended_price": "188"},
            "sources": [],
        }

    original_cache = probe.cp._cache
    original_photo_cache = probe.cp.photo_check._client
    original_flag = os.environ.get(probe._FLAG)
    original_methods = (
        probe.cp.llm_filter._ask_openai,
        probe.cp.GooglePriceSource._serp,
        probe.cp.GooglePriceSource._page_price,
        probe.cp.PromPriceSource._page_products,
        probe.cp.AvtoproPriceSource.search,
    )
    monkeypatch.setattr(probe, "get_settings", settings)
    monkeypatch.setattr(probe.cp, "competitor_prices_for_query", fake_report)

    await probe.main()

    payload = json.loads(capsys.readouterr().out)
    assert calls == [
        ("availability-probe:5202CY", "false"),
        ("availability-probe:5202CY", "true"),
        ("availability-probe:211217", "false"),
        ("availability-probe:211217", "true"),
    ]
    assert payload["configured"] == {"serper": True, "llm": True}
    assert payload["usage"] == {
        "full_reports": 4,
        "serper_calls": 0,
        "llm_calls": 0,
        "prom_pages": 0,
        "google_pages": 0,
        "avtopro_reports": 0,
    }
    assert payload["acceptance"] == {
        "positive_cases": 0,
        "passes": False,
        "rule": (
            "At least one real out-of-stock offer must be observed; every "
            "observed one must stay visible, be demoted and remain outside "
            "the exact current statistics selection."
        ),
    }
    assert probe.cp._cache is original_cache
    assert probe.cp.photo_check._client is original_photo_cache
    assert os.environ.get(probe._FLAG) == original_flag
    assert (
        probe.cp.llm_filter._ask_openai,
        probe.cp.GooglePriceSource._serp,
        probe.cp.GooglePriceSource._page_price,
        probe.cp.PromPriceSource._page_products,
        probe.cp.AvtoproPriceSource.search,
    ) == original_methods
    assert settings.cache_clears == 5


def test_probe_acceptance_requires_unavailable_to_stay_out_of_stats():
    probe = _load_probe()

    def payload(prices):
        return {
            "sources": [
                {
                    "offers": [
                        {
                            "price": str(price),
                            "confidence": confidence,
                            "availability": availability,
                            "url": f"https://shop.ua/{price}",
                        }
                        for price, confidence, availability in prices
                    ]
                }
            ]
        }

    normal = probe._availability_assertions(
        payload(
            [
                (100, 0.5, "Немає в наявності"),
                (180, 0.9, "В наявності"),
                (200, 0.9, None),
                (220, 0.9, "Під замовлення"),
            ]
        )
    )
    assert normal["passes"] is True
    assert normal["out_of_stock_in_stats_urls"] == []
    assert normal["thin_market_fallback_active"] is False

    thin = probe._availability_assertions(
        payload(
            [
                (100, 0.5, "Немає в наявності"),
                (200, 0.9, "В наявності"),
                (220, 0.9, None),
            ]
        )
    )
    assert thin["passes"] is False
    assert thin["out_of_stock_in_stats_urls"] == ["https://shop.ua/100"]
    assert thin["thin_market_fallback_active"] is True


async def test_probe_fails_before_collection_without_required_keys(monkeypatch):
    probe = _load_probe()
    settings = _SettingsProvider(configured=False)
    called = False

    async def forbidden_report(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("external collection must not start")

    monkeypatch.setattr(probe, "get_settings", settings)
    monkeypatch.setattr(probe.cp, "competitor_prices_for_query", forbidden_report)

    with pytest.raises(RuntimeError, match="no external requests were made"):
        await probe.main()

    assert called is False
    assert settings.cache_clears == 0
