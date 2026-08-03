"""The one hard bound on what a pricing position may spend on the LLM.

F9: the bound used to be a ``_ProviderCallBudget`` object created inside the
automatic review walk.  That object lives for the length of one Python call, so
it bounded exactly one path.  ``POST
/observations/{id}/comparability-reviews`` calls
``request_observation_comparability_review(force=True)`` directly -- no walk, no
budget object -- and ``force`` skips the cached row on purpose, so every retry
was a fresh billable call.  Five clicks against a configured budget of one cost
five calls, and a per-request counter could never have said otherwise: two
requests are two counters, and a worker restart is a third.

So the counter is not in the process.  It is one row per pricing position + run
(``pricing_run_items.id``, which *is* "position within this run"), reserved
before the call is made:

    INSERT ... VALUES (position, 1, limit)
    ON CONFLICT (pricing_run_item_id) DO UPDATE SET spent = spent + 1
     WHERE spent < least(call_limit, limit)
    RETURNING spent

One statement, so the read and the increment cannot be split by another
transaction: the ``ON CONFLICT`` path takes the row lock itself and re-evaluates
``WHERE`` against the committed row, which is exactly the compare-and-increment
this needs.  No row back means the budget is spent.  Nothing is held across the
provider call, so a slow provider cannot pin a connection or a lock.

``least(call_limit, limit)`` and not ``limit``: the row's ``call_limit`` is the
allowance the position *started* with, and a later reservation may lower it but
never raise it.  Overwriting it with whatever the current process is configured
for would make the durable bound only as strong as the newest deployment --
raise ``PRICING_LLM_MAX_PROVIDER_CALLS_PER_POSITION`` from 1 to 10 and restart,
and every position already at its bound would be handed nine more calls with no
record that it happened.  A restart is exactly the case this ledger exists to
survive, so the effective limit is monotonically non-increasing.

Four properties follow, and each is a thing the in-memory counter did not have:

* durable -- a restart, a second worker and a second HTTP request all see the
  same row, so the bound is on the position, not on the process;
* atomic -- concurrent reservations serialize on one row, so N simultaneous
  ``force=true`` requests spend at most the limit between them;
* exact -- one reservation per billable HTTP attempt, taken *before* the
  attempt, by the provider adapter itself (see ``reserve_attempt`` in
  ``OpenAIResponsesComparabilityProvider``), so its internal retry is charged
  like any other POST.  Counting after the fact would let a whole concurrent
  wave through, and counting per ``review()`` call would miss the retry that the
  provider bills for anyway;
* non-expanding -- the allowance a position started with cannot be widened by a
  configuration change or a restart.

A refused reservation is never a silent skip: the caller turns it into a
persisted ``INSUFFICIENT_DATA`` decision stamped
``LLM_PROVIDER_CALL_BUDGET_EXHAUSTED``, which ``engine.py`` reads as
``MANUAL_LLM_COMPARABILITY_INSUFFICIENT`` -- excluded from the evidence, routed
to a human, and still a row, so the finalizer barrier in
``claim_collection_finalization`` clears instead of stranding the run.

The table is deliberately not part of the ORM domain model: it holds no
evidence, it is the only mutable counter in this area, and it must stay out of
the append-only review history.  Until its migration lands,
``ensure_provider_call_budget_table`` is what test setups use to create it;
production code never issues DDL, and a missing table fails closed (no
reservation, therefore no call) rather than silently unbounding the bill.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
import logging
from typing import Protocol
from uuid import UUID

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Uuid,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from marko.infrastructure.db.session import async_session_factory


log = logging.getLogger(__name__)


#: Stamped on the decision of an offer the budget refused to pay for.  It is the
#: difference between "we judged this and found nothing" and "we never asked",
#: and it is what makes the bound visible to an operator instead of a quiet gap
#: in the evidence base.
PROVIDER_CALL_BUDGET_EXHAUSTED = "LLM_PROVIDER_CALL_BUDGET_EXHAUSTED"

#: What a reservation is being spent on.  Round 6 added a second paid LLM path
#: (AI-assisted evidence extraction) over the same positions, and one row per
#: position would have made the two share a counter *and* a ``call_limit``.
#: That is not a shared bound, it is a collision: ``least(call_limit, limit)`` is
#: deliberately one-way, so an extraction reserving with its ceiling of 4 would
#: permanently narrow a comparability budget of 10 on the same position -- and
#: the narrowing would look exactly like a correctly enforced bound.
#:
#: The ledger is generalized rather than duplicated.  A second table would mean
#: a second copy of the compare-and-increment statement, the fail-closed missing
#: table path and the monotonic ``call_limit`` rule, and the copy that drifts is
#: the one that stops bounding the bill.
COMPARABILITY_PURPOSE = "comparability"
AI_EVIDENCE_EXTRACTION_PURPOSE = "ai_evidence_extraction"

#: Mirrors the CHECK constraint in migration ``20260802_0041``.  An allowlist and
#: not a free string: a typo in a purpose would silently open a fresh, unbounded
#: counter for the same position rather than failing.
CALL_BUDGET_PURPOSES = frozenset({COMPARABILITY_PURPOSE, AI_EVIDENCE_EXTRACTION_PURPOSE})

#: Physical HTTP attempts one logical provider call may make, retry included.
#: The number is small and fixed on purpose: the durable ledger bounds the spend
#: per position, but a retry loop that is itself unbounded can still burn a
#: whole position's budget on one hopeless candidate.
MAX_PHYSICAL_ATTEMPTS = 2

#: Its own ``MetaData``, deliberately not ``Base.metadata``: this counter is not
#: a domain entity, it must not be created by anything that builds the evidence
#: schema, and it must never be mistaken for a table the append-only triggers
#: protect.  Keeping it out also means the migration that owns it can declare it
#: however it likes without colliding with a second declaration here.
budget_metadata = MetaData()

provider_call_budget_table = Table(
    "llm_provider_call_budget",
    budget_metadata,
    # The foreign key lives in the DDL below rather than in this Table: nothing
    # here needs it to build a statement, and referencing a table this MetaData
    # does not hold would make the object unusable.
    Column("pricing_run_item_id", Uuid, primary_key=True),
    Column(
        "purpose",
        String(32),
        primary_key=True,
        nullable=False,
        server_default=COMPARABILITY_PURPOSE,
    ),
    Column("workspace_id", Uuid, nullable=False),
    Column("spent", Integer, nullable=False, server_default="0"),
    Column("call_limit", Integer, nullable=False),
    Column(
        "first_reserved_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
)

#: The schema the migration must create, verbatim.  ``ON DELETE CASCADE``
#: because a deleted run has no budget left to bound; the checks because a
#: negative spend or a non-positive limit would each be a silent way to unbound
#: the bill.
PROVIDER_CALL_BUDGET_DDL = """
CREATE TABLE IF NOT EXISTS llm_provider_call_budget (
    pricing_run_item_id UUID NOT NULL
        REFERENCES pricing_run_items(id) ON DELETE CASCADE,
    purpose VARCHAR(32) NOT NULL DEFAULT 'comparability',
    workspace_id UUID NOT NULL
        REFERENCES workspaces(id) ON DELETE RESTRICT,
    spent INTEGER NOT NULL DEFAULT 0,
    call_limit INTEGER NOT NULL,
    first_reserved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT llm_provider_call_budget_pkey
        PRIMARY KEY (pricing_run_item_id, purpose),
    CONSTRAINT ck_llm_provider_call_budget_spent CHECK (spent >= 0),
    CONSTRAINT ck_llm_provider_call_budget_limit CHECK (call_limit > 0),
    CONSTRAINT ck_llm_provider_call_budget_purpose
        CHECK (purpose IN ('comparability', 'ai_evidence_extraction'))
)
"""


async def ensure_provider_call_budget_table(engine: AsyncEngine) -> None:
    """Create the ledger table if it is not there yet (test setup only).

    Production gets the table from a migration.  Application code never issues
    DDL: a service that can create its own schema hides the deployment that did
    not happen, which is the same class of defect ``schema_state.py`` exists to
    refuse.
    """

    async with engine.begin() as connection:
        await connection.execute(text(PROVIDER_CALL_BUDGET_DDL))


class ProviderCallLedger(Protocol):
    """Where a position's spend is counted, and how a slot is claimed.

    ``purpose`` defaults to ``comparability`` throughout so the callers that
    predate the second paid path keep counting in exactly the row they always
    counted in.  It is a keyword-only argument with a default rather than a new
    positional one for the same reason: a partially updated call site must not
    be able to silently start counting somewhere else.
    """

    async def reserve(
        self,
        *,
        position_id: UUID,
        workspace_id: UUID,
        limit: int,
        purpose: str = COMPARABILITY_PURPOSE,
    ) -> bool:
        """Claim one billable attempt.  ``False`` means the budget is spent."""
        ...

    async def spent(
        self, *, position_id: UUID, purpose: str = COMPARABILITY_PURPOSE
    ) -> int:
        """Attempts already claimed for this position and purpose."""
        ...

    async def observed_limit(
        self, *, position_id: UUID, purpose: str = COMPARABILITY_PURPOSE
    ) -> int | None:
        """The allowance this position started with, or ``None`` if unstarted."""
        ...


class DurableProviderCallLedger:
    """The production ledger: one row per position, one statement per claim."""

    async def reserve(
        self,
        *,
        position_id: UUID,
        workspace_id: UUID,
        limit: int,
        purpose: str = COMPARABILITY_PURPOSE,
    ) -> bool:
        if limit <= 0:
            return False
        _require_known_purpose(purpose)
        # The allowance in force is the smaller of what the position started
        # with and what this process is configured for: a later, higher setting
        # must not widen a bound that is already being spent against.
        effective_limit = func.least(provider_call_budget_table.c.call_limit, limit)
        statement = (
            pg_insert(provider_call_budget_table)
            .values(
                pricing_run_item_id=position_id,
                purpose=purpose,
                workspace_id=workspace_id,
                spent=1,
                call_limit=limit,
            )
            .on_conflict_do_update(
                index_elements=[
                    provider_call_budget_table.c.pricing_run_item_id,
                    provider_call_budget_table.c.purpose,
                ],
                set_={
                    "spent": provider_call_budget_table.c.spent + 1,
                    "call_limit": effective_limit,
                    "updated_at": func.now(),
                },
                # Evaluated against the committed row under its lock, so two
                # concurrent claimants cannot both see the same ``spent``.
                where=provider_call_budget_table.c.spent < effective_limit,
            )
            .returning(provider_call_budget_table.c.spent)
        )
        async with async_session_factory() as session:
            try:
                claimed = (await session.execute(statement)).scalar_one_or_none()
            except ProgrammingError:
                # The migration has not landed.  Fail closed: an unbounded bill
                # is the failure this whole module exists to prevent.
                await session.rollback()
                log.error(
                    "llm provider-call budget ledger is missing; refusing the "
                    "%s call for position %s",
                    purpose,
                    position_id,
                )
                return False
            await session.commit()
        return claimed is not None

    async def spent(
        self, *, position_id: UUID, purpose: str = COMPARABILITY_PURPOSE
    ) -> int:
        async with async_session_factory() as session:
            try:
                value = await session.scalar(
                    select(provider_call_budget_table.c.spent).where(
                        provider_call_budget_table.c.pricing_run_item_id == position_id,
                        provider_call_budget_table.c.purpose == purpose,
                    )
                )
            except ProgrammingError:
                await session.rollback()
                return 0
        return int(value or 0)

    async def observed_limit(
        self, *, position_id: UUID, purpose: str = COMPARABILITY_PURPOSE
    ) -> int | None:
        async with async_session_factory() as session:
            try:
                value = await session.scalar(
                    select(provider_call_budget_table.c.call_limit).where(
                        provider_call_budget_table.c.pricing_run_item_id == position_id,
                        provider_call_budget_table.c.purpose == purpose,
                    )
                )
            except ProgrammingError:
                await session.rollback()
                return None
        return None if value is None else int(value)


class InMemoryProviderCallLedger:
    """Process-local ledger for tests that have no database.

    It is deliberately the same object shape as the durable one so the guard
    above it is exercised by the same code path -- but it is not a fallback:
    nothing in production selects it, because a process-local counter is the
    defect (F9), not a degraded mode of the fix.
    """

    def __init__(self) -> None:
        # Keyed by ``(position, purpose)`` exactly like the durable primary key,
        # so a test cannot pass here on a collision the database would have kept
        # apart -- or the reverse.
        self._spent: dict[tuple[UUID, str], int] = {}
        self._limits: dict[tuple[UUID, str], int] = {}
        self._lock = asyncio.Lock()

    async def reserve(
        self,
        *,
        position_id: UUID,
        workspace_id: UUID,
        limit: int,
        purpose: str = COMPARABILITY_PURPOSE,
    ) -> bool:
        del workspace_id
        if limit <= 0:
            return False
        _require_known_purpose(purpose)
        key = (position_id, purpose)
        async with self._lock:
            current = self._spent.get(key, 0)
            # Same rule as the durable ledger: the started allowance may shrink,
            # never grow, so a test cannot pass here and fail in PostgreSQL.
            effective = min(self._limits.get(key, limit), limit)
            if current >= effective:
                return False
            self._spent[key] = current + 1
            self._limits[key] = effective
        return True

    async def spent(
        self, *, position_id: UUID, purpose: str = COMPARABILITY_PURPOSE
    ) -> int:
        return self._spent.get((position_id, purpose), 0)

    async def observed_limit(
        self, *, position_id: UUID, purpose: str = COMPARABILITY_PURPOSE
    ) -> int | None:
        return self._limits.get((position_id, purpose))


@dataclass(frozen=True, slots=True)
class PositionCallBudget:
    """One position's budget, bound to a ledger.

    ``position_id`` is ``None`` only when the caller could not establish which
    position it is spending for.  That is not a licence to spend: an unattributed
    call cannot be bounded by anything, so it is refused.
    """

    ledger: ProviderCallLedger
    position_id: UUID | None
    workspace_id: UUID | None
    limit: int
    #: Which counter this budget spends from.  Last and defaulted so every
    #: existing construction keeps meaning what it meant.
    purpose: str = COMPARABILITY_PURPOSE

    async def reserve(self) -> bool:
        if self.position_id is None or self.workspace_id is None:
            log.error("llm provider call has no pricing position to bound it; refusing")
            return False
        return await self.ledger.reserve(
            position_id=self.position_id,
            workspace_id=self.workspace_id,
            limit=self.limit,
            purpose=self.purpose,
        )

    async def spent(self) -> int:
        if self.position_id is None:
            return 0
        return await self.ledger.spent(
            position_id=self.position_id, purpose=self.purpose
        )

    async def effective_limit(self) -> int:
        """What this position may still be charged in total.

        The ledger's stored ``call_limit`` wins when it is the smaller one, so a
        setting raised between two runs of the same position does not widen a
        bound already in force.  ``reserve`` enforces this by itself; reading it
        here keeps the caller's own accounting agreeing with the reservation,
        which is what decides whether a declined offer is labelled
        ``PROVIDER_CALL_BUDGET`` or discovered as a provider failure.
        """

        if self.position_id is None:
            return self.limit
        started = await self.ledger.observed_limit(
            position_id=self.position_id, purpose=self.purpose
        )
        if started is None:
            return self.limit
        return min(self.limit, started)

    async def remaining(self) -> int:
        return max(0, await self.effective_limit() - await self.spent())


def _require_known_purpose(purpose: str) -> None:
    if purpose not in CALL_BUDGET_PURPOSES:
        raise ValueError(
            f"unknown provider-call budget purpose {purpose!r}; "
            f"expected one of {sorted(CALL_BUDGET_PURPOSES)}"
        )


class AttemptBudgetExhausted(RuntimeError):
    """The bound, not the provider, is what ended the work.

    Carries ``error_code`` so the caller persists the same
    ``LLM_PROVIDER_CALL_BUDGET_EXHAUSTED`` stamp whichever path raised it: an
    operator reading a failed row has to be able to tell "we asked and it went
    wrong" from "we never asked".
    """

    error_code = PROVIDER_CALL_BUDGET_EXHAUSTED

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(slots=True)
class BudgetedAttempts:
    """The only retry loop a paid LLM adapter in this repo should run.

    ``async for attempt in BudgetedAttempts(budget):`` yields attempt numbers
    ``0, 1, ...`` and reserves one durable slot *before* yielding each one.  Two
    separate failures are prevented by having one object own both jobs:

    * a retry that skips the reservation -- the provider bills for a request it
      processed even when the answer never reached us, so the billable unit is
      the HTTP attempt, not the logical call.  Round 5 fixed this inside the
      comparability adapter; a second adapter re-deriving the loop is exactly
      how that fix gets lost;
    * a reservation loop that is itself unbounded -- the ledger caps a
      *position*, so an adapter that retried while the ledger said yes could
      spend a whole position on one hopeless candidate.  ``max_attempts`` is
      the second, independent bound.

    Refusal is fail-closed and typed.  Before the first attempt it means no
    request was made at all; before a retry it means the retry was abandoned,
    and ``refused_retry_after`` records the failure that would have been
    retried, because the budget is what turned a retryable failure into a final
    one and that is what the persisted row has to name.

    Nothing is held across the provider call: the reservation is a committed
    row, not a lock, so a slow provider cannot pin a connection.
    """

    budget: PositionCallBudget
    max_attempts: int = MAX_PHYSICAL_ATTEMPTS
    #: Set by the caller before ``continue``-ing, purely so a refused retry can
    #: name what it declined to retry.
    last_failure: str | None = None
    made: int = field(default=0, init=False)
    refused_at_start: bool = field(default=False, init=False)
    refused_retry_after: str | None = field(default=None, init=False)

    async def __aiter__(self) -> AsyncIterator[int]:
        while self.made < self.max_attempts:
            if not await self._reserve_next():
                if self.made == 0:
                    self.refused_at_start = True
                else:
                    self.refused_retry_after = self.last_failure or "an earlier failure"
                return
            attempt = self.made
            self.made += 1
            yield attempt

    async def _reserve_next(self) -> bool:
        if not await self.budget.reserve():
            return False
        return True

    @property
    def refused(self) -> bool:
        return self.refused_at_start or self.refused_retry_after is not None

    def raise_if_refused(self) -> None:
        """Turn a refusal into the typed error the caller persists."""

        if self.refused_at_start:
            raise AttemptBudgetExhausted(
                "provider-call budget for this catalogue position is spent; "
                "no request was made"
            )
        if self.refused_retry_after is not None:
            raise AttemptBudgetExhausted(
                "provider-call budget for this catalogue position is spent; "
                f"the retry after {self.refused_retry_after} was not made"
            )


_default_ledger: ProviderCallLedger = DurableProviderCallLedger()


def default_provider_call_ledger() -> ProviderCallLedger:
    return _default_ledger


def evidence_extraction_budget(
    *,
    position_id: UUID | None,
    workspace_id: UUID | None,
    limit: int,
    ledger: ProviderCallLedger | None = None,
) -> PositionCallBudget:
    """A budget bound to the extraction counter of one position.

    A named constructor so no call site has to remember to pass ``purpose``: a
    forgotten one would spend the comparability budget instead, which is both a
    wrong bill and a silent narrowing of a bound that is already in force.
    """

    return PositionCallBudget(
        ledger=ledger or default_provider_call_ledger(),
        position_id=position_id,
        workspace_id=workspace_id,
        limit=limit,
        purpose=AI_EVIDENCE_EXTRACTION_PURPOSE,
    )


__all__ = [
    "AI_EVIDENCE_EXTRACTION_PURPOSE",
    "AttemptBudgetExhausted",
    "BudgetedAttempts",
    "CALL_BUDGET_PURPOSES",
    "COMPARABILITY_PURPOSE",
    "DurableProviderCallLedger",
    "InMemoryProviderCallLedger",
    "MAX_PHYSICAL_ATTEMPTS",
    "PROVIDER_CALL_BUDGET_EXHAUSTED",
    "PositionCallBudget",
    "ProviderCallLedger",
    "default_provider_call_ledger",
    "ensure_provider_call_budget_table",
    "evidence_extraction_budget",
    "PROVIDER_CALL_BUDGET_DDL",
    "provider_call_budget_table",
]
