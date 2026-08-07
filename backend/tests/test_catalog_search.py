"""Store catalog search and its cross-store OE/SKU fallback."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

import marko.repositories.listings as listings_repo
from marko.infrastructure.db.models import Listing, MarketplaceStore
from marko.services import catalog_search
from marko.services.catalog_search import search_other_stores


def _sql(condition) -> str:
    return str(
        select(Listing.id)
        .where(condition)
        .compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def _listing(**overrides) -> Listing:
    values = {
        "id": uuid4(),
        "store_id": uuid4(),
        "external_id": "2858586065",
        "name": "Амортизатор капота VW Passat B5",
        "url": "https://prom.ua/ua/p2858586065-amortizator.html",
        "sku": "77641543",
        "model_id": None,
        "brand": "KEMP",
        "currency": "UAH",
        "current_price": Decimal("256.50"),
        "is_available": True,
        "raw_data": {"image": "https://images.example/1.jpg"},
    }
    values.update(overrides)
    return Listing(**values)


def _store(**overrides) -> MarketplaceStore:
    values = {
        "id": uuid4(),
        "marketplace": "prom",
        "external_id": "3912822",
        "name": "parts-avto",
        "canonical_url": "https://prom.ua/ua/c3912822-parts-avto.html",
    }
    values.update(overrides)
    return MarketplaceStore(**values)


def test_blank_query_leaves_the_catalog_page_unfiltered() -> None:
    assert listings_repo.listing_search_condition(None) is None
    assert listings_repo.listing_search_condition("   ") is None


def test_search_condition_keeps_a_cyrillic_title_lane() -> None:
    sql = _sql(listings_repo.listing_search_condition("Бендикс"))

    assert "ILIKE '%%Бендикс%%'" in sql
    assert "'%%БЕНДИКС%%'" in sql


def test_search_condition_requires_every_token_of_a_multi_word_query() -> None:
    sql = _sql(listings_repo.listing_search_condition("Бендикс MB126"))

    assert "'%%БЕНДИКС%%' ESCAPE '\\\\' AND" in sql
    assert "'%%MB126%%'" in sql


def test_search_condition_escapes_like_wildcards() -> None:
    sql = _sql(listings_repo.listing_search_condition("100%_x"))

    assert "ILIKE '%%100\\\\%%\\\\_x%%'" in sql


def test_identity_condition_ignores_an_empty_identity_set() -> None:
    assert listings_repo.listing_identity_condition(()) is None
    assert listings_repo.listing_identity_condition(("", "")) is None


def test_identity_condition_compares_normalized_article_fields() -> None:
    sql = _sql(listings_repo.listing_identity_condition(("1K0121251",)))

    # Prom ``Listing.external_id`` is a card/listing id, never a product
    # identity.  It must not participate in this query or an unrelated card
    # whose id equals an OE would be shown as a match.
    assert sql.count("'[^A-Z0-9]'") == 4
    assert "IN ('1K0121251')" in sql
    assert "LIKE '%%1K0121251%%'" in sql


def test_listing_card_id_is_not_used_as_product_identity() -> None:
    listing = _listing(
        sku=None,
        model_id=None,
        external_id="93818439",
        raw_data={},
    )
    match = catalog_search._listing_match(
        listing,
        _store(),
        identities=("93818439",),
        reference="93818439",
    )

    assert match.matched_on == "name"


def test_match_reports_the_seller_article_lane() -> None:
    match = catalog_search._listing_match(
        _listing(),
        _store(),
        identities=("77641543",),
        reference="77641543",
    )

    assert match.matched_on == "sku"
    assert match.matched_value == "77641543"
    assert match.via_cross is False
    assert match.source == "store"
    assert match.image_url == "https://images.example/1.jpg"


def test_match_reports_an_oe_number_carried_by_the_title() -> None:
    match = catalog_search._listing_match(
        _listing(sku=None, name="Насос ГУР 1K0 121 251 для VW"),
        _store(),
        identities=("1K0121251",),
        reference="1K0121251",
    )

    assert match.matched_on == "oem"
    assert match.matched_value == "1K0121251"


def test_title_oem_fallback_requires_identifier_boundaries() -> None:
    match = catalog_search._listing_match(
        _listing(sku=None, name="Колодка 1K01212510 комплект"),
        _store(),
        identities=("1K0121251",),
        reference="1K0121251",
    )

    assert match.matched_on == "name"


def test_short_numeric_title_oem_requires_an_explicit_label() -> None:
    unlabelled = catalog_search._listing_match(
        _listing(sku=None, name="Фильтр 1234567 для VW"),
        _store(),
        identities=("123456",),
        reference="123456",
    )
    labelled = catalog_search._listing_match(
        _listing(sku=None, name="Фильтр OE 123456 для VW"),
        _store(),
        identities=("123456",),
        reference="123456",
    )
    hash_labelled = catalog_search._listing_match(
        _listing(sku=None, name="Фильтр #123456 для VW"),
        _store(),
        identities=("123456",),
        reference="123456",
    )

    assert unlabelled.matched_on == "name"
    assert labelled.matched_on == "oem"
    assert labelled.matched_value == "123456"
    assert hash_labelled.matched_on == "oem"
    assert hash_labelled.matched_value == "123456"


def test_match_flags_a_hit_reached_through_a_confirmed_cross() -> None:
    match = catalog_search._listing_match(
        _listing(sku="06A121011X"),
        _store(),
        identities=("1K0121251", "06A121011X"),
        reference="1K0121251",
    )

    assert match.matched_on == "sku"
    assert match.via_cross is True


def test_match_prefers_the_original_prom_seller_name() -> None:
    match = catalog_search._listing_match(
        _listing(raw_data={"seller_name": "ПРОФПАРТС"}),
        _store(name="profparts"),
        identities=("77641543",),
        reference="77641543",
    )

    assert match.store_name == "ПРОФПАРТС"


@pytest.mark.asyncio
async def test_cross_store_search_widens_the_query_with_confirmed_crosses(
    monkeypatch,
) -> None:
    requested: list[tuple[str, ...]] = []

    async def fake_crosses(_session, *, workspace_id, reference):
        return frozenset({"06A121011X"})

    async def fake_search(_session, *, workspace_id, excluded_store_id, identities, limit):
        requested.append(tuple(identities))
        return [(_listing(sku="06A121011X"), _store())]

    async def no_market_matches(*_args, **_kwargs):
        return []

    monkeypatch.setattr(catalog_search, "_confirmed_cross_oems", fake_crosses)
    monkeypatch.setattr(catalog_search, "_verified_market_matches", no_market_matches)
    monkeypatch.setattr(listings_repo, "search_listings_in_other_stores", fake_search)

    search = await search_other_stores(
        object(),
        store_id=uuid4(),
        workspace_id=uuid4(),
        query="1K0 121 251",
    )

    assert requested == [("1K0121251", "06A121011X")]
    assert search.normalized_query == "1K0121251"
    assert search.identities == ("1K0121251", "06A121011X")
    assert [match.matched_value for match in search.matches] == ["06A121011X"]
    assert search.matches[0].via_cross is True


@pytest.mark.asyncio
async def test_cross_store_identity_lane_discards_normalized_substring_only_rows(
    monkeypatch,
) -> None:
    async def no_crosses(_session, *, workspace_id, reference):
        return frozenset()

    async def fake_search(
        _session, *, workspace_id, excluded_store_id, identities, limit
    ):
        assert limit >= 4
        return [
            (
                _listing(
                    sku=None,
                    name="Колодка 1K01212510 комплект",
                ),
                _store(external_id="bad", name="bad"),
            ),
            (
                _listing(
                    sku=None,
                    name="Насос 1K0 121 251 для VW",
                ),
                _store(external_id="good", name="good"),
            ),
        ]

    async def no_market_matches(*_args, **_kwargs):
        return []

    monkeypatch.setattr(catalog_search, "_confirmed_cross_oems", no_crosses)
    monkeypatch.setattr(catalog_search, "_verified_market_matches", no_market_matches)
    monkeypatch.setattr(listings_repo, "search_listings_in_other_stores", fake_search)

    search = await search_other_stores(
        object(),
        store_id=uuid4(),
        workspace_id=uuid4(),
        query="1K0 121 251",
        limit=1,
    )

    assert len(search.matches) == 1
    assert search.matches[0].store_name == "good"
    assert search.matches[0].matched_on == "oem"


@pytest.mark.asyncio
async def test_cross_store_search_falls_back_to_wording_without_an_identity(
    monkeypatch,
) -> None:
    async def unexpected_identity_search(*_args, **_kwargs):
        raise AssertionError("a Cyrillic query carries no OE identity")

    async def fake_text_search(_session, *, workspace_id, excluded_store_id, query, limit):
        assert query == "Бендикс"
        return [(_listing(name="Бендикс стартера"), _store())]

    monkeypatch.setattr(
        listings_repo, "search_listings_in_other_stores", unexpected_identity_search
    )
    monkeypatch.setattr(
        listings_repo, "search_listing_text_in_other_stores", fake_text_search
    )

    search = await search_other_stores(
        object(),
        store_id=uuid4(),
        workspace_id=uuid4(),
        query="Бендикс",
    )

    assert search.normalized_query == ""
    assert search.identities == ()
    assert [match.matched_on for match in search.matches] == ["name"]


@pytest.mark.asyncio
async def test_cross_store_search_rejects_a_fragment_too_short_to_identify(
    monkeypatch,
) -> None:
    async def unexpected(*_args, **_kwargs):
        raise AssertionError("a two-character fragment must not be treated as an OE")

    monkeypatch.setattr(listings_repo, "search_listings_in_other_stores", unexpected)
    monkeypatch.setattr(
        listings_repo,
        "search_listing_text_in_other_stores",
        lambda *_args, **_kwargs: _empty(),
    )

    search = await search_other_stores(
        object(), store_id=uuid4(), workspace_id=uuid4(), query="A1"
    )

    assert search.normalized_query == ""
    assert search.matches == ()


@pytest.mark.asyncio
async def test_identity_query_never_degrades_to_unverified_text_fallback(
    monkeypatch,
) -> None:
    async def no_identity_matches(*_args, **_kwargs):
        return []

    async def unexpected_text_search(*_args, **_kwargs):
        raise AssertionError("an identity query must not enter the wording lane")

    monkeypatch.setattr(
        listings_repo, "search_listings_in_other_stores", no_identity_matches
    )
    monkeypatch.setattr(
        listings_repo,
        "search_listing_text_in_other_stores",
        unexpected_text_search,
    )
    monkeypatch.setattr(catalog_search, "_confirmed_cross_oems", lambda *_args, **_kwargs: _empty())
    monkeypatch.setattr(catalog_search, "_verified_market_matches", no_identity_matches)

    search = await search_other_stores(
        object(),
        store_id=uuid4(),
        workspace_id=uuid4(),
        query="123456",
    )

    assert search.normalized_query == "123456"
    assert search.matches == ()


async def _empty() -> list:
    return []


class _StatementRecorder:
    """Session double that captures the statement instead of executing it."""

    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement):
        self.statements.append(statement)

        class _Empty:
            def scalars(self):
                return self

            @staticmethod
            def all() -> list:
                return []

        return _Empty()

    def compiled(self) -> str:
        assert len(self.statements) == 1
        return str(
            self.statements[0].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "search",
    [
        listings_repo.search_listings_in_other_stores,
        listings_repo.search_listing_text_in_other_stores,
    ],
    ids=["identity_lane", "text_lane"],
)
async def test_cross_store_search_is_scoped_to_the_calling_workspace(search) -> None:
    """F2-0103: снятие фильтра арендатора обязано ронять тест.

    Мутант MU-04-B (удаление ``WorkspaceStore.workspace_id == workspace_id`` из
    ``_search_other_stores``) переживал весь backend suite. Инвариант проверяется
    на форме SQL, поэтому срабатывает в каждом прогоне, а не только при наличии
    живого PostgreSQL.
    """
    workspace_id = uuid4()
    recorder = _StatementRecorder()

    kwargs = (
        {"identities": ("77641543",)}
        if search is listings_repo.search_listings_in_other_stores
        else {"query": "77641543"}
    )
    await search(
        recorder,
        workspace_id=workspace_id,
        excluded_store_id=uuid4(),
        limit=24,
        **kwargs,
    )

    sql = recorder.compiled()
    assert "workspace_stores" in sql
    assert f"workspace_stores.workspace_id = '{workspace_id}'" in sql


@pytest.mark.asyncio
async def test_store_product_pagination_has_a_total_name_id_order() -> None:
    recorder = _StatementRecorder()

    await listings_repo.list_listings_for_store(
        recorder,
        uuid4(),
        limit=2,
        offset=1,
    )

    sql = recorder.compiled()
    assert "ORDER BY listings.name, listings.id" in sql
    assert "LIMIT 2 OFFSET 1" in sql


@pytest.mark.asyncio
async def test_cross_store_search_has_a_total_store_name_id_order() -> None:
    recorder = _StatementRecorder()

    await listings_repo.search_listings_in_other_stores(
        recorder,
        workspace_id=uuid4(),
        excluded_store_id=uuid4(),
        identities=("77641543",),
        limit=24,
    )

    sql = recorder.compiled()
    assert (
        "ORDER BY marketplace_stores.external_id, listings.name, listings.id" in sql
    )


@pytest.mark.asyncio
async def test_cross_store_search_is_competitor_only() -> None:
    recorder = _StatementRecorder()

    await listings_repo.search_listings_in_other_stores(
        recorder,
        workspace_id=uuid4(),
        excluded_store_id=uuid4(),
        identities=("77641543",),
        limit=24,
    )

    sql = recorder.compiled()
    assert "workspace_stores.kind = 'competitor'" in sql


@pytest.mark.asyncio
async def test_verified_market_matches_require_admitted_competitor_evidence() -> None:
    recorder = _StatementRecorder()

    await catalog_search._verified_market_matches(
        recorder,
        workspace_id=uuid4(),
        identities=("1K0121251",),
        reference="1K0121251",
        limit=10,
    )

    sql = recorder.compiled()
    assert "market_observations.automatic_eligible IS true" in sql
    assert "market_observations.comparability_hard_gate_result = 'PASS'" in sql
    assert "market_observations.seller_identity_verified IS true" in sql
    assert "market_observations.source_provenance_verified IS true" in sql
    assert "observation_tier_classifications_1.cohort_role = 'TARGET_MARKET'" in sql
    assert "observation_tier_classifications_1.is_kemp IS false" in sql
    assert "observation_tier_classifications_1.is_dumping IS false" in sql
    assert "observation_tier_classifications_1.exclusion_reason IS NULL" in sql
    assert "market_observations.source IN" in sql
    assert "workspace_stores_1.kind = 'owned'" in sql
    assert "marketplace_stores_1.marketplace = 'prom'" in sql
