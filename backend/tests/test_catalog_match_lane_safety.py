"""Что кнопка «Сопоставить» обязана делать до того, как потратит деньги.

Дорожка платная и запускается оператором из интерфейса, поэтому её выключатель
проверяется раньше всего остального, а расширение входа модели не имеет права
сдвинуть входные хеши уже оплаченных отзывов — иначе кэш обесценится и вся
последующая работа станет платной заново.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from marko.core.config import Settings
from marko.services import catalog_match
from marko.services.candidate_offer_grouping import group_candidate_offers
from marko.services.no_oe_pricing import NoOeQueryPlan, build_no_oe_review_input


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "pricing_llm_comparability_mode": "required",
        "pricing_llm_api_key": "test-key-not-a-real-secret",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_the_lane_is_off_until_it_is_switched_on(monkeypatch) -> None:
    def _explode() -> None:  # pragma: no cover - must not be reached
        raise AssertionError("disabled lane must not open a session")

    monkeypatch.setattr(catalog_match, "async_session_factory", _explode)

    result = await catalog_match.process_catalog_match_run(
        SimpleNamespace(), settings=_settings(catalog_match_enabled=False)
    )

    assert result is None


def test_the_switch_is_its_own_and_defaults_to_off() -> None:
    settings = _settings()

    assert settings.catalog_match_enabled is False
    # Не общий с дорожкой без OE: та закрыта по своей причине и висит на
    # другой точке входа.
    assert settings.pricing_no_oe_discovery_enabled is False
    assert settings.catalog_match_max_groups >= 42


def _offer(**kwargs: object) -> SimpleNamespace:
    base = {
        "id": kwargs.pop("id", "offer-1"),
        "title": "Кришка BMW",
        "sku": "B1",
        "brand": "BMW",
        "seller_id": "seller",
        "sale_price": None,
        "currency": "UAH",
        "selection_status": "SELECTED",
        "selection_reason": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_an_admitted_group_carries_no_gate_verdict_into_the_review() -> None:
    group = group_candidate_offers([_offer()])[0]

    assert catalog_match._gate_assessment(group) is None


def test_a_refused_group_tells_the_model_what_was_refused_and_why() -> None:
    group = group_candidate_offers(
        [_offer(selection_status="REJECTED", selection_reason="OEM_CONFLICT")]
    )[0]

    assessment = catalog_match._gate_assessment(group)

    assert assessment is not None
    assert assessment["deterministic_gates"] == "REJECTED"
    assert assessment["reasons"] == ["OEM_CONFLICT"]
    # Пересмотр, а не суд вслепую — решение владельца 22.08.
    assert "refusal holds" in assessment["instruction"]


def _plan() -> NoOeQueryPlan:
    return NoOeQueryPlan(
        queries=("357905851D",),
        source_fields=("catalog_discovery_run",),
        frozen_input_sha256="0" * 64,
    )


def test_the_new_field_does_not_move_the_hashes_of_paid_reviews() -> None:
    """Без ворот вход обязан быть побайтово прежним: кэш OE-дорожки живой."""

    without = build_no_oe_review_input(
        start_snapshot={"sku": "1153724214", "brand": "VW"},
        exact_offer={"offer_id": "a", "title": "Корпус"},
        plan=_plan(),
    )

    assert "gate_assessment" not in without["deterministic_context"]


def test_the_gate_verdict_reaches_the_model_when_there_is_one() -> None:
    with_gate = build_no_oe_review_input(
        start_snapshot={"sku": "1153724214", "brand": "VW"},
        exact_offer={"offer_id": "a", "title": "Корпус"},
        plan=_plan(),
        gate_assessment={"deterministic_gates": "REJECTED", "reasons": ["USED"]},
    )

    context = with_gate["deterministic_context"]["gate_assessment"]
    assert context["reasons"] == ["USED"]


def test_our_own_condition_travels_with_the_question() -> None:
    """Карточка 2141006 помечена «Вживаний» — сравнение с новым не то же самое."""

    payload = build_no_oe_review_input(
        start_snapshot={
            "sku": "2141006",
            "brand": "Mercedes-Benz",
            "characteristics_raw": {"Стан": "Вживаний"},
        },
        exact_offer={"offer_id": "a", "title": "Шпилька"},
        plan=_plan(),
    )

    assert payload["our_product"]["characteristics_raw"] == {"Стан": "Вживаний"}
