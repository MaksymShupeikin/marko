"""F9: one hard, durable, atomic provider-call budget for every entrypoint.

The per-position bound used to live in a ``_ProviderCallBudget`` object created
inside ``_ensure_observation_ids``.  That object is per Python call, so it bound
exactly one thing: the automatic walk.  ``POST
/observations/{id}/comparability-reviews`` calls
``request_observation_comparability_review(force=True)`` directly, with no
budget object anywhere on the path, so an operator (or a retry loop, or a
script) could spend an unbounded number of billable calls on a position whose
budget was already spent -- and a fresh in-memory counter per HTTP request could
never have stopped it.

The bound is therefore a durable, atomic reservation keyed by pricing position +
run (``pricing_run_items.id``), taken *before* the call is made, and consulted
again by the provider's own internal retry.  Everything a refused reservation
touches stays exactly as it was: an explicit persisted ``INSUFFICIENT_DATA``
row stamped ``LLM_PROVIDER_CALL_BUDGET_EXHAUSTED``, which ``engine.py`` reads as
``MANUAL_LLM_COMPARABILITY_INSUFFICIENT`` -- never evidence-eligible, never a
missing row that strands the finalizer barrier.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
import os
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from sqlalchemy import select

from marko.core.config import get_settings
from marko.infrastructure.db.models import CandidateComparabilityReview
from marko.infrastructure.db.session import async_session_factory, engine
from marko.services.llm_call_budget import (
    DurableProviderCallLedger,
    PROVIDER_CALL_BUDGET_EXHAUSTED,
    ensure_provider_call_budget_table,
    provider_call_budget_table,
)
from marko.services.llm_comparability import (
    ComparabilityMatchLevel,
    ComparabilityVerdict,
    FindingOutcome,
    LLMComparabilityOutput,
    OpenAIResponsesComparabilityProvider,
    ProviderReview,
    ReviewDimensionFinding,
    ensure_run_item_comparability_reviews,
    request_observation_comparability_review,
)
from marko.services.market_collection import claim_collection_finalization
from test_llm_comparability_postgres import (  # noqa: E402
    _cleanup,
    _seed_wide_cohort,
)


pytestmark = pytest.mark.postgres

_REQUIRES_POSTGRES = pytest.mark.skipif(
    os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") != "1",
    reason="set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database",
)


@pytest.fixture(autouse=True)
async def _ledger_table() -> None:
    """Create the ledger table until its migration lands.

    ``llm_provider_call_budget`` is owned by a migration this agent does not
    write.  ``checkfirst`` makes this a no-op the moment that migration exists,
    so nothing here has to be undone later -- and the production code path still
    never issues DDL of its own.
    """

    if os.environ.get("MARKO_RUN_POSTGRES_INTEGRATION") != "1":
        return
    await ensure_provider_call_budget_table(engine)


class _CountingProvider:
    """Counts every billable call, and never touches the network."""

    def __init__(self) -> None:
        self.calls = 0

    async def review(
        self,
        *,
        input_snapshot: object,
        image_urls: object,
    ) -> ProviderReview:
        del input_snapshot, image_urls
        self.calls += 1
        await asyncio.sleep(0)
        return ProviderReview(
            output=LLMComparabilityOutput(
                verdict=ComparabilityVerdict.COMPARABLE,
                match_level=ComparabilityMatchLevel.ACCEPTABLE_ANALOGUE,
                confidence=Decimal("0.9300"),
                rationale="OE and part type agree in the retained evidence.",
                dimension_findings=[
                    ReviewDimensionFinding(
                        dimension="part_type",
                        outcome=FindingOutcome.MATCH,
                        our_value="brake disc",
                        candidate_value="brake disc",
                        explanation="Both cards identify a front brake disc.",
                    )
                ],
            ),
            response_id=f"response-{self.calls}",
            model="integration-model",
            usage={"input_tokens": 10, "output_tokens": 4},
            latency_ms=1,
        )


def _configure(monkeypatch: pytest.MonkeyPatch, *, budget: int) -> None:
    monkeypatch.setenv("PRICING_LLM_COMPARABILITY_MODE", "required")
    monkeypatch.setenv("PRICING_LLM_API_KEY", "integration-test-key")
    monkeypatch.setenv("PRICING_LLM_MODEL", "integration-model")
    monkeypatch.setenv("PRICING_LLM_MAX_PROVIDER_CALLS_PER_POSITION", str(budget))
    monkeypatch.setenv("PRICING_LLM_MAX_CONCURRENCY", "4")
    get_settings.cache_clear()


@_REQUIRES_POSTGRES
@pytest.mark.asyncio
async def test_repeated_force_cannot_outspend_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F9 repro: configured budget 1, five direct forced calls.

    ``force=True`` is the admin route's payload.  It bypasses the cached row on
    purpose -- that is what makes it a *provider* call every single time -- so
    without a durable bound five clicks cost five calls against a budget of one.
    """

    workspace_id = uuid4()
    user_id = uuid4()
    provider = _CountingProvider()
    budget = 1
    direct_forced_calls = 5

    _configure(monkeypatch, budget=budget)
    try:
        _run_id, run_item_id, observation_ids = await _seed_wide_cohort(
            workspace_id=workspace_id,
            user_id=user_id,
            offers=3,
        )
        for _ in range(direct_forced_calls):
            await request_observation_comparability_review(
                observation_ids[0],
                workspace_id=workspace_id,
                force=True,
                provider=provider,
            )

        assert provider.calls <= budget, (
            f"{direct_forced_calls} forced admin reviews spent {provider.calls} "
            f"provider calls against a configured budget of {budget}"
        )

        async with async_session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(CandidateComparabilityReview)
                        .where(
                            CandidateComparabilityReview.market_observation_id
                            == observation_ids[0]
                        )
                        .order_by(CandidateComparabilityReview.attempt_no)
                    )
                ).all()
            )
            spent = await session.scalar(
                select(provider_call_budget_table.c.spent).where(
                    provider_call_budget_table.c.pricing_run_item_id == run_item_id
                )
            )

        # The bound is on the ledger, not in anybody's memory.
        assert int(spent or 0) == budget
        # Every refused request still ends in a decision, so the finalizer
        # barrier keeps clearing, and each one names the bound that refused it.
        assert len(rows) == direct_forced_calls
        refused = [row for row in rows if row.error_code is not None]
        assert len(refused) == direct_forced_calls - budget
        assert all(row.error_code == PROVIDER_CALL_BUDGET_EXHAUSTED for row in refused)
        # Fail-closed: never eligible evidence, always manual review.
        assert all(row.verdict == "INSUFFICIENT_DATA" for row in refused)
        assert all(row.status == "FAILED" for row in refused)
        assert all(row.cache_hit_review_id is None for row in refused)
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id, user_id)


@_REQUIRES_POSTGRES
@pytest.mark.asyncio
async def test_simultaneous_forced_requests_cannot_outspend_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two HTTP requests are two counters unless the reservation is atomic."""

    workspace_id = uuid4()
    user_id = uuid4()
    provider = _CountingProvider()
    budget = 2

    _configure(monkeypatch, budget=budget)
    try:
        _run_id, _run_item_id, observation_ids = await _seed_wide_cohort(
            workspace_id=workspace_id,
            user_id=user_id,
            offers=8,
        )
        outcomes: list[Any] = await asyncio.gather(
            *(
                request_observation_comparability_review(
                    observation_id,
                    workspace_id=workspace_id,
                    force=True,
                    provider=provider,
                )
                for observation_id in observation_ids
            ),
            return_exceptions=True,
        )

        assert not [item for item in outcomes if isinstance(item, BaseException)]
        assert provider.calls <= budget
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id, user_id)


@_REQUIRES_POSTGRES
@pytest.mark.asyncio
async def test_budget_survives_a_process_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restart must not hand the position a fresh budget.

    Nothing in the process is allowed to be the counter: the settings cache is
    cleared and every in-process object is dropped between the two halves, which
    is what a worker restart looks like from the database's side.
    """

    workspace_id = uuid4()
    user_id = uuid4()
    budget = 2

    _configure(monkeypatch, budget=budget)
    try:
        _run_id, _run_item_id, observation_ids = await _seed_wide_cohort(
            workspace_id=workspace_id,
            user_id=user_id,
            offers=6,
        )
        before = _CountingProvider()
        for observation_id in observation_ids[:budget]:
            await request_observation_comparability_review(
                observation_id,
                workspace_id=workspace_id,
                force=True,
                provider=before,
            )
        assert before.calls == budget

        # "Restart": no shared object survives, only the database.
        get_settings.cache_clear()
        _configure(monkeypatch, budget=budget)

        after = _CountingProvider()
        for observation_id in observation_ids[budget:]:
            await request_observation_comparability_review(
                observation_id,
                workspace_id=workspace_id,
                force=True,
                provider=after,
            )

        assert after.calls == 0, "a restart handed the position a second budget"
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id, user_id)


@_REQUIRES_POSTGRES
@pytest.mark.asyncio
async def test_the_ledger_itself_is_atomic_under_concurrent_transactions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reservation, stripped of everything around it.

    ``spent`` is read and incremented by one statement, so twenty transactions
    contending for a limit of five hand out five slots.  A read-then-write
    ledger would hand out up to twenty: every transaction would see the same
    committed ``spent`` under snapshot isolation.
    """

    workspace_id = uuid4()
    user_id = uuid4()
    limit = 5
    contenders = 20

    _configure(monkeypatch, budget=limit)
    try:
        _run_id, run_item_id, _observation_ids = await _seed_wide_cohort(
            workspace_id=workspace_id,
            user_id=user_id,
            offers=1,
        )
        ledger = DurableProviderCallLedger()

        granted = await asyncio.gather(
            *(
                ledger.reserve(
                    position_id=run_item_id,
                    workspace_id=workspace_id,
                    limit=limit,
                )
                for _ in range(contenders)
            )
        )

        assert sum(1 for item in granted if item) == limit
        assert await ledger.spent(position_id=run_item_id) == limit
        # And it stays refused: the row is the bound, not the burst.
        assert (
            await ledger.reserve(
                position_id=run_item_id,
                workspace_id=workspace_id,
                limit=limit,
            )
            is False
        )
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id, user_id)


@_REQUIRES_POSTGRES
@pytest.mark.asyncio
async def test_a_spent_budget_still_leaves_every_offer_a_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound may stop the calls; it may never stop the rows.

    ``claim_collection_finalization`` refuses to finalize while any observation
    of a classified item lacks a review row.  A budget spent by an operator's
    forced retries before the automatic walk even starts is the case where that
    barrier is easiest to strand -- the walk has nothing left to spend, so every
    offer must still be declined explicitly.
    """

    workspace_id = uuid4()
    user_id = uuid4()
    budget = 2
    offers = 7

    _configure(monkeypatch, budget=budget)
    try:
        run_id, run_item_id, observation_ids = await _seed_wide_cohort(
            workspace_id=workspace_id,
            user_id=user_id,
            offers=offers,
        )
        by_hand = _CountingProvider()
        for _ in range(4):
            await request_observation_comparability_review(
                observation_ids[0],
                workspace_id=workspace_id,
                force=True,
                provider=by_hand,
            )
        assert by_hand.calls == budget

        walk = _CountingProvider()
        await ensure_run_item_comparability_reviews(run_item_id, provider=walk)

        assert walk.calls == 0, "the walk was handed a second budget"

        async with async_session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(CandidateComparabilityReview).where(
                            CandidateComparabilityReview.market_observation_id.in_(
                                observation_ids
                            )
                        )
                    )
                ).all()
            )

        # The barrier's precondition: every observation carries a decision.
        assert _observation_ids_of(rows) == set(observation_ids)
        declined = [row for row in rows if row.status == "SKIPPED"]
        assert len(declined) == offers - 1
        assert all(row.error_code == PROVIDER_CALL_BUDGET_EXHAUSTED for row in declined)
        assert all(row.verdict == "INSUFFICIENT_DATA" for row in declined)

        claimed = await claim_collection_finalization(
            run_id, task_id="durable-budget-barrier-proof"
        )
        assert claimed is True
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id, user_id)


def _observation_ids_of(rows: list[Any]) -> set[UUID]:
    return {row.market_observation_id for row in rows}


async def _ledger_row(run_item_id: UUID) -> tuple[int, int]:
    async with async_session_factory() as session:
        row = (
            await session.execute(
                select(
                    provider_call_budget_table.c.spent,
                    provider_call_budget_table.c.call_limit,
                ).where(provider_call_budget_table.c.pricing_run_item_id == run_item_id)
            )
        ).one()
    return int(row.spent), int(row.call_limit)


@_REQUIRES_POSTGRES
@pytest.mark.asyncio
async def test_an_injected_real_provider_cannot_retry_past_the_durable_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F9 repro, public path, real ledger: budget 1 must buy exactly one POST.

    ``request_observation_comparability_review`` takes a provider, and a caller
    that hands it a real ``OpenAIResponsesComparabilityProvider`` used to hand
    it an adapter with no budget hook inside.  The outer invocation reserved
    once, the adapter retried the 429 for free, and the position was billed
    twice while this row still read ``spent = 1``.

    ``MockTransport`` counts the POSTs; nothing leaves the process.
    """

    workspace_id = uuid4()
    user_id = uuid4()
    posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        del request
        return httpx.Response(429, json={"error": "slow down"})

    _configure(monkeypatch, budget=1)
    try:
        _run_id, run_item_id, observation_ids = await _seed_wide_cohort(
            workspace_id=workspace_id,
            user_id=user_id,
            offers=2,
        )
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            provider = OpenAIResponsesComparabilityProvider(
                get_settings(),
                client=client,
            )
            await request_observation_comparability_review(
                observation_ids[0],
                workspace_id=workspace_id,
                force=True,
                provider=provider,
            )

        assert posts == 1, (
            f"a budget of 1 bought {posts} billable provider requests through "
            "an injected adapter's internal retry"
        )
        spent, call_limit = await _ledger_row(run_item_id)
        assert (spent, call_limit) == (1, 1)

        async with async_session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(CandidateComparabilityReview).where(
                            CandidateComparabilityReview.market_observation_id
                            == observation_ids[0]
                        )
                    )
                ).all()
            )

        # Fail-closed, typed, and on the record.
        assert len(rows) == 1
        assert rows[0].status == "FAILED"
        assert rows[0].error_code == PROVIDER_CALL_BUDGET_EXHAUSTED
        assert rows[0].verdict == "INSUFFICIENT_DATA"
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id, user_id)


@_REQUIRES_POSTGRES
@pytest.mark.asyncio
async def test_an_affordable_retry_is_charged_against_the_durable_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the bound: a paid retry is a spent slot.

    A budget of 2 buys the retry, and the ledger has to show 2 -- otherwise the
    bound is not "N billable requests" but "N review calls", which is what let a
    limit of N cost 2N.
    """

    workspace_id = uuid4()
    user_id = uuid4()
    posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        del request
        return httpx.Response(503, json={"error": "unavailable"})

    _configure(monkeypatch, budget=2)
    try:
        _run_id, run_item_id, observation_ids = await _seed_wide_cohort(
            workspace_id=workspace_id,
            user_id=user_id,
            offers=2,
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAIResponsesComparabilityProvider(
                get_settings(),
                client=client,
            )
            await request_observation_comparability_review(
                observation_ids[0],
                workspace_id=workspace_id,
                force=True,
                provider=provider,
            )

        assert posts == 2
        assert await _ledger_row(run_item_id) == (2, 2)
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id, user_id)


@_REQUIRES_POSTGRES
@pytest.mark.asyncio
async def test_a_restart_with_a_raised_setting_cannot_widen_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F9: ``call_limit`` is the allowance the position started with.

    The reservation used to write the caller's current limit into the row on
    every conflict.  Raising ``PRICING_LLM_MAX_PROVIDER_CALLS_PER_POSITION``
    and restarting therefore handed every already-bounded position the
    difference: the row still looked authoritative, and the bill went up with
    no record of a decision to raise it.
    """

    workspace_id = uuid4()
    user_id = uuid4()

    _configure(monkeypatch, budget=1)
    try:
        _run_id, run_item_id, observation_ids = await _seed_wide_cohort(
            workspace_id=workspace_id,
            user_id=user_id,
            offers=6,
        )
        before = _CountingProvider()
        await request_observation_comparability_review(
            observation_ids[0],
            workspace_id=workspace_id,
            force=True,
            provider=before,
        )
        assert before.calls == 1
        assert await _ledger_row(run_item_id) == (1, 1)

        # "Restart", with a bigger number in the environment.
        _configure(monkeypatch, budget=10)

        after = _CountingProvider()
        for observation_id in observation_ids[1:]:
            await request_observation_comparability_review(
                observation_id,
                workspace_id=workspace_id,
                force=True,
                provider=after,
            )

        assert after.calls == 0, "a raised setting reopened a spent position"
        assert await _ledger_row(run_item_id) == (1, 1)

        # And the automatic walk agrees, so the tail is declined with the
        # labelled row rather than discovered as provider failures.
        walk = _CountingProvider()
        await ensure_run_item_comparability_reviews(run_item_id, provider=walk)
        assert walk.calls == 0
        assert await _ledger_row(run_item_id) == (1, 1)
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id, user_id)


@_REQUIRES_POSTGRES
@pytest.mark.asyncio
async def test_a_lowered_setting_applies_to_a_started_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-increasing, not frozen: a deliberate cost cut must bite at once."""

    workspace_id = uuid4()
    user_id = uuid4()

    _configure(monkeypatch, budget=5)
    try:
        _run_id, run_item_id, observation_ids = await _seed_wide_cohort(
            workspace_id=workspace_id,
            user_id=user_id,
            offers=6,
        )
        before = _CountingProvider()
        for observation_id in observation_ids[:2]:
            await request_observation_comparability_review(
                observation_id,
                workspace_id=workspace_id,
                force=True,
                provider=before,
            )
        assert before.calls == 2

        _configure(monkeypatch, budget=2)

        after = _CountingProvider()
        await request_observation_comparability_review(
            observation_ids[2],
            workspace_id=workspace_id,
            force=True,
            provider=after,
        )

        assert after.calls == 0
        spent, call_limit = await _ledger_row(run_item_id)
        assert spent == 2
        assert call_limit == 5, "the stored allowance is only lowered by a grant"
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id, user_id)


@_REQUIRES_POSTGRES
@pytest.mark.asyncio
async def test_two_concurrent_workers_share_one_positions_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two walks over the same position are two processes, one ledger row.

    Retries and restarts aside, the shape that actually happens in production is
    two workers claiming work for the same run item at once.  Nothing in either
    process is the counter, so the sum of what they spend is the position's
    budget -- not twice it.
    """

    workspace_id = uuid4()
    user_id = uuid4()
    budget = 3

    _configure(monkeypatch, budget=budget)
    try:
        _run_id, run_item_id, observation_ids = await _seed_wide_cohort(
            workspace_id=workspace_id,
            user_id=user_id,
            offers=9,
        )
        first = _CountingProvider()
        second = _CountingProvider()

        outcomes: list[Any] = await asyncio.gather(
            ensure_run_item_comparability_reviews(run_item_id, provider=first),
            ensure_run_item_comparability_reviews(run_item_id, provider=second),
            return_exceptions=True,
        )
        assert not [item for item in outcomes if isinstance(item, BaseException)]

        assert first.calls + second.calls <= budget
        spent, call_limit = await _ledger_row(run_item_id)
        assert spent <= budget
        assert call_limit == budget

        async with async_session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(CandidateComparabilityReview).where(
                            CandidateComparabilityReview.market_observation_id.in_(
                                observation_ids
                            )
                        )
                    )
                ).all()
            )

        # Whichever worker lost the race, every observation still has a row, so
        # the finalizer barrier still clears.
        assert _observation_ids_of(rows) == set(observation_ids)
    finally:
        get_settings.cache_clear()
        await _cleanup(workspace_id, user_id)
