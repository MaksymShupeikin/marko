"""A run has to be able to say what its no-OE lane cost.

The discovery lane calls the paid provider once per candidate offer through its
own code path. Until 2026-08-18 it stored the verdict and nothing else: no
tokens, no cost, no rate card. A run therefore reported the OE lane's spend as
the whole bill — the panel read $0.157 while discovery was still calling out
every two minutes — and the customer's cost expectation was built on the
smaller lane.
"""

from collections import Counter
from decimal import Decimal
from types import SimpleNamespace

from marko.infrastructure.db.models import PricingDiscoveryReview
from marko.services.comparability_reporting import accumulate_provider_spend


def _booked(total_usd: str, *, tokens: int, rate: str = "card-v1") -> SimpleNamespace:
    return SimpleNamespace(
        usage={"total_tokens": tokens, "output_tokens": tokens // 2},
        estimated_cost={"total_usd": total_usd},
        rate_card_version=rate,
    )


def test_the_discovery_review_row_can_carry_what_the_call_cost() -> None:
    columns = set(PricingDiscoveryReview.__table__.columns.keys())

    assert {"usage", "estimated_cost", "rate_card_version"} <= columns


def test_both_lanes_add_into_one_bill() -> None:
    tokens: Counter[str] = Counter()
    rates: set[str] = set()

    oe = accumulate_provider_spend(
        [_booked("0.10", tokens=1000)], token_totals=tokens, rate_versions=rates
    )
    discovery = accumulate_provider_spend(
        [_booked("0.25", tokens=400), _booked("0.05", tokens=200, rate="card-v2")],
        token_totals=tokens,
        rate_versions=rates,
    )

    assert oe + discovery == Decimal("0.40")
    assert tokens["total_tokens"] == 1600
    assert rates == {"card-v1", "card-v2"}


def test_a_row_that_booked_nothing_costs_nothing() -> None:
    """An unbooked call must read as zero, never crash the report."""

    tokens: Counter[str] = Counter()
    rates: set[str] = set()

    total = accumulate_provider_spend(
        [SimpleNamespace(usage=None, estimated_cost=None, rate_card_version=None)],
        token_totals=tokens,
        rate_versions=rates,
    )

    assert total == Decimal("0")
    assert tokens == Counter()
    assert rates == set()
