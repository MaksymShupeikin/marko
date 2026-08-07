"""Когда группировка площадки сама по себе является утверждением об OE.

Ревью 2026-08-01: `retrieval_kind` и признак расширения доезжают до наблюдения,
но проверяющий идентичность по-прежнему требует, чтобы номер был **повторён** в
тексте карточки. Продавцы на странице кода детали номер в заголовке не пишут —
замер 2026-07-31 выбросил так 1887 предложений из 2181, — поэтому предложение с
`prom_oe_page` становилось `UNKNOWN` и в цену не попадало.

Здесь проверяется обратное: утверждение источника принимается, но только когда
источник действительно авторитетен, и никогда — вместо противоречия.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from marko.services.offer_identity import (
    OeEvidenceItem,
    OeEvidenceSourceKind,
    OeVerificationStatus,
    SourceAssertion,
    verify_offer_identity,
)
from marko.services.scraper_contract import (
    RETRIEVAL_KIND_PRODUCT_SEED_COMPARISON,
    RETRIEVAL_KIND_PROM_OE_PAGE,
    RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED,
)


_OUR_OE = "1K0615301"
_CAPTURE_SHA = "a" * 64


def _assertion(
    *,
    retrieval_kind: str = RETRIEVAL_KIND_PROM_OE_PAGE,
    queried_oe_norm: str = _OUR_OE,
    capture_sha256: str = _CAPTURE_SHA,
    confidence: Decimal = Decimal("0.95"),
    via_oe_number: str | None = None,
) -> SourceAssertion:
    return SourceAssertion(
        queried_oe_norm=queried_oe_norm,
        retrieval_kind=retrieval_kind,
        capture_sha256=capture_sha256,
        confidence=confidence,
        via_oe_number=via_oe_number,
    )


def _evidence(value: str) -> OeEvidenceItem:
    return OeEvidenceItem(
        raw_value=value,
        normalized_value=value,
        source_kind=OeEvidenceSourceKind.TITLE,
        source_record_id="listing-1",
        raw_capture_id="capture-1",
        raw_content_sha256=_CAPTURE_SHA,
        json_path=None,
        char_span=(0, len(value)),
        context_label="title",
        extractor_method="regex",
        extractor_version="test-v1",
        confidence=Decimal("0.99"),
        correlation_group=f"candidate-text:{value}",
    )


def test_oe_page_without_a_repeated_number_is_verified_by_the_source() -> None:
    """Положительный случай: площадка сама подшила предложение под наш код."""

    verification = verify_offer_identity(
        _OUR_OE,
        (),
        (),
        source_assertion=_assertion(),
    )

    assert verification.status is OeVerificationStatus.VERIFIED_EXACT
    assert verification.verified_matched_oe_norm == _OUR_OE
    assert verification.comparison_identity_key is not None
    assert "OE_ASSERTED_BY_SOURCE_PAGE" in verification.reason_codes


def test_widened_page_is_a_cross_not_an_exact_identity() -> None:
    """Рынок родственного номера — это кросс, а не тот же самый номер.

    Раньше этот тест утверждал ``VERIFIED_CROSS`` для расширения без
    названного номера и без подтверждённого родства — то есть закреплял
    дефект. Кросс обязан назвать, к чему он относится, и опираться на
    доказанное родство; ужесточено по ревью round 2 (F6).
    """

    verification = verify_offer_identity(
        _OUR_OE,
        (),
        (_cross(_OUR_OE, "7L6121253C"),),
        source_assertion=_assertion(
            retrieval_kind=RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED,
            via_oe_number="7L6121253C",
        ),
    )

    assert verification.status is OeVerificationStatus.VERIFIED_CROSS
    assert verification.verified_matched_oe_norm == "7L6121253C"
    assert "OE_ASSERTED_BY_WIDENED_SOURCE_PAGE" in verification.reason_codes


def test_a_generic_search_never_asserts_identity() -> None:
    """Состязательный случай: обычный поиск не является утверждением.

    Иначе любая выдача текстового поиска молча становилась бы подтверждённой
    идентичностью, а это ровно тот дефект, из-за которого 15 улик из 39
    оказались шнеками для мясорубок.
    """

    verification = verify_offer_identity(
        _OUR_OE,
        (),
        (),
        source_assertion=_assertion(
            retrieval_kind=RETRIEVAL_KIND_PRODUCT_SEED_COMPARISON
        ),
    )

    assert verification.status is OeVerificationStatus.UNKNOWN
    assert verification.verified_matched_oe_norm is None


@pytest.mark.parametrize(
    ("kwargs", "why"),
    (
        ({"capture_sha256": ""}, "без неизменяемого захвата утверждать нечем"),
        ({"queried_oe_norm": "9Z9999999"}, "страница не того номера"),
        ({"confidence": Decimal("0")}, "нулевая уверенность не утверждение"),
    ),
)
def test_assertion_is_refused_without_provenance(kwargs, why: str) -> None:
    verification = verify_offer_identity(
        _OUR_OE,
        (),
        (),
        source_assertion=_assertion(**kwargs),
    )

    assert verification.status is OeVerificationStatus.UNKNOWN, why


def test_source_assertion_never_overrides_a_contradiction() -> None:
    """Противоречие в карточке сильнее утверждения источника.

    Площадка могла подшить предложение под наш код и ошибиться; извлечённый из
    карточки чужой номер — это факт о самом товаре, и он остаётся решающим.
    """

    verification = verify_offer_identity(
        _OUR_OE,
        (_evidence("9Z9999999"),),
        (),
        source_assertion=_assertion(),
    )

    assert verification.status is not OeVerificationStatus.VERIFIED_EXACT
    assert verification.verified_matched_oe_norm is None


def test_a_repeated_number_still_verifies_without_any_assertion() -> None:
    """Прежний путь не сломан: номер в карточке подтверждает сам себя."""

    verification = verify_offer_identity(_OUR_OE, (_evidence(_OUR_OE),), ())

    assert verification.status is OeVerificationStatus.VERIFIED_EXACT
    assert "OE_VERIFIED_EXACT" in verification.reason_codes


def test_an_assertion_without_provenance_is_not_recorded_at_all() -> None:
    """Способ извлечения без захвата — заявление без основания.

    База отвергает такую строку (``..._source_assertion_provenance``), поэтому
    запись «наполовину» уронила бы весь сбор, а не только заявление. Захват
    бывает неполным, так что случай не гипотетический.
    """

    assert not _assertion(capture_sha256="   ").authoritative_for(_OUR_OE)
    assert not _assertion(capture_sha256="").authoritative_for(_OUR_OE)


def _cross(target: str, via: str):
    from marko.services.offer_identity import ConfirmedCross

    return ConfirmedCross(
        search_oe_norm=target,
        candidate_oe_norm=via,
        canonical_identity_key=f"cross:{target}:{via}",
        confidence=Decimal("0.90"),
    )


def test_a_widened_page_needs_the_number_it_was_taken_by() -> None:
    """Расширение без названного номера ничего не подтверждает.

    Иначе кросс объявляется, не называя, к чему он относится.
    """

    verification = verify_offer_identity(
        _OUR_OE,
        (),
        (),
        source_assertion=_assertion(
            retrieval_kind=RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED,
            via_oe_number=None,
        ),
    )

    assert verification.status is OeVerificationStatus.UNKNOWN


def test_a_widened_page_needs_a_proven_cross_to_the_via_number() -> None:
    """Запрос по номеру не является доказательством родства.

    Площадка могла подшить рынок под родственный номер ошибочно; без
    подтверждённого кросса target↔via это предположение, а не идентичность.
    """

    verification = verify_offer_identity(
        _OUR_OE,
        (),
        (),
        source_assertion=_assertion(
            retrieval_kind=RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED,
            via_oe_number="7L6121253C",
        ),
    )

    assert verification.status is OeVerificationStatus.UNKNOWN, (
        "без подтверждённого кросса расширение не подтверждает идентичность"
    )


def test_a_widened_page_with_a_proven_cross_is_a_cross() -> None:
    verification = verify_offer_identity(
        _OUR_OE,
        (),
        (_cross(_OUR_OE, "7L6121253C"),),
        source_assertion=_assertion(
            retrieval_kind=RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED,
            via_oe_number="7L6121253C",
        ),
    )

    assert verification.status is OeVerificationStatus.VERIFIED_CROSS
    assert "OE_ASSERTED_BY_WIDENED_SOURCE_PAGE" in verification.reason_codes
    # Честная идентичность: подтверждён номер, по которому взят рынок.
    assert verification.verified_matched_oe_norm == "7L6121253C"
