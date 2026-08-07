"""Competitor cards are replayed across positions, not refetched for each.

``load_replay_cache`` is scoped to one owner, so the same card was fetched
again for every position and every run. With the detail budget unbounded
(owner decision, 2026-08-06) that is the difference between a catalogue pass
costing days and costing hours: throughput is one request per two seconds
globally, not per worker.

Replay is safe here specifically because a product card supplies no monetary
field — ``PromGateway._fetch_candidate_detail`` keeps price, availability,
title, images and seller identity at listing time — so a stale card cannot
move a price. No database is needed to prove which rows a query asks for, so
a recording session stands in for one.
"""

from __future__ import annotations

import pytest

from marko.services.scrape_journal import load_detail_replay_cache


class _EmptyResult:
    def all(self):
        return []


class _RecordingSession:
    """Answers every query with nothing and remembers what was asked."""

    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _EmptyResult()

    def rendered(self) -> str:
        return " ".join(
            str(statement.compile(compile_kwargs={"literal_binds": True}))
            for statement in self.statements
        )

    def filters(self) -> str:
        """Only the WHERE clauses; every column appears in the SELECT list."""

        return " ".join(
            self.rendered().split(" WHERE ", 1)[1:]
        )


@pytest.mark.asyncio
async def test_the_shared_cache_is_not_scoped_to_one_target_or_run() -> None:
    session = _RecordingSession()

    await load_detail_replay_cache(session, max_age_hours=72)

    rendered = session.rendered()
    assert "scrape_http_requests" in rendered
    assert "scrape_evidence_blobs" in rendered
    assert "scrape_target_id" not in session.filters()
    assert "sync_run_id" not in session.filters()


@pytest.mark.asyncio
async def test_only_product_cards_are_shared_between_positions() -> None:
    """A search page belongs to its query; only a card is position-agnostic."""

    session = _RecordingSession()

    await load_detail_replay_cache(session, max_age_hours=72)

    rendered = session.rendered()
    assert "'product_page'" in rendered
    assert "'search_page'" not in rendered


@pytest.mark.asyncio
async def test_replay_is_bounded_by_age_and_by_a_completed_outcome() -> None:
    session = _RecordingSession()

    await load_detail_replay_cache(session, max_age_hours=72)

    rendered = session.rendered()
    assert "started_at" in rendered
    assert "'success'" in rendered and "'replayed'" in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize("max_age_hours", [0, -1])
async def test_a_disabled_cache_asks_the_database_nothing(max_age_hours: int) -> None:
    session = _RecordingSession()

    assert await load_detail_replay_cache(session, max_age_hours=max_age_hours) == {}
    assert session.statements == []


@pytest.mark.asyncio
async def test_an_empty_request_kind_set_asks_the_database_nothing() -> None:
    session = _RecordingSession()

    assert (
        await load_detail_replay_cache(session, max_age_hours=72, request_kinds=())
        == {}
    )
    assert session.statements == []
