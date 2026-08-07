"""Наші власні вітрини не мають витрачати квоту конкурентів.

KEMP тримає на prom.ua чотири магазини (2847093, 3912822, 3325174, 4015921) з
однаковими картками, тож вони схожі на наш товар краще за будь-якого
конкурента.  Виміряно 2026-07-31: 48 із 65 збігів за назвою були нашими
магазинами, і кожен з них займав слот ``max_sellers=10`` ще до того, як
цінові гейти щось побачили.

Виключення вже підтримують і шлюз, і матчер — і застосовують його ДО
обмеження.  Тут перевіряється, що виробничий шлях справді передає туди наші
ідентифікатори, і що пізніше виключення при матеріалізації залишається як
другий рубіж.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from marko.infrastructure.db.models import PricingRun, PricingRunItem, ScrapeTarget
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.gateway import PromGateway
from marko.services import market_collection
from marko.services.matching import ComparisonParams, PriceComparison, build_comparison
from marko.services.parser_models import SeedInfo
from marko.services.scraper_contract import (
    PROM_ADAPTER_VERSION,
    FrozenPromScraperAdapter,
    ScrapeInput,
)

from factories import product

SEED_URL = "https://prom.ua/ua/p1153738393-radiator-folksvagen-tuareg.html"

#: Чотири вітрини KEMP на prom.ua.  Насіння належить першій із них.
OWNED_SELLER_IDS = frozenset({"2847093", "3912822", "3325174", "4015921"})


def _seed() -> SeedInfo:
    return SeedInfo(
        product=product(
            id=1,
            name="Радіатор VW Touareg 2.5 TDI 710*549",
            price="5163",
            company={"id": 2847093, "name": "KEMP"},
        ),
        seller_count=2,
        min_price=None,
        max_price=None,
    )


def _offer(index: int, price: str, seller_id: int):
    return product(
        id=100 + index,
        name="Радіатор VW Touareg 2.5 TDI 710*549",
        identifiers={"mpn": "7L6121253"},
        price=price,
        urlText="radiator",
        company={"id": seller_id, "name": f"Магазин {seller_id}"},
    )


# -- Матчер: виключення застосовується до обмеження --------------------------


def test_owned_storefronts_never_consume_a_capped_competitor_slot() -> None:
    """Три інші вітрини дешевші за конкурентів; квота — два продавці."""

    candidates = [
        _offer(1, "1000", 3912822),
        _offer(2, "1010", 3325174),
        _offer(3, "1020", 4015921),
        _offer(4, "3000", 900001),
        _offer(5, "3100", 900002),
        _offer(6, "3200", 900003),
    ]

    comparison = build_comparison(
        _seed(),
        candidates,
        ComparisonParams(
            query="7L6121253",
            threshold=0.55,
            max_sellers=2,
            excluded_seller_ids=OWNED_SELLER_IDS,
        ),
    )

    assert [offer.product.seller_id for offer in comparison.offers] == [900001, 900002]
    assert comparison.candidates_scanned == 6


def test_excluding_only_the_seeds_own_seller_is_not_enough() -> None:
    """Насіння належить 2847093; без переліку решта трьох проходить далі."""

    candidates = [
        _offer(1, "1000", 3912822),
        _offer(2, "1010", 3325174),
        _offer(3, "3000", 900001),
    ]
    params = {"query": "q", "threshold": 0.55, "max_sellers": 2}

    without_list = build_comparison(_seed(), candidates, ComparisonParams(**params))
    with_list = build_comparison(
        _seed(),
        candidates,
        ComparisonParams(**params, excluded_seller_ids=OWNED_SELLER_IDS),
    )

    assert [offer.product.seller_id for offer in without_list.offers] == [
        3912822,
        3325174,
    ]
    assert [offer.product.seller_id for offer in with_list.offers] == [900001]


def test_owned_seller_ids_are_compared_as_text() -> None:
    """``company.id`` приходить числом, а магазини зберігаються рядком."""

    comparison = build_comparison(
        _seed(),
        [_offer(1, "1000", 3912822)],
        ComparisonParams(
            query="q",
            threshold=0.55,
            max_sellers=10,
            excluded_seller_ids=frozenset({"3912822"}),
        ),
    )

    assert comparison.offers == []


# -- Виробничий шлях: заявка -> адаптер -> шлюз ------------------------------


def test_the_production_adapter_passes_owned_sellers_into_matching() -> None:
    seen: dict[str, object] = {}

    class Gateway:
        def __init__(self, _config) -> None:
            pass

        def compare(self, url, query, *, strict, excluded_seller_ids):
            seen["url"] = url
            seen["excluded_seller_ids"] = excluded_seller_ids
            return build_comparison(
                _seed(),
                [_offer(1, "1000", 3912822), _offer(4, "3000", 900001)],
                ComparisonParams(
                    query=query,
                    threshold=0.55,
                    max_sellers=10,
                    excluded_seller_ids=excluded_seller_ids,
                ),
            )

    adapter = FrozenPromScraperAdapter(
        ScrapeConfig(),
        gateway_factory=Gateway,
        excluded_seller_ids=OWNED_SELLER_IDS,
    )
    output = adapter.extract(ScrapeInput.build(SEED_URL, "7L6121253"))

    assert seen["excluded_seller_ids"] == OWNED_SELLER_IDS
    sellers = [
        record["product"]["seller_id"]
        for record in output.payload["output"]["records"]
    ]
    assert sellers == [900001]


def test_the_adapter_defaults_to_excluding_nobody() -> None:
    seen: dict[str, object] = {}

    class Gateway:
        def __init__(self, _config) -> None:
            pass

        def compare(self, url, query, *, strict, excluded_seller_ids):
            seen["excluded_seller_ids"] = excluded_seller_ids
            return PriceComparison(
                seed=_seed(), query=query, offers=[], candidates_scanned=0
            )

    FrozenPromScraperAdapter(ScrapeConfig(), gateway_factory=Gateway).extract(
        ScrapeInput.build(SEED_URL, "7L6121253")
    )

    assert seen["excluded_seller_ids"] == frozenset()


def test_the_gateway_applies_the_exclusion_before_the_cap(monkeypatch) -> None:
    """Через увесь шлюз: одинадцять наших карток не забирають обидва слоти."""

    candidates = [_offer(index, str(1000 + index), 3912822) for index in range(1, 12)]
    candidates += [
        _offer(50 + index, str(5000 + index), 900000 + index) for index in range(1, 4)
    ]
    monkeypatch.setattr(
        PromGateway,
        "_fetch_seed_with_motors",
        lambda self, client, url, lang: (_seed(), None),
    )
    monkeypatch.setattr(
        PromGateway,
        "_collect_candidates",
        lambda self, client, query, lang, *, strict=False: iter(candidates),
    )

    comparison = PromGateway(ScrapeConfig(max_sellers=2)).compare(
        SEED_URL,
        query="7L6121253",
        excluded_seller_ids=OWNED_SELLER_IDS,
    )

    assert [offer.product.seller_id for offer in comparison.offers] == [900001, 900002]


def test_the_collection_worker_hands_owned_sellers_to_the_adapter(
    monkeypatch,
) -> None:
    """Ідентифікатори, зібрані під час заявки, доходять до придбання."""

    seen: dict[str, object] = {}

    class Adapter:
        def __init__(
            self,
            _config,
            *,
            excluded_seller_ids=frozenset(),
            min_independent_sellers=0,
        ) -> None:
            seen["excluded_seller_ids"] = excluded_seller_ids
            seen["min_independent_sellers"] = min_independent_sellers

        def extract(self, _scrape_input):
            return SimpleNamespace(payload={})

    class Trace:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(market_collection, "FrozenPromScraperAdapter", Adapter)
    monkeypatch.setattr(
        market_collection,
        "_raise_on_required_request_failure",
        lambda trace: None,
    )
    monkeypatch.setattr(market_collection, "scrape_execution", lambda trace: Trace())

    market_collection._collect_target_output(
        ScrapeInput.build(SEED_URL, "7L6121253"),
        SimpleNamespace(),
        excluded_seller_ids=OWNED_SELLER_IDS,
    )

    assert seen["excluded_seller_ids"] == OWNED_SELLER_IDS


class _RecordingSession:
    """Досить сесії, щоб пройти заявку і записати, що з неї прочитали."""

    def __init__(self, owned: list[object]) -> None:
        self._owned = owned
        self.added: list[object] = []
        self.statements: list[str] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid4()

    async def commit(self) -> None:
        return None

    async def scalars(self, statement):
        self.statements.append(str(statement))
        owned = self._owned

        class _Result:
            def all(self):
                return list(owned)

        return _Result()


def _claim_fixtures():
    run = PricingRun(id=uuid4(), workspace_id=uuid4(), parser_version="v")
    item = PricingRunItem(
        id=uuid4(),
        pricing_run_id=run.id,
        catalog_item_id=uuid4(),
        status="queued",
        attempts=0,
    )
    target = ScrapeTarget(
        id=uuid4(),
        pricing_run_id=run.id,
        status="queued",
        input_kind="product_seed",
        original_url=SEED_URL,
        query="7L6121253",
        adapter_version=PROM_ADAPTER_VERSION,
        network_attempts=0,
        max_task_executions=3,
        delivery_count=0,
        fencing_token=0,
        raw_size_bytes=0,
    )
    catalog_item = SimpleNamespace(
        id=uuid4(), product_url=SEED_URL, oe_norm="7L6121253"
    )
    return run, item, target, catalog_item


@pytest.mark.asyncio
async def test_the_claim_reads_owned_storefronts_before_acquisition_starts() -> None:
    run, item, target, catalog_item = _claim_fixtures()
    session = _RecordingSession(["2847093", " 3912822 ", "3325174", "4015921"])

    claim = await market_collection._claim_target_item(
        session,
        item=item,
        run=run,
        catalog_item=catalog_item,
        target=target,
        task_id="task-1",
        is_redelivery=False,
    )

    assert claim.action == "target_collect"
    assert claim.excluded_seller_ids == OWNED_SELLER_IDS
    owned_query = next(
        statement
        for statement in session.statements
        if "marketplace_stores" in statement
    )
    assert "workspace_stores" in owned_query
    assert "workspace_stores.kind" in owned_query


@pytest.mark.asyncio
async def test_an_absent_store_id_never_becomes_a_literal_none() -> None:
    """Порожній ідентифікатор не має читатися як заповнений перелік."""

    run, item, target, catalog_item = _claim_fixtures()
    session = _RecordingSession([None, "", "  ", "2847093"])

    claim = await market_collection._claim_target_item(
        session,
        item=item,
        run=run,
        catalog_item=catalog_item,
        target=target,
        task_id="task-1",
        is_redelivery=False,
    )

    assert claim.excluded_seller_ids == frozenset({"2847093"})


def test_the_legacy_comparison_path_also_excludes_our_storefronts(
    monkeypatch,
) -> None:
    seen: dict[str, object] = {}

    class Gateway:
        def compare(self, url, *, query, excluded_seller_ids):
            seen["excluded_seller_ids"] = excluded_seller_ids
            return PriceComparison(
                seed=_seed(), query=query, offers=[], candidates_scanned=0
            )

    class Guard:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def wait_for_slot(self) -> None:
            return None

        def record_success(self) -> None:
            return None

        def record_failure(self) -> None:
            return None

    monkeypatch.setattr(market_collection, "PromGateway", Gateway)
    monkeypatch.setattr(
        market_collection,
        "require_live_prom_marketplace_collection",
        lambda settings: None,
    )
    monkeypatch.setattr(market_collection, "DistributedCollectionGuard", Guard)

    market_collection._collect_comparison(
        SEED_URL,
        "7L6121253",
        excluded_seller_ids=OWNED_SELLER_IDS,
    )

    assert seen["excluded_seller_ids"] == OWNED_SELLER_IDS


# -- Другий рубіж не знято ---------------------------------------------------


def test_the_downstream_owned_seller_exclusion_is_kept_as_defence_in_depth() -> None:
    """Якщо власна вітрина все ж дійшла до матеріалізації, вона наша, не ринок."""

    role = market_collection._initial_cohort_role(
        SimpleNamespace(
            is_used=False,
            is_kemp=False,
            exclusion_reason=None,
        ),
        is_owned=True,
    )

    assert role.value == "OWNED_STORE"


def test_a_kept_owned_offer_is_still_priced_out_of_the_market_cohort() -> None:
    """Ціна власної вітрини не входить у статистику порівняння."""

    comparison = build_comparison(
        _seed(),
        [_offer(1, "1000", 3912822), _offer(4, "3000", 900001)],
        ComparisonParams(
            query="q",
            threshold=0.55,
            max_sellers=10,
            excluded_seller_ids=OWNED_SELLER_IDS,
        ),
    )

    assert comparison.min_price == Decimal("3000")
