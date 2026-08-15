"""Commercial offer traps cannot silently establish the price floor."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from marko.services.market_collection import _json_safe
from marko.services.offer_integrity import (
    OfferIntegrityStatus,
    assess_offer_integrity,
    build_offer_amount_context,
)


@pytest.mark.parametrize(
    ("description", "reason"),
    (
        ("Цена по запросу, пишите менеджеру", "PRICE_ON_REQUEST"),
        ("Б/у деталь с разборки", "USED_OR_REFURBISHED"),
        ("Услуга по ремонту вашего агрегата", "SERVICE_NOT_PART"),
    ),
)
def test_explicitly_unusable_offer_is_rejected(description: str, reason: str) -> None:
    assessment = assess_offer_integrity(
        title="Автодеталь",
        description=description,
        is_available=True,
        detail_evidence_safe=True,
    )

    assert assessment.status is OfferIntegrityStatus.REJECT
    assert reason in assessment.reason_codes


@pytest.mark.parametrize(
    ("description", "reason"),
    (
        ("Цена от 300 грн, зависит от варианта", "STARTING_OR_VARIANT_PRICE"),
        ("Цена указана как залог за обменный фонд", "DEPOSIT_OR_EXCHANGE_AMOUNT"),
        ("Только оптом, минимальный заказ 10 шт", "WHOLESALE_OR_MINIMUM_QUANTITY"),
        ("Некомплект, без датчика", "DAMAGED_OR_INCOMPLETE"),
        ("Отправка только по предоплате", "PREPAYMENT_OR_PREORDER"),
        ("Оформляем предзаказ, поставка 7 дней", "PREPAYMENT_OR_PREORDER"),
        ("Товар під замовлення, термін 5 днів", "MADE_TO_ORDER"),
        ("Под заказ, поставка из Европы", "MADE_TO_ORDER"),
        ("Возможен торг у капота", "BARGAIN_OR_AUCTION"),
        ("Продажа через аукцион", "BARGAIN_OR_AUCTION"),
    ),
)
def test_conditionally_usable_offer_requires_review(
    description: str,
    reason: str,
) -> None:
    assessment = assess_offer_integrity(
        title="Новая автодеталь",
        description=description,
        is_available=True,
        detail_evidence_safe=True,
    )

    assert assessment.status is OfferIntegrityStatus.MANUAL_REVIEW
    assert reason in assessment.reason_codes


@pytest.mark.parametrize(
    "description",
    (
        "Продаётся на запчасти, состояние не проверялось",
        "Продається на запчастини",
        "Двигатель-донор, снят с авто",
        "Нерабочий компрессор кондиционера",
        "Selling for parts only",
    ),
)
def test_parts_donor_offer_is_rejected(description: str) -> None:
    assessment = assess_offer_integrity(
        title="Автодеталь",
        description=description,
        is_available=True,
        detail_evidence_safe=True,
    )

    assert assessment.status is OfferIntegrityStatus.REJECT
    assert "PARTS_DONOR" in assessment.reason_codes


def test_nonworking_time_phrase_is_not_a_parts_donor() -> None:
    # «В нерабочее время» говорит о графике звонков, а не о детали: словосочетание
    # не должно превращать нормальную карточку в донора.
    assessment = assess_offer_integrity(
        title="Новый насос",
        description="В нерабочее время и в нерабочие дни не звоните",
        is_available=True,
        detail_evidence_safe=True,
    )

    assert assessment.status is OfferIntegrityStatus.PASS


def test_no_prepayment_required_phrase_passes() -> None:
    # «Без предоплаты» — обычное наложенное-платёжное предложение, а не ловушка.
    assessment = assess_offer_integrity(
        title="Новый радиатор",
        description="Наложенный платеж без предоплаты, отправка сегодня",
        is_available=True,
        detail_evidence_safe=True,
    )

    assert assessment.status is OfferIntegrityStatus.PASS


@pytest.mark.parametrize(
    ("description", "measure_unit"),
    (
        ("Цена за штуку, продаются только парой", "пара"),
        ("Ціна за штуку", "компл."),
        ("Цена за комплект", "шт."),
    ),
)
def test_unit_ambiguity_requires_review(
    description: str,
    measure_unit: str,
) -> None:
    assessment = assess_offer_integrity(
        title="Новая автодеталь",
        description=description,
        measure_unit=measure_unit,
        is_available=True,
        detail_evidence_safe=True,
    )

    assert assessment.status is OfferIntegrityStatus.MANUAL_REVIEW
    assert "UNIT_AMBIGUITY" in assessment.reason_codes


def test_matching_price_unit_phrase_passes() -> None:
    assessment = assess_offer_integrity(
        title="Новая автодеталь",
        description="Цена за пару",
        measure_unit="пара",
        is_available=True,
        detail_evidence_safe=True,
    )

    assert assessment.status is OfferIntegrityStatus.PASS


def test_regular_new_available_offer_passes() -> None:
    assessment = assess_offer_integrity(
        title="Новый радиатор двигателя Nissens",
        description="Цена за одну штуку, в наличии",
        condition="new",
        is_available=True,
        detail_evidence_safe=True,
    )

    assert assessment.status is OfferIntegrityStatus.PASS


def test_lone_300_floor_against_1000_requires_review() -> None:
    base = assess_offer_integrity(
        title="Новая автодеталь",
        is_available=True,
        detail_evidence_safe=True,
    )
    context = build_offer_amount_context(
        displayed_amount="300",
        currency="UAH",
        customer_amount="700",
        peer_offers=(("1000", "seller-b"), ("1300", "seller-c")),
        assessment=base,
    )

    assert context.floor_gap_ratio == Decimal("0.3")
    assert context.assessment.status is OfferIntegrityStatus.MANUAL_REVIEW
    assert "SINGLE_LISTING_FLOOR_GAP" in context.assessment.reason_codes


def test_normal_floor_gap_passes_and_independent_equal_floor_corroborates() -> None:
    base = assess_offer_integrity(
        title="Новая автодеталь",
        is_available=True,
        detail_evidence_safe=True,
    )
    normal = build_offer_amount_context(
        displayed_amount="1000",
        currency="UAH",
        peer_offers=(("1100", "seller-b"), ("1300", "seller-c")),
        assessment=base,
    )
    corroborated = build_offer_amount_context(
        displayed_amount="300",
        currency="UAH",
        peer_offers=(("300", "seller-b"), ("1000", "seller-c")),
        assessment=base,
    )

    assert normal.assessment.status is OfferIntegrityStatus.PASS
    assert corroborated.assessment.status is OfferIntegrityStatus.PASS


def test_observation_json_payload_can_contain_decimal_integrity_context() -> None:
    assessment = assess_offer_integrity(
        title="Новый радиатор",
        description="Цена за одну штуку",
        is_available=True,
        detail_evidence_safe=True,
    )
    payload = _json_safe(
        {
            "offer_integrity": assessment.as_dict(),
            "semantic_gate": {
                "status": "PRICING_EVIDENCE",
                "score": Decimal("0.9800"),
            },
            "source_confidence_factors": {"listing_identity": Decimal("1")},
        }
    )

    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    decoded = json.loads(encoded)
    assert decoded["semantic_gate"]["score"] == "0.9800"
    assert decoded["source_confidence_factors"]["listing_identity"] == "1"
    assert decoded["offer_integrity"]["status"] == "PASS"
