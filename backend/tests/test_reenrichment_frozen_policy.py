"""Повторное обогащение обязано считать по замороженной политике прогона.

Ревью round 2: ``oe_reenrichment`` пересобирал политику через
``policy_from_dict(run.policy_config)`` — то есть терял проверку
``policy_snapshot_hash``. Изменение развёрнутой политики меняло результат уже
идущего ограниченного прогона, и повторить его было нельзя.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from marko.services.pricing_runs import (
    execution_policy_hash,
    load_run_execution_policy,
    policy_from_dict,
    policy_to_dict,
)


def _frozen_run():
    policy = policy_from_dict(None)
    document = policy_to_dict(policy)
    return SimpleNamespace(
        policy_config=document,
        policy_snapshot_hash=execution_policy_hash(document),
    )


def test_reenrichment_reads_the_frozen_snapshot_not_the_deployment_file() -> None:
    """Модуль обязан звать проверяющий загрузчик, а не сырую пересборку."""

    import marko.services.oe_reenrichment as module

    source = module.__loader__.get_source(module.__name__)
    assert "policy_from_dict(run.policy_config)" not in source, (
        "повторное обогащение снова собирает политику из текущего развёртывания"
    )
    assert "load_run_execution_policy" in source


def test_a_frozen_snapshot_round_trips_under_the_verifying_loader() -> None:
    run = _frozen_run()
    policy = load_run_execution_policy(run)
    assert policy.version == policy_from_dict(None).version


def test_a_corrupted_snapshot_fails_closed() -> None:
    """Порча снимка обязана останавливать расчёт, а не молча его продолжать."""

    run = _frozen_run()
    tampered = dict(run.policy_config)
    raise_block = dict(tampered.get("raise_policy") or {})
    if raise_block:
        raise_block["min_evidence"] = 999
        tampered["raise_policy"] = raise_block
    else:
        tampered["version"] = "tampered"
    broken = SimpleNamespace(
        policy_config=tampered,
        policy_snapshot_hash=run.policy_snapshot_hash,
    )
    with pytest.raises(Exception):
        load_run_execution_policy(broken)


def test_changing_the_deployment_policy_cannot_change_a_frozen_run() -> None:
    """Развёрнутая политика — источник для НОВОГО предпросмотра, не для прогона."""

    run = _frozen_run()
    before = load_run_execution_policy(run)
    deployed = policy_from_dict(None)
    drifted = replace(deployed, version="deployment-drifted-v9")
    assert drifted.version != before.version
    after = load_run_execution_policy(run)
    assert after.version == before.version
