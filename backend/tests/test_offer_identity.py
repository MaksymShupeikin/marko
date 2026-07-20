from decimal import Decimal
from uuid import uuid4

from marko.services.offer_identity import (
    ConfirmedCross,
    OeVerificationStatus,
    canonical_cross_identity_key,
    evidence_strength,
    extract_oe_evidence,
    persisted_identity_fields_consistent,
    verify_offer_identity,
)


Q = "1K0121251"
Y = "8K0615121"


def _manifest(*, verified: bool = True) -> dict[str, str]:
    return {
        "source_record_id": "prom-product-42",
        "raw_capture_id": str(uuid4()),
        "raw_content_sha256": "a" * 64 if verified else "",
    }


def _verify(raw_offer, *, crosses=(), legacy=False, provenance=True):
    evidence = extract_oe_evidence(
        raw_offer,
        _manifest(verified=provenance),
    )
    return evidence, verify_offer_identity(
        Q,
        evidence,
        crosses,
        legacy_without_reenrichment=legacy,
    )


def test_search_query_alone_can_never_verify_candidate_oe() -> None:
    evidence, result = _verify({"name": "Гальмівні колодки KEMP"})

    assert evidence == ()
    assert result.status == OeVerificationStatus.UNKNOWN
    assert result.verified_matched_oe_norm is None
    assert result.comparison_identity_key is None


def test_structured_exact_oe_verifies_across_different_brand() -> None:
    _, result = _verify({"oe_raw": "1K0 121 251", "brand": "VAG"})

    assert result.status == OeVerificationStatus.VERIFIED_EXACT
    assert result.verified_matched_oe_norm == Q
    assert result.comparison_identity_key == Q
    assert result.confidence == Decimal("0.9900")


def test_unlabeled_sku_is_below_automatic_threshold() -> None:
    _, result = _verify({"sku": "1K0-121-251"})

    assert result.status == OeVerificationStatus.UNKNOWN
    assert result.confidence == Decimal("0.7800")


def test_two_independent_medium_sources_can_verify() -> None:
    _, result = _verify(
        {
            "sku": "1K0-121-251",
            "description": "Каталожний OE: 1K0 121 251 для перевірки",
        }
    )

    assert result.status == OeVerificationStatus.VERIFIED_EXACT
    assert result.confidence >= Decimal("0.90")


def test_duplicate_text_does_not_create_false_independence() -> None:
    text = "OE: 1K0 121 251"
    evidence = extract_oe_evidence(
        {"name": text, "description": text},
        _manifest(),
    )

    assert evidence_strength(Q, evidence) == Decimal("0.9000")


def test_strong_conflicting_oe_is_conflict_not_a_match() -> None:
    _, result = _verify({"oe_raw": Y})

    assert result.status == OeVerificationStatus.CONFLICT
    assert result.verified_matched_oe_norm is None


def test_exact_plus_conflicting_strong_oe_is_ambiguous() -> None:
    _, result = _verify({"oe_raw": [Q, Y]})

    assert result.status == OeVerificationStatus.AMBIGUOUS
    assert result.comparison_identity_key is None


def test_only_confirmed_one_hop_cross_can_verify_cross_identity() -> None:
    cross = ConfirmedCross(
        search_oe_norm=Q,
        candidate_oe_norm=Y,
        canonical_identity_key=canonical_cross_identity_key(Q, Y),
        confidence=Decimal("0.94"),
    )
    _, result = _verify({"oe_raw": Y}, crosses=(cross,))

    assert result.status == OeVerificationStatus.VERIFIED_CROSS
    assert result.verified_matched_oe_norm == Y
    assert result.comparison_identity_key == f"XREF:{Q}|{Y}"
    assert result.confidence == Decimal("0.94")


def test_missing_raw_provenance_cannot_verify() -> None:
    evidence, result = _verify({"oe_raw": Q}, provenance=False)

    assert evidence[0].confidence == 0
    assert result.status == OeVerificationStatus.UNKNOWN


def test_legacy_payload_never_promotes_attributed_oe_without_reenrichment() -> None:
    _, result = _verify({"oe_raw": Q}, legacy=True)

    assert result.status == OeVerificationStatus.LEGACY_UNVERIFIED
    assert result.verified_matched_oe_norm is None


def test_price_year_and_phone_like_values_are_not_oe_evidence() -> None:
    evidence, result = _verify({"name": "Ціна 3800, рік 2024, телефон 0501234567"})

    assert evidence == ()
    assert result.status == OeVerificationStatus.UNKNOWN


def test_punctuation_variant_normalizes_deterministically() -> None:
    _, result = _verify({"oe": "1k0-121/251"})

    assert result.status == OeVerificationStatus.VERIFIED_EXACT
    assert result.verified_matched_oe_norm == Q


def test_persisted_verified_identity_requires_v_in_e_and_consistent_k() -> None:
    from types import SimpleNamespace

    valid = SimpleNamespace(
        search_oe_norm=Q,
        extracted_oe_norms=[Q],
        verified_matched_oe_norm=Q,
        comparison_identity_key=Q,
        oe_verification_status="VERIFIED_EXACT",
        via_cross=False,
        cross_link_id=None,
    )

    assert persisted_identity_fields_consistent(valid) is True
    valid.extracted_oe_norms = [Y]
    assert persisted_identity_fields_consistent(valid) is False
