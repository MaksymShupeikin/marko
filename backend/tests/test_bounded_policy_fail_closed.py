"""F3: ограниченный прогон обязан отказываться считать без своего снимка политики.

Независимая проверка 2026-08-02 повторила разрыв, который прежняя правка не
закрыла: ``load_run_execution_policy`` возвращалась к ``policy_from_dict`` всякий
раз, когда ``policy_snapshot_hash`` был NULL или испорчен — в том числе для
ограниченных прогонов с контрактом области v2.  То есть строка, завершённая ещё
до миграции 0035, при повторном обогащении или воспроизведении читала ТЕКУЩИЙ
файл развёртывания и выдавала его за исторический вход расчёта.

Разница между «нечего замораживать» и «заморозка потеряна» — это не деталь
реализации: в первом случае прежнего снимка никогда не было, во втором он был и
исчез.  Первому возврат к развёрнутой политике разрешён контрактом, второму —
нет, и подменять одно другим значит переписывать историю молча.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

import marko.services.pricing_runs as pricing_runs
from marko.services.pricing_runs import (
    CONFIRMATION_SOURCE_LEGACY_UNBOUNDED,
    CONFIRMATION_SOURCE_OPERATOR,
    LEGACY_UNBOUNDED_SCOPE_CONTRACT,
    PRICING_RUN_SCOPE_CONTRACT_VERSION,
    PricingRunExecutionPolicyError,
    execution_policy_hash,
    is_legacy_unbounded_run,
    load_run_execution_policy,
    policy_from_dict,
    policy_to_dict,
)


def _snapshot() -> dict:
    return policy_to_dict(policy_from_dict(None))


def _bounded_run(**overrides) -> SimpleNamespace:
    """Строка ограниченного прогона: контракт области объявлен, область заморожена."""

    document = _snapshot()
    kwargs: dict = {
        "id": uuid4(),
        "policy_config": document,
        "policy_snapshot_hash": execution_policy_hash(document),
        "scope_contract_version": PRICING_RUN_SCOPE_CONTRACT_VERSION,
        "scope_confirmation_source": CONFIRMATION_SOURCE_OPERATOR,
        "scope_hash": "a" * 64,
        "catalog_snapshot_hash": "b" * 64,
        "scope_frozen_at": "2026-08-01T00:00:00+00:00",
        "status": "completed",
    }
    kwargs.update(overrides)
    return SimpleNamespace(**kwargs)


def _legacy_run(**overrides) -> SimpleNamespace:
    """Настоящий доконтрактный прогон: ни манифеста, ни подтверждения, ни отпечатков."""

    kwargs: dict = {
        "id": uuid4(),
        "policy_config": {"version": "pricing-v2"},
        "policy_snapshot_hash": None,
        "scope_contract_version": None,
        "scope_confirmation_source": CONFIRMATION_SOURCE_LEGACY_UNBOUNDED,
        "scope_hash": None,
        "catalog_snapshot_hash": None,
        "scope_frozen_at": None,
        "status": "completed",
    }
    kwargs.update(overrides)
    return SimpleNamespace(**kwargs)


# --- «до 0035»: ограниченная строка без отпечатка политики --------------------


def test_a_pre_0035_bounded_run_with_a_null_hash_fails_closed() -> None:
    """Ровно репро: ограниченный прогон v2, завершённый до 0035, отпечатка не несёт.

    Прежняя ветка отдавала ему ``policy_from_dict`` — то есть текущий файл
    развёртывания под видом входа уже принятого расчёта.
    """

    run = _bounded_run(policy_snapshot_hash=None)

    with pytest.raises(PricingRunExecutionPolicyError, match="EXECUTION_POLICY_NOT_FROZEN"):
        load_run_execution_policy(run)


@pytest.mark.parametrize(
    "broken",
    ["", "   ", "not-a-sha256", "zz" * 32, "a" * 63, "a" * 65, 12345, None],
)
def test_a_bounded_run_with_a_malformed_hash_fails_closed(broken) -> None:
    """Испорченный отпечаток — это потерянная заморозка, а не её отсутствие."""

    run = _bounded_run(policy_snapshot_hash=broken)

    with pytest.raises(PricingRunExecutionPolicyError, match="EXECUTION_POLICY_NOT_FROZEN"):
        load_run_execution_policy(run)


def test_a_bounded_run_never_reads_a_changed_deployment_policy(monkeypatch) -> None:
    """Подмена файла развёртывания не должна доезжать до исторической строки.

    Здесь важен не только тип отказа: если бы возврат к развёрнутой политике
    сохранился, тест увидел бы ``d``-отпечаток чужой политики в результате.
    """

    run = _bounded_run(policy_snapshot_hash=None)
    drifted = replace(
        pricing_runs._configured_raise_policy(),
        source_sha256="d" * 64,
    )
    monkeypatch.setattr(pricing_runs, "_configured_raise_policy", lambda: drifted)

    with pytest.raises(PricingRunExecutionPolicyError) as failure:
        load_run_execution_policy(run)

    assert "d" * 64 not in str(failure.value)


@pytest.mark.parametrize(
    "confirmation_source",
    ["OPERATOR", "SYSTEM_REPLAY", "E2E_FIXTURE_REPLAY"],
)
def test_every_bounded_lane_fails_closed_without_a_frozen_policy(
    confirmation_source,
) -> None:
    """Полоса власти не меняет ответа: заморожен — считаем, не заморожен — отказ."""

    run = _bounded_run(
        policy_snapshot_hash=None, scope_confirmation_source=confirmation_source
    )

    with pytest.raises(PricingRunExecutionPolicyError, match="EXECUTION_POLICY_NOT_FROZEN"):
        load_run_execution_policy(run)


def test_a_row_that_declares_no_contract_but_carries_scope_hashes_is_not_legacy() -> None:
    """Полулегаси не бывает: объявленная область без контракта — тоже отказ.

    Иначе достаточно было бы обнулить ``scope_contract_version``, чтобы вернуть
    ограниченному прогону право читать живую политику.
    """

    run = _bounded_run(policy_snapshot_hash=None, scope_contract_version=None)

    assert not is_legacy_unbounded_run(run)
    with pytest.raises(PricingRunExecutionPolicyError, match="EXECUTION_POLICY_NOT_FROZEN"):
        load_run_execution_policy(run)


def test_a_bounded_run_with_a_legacy_confirmation_source_is_not_legacy() -> None:
    """И обратно: подменённый источник подтверждения не делает прогон доконтрактным."""

    run = _bounded_run(
        policy_snapshot_hash=None,
        scope_confirmation_source=CONFIRMATION_SOURCE_LEGACY_UNBOUNDED,
    )

    assert not is_legacy_unbounded_run(run)
    with pytest.raises(PricingRunExecutionPolicyError, match="EXECUTION_POLICY_NOT_FROZEN"):
        load_run_execution_policy(run)


# --- совместимость, которую контракт обязан сохранить -------------------------


def test_a_true_legacy_unbounded_run_still_loads_the_deployment_policy() -> None:
    """Доконтрактный прогон досчитывается по прежнему пути — иначе его не досчитать."""

    run = _legacy_run()

    policy = load_run_execution_policy(run)

    assert is_legacy_unbounded_run(run)
    assert policy.version == policy_from_dict(None).version


def test_a_run_marked_legacy_unbounded_by_contract_version_still_loads() -> None:
    """Тот же путь для строк, где контракт назван словом ``LEGACY_UNBOUNDED``."""

    run = _legacy_run(scope_contract_version=LEGACY_UNBOUNDED_SCOPE_CONTRACT)

    assert is_legacy_unbounded_run(run)
    assert load_run_execution_policy(run).version == policy_from_dict(None).version


def test_a_frozen_bounded_run_still_round_trips_through_its_snapshot() -> None:
    """Заморозка, которая на месте, продолжает работать без изменений."""

    run = _bounded_run()

    assert load_run_execution_policy(run).version == policy_from_dict(None).version


def test_a_frozen_bounded_run_still_rejects_a_tampered_snapshot() -> None:
    """Расхождение снимка и отпечатка остаётся отдельным типизированным отказом."""

    run = _bounded_run()
    run.policy_config = {**run.policy_config, "version": "tampered-v9"}

    with pytest.raises(PricingRunExecutionPolicyError, match="EXECUTION_POLICY_TAMPERED"):
        load_run_execution_policy(run)


def test_the_typed_error_stays_inside_the_pricing_run_error_family() -> None:
    """Вызывающие ловят ``PricingRunError``: новый тип обязан оставаться внутри семьи."""

    assert issubclass(PricingRunExecutionPolicyError, pricing_runs.PricingRunError)
