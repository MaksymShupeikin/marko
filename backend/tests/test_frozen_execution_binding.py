"""F4: снимок обязан быть привязан к той строке членства, в которой лежит.

Ревью round 2 (независимый валидатор) воспроизвело: ``verified_start_snapshot``
проверяет только собственный отпечаток снимка. Отпечаток — доказательство того,
что снимок не правили, и НЕ доказательство того, что он описывает эту позицию.
Пересчитать честный SHA-256 поверх снимка товара B и положить его в
``PricingRunItem`` товара A было достаточно, чтобы ограниченный прогон посчитал
чужую позицию, и в базе не осталось бы ни следа.

Второй воспроизведённый дефект: обязательные поля снимка (``source_row``,
``name``, ``mpn_norm``, ``identity_status``) при отсутствии подменялись
значениями по умолчанию — нулём, пустой строкой, ``UNRESOLVED``. Дырка в
замороженных входах становилась правдоподобным значением.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from marko.services.market_collection import (
    FrozenBindingError,
    display_catalog_item,
    resolve_bound_execution_item,
)
from marko.services.pricing_runs import (
    PRICING_RUN_SCOPE_CONTRACT_VERSION,
    frozen_catalog_item_from_snapshot,
    start_snapshot_fingerprint,
)


ITEM_A = UUID("aaaaaaaa-0000-4000-8000-000000000001")
ITEM_B = UUID("bbbbbbbb-0000-4000-8000-000000000002")
RUN_ID = UUID("11111111-0000-4000-8000-000000000001")
OTHER_RUN_ID = UUID("22222222-0000-4000-8000-000000000002")


def _snapshot(
    *,
    catalog_item_id: UUID = ITEM_A,
    membership_position: int = 0,
    override_id: UUID | None = None,
    cost_record_id: UUID | None = None,
    **overrides: object,
) -> dict[str, object]:
    """Полный снимок ровно в том виде, в каком его пишет старт прогона."""

    snapshot: dict[str, object] = {
        "contract_version": PRICING_RUN_SCOPE_CONTRACT_VERSION,
        "frozen_at": "2026-08-01T00:00:00+00:00",
        "membership_position": membership_position,
        "catalog_item_id": str(catalog_item_id),
        "source_row": 7,
        "sku": "SKU-1",
        "oe_norm": "1K0615301",
        "mpn_norm": "MPN1",
        "name": "Диск тормозной",
        "brand": "KEMP",
        "category": "brakes",
        "current_price": "1000.00",
        "currency": "UAH",
        "stock_status": "IN_STOCK",
        "product_url": None,
        "is_available": True,
        "identity_status": "VERIFIED",
        "stock_qty": "5",
        "stock_age_days": None,
        "expected_units_sold": None,
        "units_sold_30d": None,
        "units_sold_60d": None,
        "units_sold_90d": None,
        "days_since_last_sale": None,
        "historical_monthly_units": None,
        "views_30d": None,
        "conversion_rate_proxy": None,
        "manual_priority": None,
        "catalog_item_override_id": str(override_id) if override_id else None,
        "override_values": None,
        "cost_record_id": str(cost_record_id) if cost_record_id else None,
        "cost_record_sequence_no": None,
    }
    snapshot.update(overrides)
    return snapshot


def _run(*, bounded: bool = True, run_id: UUID = RUN_ID) -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id,
        scope_contract_version=(
            PRICING_RUN_SCOPE_CONTRACT_VERSION if bounded else "LEGACY_UNBOUNDED"
        ),
    )


def _run_item(
    snapshot: dict[str, object],
    *,
    catalog_item_id: UUID = ITEM_A,
    membership_position: int = 0,
    override_id: UUID | None = None,
    cost_record_id: UUID | None = None,
    pricing_run_id: UUID = RUN_ID,
    rehash: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        pricing_run_id=pricing_run_id,
        catalog_item_id=catalog_item_id,
        membership_position=membership_position,
        catalog_item_override_id=override_id,
        cost_record_id=cost_record_id,
        start_snapshot=snapshot,
        # Отпечаток честный: атака — не подделка хеша, а подмена содержимого,
        # для которого хеш пересчитан правильно.
        start_snapshot_hash=(
            start_snapshot_fingerprint(snapshot) if rehash else "0" * 64
        ),
    )


def _live(item_id: UUID = ITEM_A) -> SimpleNamespace:
    return SimpleNamespace(id=item_id, category="LIVE-DRIFT", oe_norm="LIVE-DRIFT")


# -- Положительный случай ----------------------------------------------------


def test_a_bound_snapshot_resolves_to_the_frozen_position() -> None:
    snapshot = _snapshot()
    resolved = resolve_bound_execution_item(_run(), _run_item(snapshot), _live())

    assert resolved.id == ITEM_A
    assert resolved.category == "brakes"
    assert resolved.oe_norm == "1K0615301"
    assert resolved.source_row == 7
    assert resolved.identity_status == "VERIFIED"


# -- F4: связь снимка со строкой членства ------------------------------------


def test_a_correctly_hashed_snapshot_of_another_item_is_refused() -> None:
    """Отпечаток сходится, а описанная позиция — другая.

    Ровно этот случай проходил раньше: ``verified_start_snapshot`` возвращал
    снимок, ``frozen_catalog_item_from_snapshot`` брал из него ``id`` товара B,
    и весь прогон позиции A считался по товару B.
    """

    smuggled = _snapshot(catalog_item_id=ITEM_B)
    run_item = _run_item(smuggled, catalog_item_id=ITEM_A)

    # Отпечаток действительно сходится — защита обязана держаться не на нём.
    assert run_item.start_snapshot_hash == start_snapshot_fingerprint(smuggled)
    # И прежний путь действительно вернул бы чужую позицию.
    assert frozen_catalog_item_from_snapshot(smuggled).id == ITEM_B

    with pytest.raises(FrozenBindingError, match="START_SNAPSHOT_MISBOUND"):
        resolve_bound_execution_item(_run(), run_item, _live())


@pytest.mark.parametrize(
    ("snapshot_kwargs", "row_kwargs", "why"),
    (
        (
            {"membership_position": 3},
            {"membership_position": 0},
            "место в замороженном членстве",
        ),
        (
            {"override_id": UUID("cccccccc-0000-4000-8000-000000000003")},
            {"override_id": None},
            "правка оператора",
        ),
        (
            {"cost_record_id": UUID("dddddddd-0000-4000-8000-000000000004")},
            {"cost_record_id": None},
            "запись себестоимости",
        ),
    ),
)
def test_every_named_binding_must_match_the_membership_row(
    snapshot_kwargs, row_kwargs, why: str
) -> None:
    snapshot = _snapshot(**snapshot_kwargs)
    run_item = _run_item(snapshot, **row_kwargs)

    with pytest.raises(FrozenBindingError, match="START_SNAPSHOT_MISBOUND"):
        resolve_bound_execution_item(_run(), run_item, _live())


def test_a_run_item_belonging_to_another_run_is_refused() -> None:
    run_item = _run_item(_snapshot(), pricing_run_id=OTHER_RUN_ID)

    with pytest.raises(FrozenBindingError, match="START_SNAPSHOT_UNBOUND"):
        resolve_bound_execution_item(_run(), run_item, _live())


def test_a_live_row_for_a_different_position_is_refused() -> None:
    """Живая строка чужого товара рядом с позицией — уже расхождение."""

    with pytest.raises(FrozenBindingError, match="START_SNAPSHOT_UNBOUND"):
        resolve_bound_execution_item(_run(), _run_item(_snapshot()), _live(ITEM_B))


# -- F4: обязательные поля не подменяются значением по умолчанию -------------


@pytest.mark.parametrize(
    ("field", "default_it_used_to_get"),
    (
        ("source_row", 0),
        ("name", ""),
        ("mpn_norm", ""),
        ("identity_status", "UNRESOLVED"),
        ("sku", None),
        ("category", None),
    ),
)
def test_a_missing_required_field_fails_closed_instead_of_defaulting(
    field: str, default_it_used_to_get: object
) -> None:
    snapshot = _snapshot()
    snapshot.pop(field)
    run_item = _run_item(snapshot)

    with pytest.raises(FrozenBindingError, match="START_SNAPSHOT_INCOMPLETE"):
        resolve_bound_execution_item(_run(), run_item, _live())

    if default_it_used_to_get is not None:
        # Прежний путь молча подставлял значение по умолчанию: дырка в
        # замороженных входах выглядела как настоящее значение.
        assert (
            getattr(frozen_catalog_item_from_snapshot(snapshot), field)
            == default_it_used_to_get
        )


def test_an_empty_required_string_is_not_a_value() -> None:
    run_item = _run_item(_snapshot(identity_status="   "))

    with pytest.raises(FrozenBindingError, match="START_SNAPSHOT_INCOMPLETE"):
        resolve_bound_execution_item(_run(), run_item, _live())


def test_an_empty_manufacturer_number_is_a_legitimate_value() -> None:
    """``mpn_norm`` законно бывает пустым — отказывать здесь нельзя."""

    resolved = resolve_bound_execution_item(
        _run(), _run_item(_snapshot(mpn_norm="")), _live()
    )

    assert resolved.mpn_norm == ""


def test_a_non_integer_source_row_is_corrupt_not_zero() -> None:
    run_item = _run_item(_snapshot(source_row="7"))

    with pytest.raises(FrozenBindingError, match="START_SNAPSHOT_CORRUPT"):
        resolve_bound_execution_item(_run(), run_item, _live())


# -- Историческая ветка ------------------------------------------------------


def test_a_legacy_unbounded_run_still_reads_its_live_row() -> None:
    live = _live()

    assert (
        resolve_bound_execution_item(_run(bounded=False), _run_item(_snapshot()), live)
        is live
    )


def test_a_legacy_unbounded_run_without_its_live_row_is_refused() -> None:
    with pytest.raises(FrozenBindingError, match="START_SNAPSHOT_UNBOUND"):
        resolve_bound_execution_item(_run(bounded=False), _run_item(_snapshot()), None)


def test_the_display_only_accessor_is_named_and_does_nothing_else() -> None:
    """Живой каталог остаётся доступен, но только под своим именем."""

    live = _live()

    assert display_catalog_item(live) is live
    assert display_catalog_item(None) is None


def test_the_frozen_position_carries_decimals_not_strings() -> None:
    resolved = resolve_bound_execution_item(_run(), _run_item(_snapshot()), _live())

    assert resolved.current_price == Decimal("1000.00")
    assert resolved.stock_qty == Decimal("5")
