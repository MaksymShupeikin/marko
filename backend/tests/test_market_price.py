from decimal import Decimal
from types import SimpleNamespace

import pytest

from marko.services.market_price import effective_observation_price


def test_sale_price_wins_over_crossed_out_reference_and_legacy_price() -> None:
    observation = SimpleNamespace(
        price=Decimal("412"),
        sale_price=Decimal("330"),
        reference_price=Decimal("412"),
    )

    assert effective_observation_price(observation) == Decimal("330")


def test_legacy_observation_falls_back_to_price() -> None:
    observation = SimpleNamespace(price=Decimal("412"), sale_price=None)

    assert effective_observation_price(observation) == Decimal("412")


def test_invalid_sale_price_does_not_hide_valid_active_price() -> None:
    observation = SimpleNamespace(price=Decimal("412"), sale_price=Decimal("0"))

    assert effective_observation_price(observation) == Decimal("412")


def test_missing_active_price_fails_closed() -> None:
    with pytest.raises(ValueError, match="valid active price"):
        effective_observation_price(SimpleNamespace(price=None, sale_price=None))
