"""HIGH 7: ``required`` mode must carry a hard provider-call bound.

``shadow`` mode stops once ``pricing_llm_max_confirmed_reviews`` offers are
confirmed, but ``required`` mode raises that ceiling to the cohort size on
purpose: ``engine.py`` reads a missing review as
``MANUAL_LLM_COMPARABILITY_MISSING`` and drops the offer from the evidence
behind the price.  The consequence was that ``required`` mode had no bound on
provider calls at all -- acquisition is page-capped, not seller-capped, so a
prom.ua part-code page keeps a median 81 offers past the gates and every one of
them cost a call.  ~46k calls per catalogue today; ~376k if the collector cap
is raised.

``pricing_llm_max_provider_calls_per_position`` is that bound.  What it must not
become is a silent downgrade of ``required`` to ``shadow``, so these tests hold
three properties together:

* the bound is hard and exact -- no overshoot by a concurrency wave;
* every declined offer still carries a decision, so the finalizer barrier in
  ``claim_collection_finalization`` still clears and the run reaches a terminal
  state instead of hanging;
* a declined offer is fail-closed and visibly labelled -- manual review, never
  silent eligibility, and never confusable with an offer that simply lost to
  cheaper confirmed ones.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
import uuid
from uuid import uuid4

import httpx
import pytest

from marko.core.config import Settings
from marko.services import llm_comparability
from marko.services.llm_call_budget import (
    InMemoryProviderCallLedger,
    PositionCallBudget,
)
from marko.services.llm_comparability import (
    PROVIDER_CALL_BUDGET_EXHAUSTED,
    ComparabilityMatchLevel,
    ComparabilityProviderError,
    ComparabilityVerdict,
    EffectiveComparabilityReview,
    FindingOutcome,
    LLMComparabilityOutput,
    ProviderReview,
    ReviewDimensionFinding,
    _PreparedReview,
    _ProviderCallBudget,
)
from metis.pricing import (
    CompetitorOffer,
    ProductPricingContext,
    ProductTier,
    RecommendationAction,
    recommend_price,
    verified_comparison_evidence,
)


# The measured median of a prom.ua part-code page after the gates.
MEASURED_COHORT = 81


def _confirmed_review(observation_id: uuid.UUID) -> EffectiveComparabilityReview:
    return EffectiveComparabilityReview(
        review_id=uuid4(),
        market_observation_id=observation_id,
        input_hash="0" * 64,
        verdict=ComparabilityVerdict.COMPARABLE,
        match_level=ComparabilityMatchLevel.ACCEPTABLE_ANALOGUE,
        confidence=Decimal("0.9"),
        rationale="Same part type and OE reference.",
        dimension_findings=(),
        hard_stop_conflicts=(),
        decision_source="LLM",
        status="COMPLETED",
        provider="openai_responses",
        model_id="gpt-test",
        prompt_version="v1",
        reviewed_at=datetime(2026, 8, 1, tzinfo=UTC),
        cache_hit_review_id=None,
    )


def _patch_review_calls(
    monkeypatch: pytest.MonkeyPatch,
    *,
    confirm: bool = True,
) -> tuple[list[uuid.UUID], list[tuple[uuid.UUID, object]]]:
    """Stub both outcomes of the walk: a judgement and a declined offer.

    Both must be stubbed.  The decline path reaches PostgreSQL, so a test that
    stubs only the judgement fails on a live connection rather than on its own
    assertion.  The decline stub records *why* each offer was declined, which is
    the property that separates a bounded cost from a truncated evidence base.
    """

    judged: list[uuid.UUID] = []
    declined: list[tuple[uuid.UUID, object]] = []

    async def fake_review(
        observation_id: uuid.UUID,
        **_: object,
    ) -> EffectiveComparabilityReview:
        judged.append(observation_id)
        review = _confirmed_review(observation_id)
        if confirm:
            return review
        return replace(
            review,
            verdict=ComparabilityVerdict.NOT_COMPARABLE,
            match_level=ComparabilityMatchLevel.NOT_APPLICABLE,
        )

    async def fake_skip(
        observation_id: uuid.UUID,
        *,
        reason: object = "CONFIRMED_CEILING",
        **_: object,
    ) -> EffectiveComparabilityReview:
        declined.append((observation_id, reason))
        return replace(
            _confirmed_review(observation_id),
            verdict=ComparabilityVerdict.INSUFFICIENT_DATA,
            match_level=ComparabilityMatchLevel.NOT_APPLICABLE,
            status="SKIPPED",
        )

    monkeypatch.setattr(
        llm_comparability,
        "request_observation_comparability_review",
        fake_review,
    )
    monkeypatch.setattr(
        llm_comparability,
        "skip_observation_comparability_review",
        fake_skip,
    )
    return judged, declined


def _required_settings(**overrides: Any) -> Settings:
    return Settings(
        pricing_llm_comparability_mode="required",
        pricing_llm_api_key="sk-test",
        pricing_llm_model="gpt-test",
        **overrides,
    )


# --------------------------------------------------------------------------
# The bound itself
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_required_mode_bounds_provider_calls_for_a_measured_cohort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One catalogue position must not be able to spend 81 provider calls."""

    observation_ids = [uuid4() for _ in range(MEASURED_COHORT)]
    judged, declined = _patch_review_calls(monkeypatch)
    settings = _required_settings()

    await llm_comparability._ensure_observation_ids(
        observation_ids,
        settings=settings,
        provider=None,
    )

    bound = settings.pricing_llm_max_provider_calls_per_position
    assert len(judged) == bound
    assert len(declined) == MEASURED_COHORT - bound
    # Cheapest first: the calls are spent on the offers a decision is taken
    # against, not on an arbitrary slice of the cohort.
    assert judged == observation_ids[:bound]


@pytest.mark.asyncio
async def test_budget_does_not_overshoot_by_a_concurrency_wave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound is hard, not "hard give or take a wave".

    The confirmation ceiling is checked between waves and may overshoot by one,
    which is acceptable for a heuristic stop.  A cost bound may not: the wave is
    trimmed to what is left of the budget before it is dispatched.  A budget of
    7 against a concurrency of 4 costs 8 calls if it is not.
    """

    observation_ids = [uuid4() for _ in range(30)]
    judged, _declined = _patch_review_calls(monkeypatch)

    await llm_comparability._ensure_observation_ids(
        observation_ids,
        settings=_required_settings(
            pricing_llm_max_provider_calls_per_position=7,
            pricing_llm_max_concurrency=4,
        ),
        provider=None,
    )

    assert len(judged) == 7


@pytest.mark.parametrize("budget", (1, 2, 9, 10, 11))
@pytest.mark.asyncio
async def test_budget_is_exact_at_every_boundary(
    monkeypatch: pytest.MonkeyPatch,
    budget: int,
) -> None:
    """A cohort wider than the budget spends the budget exactly -- never more."""

    observation_ids = [uuid4() for _ in range(40)]
    judged, declined = _patch_review_calls(monkeypatch)

    await llm_comparability._ensure_observation_ids(
        observation_ids,
        settings=_required_settings(
            pricing_llm_max_provider_calls_per_position=budget,
            pricing_llm_max_concurrency=3,
        ),
        provider=None,
    )

    assert len(judged) == budget
    assert len(declined) == len(observation_ids) - budget


@pytest.mark.asyncio
async def test_a_cohort_that_fits_the_budget_is_judged_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Off-by-one guard: the budget is what may be spent, not what must be left.

    A cohort exactly as wide as the budget is the case where an inclusive/
    exclusive slip silently drops the dearest offer from the evidence base.
    """

    observation_ids = [uuid4() for _ in range(10)]
    judged, declined = _patch_review_calls(monkeypatch)

    await llm_comparability._ensure_observation_ids(
        observation_ids,
        settings=_required_settings(
            pricing_llm_max_provider_calls_per_position=10,
        ),
        provider=None,
    )

    assert judged == observation_ids
    assert declined == [], "nothing was declined, so nothing needs a decline row"


@pytest.mark.asyncio
async def test_budget_bounds_a_cohort_that_confirms_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The residual worst case the confirmation ceiling never bounded.

    The ceiling counts confirmations, so a cohort the reviewer rejects reaches
    it never and used to be judged in full in every mode.  The budget counts
    calls, so it bounds this case too.
    """

    observation_ids = [uuid4() for _ in range(30)]
    judged, declined = _patch_review_calls(monkeypatch, confirm=False)

    await llm_comparability._ensure_observation_ids(
        observation_ids,
        settings=Settings(
            pricing_llm_comparability_mode="off",
            pricing_llm_max_provider_calls_per_position=6,
        ),
        provider=None,
    )

    assert len(judged) == 6
    assert len(declined) == 24


# --------------------------------------------------------------------------
# Terminal progression: the decision rows stay complete
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_offer_past_the_budget_still_carries_a_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The finalizer barrier counts review rows, not judgements.

    ``claim_collection_finalization`` refuses to finalize while any observation
    of a classified item lacks a review row, and
    ``finalize_pricing_collection_task`` returns 0 without retrying when that
    barrier is unmet -- the run would hang short of a terminal state forever.
    So the budget may stop the calls, never the rows.
    """

    observation_ids = [uuid4() for _ in range(MEASURED_COHORT)]
    judged, declined = _patch_review_calls(monkeypatch)

    await llm_comparability._ensure_observation_ids(
        observation_ids,
        settings=_required_settings(
            pricing_llm_max_provider_calls_per_position=4,
        ),
        provider=None,
    )

    declined_ids = [observation_id for observation_id, _reason in declined]
    # The barrier's invariant: every observation carries a decision, exactly one.
    assert sorted(judged + declined_ids, key=str) == sorted(observation_ids, key=str)
    assert judged == observation_ids[:4]
    assert declined_ids == observation_ids[4:]


@pytest.mark.asyncio
async def test_budget_declines_are_labelled_as_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exceeding the bound is an explicit outcome, not an anonymous skip."""

    observation_ids = [uuid4() for _ in range(20)]
    _judged, declined = _patch_review_calls(monkeypatch)

    await llm_comparability._ensure_observation_ids(
        observation_ids,
        settings=_required_settings(
            pricing_llm_max_provider_calls_per_position=5,
        ),
        provider=None,
    )

    assert declined, "a 20-offer cohort must exceed a budget of 5"
    assert {reason for _observation_id, reason in declined} == {"PROVIDER_CALL_BUDGET"}


@pytest.mark.asyncio
async def test_ceiling_declines_are_not_labelled_as_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two stops must stay distinguishable.

    An offer that lost to cheaper confirmed offers is a complete decision; an
    offer nobody asked about is a hole in the evidence base.  Reporting the
    second as the first hides exactly what this bound was added to expose.
    """

    observation_ids = [uuid4() for _ in range(30)]
    judged, declined = _patch_review_calls(monkeypatch)

    await llm_comparability._ensure_observation_ids(
        observation_ids,
        settings=Settings(
            pricing_llm_comparability_mode="shadow",
            pricing_llm_api_key="sk-test",
            pricing_llm_model="gpt-test",
            pricing_llm_max_confirmed_reviews=6,
            pricing_llm_max_concurrency=3,
            # Wide enough that the confirmation ceiling is what stops the walk.
            pricing_llm_max_provider_calls_per_position=100,
        ),
        provider=None,
    )

    assert len(judged) == 6
    assert declined, "a 30-offer cohort must exceed a ceiling of 6"
    assert {reason for _observation_id, reason in declined} == {"CONFIRMED_CEILING"}


# --------------------------------------------------------------------------
# Fail-closed, and not a silent downgrade to shadow
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_decline_is_persisted_fail_closed_and_stamped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The row written for a budget decline is what an operator has to see."""

    observation_id = uuid4()
    prepared = _PreparedReview(
        workspace_id=uuid4(),
        observation_id=observation_id,
        catalog_item_id=uuid4(),
        request_key="k" * 64,
        input_hash="1" * 64,
        attempt_no=1,
        input_snapshot={"our_product": {}},
        image_urls=(),
        hard_stop_conflicts=(),
    )
    captured: dict[str, Any] = {}

    async def fake_prepare(*_args: object, **_kwargs: object) -> _PreparedReview:
        return prepared

    async def fake_persist(
        _prepared: _PreparedReview,
        **kwargs: Any,
    ) -> EffectiveComparabilityReview:
        captured.update(kwargs)
        return _confirmed_review(observation_id)

    monkeypatch.setattr(llm_comparability, "_prepare_review", fake_prepare)
    monkeypatch.setattr(llm_comparability, "_persist_prepared_review", fake_persist)

    await llm_comparability.skip_observation_comparability_review(
        observation_id,
        settings=_required_settings(
            pricing_llm_max_provider_calls_per_position=5,
        ),
        reason="PROVIDER_CALL_BUDGET",
    )

    output = captured["output"]
    # Fail-closed: never eligible evidence.
    assert output.verdict is ComparabilityVerdict.INSUFFICIENT_DATA
    assert output.match_level is ComparabilityMatchLevel.NOT_APPLICABLE
    # A local deterministic decision, not a provider answer, and on the record.
    assert captured["decision_source"] == "HARD_RULE"
    assert captured["status"] == "SKIPPED"
    # Visible: machine-readable, and it names the bound that bit.
    assert captured["error_code"] == PROVIDER_CALL_BUDGET_EXHAUSTED
    assert "5" in output.rationale


@pytest.mark.asyncio
async def test_ceiling_decline_is_not_stamped_with_the_budget_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stamp must mean something -- so it may not be on every skip row."""

    observation_id = uuid4()
    prepared = _PreparedReview(
        workspace_id=uuid4(),
        observation_id=observation_id,
        catalog_item_id=uuid4(),
        request_key="k" * 64,
        input_hash="1" * 64,
        attempt_no=1,
        input_snapshot={"our_product": {}},
        image_urls=(),
        hard_stop_conflicts=(),
    )
    captured: dict[str, Any] = {}

    async def fake_prepare(*_args: object, **_kwargs: object) -> _PreparedReview:
        return prepared

    async def fake_persist(
        _prepared: _PreparedReview,
        **kwargs: Any,
    ) -> EffectiveComparabilityReview:
        captured.update(kwargs)
        return _confirmed_review(observation_id)

    monkeypatch.setattr(llm_comparability, "_prepare_review", fake_prepare)
    monkeypatch.setattr(llm_comparability, "_persist_prepared_review", fake_persist)

    await llm_comparability.skip_observation_comparability_review(
        observation_id,
        settings=_required_settings(),
    )

    assert captured["error_code"] is None
    assert captured["output"].verdict is ComparabilityVerdict.INSUFFICIENT_DATA


def test_a_budget_declined_offer_goes_to_manual_review_not_into_the_price() -> None:
    """The bound must not silently downgrade ``required`` to ``shadow``.

    A budget decline reaches ``engine.py`` as an ``INSUFFICIENT_DATA`` review,
    which is ``MANUAL_LLM_COMPARABILITY_INSUFFICIENT`` -- excluded from the
    evidence and routed to a human.  In ``shadow`` the same offer would price
    unreviewed, so this is strictly the stricter outcome, and it is not the
    ``MANUAL_LLM_COMPARABILITY_MISSING`` of an offer with no row at all.
    """

    offer = CompetitorOffer(
        observation_id="obs-budget",
        seller_id="seller-budget",
        seller_name="Seller",
        price=Decimal("1000"),
        currency="UAH",
        currency_raw="UAH",
        is_available=True,
        age_hours=Decimal("1"),
        match_confidence=Decimal("0.99"),
        tier=ProductTier.BUDGET,
        tier_confidence=Decimal("0.99"),
        source_confidence=Decimal("1"),
        comparison_evidence=verified_comparison_evidence(
            stable_seller_id="seller-budget",
            source_record_id="obs-budget",
        ),
        semantic_review_required=True,
        # The shape of the row a budget decline writes.
        semantic_review_id="review-budget",
        semantic_review_verdict="INSUFFICIENT_DATA",
        semantic_review_match_level="NOT_APPLICABLE",
        semantic_review_confidence=Decimal("0"),
    )

    result = recommend_price(
        ProductPricingContext(
            sku="SKU-LLM",
            category="brakes",
            current_price=Decimal("800"),
        ),
        [offer],
        {},
    )

    assert result.action is RecommendationAction.INSUFFICIENT_DATA
    assert result.recommended_price is None
    assert result.excluded[0].reason == "MANUAL_LLM_COMPARABILITY_INSUFFICIENT"
    assert not [item for item in result.evidence if item.observation_id == "obs-budget"]


# --------------------------------------------------------------------------
# The guard at the call site
# --------------------------------------------------------------------------


class _StubProvider:
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
        # Yield so concurrent callers interleave inside the provider.
        await asyncio.sleep(0)
        return ProviderReview(
            output=LLMComparabilityOutput(
                verdict=ComparabilityVerdict.COMPARABLE,
                match_level=ComparabilityMatchLevel.ACCEPTABLE_ANALOGUE,
                confidence=Decimal("0.9"),
                rationale="Same part type and OE reference in both cards.",
                dimension_findings=[
                    ReviewDimensionFinding(
                        dimension="part_type",
                        outcome=FindingOutcome.MATCH,
                        explanation="Both cards identify a front brake disc.",
                    )
                ],
            ),
            response_id=f"response-{self.calls}",
            model="gpt-test",
            usage={},
            latency_ms=1,
        )


def _budget(
    limit: int,
    *,
    ledger: InMemoryProviderCallLedger | None = None,
    position_id: uuid.UUID | None = None,
) -> PositionCallBudget:
    return PositionCallBudget(
        ledger=ledger or InMemoryProviderCallLedger(),
        position_id=position_id or uuid4(),
        workspace_id=uuid4(),
        limit=limit,
    )


@pytest.mark.asyncio
async def test_guard_refuses_the_call_past_the_budget() -> None:
    inner = _StubProvider()
    budget = _ProviderCallBudget(inner, budget=_budget(2))

    for _ in range(2):
        await budget.review(input_snapshot={}, image_urls=())

    with pytest.raises(ComparabilityProviderError) as excinfo:
        await budget.review(input_snapshot={}, image_urls=())

    assert excinfo.value.code == PROVIDER_CALL_BUDGET_EXHAUSTED
    assert inner.calls == 2, "the refused call must never reach the provider"
    assert await budget.exhausted() is True


@pytest.mark.asyncio
async def test_guard_holds_under_concurrency() -> None:
    """Counting on return instead of on entry lets a whole wave through."""

    inner = _StubProvider()
    budget = _ProviderCallBudget(inner, budget=_budget(3))

    outcomes = await asyncio.gather(
        *(budget.review(input_snapshot={}, image_urls=()) for _ in range(12)),
        return_exceptions=True,
    )

    refused = [
        item for item in outcomes if isinstance(item, ComparabilityProviderError)
    ]
    assert inner.calls == 3
    assert len(refused) == 9
    assert {item.code for item in refused} == {PROVIDER_CALL_BUDGET_EXHAUSTED}


@pytest.mark.asyncio
async def test_a_call_without_a_position_to_charge_is_refused() -> None:
    """An unattributable call is not a free call.

    Nothing that reaches the provider is allowed to be outside the ledger, so a
    review whose pricing position could not be established is refused rather
    than waved through as "no budget applies here".
    """

    inner = _StubProvider()
    budget = _ProviderCallBudget(
        inner,
        budget=PositionCallBudget(
            ledger=InMemoryProviderCallLedger(),
            position_id=None,
            workspace_id=None,
            limit=10,
        ),
    )

    with pytest.raises(ComparabilityProviderError) as excinfo:
        await budget.review(input_snapshot={}, image_urls=())

    assert excinfo.value.code == PROVIDER_CALL_BUDGET_EXHAUSTED
    assert inner.calls == 0


@pytest.mark.asyncio
async def test_walk_and_guard_agree_on_one_shared_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wave accounting and the reservation must agree.

    The guard fires during a normal walk only if the accounting is wrong, and
    then offers are refused at the call site and persisted as FAILED rather than
    declined cleanly -- still fail-closed, but the wrong shape of evidence.  The
    two layers exist so one covers a bug in the other, not so the second does
    the work.

    This drives the real ``request_observation_comparability_review``, because
    after F9 that is where the reservation is taken; stubbing it out would prove
    only that the walk still counts to nine.
    """

    observation_ids = [uuid4() for _ in range(40)]
    position_id = uuid4()
    inner = _StubProvider()
    ledger = InMemoryProviderCallLedger()
    persisted: list[dict[str, Any]] = []

    async def fake_prepare(
        observation_id: uuid.UUID,
        **_: object,
    ) -> _PreparedReview:
        return _PreparedReview(
            workspace_id=uuid4(),
            observation_id=observation_id,
            catalog_item_id=uuid4(),
            request_key=uuid4().hex * 2,
            input_hash="1" * 64,
            attempt_no=1,
            input_snapshot={"our_product": {}},
            image_urls=(),
            hard_stop_conflicts=(),
            pricing_run_item_id=position_id,
        )

    async def fake_persist(
        prepared: _PreparedReview,
        **kwargs: Any,
    ) -> EffectiveComparabilityReview:
        persisted.append(kwargs)
        return _confirmed_review(prepared.observation_id)

    monkeypatch.setattr(llm_comparability, "_prepare_review", fake_prepare)
    monkeypatch.setattr(llm_comparability, "_persist_prepared_review", fake_persist)
    monkeypatch.setattr(
        llm_comparability,
        "skip_observation_comparability_review",
        _record_skips(),
    )

    await llm_comparability._ensure_observation_ids(
        observation_ids,
        settings=_required_settings(
            pricing_llm_max_provider_calls_per_position=9,
            pricing_llm_max_concurrency=4,
        ),
        provider=inner,
        position_id=position_id,
        ledger=ledger,
    )

    assert inner.calls == 9
    assert await ledger.spent(position_id=position_id) == 9
    # The walk stayed inside the budget, so nothing was refused at the call site.
    assert [item for item in persisted if item["status"] != "COMPLETED"] == []


def _record_skips() -> Any:
    async def fake_skip(*_args: object, **_kwargs: object) -> None:
        return None

    return fake_skip


@pytest.mark.asyncio
async def test_each_position_gets_its_own_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound is per position, so one wide cohort cannot starve another."""

    groups = {uuid4(): [uuid4() for _ in range(9)] for _ in range(3)}
    judged, declined = _patch_review_calls(monkeypatch)

    await llm_comparability._ensure_observation_groups(
        groups,
        settings=_required_settings(
            pricing_llm_max_provider_calls_per_position=4,
        ),
        provider=None,
        ledger=InMemoryProviderCallLedger(),
    )

    assert len(judged) == 3 * 4
    assert len(declined) == 3 * 5
    for group in groups.values():
        assert [item for item in judged if item in set(group)] == group[:4]


# --------------------------------------------------------------------------
# F9: the same budget binds force / admin / manual retry
# --------------------------------------------------------------------------


def _stub_position(
    monkeypatch: pytest.MonkeyPatch,
    *,
    position_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Run the real review path against one position, without a database."""

    persisted: list[dict[str, Any]] = []

    async def fake_prepare(
        observation_id: uuid.UUID,
        **_: object,
    ) -> _PreparedReview:
        return _PreparedReview(
            workspace_id=uuid4(),
            observation_id=observation_id,
            catalog_item_id=uuid4(),
            request_key=uuid4().hex * 2,
            input_hash="1" * 64,
            attempt_no=1,
            input_snapshot={"our_product": {}},
            image_urls=(),
            hard_stop_conflicts=(),
            pricing_run_item_id=position_id,
        )

    async def fake_persist(
        prepared: _PreparedReview,
        **kwargs: Any,
    ) -> EffectiveComparabilityReview:
        persisted.append(kwargs)
        return _confirmed_review(prepared.observation_id)

    async def fake_persist_failed(
        prepared: _PreparedReview,
        **kwargs: Any,
    ) -> EffectiveComparabilityReview:
        persisted.append({"status": "FAILED", **kwargs})
        return replace(
            _confirmed_review(prepared.observation_id),
            verdict=ComparabilityVerdict.INSUFFICIENT_DATA,
            match_level=ComparabilityMatchLevel.SUSPICIOUS,
            status="FAILED",
        )

    monkeypatch.setattr(llm_comparability, "_prepare_review", fake_prepare)
    monkeypatch.setattr(llm_comparability, "_persist_prepared_review", fake_persist)
    monkeypatch.setattr(
        llm_comparability, "_persist_failed_review", fake_persist_failed
    )
    return persisted


@pytest.mark.asyncio
async def test_repeated_force_shares_the_position_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F9: the admin route's ``force=true`` is not a way around the bound.

    ``force`` skips the cached row deliberately, so each request is a fresh
    billable call.  Before the fix there was no budget object anywhere on that
    path -- five requests against a budget of one cost five calls.  The budget
    now lives in ``request_observation_comparability_review`` itself, so the
    sixth request pays nothing no matter who asks.
    """

    position_id = uuid4()
    observation_id = uuid4()
    inner = _StubProvider()
    ledger = InMemoryProviderCallLedger()
    persisted = _stub_position(monkeypatch, position_id=position_id)

    for _ in range(5):
        await llm_comparability.request_observation_comparability_review(
            observation_id,
            force=True,
            settings=_required_settings(
                pricing_llm_max_provider_calls_per_position=1,
            ),
            provider=inner,
            ledger=ledger,
        )

    assert inner.calls == 1
    assert await ledger.spent(position_id=position_id) == 1
    # Every refused request still ends with a decision on the record, and the
    # record says which bound refused it.
    refused = [item for item in persisted if item["status"] == "FAILED"]
    assert len(refused) == 4
    assert {item["error_code"] for item in refused} == {PROVIDER_CALL_BUDGET_EXHAUSTED}


@pytest.mark.asyncio
async def test_simultaneous_forced_requests_share_the_position_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two requests are two counters unless the reservation is atomic."""

    position_id = uuid4()
    inner = _StubProvider()
    ledger = InMemoryProviderCallLedger()
    _stub_position(monkeypatch, position_id=position_id)

    await asyncio.gather(
        *(
            llm_comparability.request_observation_comparability_review(
                uuid4(),
                force=True,
                settings=_required_settings(
                    pricing_llm_max_provider_calls_per_position=3,
                ),
                provider=inner,
                ledger=ledger,
            )
            for _ in range(20)
        )
    )

    assert inner.calls == 3


@pytest.mark.asyncio
async def test_the_walk_cannot_respend_what_force_already_spent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One budget per position, not one per entrypoint.

    An operator who spent the position's budget by hand leaves the automatic
    walk nothing to spend, and the walk declines the whole cohort with the
    labelled ``SKIPPED`` row rather than discovering the bound at the call site.
    """

    position_id = uuid4()
    inner = _StubProvider()
    ledger = InMemoryProviderCallLedger()
    _stub_position(monkeypatch, position_id=position_id)
    settings = _required_settings(pricing_llm_max_provider_calls_per_position=2)

    for _ in range(2):
        await llm_comparability.request_observation_comparability_review(
            uuid4(),
            force=True,
            settings=settings,
            provider=inner,
            ledger=ledger,
        )
    assert inner.calls == 2

    declined: list[tuple[uuid.UUID, object]] = []

    async def fake_skip(
        observation_id: uuid.UUID,
        *,
        reason: object = "CONFIRMED_CEILING",
        **_: object,
    ) -> None:
        declined.append((observation_id, reason))

    monkeypatch.setattr(
        llm_comparability,
        "skip_observation_comparability_review",
        fake_skip,
    )

    cohort = [uuid4() for _ in range(6)]
    await llm_comparability._ensure_observation_ids(
        cohort,
        settings=settings,
        provider=inner,
        position_id=position_id,
        ledger=ledger,
    )

    assert inner.calls == 2, "the walk found the position's budget already spent"
    assert [observation_id for observation_id, _reason in declined] == cohort
    assert {reason for _observation_id, reason in declined} == {"PROVIDER_CALL_BUDGET"}


@pytest.mark.asyncio
async def test_an_internal_provider_retry_pays_for_itself() -> None:
    """A budget of N must not buy 2N billable requests.

    The adapter retries once on a timeout or a 429/5xx.  The provider bills for
    a request it processed even when the answer never reached us, so a bound
    that charged one slot per ``review()`` would be off by exactly the retry
    rate.  Both attempts ask the same ledger for their own slot, and the caller
    supplies no hook of its own -- the gate binds one.
    """

    posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        del request
        return httpx.Response(429, json={"error": "slow down"})

    settings = _required_settings(pricing_llm_max_provider_calls_per_position=1)
    ledger = InMemoryProviderCallLedger()
    position_id = uuid4()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        budget = _budget(2, ledger=ledger, position_id=position_id)
        provider = llm_comparability.OpenAIResponsesComparabilityProvider(
            settings,
            client=client,
        )
        with pytest.raises(ComparabilityProviderError) as excinfo:
            await _ProviderCallBudget(provider, budget=budget).review(
                input_snapshot={"our_product": {}},
                image_urls=(),
            )

    # Two slots, two requests: the retry was paid for, not smuggled.
    assert posts == 2
    assert await ledger.spent(position_id=position_id) == 2
    assert excinfo.value.code == "LLM_HTTP_ERROR"


@pytest.mark.asyncio
async def test_a_retry_the_budget_cannot_pay_for_is_not_made() -> None:
    """The bound wins over the retry policy, and stays fail-closed."""

    posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        del request
        raise httpx.ConnectTimeout("provider timed out")

    settings = _required_settings(pricing_llm_max_provider_calls_per_position=1)
    ledger = InMemoryProviderCallLedger()
    position_id = uuid4()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        budget = _budget(1, ledger=ledger, position_id=position_id)
        provider = llm_comparability.OpenAIResponsesComparabilityProvider(
            settings,
            client=client,
        )
        with pytest.raises(ComparabilityProviderError) as excinfo:
            await _ProviderCallBudget(provider, budget=budget).review(
                input_snapshot={"our_product": {}},
                image_urls=(),
            )

    assert posts == 1, "the unaffordable retry was made anyway"
    assert await ledger.spent(position_id=position_id) == 1
    # A retryable transport failure is not a final one by itself: what made it
    # final is the bound, so that is what the persisted row names.  The failure
    # that would have been retried stays in the detail, so nothing is lost.
    assert excinfo.value.code == PROVIDER_CALL_BUDGET_EXHAUSTED
    assert "ConnectTimeout" in excinfo.value.safe_detail


@pytest.mark.asyncio
async def test_injected_real_provider_is_bounded_on_the_public_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F9 repro: the reservation must sit at the HTTP attempt, not the call.

    ``request_observation_comparability_review`` accepts a provider, and the
    caller that hands it a real ``OpenAIResponsesComparabilityProvider`` gets an
    adapter whose internal retry knows nothing about the budget.  The outer
    invocation reserved once, the adapter then retried a 429 for free, and a
    configured budget of one bought two billable POSTs while the durable ledger
    still read ``spent = 1``.

    The bound is therefore taken per HTTP attempt, by the adapter itself, for
    every real provider -- default-created or injected -- and the first attempt
    is charged exactly once.
    """

    posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        del request
        return httpx.Response(429, json={"error": "slow down"})

    position_id = uuid4()
    ledger = InMemoryProviderCallLedger()
    persisted = _stub_position(monkeypatch, position_id=position_id)
    settings = _required_settings(pricing_llm_max_provider_calls_per_position=1)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        # Exactly what an injecting caller writes: no budget hook of its own.
        provider = llm_comparability.OpenAIResponsesComparabilityProvider(
            settings,
            client=client,
        )
        await llm_comparability.request_observation_comparability_review(
            uuid4(),
            settings=settings,
            provider=provider,
            ledger=ledger,
        )

    assert posts == 1, "the retry was billed without a reservation"
    assert await ledger.spent(position_id=position_id) == 1
    # Fail-closed, and on the record: a decision row naming the bound.
    assert [item["status"] for item in persisted] == ["FAILED"]
    assert persisted[0]["error_code"] == PROVIDER_CALL_BUDGET_EXHAUSTED
    assert "429" in persisted[0]["error_detail"]


@pytest.mark.asyncio
async def test_injected_real_provider_still_spends_a_whole_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Attempt-level accounting must not under-spend either.

    Charging the retry is only correct if the first attempt is charged once:
    a budget of 4 has to buy 4 POSTs, not 2 review calls of 2 attempts each and
    not 8 attempts.
    """

    posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        del request
        return httpx.Response(429, json={"error": "slow down"})

    position_id = uuid4()
    ledger = InMemoryProviderCallLedger()
    _stub_position(monkeypatch, position_id=position_id)
    settings = _required_settings(pricing_llm_max_provider_calls_per_position=4)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = llm_comparability.OpenAIResponsesComparabilityProvider(
            settings,
            client=client,
        )
        for _ in range(5):
            await llm_comparability.request_observation_comparability_review(
                uuid4(),
                settings=settings,
                provider=provider,
                ledger=ledger,
            )

    assert posts == 4
    assert await ledger.spent(position_id=position_id) == 4


@pytest.mark.asyncio
async def test_default_created_provider_is_bounded_per_http_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same bound, on the path that builds its own adapter.

    ``provider=None`` is what the admin route and the automatic walk use, so the
    attempt-level reservation has to hold there too -- and it must hold through
    the ``httpx.AsyncClient`` the adapter creates for itself.
    """

    posts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        del request
        return httpx.Response(429, json={"error": "slow down"})

    position_id = uuid4()
    ledger = InMemoryProviderCallLedger()
    persisted = _stub_position(monkeypatch, position_id=position_id)
    settings = _required_settings(pricing_llm_max_provider_calls_per_position=1)
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def client_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(llm_comparability.httpx, "AsyncClient", client_factory)

    await llm_comparability.request_observation_comparability_review(
        uuid4(),
        force=True,
        settings=settings,
        provider=None,
        ledger=ledger,
    )

    assert posts == 1
    assert await ledger.spent(position_id=position_id) == 1
    assert persisted[0]["error_code"] == PROVIDER_CALL_BUDGET_EXHAUSTED


@pytest.mark.asyncio
async def test_a_raised_setting_cannot_widen_a_started_position() -> None:
    """F9: the allowance a position started with may shrink, never grow.

    The reservation used to write the caller's current limit into the row on
    every conflict, so raising
    ``PRICING_LLM_MAX_PROVIDER_CALLS_PER_POSITION`` and restarting handed every
    already-bounded position the difference -- silently, and with the ledger
    still looking authoritative.
    """

    ledger = InMemoryProviderCallLedger()
    position_id = uuid4()
    workspace_id = uuid4()

    assert (
        await ledger.reserve(
            position_id=position_id, workspace_id=workspace_id, limit=1
        )
        is True
    )
    # The "restart": same position, a bigger number in the environment.
    assert (
        await ledger.reserve(
            position_id=position_id, workspace_id=workspace_id, limit=10
        )
        is False
    )
    assert await ledger.spent(position_id=position_id) == 1
    assert await ledger.observed_limit(position_id=position_id) == 1


@pytest.mark.asyncio
async def test_a_lowered_setting_takes_effect_immediately() -> None:
    """Non-increasing, not frozen: a cost cut applies to work in flight."""

    ledger = InMemoryProviderCallLedger()
    position_id = uuid4()
    workspace_id = uuid4()

    for _ in range(2):
        assert (
            await ledger.reserve(
                position_id=position_id, workspace_id=workspace_id, limit=5
            )
            is True
        )
    assert (
        await ledger.reserve(
            position_id=position_id, workspace_id=workspace_id, limit=2
        )
        is False
    )
    assert await ledger.spent(position_id=position_id) == 2


@pytest.mark.asyncio
async def test_the_walk_reads_the_started_allowance_not_the_new_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wave accounting has to agree with the reservation after a restart.

    Both layers refuse the calls either way, but only the accounting decides
    whether the tail is declined as a labelled ``PROVIDER_CALL_BUDGET`` row an
    operator can read or discovered one at a time as provider failures.
    """

    position_id = uuid4()
    ledger = InMemoryProviderCallLedger()
    inner = _StubProvider()
    _stub_position(monkeypatch, position_id=position_id)

    await llm_comparability.request_observation_comparability_review(
        uuid4(),
        force=True,
        settings=_required_settings(pricing_llm_max_provider_calls_per_position=1),
        provider=inner,
        ledger=ledger,
    )
    assert inner.calls == 1

    declined: list[tuple[uuid.UUID, object]] = []

    async def fake_skip(
        observation_id: uuid.UUID,
        *,
        reason: object = "CONFIRMED_CEILING",
        **_: object,
    ) -> None:
        declined.append((observation_id, reason))

    monkeypatch.setattr(
        llm_comparability, "skip_observation_comparability_review", fake_skip
    )

    cohort = [uuid4() for _ in range(5)]
    await llm_comparability._ensure_observation_ids(
        cohort,
        # The restart: a bigger budget in the environment, same position.
        settings=_required_settings(pricing_llm_max_provider_calls_per_position=9),
        provider=inner,
        position_id=position_id,
        ledger=ledger,
    )

    assert inner.calls == 1, "a raised setting handed the position a second budget"
    assert [observation_id for observation_id, _reason in declined] == cohort
    assert {reason for _observation_id, reason in declined} == {"PROVIDER_CALL_BUDGET"}


# --------------------------------------------------------------------------
# The setting
# --------------------------------------------------------------------------


def test_budget_is_configurable_and_refuses_a_meaningless_value() -> None:
    assert Settings().pricing_llm_max_provider_calls_per_position == 10
    assert (
        Settings(
            pricing_llm_max_provider_calls_per_position=42
        ).pricing_llm_max_provider_calls_per_position
        == 42
    )
    # A budget of zero would decline a whole catalogue without ever saying why.
    with pytest.raises(ValueError):
        Settings(pricing_llm_max_provider_calls_per_position=0)
    with pytest.raises(ValueError):
        Settings(pricing_llm_max_provider_calls_per_position=-1)
