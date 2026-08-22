"""Отмена прогона обязана останавливать и дорожку без OE.

2026-08-21: полнокаталожный прогон `d9910edb` отменён штатной кнопкой — 3111
позиций сразу перешли в `cancelled`, `cancel_requested` выставлен. Задача
`process_no_oe_discovery_item` продолжала работать и делать платные вызовы
OpenAI **через 9 часов после отмены**; остановил её только
`docker compose stop pricing-worker`. Инцидент стоил $0.83 на этой дорожке
сверх $6.62 на дорожке OE.

Причина: OE-дорожка проверяет `run.cancel_requested`
(`market_collection.py:1309`), а дорожка без OE — нет. Проверок нужно две:
до сбора и **после** него, потому что живой сбор длится 2–4 минуты, а сразу
за ним уходит до десяти параллельных платных вызовов.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from marko.core.config import Settings
from marko.services import no_oe_pricing


class _ExplodingSession:
    """Сессия, которая доказывает, что до платной части дело не дошло."""

    def __init__(self, run_item, run) -> None:
        self._run_item = run_item
        self._run = run
        self.committed = 0

    async def scalar(self, _statement):
        return self._run_item

    async def get(self, _model, _identifier):
        return self._run

    async def commit(self) -> None:
        self.committed += 1

    async def scalars(self, _statement):  # pragma: no cover - must not be reached
        raise AssertionError("cancelled run must not read discovery offers")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        pricing_no_oe_discovery_enabled=True,
        pricing_llm_comparability_mode="required",
        pricing_llm_api_key="test-key-not-a-real-secret",
    )


def _run_item():
    return SimpleNamespace(
        id=uuid4(),
        pricing_run_id=uuid4(),
        status="discovering",
        start_snapshot={"name": "Шпилька ступиці", "brand": "Mercedes-Benz"},
        no_oe_discovery_run_id=None,
        finished_at=None,
    )


@pytest.mark.asyncio
async def test_cancelled_run_never_reaches_the_paid_collection(monkeypatch) -> None:
    run_item = _run_item()
    run = SimpleNamespace(
        id=run_item.pricing_run_id, workspace_id=uuid4(), cancel_requested=True
    )
    session = _ExplodingSession(run_item, run)
    monkeypatch.setattr(no_oe_pricing, "async_session_factory", lambda: session)

    async def _must_not_collect(*_args, **_kwargs):  # pragma: no cover
        raise AssertionError("cancelled run must not scrape or call the provider")

    monkeypatch.setattr(no_oe_pricing, "collect_catalog_discovery", _must_not_collect)

    result = await no_oe_pricing.process_no_oe_discovery_item(
        run_item.id, settings=_settings()
    )

    assert result is None
    assert run_item.status == "cancelled"
    assert run_item.finished_at is not None
    assert session.committed == 1


@pytest.mark.asyncio
async def test_cancel_arriving_during_the_scrape_stops_the_provider_calls(
    monkeypatch,
) -> None:
    """Сбор длится 2–4 минуты. Отмена во время него обязана быть замечена."""

    run_item = _run_item()
    run = SimpleNamespace(
        id=run_item.pricing_run_id, workspace_id=uuid4(), cancel_requested=False
    )
    session = _ExplodingSession(run_item, run)
    monkeypatch.setattr(no_oe_pricing, "async_session_factory", lambda: session)

    async def _slow_collection(*_args, **_kwargs):
        # Оператор нажал «Отменить», пока шёл сбор.
        run.cancel_requested = True
        return SimpleNamespace(run_id=uuid4())

    monkeypatch.setattr(no_oe_pricing, "collect_catalog_discovery", _slow_collection)

    result = await no_oe_pricing.process_no_oe_discovery_item(
        run_item.id, settings=_settings()
    )

    assert result is None
    assert run_item.status == "cancelled"


@pytest.mark.asyncio
async def test_a_live_run_is_not_stopped_by_the_new_gate(monkeypatch) -> None:
    """Проверка обязана уметь пропускать: иначе она глушит рабочие прогоны."""

    run_item = _run_item()
    run = SimpleNamespace(
        id=run_item.pricing_run_id, workspace_id=uuid4(), cancel_requested=False
    )
    session = _ExplodingSession(run_item, run)
    monkeypatch.setattr(no_oe_pricing, "async_session_factory", lambda: session)

    async def _collect(*_args, **_kwargs):
        return SimpleNamespace(run_id=uuid4())

    monkeypatch.setattr(no_oe_pricing, "collect_catalog_discovery", _collect)

    with pytest.raises(AssertionError, match="must not read discovery offers"):
        await no_oe_pricing.process_no_oe_discovery_item(
            run_item.id, settings=_settings()
        )

    assert run_item.status == "discovering"
