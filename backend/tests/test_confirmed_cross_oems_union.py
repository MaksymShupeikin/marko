"""Global discovery reads only current long-lived identity authority.

``cross_links`` belong to one pricing run. Reusing them globally would let a
historical description claim bypass current confidence and review policy.

No database is needed to prove which tables a query names, so a recording
session stands in for one rather than adding an sqlite driver to the project
for a test's sake.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from marko.services.catalog_discovery import (
    _confirmed_cross_oems as discovery_confirmed_cross_oems,
)
from marko.services.catalog_search import (
    _confirmed_cross_oems as search_confirmed_cross_oems,
)
from marko.infrastructure.db.models import CrossLink
from marko.services.market_collection import _load_confirmed_crosses


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

    def rendered(self) -> list[str]:
        return [
            str(statement.compile(compile_kwargs={"literal_binds": True}))
            for statement in self.statements
        ]


@pytest.mark.asyncio
async def test_discovery_excludes_run_local_cross_links() -> None:
    session = _RecordingSession()

    result = await discovery_confirmed_cross_oems(
        session, workspace_id=uuid4(), reference_oem="1K0413031BK"
    )

    tables = " ".join(session.rendered())
    assert "catalog_identity_links" in tables
    assert "cross_links" not in tables
    assert result == frozenset()


@pytest.mark.asyncio
async def test_search_excludes_run_local_cross_links() -> None:
    session = _RecordingSession()

    await search_confirmed_cross_oems(
        session, workspace_id=uuid4(), reference="1K0413031BK"
    )

    tables = " ".join(session.rendered())
    assert "catalog_identity_links" in tables
    assert "cross_links" not in tables


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        lambda session: discovery_confirmed_cross_oems(
            session, workspace_id=uuid4(), reference_oem="1K0413031BK"
        ),
        lambda session: search_confirmed_cross_oems(
            session, workspace_id=uuid4(), reference="1K0413031BK"
        ),
    ],
)
async def test_every_global_identity_query_filters_on_confirmed(call) -> None:
    """A REVIEW link must never widen an identity: every kemp.ua link no second
    source corroborated is REVIEW, as is every link carrying an anomaly."""

    session = _RecordingSession()

    await call(session)

    rendered = session.rendered()
    assert len(rendered) == 1
    for statement in rendered:
        assert "'CONFIRMED'" in statement
        assert "'REVIEW'" not in statement


@pytest.mark.asyncio
async def test_an_empty_reference_asks_the_database_nothing() -> None:
    session = _RecordingSession()

    result = await discovery_confirmed_cross_oems(
        session, workspace_id=uuid4(), reference_oem="   "
    )

    assert result == frozenset()
    assert session.statements == []


class _ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return list(self.rows)


class _CrossSession:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    async def scalars(self, statement):
        self.statements.append(statement)
        return _ScalarRows(self.rows)


@pytest.mark.asyncio
async def test_run_cross_reader_is_bidirectional_and_keeps_run_provenance() -> None:
    workspace_id = uuid4()
    run_id = uuid4()
    link = CrossLink(
        id=uuid4(),
        workspace_id=workspace_id,
        pricing_run_id=run_id,
        catalog_item_id=uuid4(),
        our_oem_norm="1K0121251",
        extracted_oem_norm="7L6121253C",
        source_listing_url="urn:test",
        source_seller="CUSTOMER_REFERENCE_GRAPH",
        raw_context="reference",
        extraction_method="CATALOG_IDENTITY_SNAPSHOT",
        validation_status="CONFIRMED",
        rejection_reason=None,
        reciprocal_evidence_url=None,
        source_evidence=[],
        validation_details={"confidence": "0.94", "automatic_eligible": True},
        method_version="catalog-identity-run-snapshot-v1",
        config_sha256="a" * 64,
    )
    session = _CrossSession([link])

    result = await _load_confirmed_crosses(
        session,
        run=SimpleNamespace(id=run_id, workspace_id=workspace_id),
        search_identity="7L6121253C",
    )

    assert len(result) == 1
    assert result[0].search_oe_norm == "7L6121253C"
    assert result[0].candidate_oe_norm == "1K0121251"
    assert result[0].confidence == Decimal("0.94")
    assert result[0].cross_link_id == str(link.id)
    rendered = str(
        session.statements[0].compile(compile_kwargs={"literal_binds": True})
    )
    assert "cross_links.our_oem_norm = '7L6121253C'" in rendered
    assert "cross_links.extracted_oem_norm = '7L6121253C'" in rendered
    assert "'CONFIRMED'" in rendered


@pytest.mark.asyncio
async def test_catalog_identity_snapshot_without_admission_flag_is_not_a_cross() -> None:
    """A snapshot label cannot substitute for its immutable admission result."""

    workspace_id = uuid4()
    run_id = uuid4()
    link = CrossLink(
        id=uuid4(),
        workspace_id=workspace_id,
        pricing_run_id=run_id,
        catalog_item_id=uuid4(),
        our_oem_norm="1K0121251",
        extracted_oem_norm="7L6121253C",
        source_listing_url="urn:test",
        source_seller="CUSTOMER_REFERENCE_GRAPH",
        raw_context="reference",
        extraction_method="CATALOG_IDENTITY_SNAPSHOT",
        validation_status="CONFIRMED",
        rejection_reason=None,
        reciprocal_evidence_url=None,
        source_evidence=[],
        validation_details={"confidence": "0.94"},
        method_version="catalog-identity-run-snapshot-v1",
        config_sha256="a" * 64,
    )

    assert (
        await _load_confirmed_crosses(
            _CrossSession([link]),
            run=SimpleNamespace(id=run_id, workspace_id=workspace_id),
            search_identity="1K0121251",
        )
        == ()
    )


@pytest.mark.asyncio
async def test_run_cross_reader_quarantines_public_number_fanout() -> None:
    """A cross shared by two catalog items is ambiguous, not a usable edge."""

    workspace_id = uuid4()
    run_id = uuid4()
    shared = "SHARED123"
    rows = [
        CrossLink(
            id=uuid4(),
            workspace_id=workspace_id,
            pricing_run_id=run_id,
            catalog_item_id=uuid4(),
            our_oem_norm="OUR1234",
            extracted_oem_norm=shared,
            source_listing_url="urn:test:one",
            source_seller="CUSTOMER_REFERENCE_GRAPH",
            raw_context="reference",
            extraction_method="CATALOG_IDENTITY_SNAPSHOT",
            validation_status="CONFIRMED",
            rejection_reason=None,
            reciprocal_evidence_url=None,
            source_evidence=[],
            validation_details={"confidence": "0.94", "automatic_eligible": True},
            method_version="catalog-identity-run-snapshot-v1",
            config_sha256="a" * 64,
        ),
        CrossLink(
            id=uuid4(),
            workspace_id=workspace_id,
            pricing_run_id=run_id,
            catalog_item_id=uuid4(),
            our_oem_norm="OTHER123",
            extracted_oem_norm=shared,
            source_listing_url="urn:test:two",
            source_seller="CUSTOMER_REFERENCE_GRAPH",
            raw_context="reference",
            extraction_method="CATALOG_IDENTITY_SNAPSHOT",
            validation_status="CONFIRMED",
            rejection_reason=None,
            reciprocal_evidence_url=None,
            source_evidence=[],
            validation_details={"confidence": "0.94", "automatic_eligible": True},
            method_version="catalog-identity-run-snapshot-v1",
            config_sha256="a" * 64,
        ),
    ]

    assert (
        await _load_confirmed_crosses(
            _CrossSession(rows),
            run=SimpleNamespace(id=run_id, workspace_id=workspace_id),
            search_identity="OUR1234",
        )
        == ()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("confidence", (None, "invalid", "NaN", "0", "1.01"))
async def test_run_cross_reader_never_invents_missing_or_invalid_confidence(
    confidence,
) -> None:
    workspace_id = uuid4()
    run_id = uuid4()
    link = CrossLink(
        id=uuid4(),
        workspace_id=workspace_id,
        pricing_run_id=run_id,
        catalog_item_id=uuid4(),
        our_oem_norm="1K0121251",
        extracted_oem_norm="7L6121253C",
        source_listing_url="urn:test",
        source_seller="CUSTOMER_REFERENCE_GRAPH",
        raw_context="reference",
        extraction_method="CATALOG_IDENTITY_SNAPSHOT",
        validation_status="CONFIRMED",
        rejection_reason=None,
        reciprocal_evidence_url=None,
        source_evidence=[],
        validation_details={"confidence": confidence},
        method_version="catalog-identity-run-snapshot-v1",
        config_sha256="a" * 64,
    )

    result = await _load_confirmed_crosses(
        _CrossSession([link]),
        run=SimpleNamespace(id=run_id, workspace_id=workspace_id),
        search_identity="1K0121251",
    )

    assert result == ()


@pytest.mark.asyncio
async def test_description_cross_requires_persisted_automatic_eligibility() -> None:
    workspace_id = uuid4()
    run_id = uuid4()
    link = CrossLink(
        id=uuid4(),
        workspace_id=workspace_id,
        pricing_run_id=run_id,
        catalog_item_id=uuid4(),
        our_oem_norm="OUR1234",
        extracted_oem_norm="ABC12345",
        source_listing_url="https://prom.ua/ua/p1-part.html",
        source_seller="Independent seller",
        raw_context="OE ABC12345",
        extraction_method="OE_MARKER",
        validation_status="CONFIRMED",
        rejection_reason=None,
        reciprocal_evidence_url=None,
        source_evidence=[],
        validation_details={
            "confidence": "0.85",
            "automatic_eligible": False,
            "independent_seller_count": 1,
        },
        method_version="description-crosses-ab-v1",
        config_sha256="b" * 64,
    )
    run = SimpleNamespace(id=run_id, workspace_id=workspace_id)

    assert (
        await _load_confirmed_crosses(
            _CrossSession([link]),
            run=run,
            search_identity="OUR1234",
        )
        == ()
    )

    link.validation_details = {
        **link.validation_details,
        "automatic_eligible": True,
        "independent_seller_count": 2,
    }
    admitted = await _load_confirmed_crosses(
        _CrossSession([link]),
        run=run,
        search_identity="OUR1234",
    )
    assert len(admitted) == 1
    assert admitted[0].confidence == Decimal("0.85")


@pytest.mark.asyncio
async def test_run_cross_reader_rejects_private_catalog_codes() -> None:
    workspace_id = uuid4()
    run_id = uuid4()
    link = CrossLink(
        id=uuid4(),
        workspace_id=workspace_id,
        pricing_run_id=run_id,
        catalog_item_id=uuid4(),
        our_oem_norm="1086282",
        extracted_oem_norm="776415",
        source_listing_url="urn:test:historical-bad-edge",
        source_seller="CUSTOMER_REFERENCE_GRAPH",
        raw_context="776415",
        extraction_method="CATALOG_IDENTITY_SNAPSHOT",
        validation_status="CONFIRMED",
        rejection_reason=None,
        reciprocal_evidence_url=None,
        source_evidence=[],
        validation_details={"confidence": "0.90", "automatic_eligible": True},
        method_version="catalog-identity-run-snapshot-v1",
        config_sha256="b" * 64,
    )

    result = await _load_confirmed_crosses(
        _CrossSession([link]),
        run=SimpleNamespace(id=run_id, workspace_id=workspace_id),
        search_identity="1086282",
    )

    assert result == ()
