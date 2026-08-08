from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from marko.services.offer_identity import (
    OE_EXTRACTOR_VERSION,
    ConfirmedCross,
    IdentityNamespace,
    IDENTITY_NAMESPACE_VERSION,
    OeEvidenceSourceKind,
    OeVerificationStatus,
    SourceAssertion,
    automatic_identity_evidence_sufficient,
    canonical_cross_identity_key,
    customer_identity_namespace,
    evidence_strength,
    extract_oe_evidence,
    extract_prom_motors_cross_proposals,
    identity_admission_snapshot_is_current,
    namespace_bound_verification,
    namespace_identity_admission,
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


def _detail_manifest() -> dict[str, str]:
    return {
        "source_record_id": "https://prom.ua/ua/p42-part.html",
        "raw_capture_id": str(uuid4()),
        "raw_content_sha256": "b" * 64,
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


def test_short_numeric_title_oe_is_not_automatic_identity_evidence() -> None:
    """A repeated/free-text six-digit code must stay review-only."""

    query = "123456"
    evidence = extract_oe_evidence(
        {
            "name": "Радіатор OE: 123456",
            "description": "Радіатор OE: 123456",
        },
        _manifest(),
    )

    result = verify_offer_identity(query, evidence)

    assert {item.normalized_value for item in evidence} == {query}
    assert result.status is OeVerificationStatus.UNKNOWN
    assert result.verified_matched_oe_norm is None
    assert result.reason_codes == (
        "OE_SHORT_NUMERIC_REQUIRES_STRUCTURED_PROOF",
    )


def test_short_numeric_structured_oe_remains_verifiable() -> None:
    """The precision gate must not reject a retained structured OE field."""

    query = "123456"
    evidence = extract_oe_evidence({"oe_raw": query}, _manifest())

    result = verify_offer_identity(query, evidence)

    assert result.status is OeVerificationStatus.VERIFIED_EXACT
    assert result.verified_matched_oe_norm == query


def test_structured_exact_oe_verifies_across_different_brand() -> None:
    _, result = _verify({"oe_raw": "1K0 121 251", "brand": "VAG"})

    assert result.status == OeVerificationStatus.VERIFIED_EXACT
    assert result.verified_matched_oe_norm == Q
    assert result.comparison_identity_key == Q
    assert result.confidence == Decimal("0.9900")


def test_parser_part_numbers_reach_identity_evidence_without_becoming_oe_claim():
    evidence = extract_oe_evidence(
        {"part_numbers": [Q]},
        _manifest(),
    )

    assert len(evidence) == 1
    assert evidence[0].source_kind is OeEvidenceSourceKind.CANDIDATE_PART_NUMBER
    assert evidence[0].context_label == "PART_NUMBER"
    # One labelled seller code is useful review evidence, but it is not enough
    # to auto-verify a public OE on its own.
    result = verify_offer_identity(Q, evidence)
    assert result.status is OeVerificationStatus.UNKNOWN


def test_part_number_plus_exact_sku_provides_independent_native_support():
    evidence = extract_oe_evidence(
        {"part_numbers": [Q], "sku": Q},
        _manifest(),
    )

    result = verify_offer_identity(Q, evidence)
    assert result.status is OeVerificationStatus.VERIFIED_EXACT
    assert result.verified_matched_oe_norm == Q
    # Discovery may expose this as a useful exact review hit, but pricing must
    # not mistake two copies of one seller namespace for an OE assertion.
    assert not automatic_identity_evidence_sufficient(
        result,
        evidence,
        require_oe_namespace=True,
    )


def test_title_only_exact_oe_is_not_automatic_pricing_identity() -> None:
    """The broad verifier may review a title hit, but pricing must abstain."""

    evidence = extract_oe_evidence(
        {"name": "Радіатор OE: 1K0 121 251"},
        _manifest(),
    )
    result = verify_offer_identity(Q, evidence)

    assert result.status is OeVerificationStatus.VERIFIED_EXACT
    assert not automatic_identity_evidence_sufficient(result, evidence)


def test_structured_exact_oe_is_eligible_for_automatic_identity() -> None:
    evidence = extract_oe_evidence({"oe_raw": Q}, _manifest())
    result = verify_offer_identity(Q, evidence)

    assert result.status is OeVerificationStatus.VERIFIED_EXACT
    assert automatic_identity_evidence_sufficient(result, evidence)
    assert automatic_identity_evidence_sufficient(
        result,
        evidence,
        require_oe_namespace=True,
    )


def test_mpn_exact_is_namespaced_and_oe_label_alone_cannot_price() -> None:
    seed = SimpleNamespace(
        identity_status="MPN_ONLY",
        oe_norm="",
        mpn_norm="313452",
        part_numbers_norm=(),
    )
    namespace = customer_identity_namespace(seed)
    assert namespace is IdentityNamespace.MPN
    evidence = extract_oe_evidence({"oe_raw": "313452"}, _manifest())
    result = namespace_bound_verification(
        verify_offer_identity("313452", evidence, allow_short_numeric_native=True),
        namespace,
    )
    assert result.status is OeVerificationStatus.VERIFIED_EXACT
    assert result.comparison_identity_key == "MPN:313452"
    base = automatic_identity_evidence_sufficient(result, evidence)
    admitted, reason = namespace_identity_admission(
        seed_namespace=namespace,
        verification=result,
        evidence_items=evidence,
        base_automatic_evidence=base,
    )
    assert admitted is False
    assert reason == "MPN_NAMESPACE_REQUIRES_CONFIRMED_OE"


def test_mpn_native_candidate_evidence_stays_review_only_without_oe() -> None:
    seed = SimpleNamespace(
        identity_status="MPN_ONLY",
        oe_norm="",
        mpn_norm="313452",
        part_numbers_norm=(),
    )
    namespace = customer_identity_namespace(seed)
    evidence = extract_oe_evidence(
        {"mpn": "313452", "sku": "313452"},
        _manifest(),
    )
    result = namespace_bound_verification(
        verify_offer_identity(
            "313452",
            evidence,
            allow_short_numeric_native=True,
        ),
        namespace,
    )
    base = automatic_identity_evidence_sufficient(result, evidence)
    admitted, reason = namespace_identity_admission(
        seed_namespace=namespace,
        verification=result,
        evidence_items=evidence,
        base_automatic_evidence=base,
    )
    assert admitted is False
    assert reason == "MPN_NAMESPACE_REQUIRES_CONFIRMED_OE"
    assert result.comparison_identity_key == "MPN:313452"


def test_namespace_snapshot_rejects_raw_mpn_key_or_missing_proof() -> None:
    admission = {
        "automatic_evidence_sufficient": True,
        "namespace_version": IDENTITY_NAMESPACE_VERSION,
        "seed_identity_namespace": "MPN",
        "verified_identity_namespace": "MPN",
        "comparison_identity_key": "MPN:313452",
    }
    assert not identity_admission_snapshot_is_current(
        admission,
        expected_identity_key="MPN:313452",
    )
    admission["comparison_identity_key"] = "313452"
    assert not identity_admission_snapshot_is_current(admission)


def test_mpn_cross_snapshot_cannot_be_revived_as_automatic() -> None:
    assert not identity_admission_snapshot_is_current(
        {
            "automatic_evidence_sufficient": True,
            "namespace_version": IDENTITY_NAMESPACE_VERSION,
            "seed_identity_namespace": "MPN",
            "verified_identity_namespace": "CROSS",
            "comparison_identity_key": "XREF:313452|Y",
        }
    )


def test_authoritative_prom_grouping_can_supply_identity_without_card_oe() -> None:
    result = verify_offer_identity(
        Q,
        (),
        source_assertion=SourceAssertion(
            queried_oe_norm=Q,
            retrieval_kind="prom_oe_page",
            capture_sha256="a" * 64,
            confidence=Decimal("0.90"),
        ),
    )

    assert result.status is OeVerificationStatus.VERIFIED_EXACT
    assert automatic_identity_evidence_sufficient(
        result,
        (),
        authoritative_identity=True,
    )


def test_private_kemp_query_cannot_be_verified_by_source_assertion() -> None:
    result = verify_offer_identity(
        "776414",
        (),
        source_assertion=SourceAssertion(
            queried_oe_norm="776414",
            retrieval_kind="prom_oe_page",
            capture_sha256="a" * 64,
            confidence=Decimal("0.99"),
        ),
    )

    assert result.status is OeVerificationStatus.UNKNOWN
    assert result.reason_codes == ("OE_PRIVATE_CATALOG_CODE_NOT_PUBLIC",)


def test_structured_long_numeric_oe_is_not_mistaken_for_a_phone() -> None:
    query = "34211157046"
    evidence = extract_oe_evidence({"oe_raw": query}, _manifest())
    result = verify_offer_identity(query, evidence)

    assert {item.normalized_value for item in evidence} == {query}
    assert result.status == OeVerificationStatus.VERIFIED_EXACT


def test_labeled_cross_number_removes_manufacturer_prefix_only() -> None:
    evidence = extract_oe_evidence(
        {
            "characteristics": [
                {
                    "name": "Кросс-номери",
                    "value": (
                        "BMW 34211157046; AUTOFREN SEINSA D42387A; "
                        "MERCEDES A 000 090 26 51"
                    ),
                }
            ]
        },
        _manifest(),
    )

    assert {item.normalized_value for item in evidence} == {
        "34211157046",
        "D42387A",
        # Multi-token grouped identifier is intentionally not collapsed to 51.
        "A0000902651",
    }


def test_structured_complete_identifiers_are_never_concatenated() -> None:
    evidence = extract_oe_evidence(
        {
            "characteristics": [
                {
                    "name": "Кросс-номери",
                    "value": (
                        "06A121031C 06B121011H+06B121019D\n"
                        "MERCEDES A 000 090 26 51"
                    ),
                }
            ]
        },
        _manifest(),
    )

    assert {item.normalized_value for item in evidence} == {
        "06A121031C",
        "06B121011H",
        "06B121019D",
        "A0000902651",
    }
    assert {
        item.source_kind for item in evidence
    } == {OeEvidenceSourceKind.COMPATIBLE_REFERENCE_LIST}


def test_confirmed_cross_in_compatible_reference_list_ignores_other_references() -> None:
    cross = ConfirmedCross(
        search_oe_norm=Q,
        candidate_oe_norm=Y,
        canonical_identity_key=canonical_cross_identity_key(Q, Y),
        confidence=Decimal("0.94"),
    )
    evidence = extract_oe_evidence(
        {
            "mpn": "AFTERMARKET42",
            "characteristics": [
                {
                    "name": "Кросс-номери",
                    "value": f"{Y}; 7701044227; 99458402",
                }
            ],
        },
        _manifest(),
    )
    result = verify_offer_identity(Q, evidence, (cross,))

    assert result.status == OeVerificationStatus.VERIFIED_CROSS
    assert result.verified_matched_oe_norm == Y
    assert result.reason_codes == (
        "OE_VERIFIED_COMPATIBLE_REFERENCE_CONFIRMED_CROSS",
    )


def test_exact_oe_in_compatible_reference_list_survives_supplier_mpn() -> None:
    evidence = extract_oe_evidence(
        {
            "mpn": "AC830088",
            "characteristics": [
                {
                    "name": "Кросс-номери",
                    "value": f"{Q}; 7701044227; 99458402",
                }
            ],
        },
        _manifest(),
    )
    result = verify_offer_identity(Q, evidence)

    assert result.status == OeVerificationStatus.VERIFIED_EXACT
    assert result.verified_matched_oe_norm == Q
    assert result.reason_codes == ("OE_VERIFIED_COMPATIBLE_REFERENCE_EXACT",)


def test_generic_oe_label_with_two_values_remains_ambiguous() -> None:
    cross = ConfirmedCross(
        search_oe_norm=Q,
        candidate_oe_norm=Y,
        canonical_identity_key=canonical_cross_identity_key(Q, Y),
        confidence=Decimal("0.94"),
    )
    evidence = extract_oe_evidence(
        {
            "characteristics": [
                {"name": "OE", "value": f"{Y}; 7701044227"}
            ]
        },
        _manifest(),
    )
    result = verify_offer_identity(Q, evidence, (cross,))

    assert result.status == OeVerificationStatus.AMBIGUOUS
    assert result.verified_matched_oe_norm is None


def test_compatible_list_cannot_override_conflicting_structured_oe() -> None:
    cross = ConfirmedCross(
        search_oe_norm=Q,
        candidate_oe_norm=Y,
        canonical_identity_key=canonical_cross_identity_key(Q, Y),
        confidence=Decimal("0.94"),
    )
    evidence = extract_oe_evidence(
        {
            "oe_raw": "7701044227",
            "characteristics": [
                {"name": "Кросс-номери", "value": Y}
            ],
        },
        _manifest(),
    )
    result = verify_offer_identity(Q, evidence, (cross,))

    assert result.status == OeVerificationStatus.AMBIGUOUS
    assert result.verified_matched_oe_norm is None


def test_verified_detail_motors_code_is_candidate_native_identity() -> None:
    detail_manifest = _detail_manifest()
    evidence = extract_oe_evidence(
        {
            "detail_evidence": {
                "field_sources": {},
                "motors": {
                    "normalized_part_code": Q,
                    "compatible_oe_numbers": [Q, Y],
                },
            }
        },
        _manifest(),
        verified_detail_manifest=detail_manifest,
    )
    result = verify_offer_identity(Q, evidence)

    assert {item.normalized_value for item in evidence} == {Q, Y}
    assert {
        item.source_kind for item in evidence
    } == {
        OeEvidenceSourceKind.DETAIL_PAGE,
        OeEvidenceSourceKind.PLATFORM_COMPATIBLE_REFERENCE_LIST,
    }
    assert {item.raw_content_sha256 for item in evidence} == {"b" * 64}
    assert result.status == OeVerificationStatus.VERIFIED_EXACT
    assert result.verified_matched_oe_norm == Q
    assert result.reason_codes == ("OE_VERIFIED_DETAIL_NATIVE_EXACT",)


def test_unverified_detail_metadata_can_never_supply_identity() -> None:
    raw_offer = {
        "detail_evidence": {
            "field_sources": {},
            "motors": {"normalized_part_code": Q},
        }
    }
    evidence = extract_oe_evidence(raw_offer, _manifest())
    result = verify_offer_identity(Q, evidence)

    assert evidence == ()
    assert result.status == OeVerificationStatus.UNKNOWN


def test_detail_compatible_numbers_do_not_masquerade_as_candidate_code() -> None:
    evidence = extract_oe_evidence(
        {
            "detail_evidence": {
                "field_sources": {},
                "motors": {
                    "normalized_part_code": Y,
                    "compatible_oe_numbers": [Q, Y],
                },
            }
        },
        _manifest(),
        verified_detail_manifest=_detail_manifest(),
    )
    result = verify_offer_identity(Q, evidence)

    assert {item.normalized_value for item in evidence} == {Q, Y}
    assert result.status == OeVerificationStatus.AMBIGUOUS
    assert result.verified_matched_oe_norm is None


def test_confirmed_xls_cross_bridges_verified_platform_compatibility_list() -> None:
    supplier_code = "DAC006TT"
    cross = ConfirmedCross(
        search_oe_norm=Q,
        candidate_oe_norm=Y,
        canonical_identity_key=canonical_cross_identity_key(Q, Y),
        confidence=Decimal("0.94"),
    )
    evidence = extract_oe_evidence(
        {
            "sku": supplier_code,
            "mpn": supplier_code,
            "characteristics": [
                {"name": "Код запчастини", "value": supplier_code}
            ],
            "detail_evidence": {
                "field_sources": {},
                "motors": {
                    "normalized_part_code": supplier_code,
                    "compatible_oe_numbers": [Q, Y, "1440094280"],
                },
            },
        },
        _manifest(),
        verified_detail_manifest=_detail_manifest(),
    )
    result = verify_offer_identity(Q, evidence, (cross,))

    assert result.status == OeVerificationStatus.VERIFIED_CROSS
    assert result.verified_matched_oe_norm == Y
    assert result.comparison_identity_key == canonical_cross_identity_key(Q, Y)
    assert result.reason_codes == (
        "OE_VERIFIED_PLATFORM_COMPATIBILITY_BRIDGE",
    )
    assert result.confidence == Decimal("0.94")


def test_confirmed_cross_accepts_platform_cross_without_repeating_seed() -> None:
    supplier_code = "MEYLE1005250038"
    cross = ConfirmedCross(
        search_oe_norm=Q,
        candidate_oe_norm=Y,
        canonical_identity_key=canonical_cross_identity_key(Q, Y),
        confidence=Decimal("0.94"),
    )
    evidence = extract_oe_evidence(
        {
            "mpn": supplier_code,
            "detail_evidence": {
                "field_sources": {},
                "motors": {
                    "normalized_part_code": supplier_code,
                    "compatible_oe_numbers": [Y, "7D0611702B"],
                },
            },
        },
        _manifest(),
        verified_detail_manifest=_detail_manifest(),
    )
    result = verify_offer_identity(Q, evidence, (cross,))

    assert result.status == OeVerificationStatus.VERIFIED_CROSS
    assert result.verified_matched_oe_norm == Y
    assert result.reason_codes == (
        "OE_VERIFIED_PLATFORM_COMPATIBILITY_BRIDGE",
    )


def test_platform_exact_seed_is_accepted_only_on_confirmed_acquisition_route() -> None:
    supplier_code = "06A121012X"
    cross = ConfirmedCross(
        search_oe_norm=Q,
        candidate_oe_norm=Y,
        canonical_identity_key=canonical_cross_identity_key(Q, Y),
        confidence=Decimal("0.94"),
    )
    raw_offer = {
        "detail_evidence": {
            "field_sources": {},
            "motors": {
                "normalized_part_code": supplier_code,
                "compatible_oe_numbers": [Q, "06A121011H"],
            },
        }
    }
    evidence = extract_oe_evidence(
        raw_offer,
        _manifest(),
        verified_detail_manifest=_detail_manifest(),
    )

    without_confirmed_route = verify_offer_identity(Q, evidence)
    with_confirmed_route = verify_offer_identity(Q, evidence, (cross,))

    assert without_confirmed_route.status == OeVerificationStatus.AMBIGUOUS
    assert with_confirmed_route.status == OeVerificationStatus.VERIFIED_EXACT
    assert with_confirmed_route.verified_matched_oe_norm == Q
    assert with_confirmed_route.reason_codes == (
        "OE_VERIFIED_PLATFORM_EXACT_ON_CONFIRMED_ROUTE",
    )


def test_platform_compatibility_bridge_requires_confirmed_cross() -> None:
    evidence = extract_oe_evidence(
        {
            "detail_evidence": {
                "field_sources": {},
                "motors": {
                    "normalized_part_code": "DAC006TT",
                    "compatible_oe_numbers": [Q, Y],
                },
            }
        },
        _manifest(),
        verified_detail_manifest=_detail_manifest(),
    )
    result = verify_offer_identity(Q, evidence)

    assert result.status == OeVerificationStatus.AMBIGUOUS
    assert result.verified_matched_oe_norm is None


def test_platform_compatibility_bridge_cannot_override_structured_oe_conflict() -> None:
    cross = ConfirmedCross(
        search_oe_norm=Q,
        candidate_oe_norm=Y,
        canonical_identity_key=canonical_cross_identity_key(Q, Y),
        confidence=Decimal("0.94"),
    )
    evidence = extract_oe_evidence(
        {
            "oe_raw": "OTHER123",
            "detail_evidence": {
                "field_sources": {},
                "motors": {
                    "normalized_part_code": "DAC006TT",
                    "compatible_oe_numbers": [Q, Y],
                },
            },
        },
        _manifest(),
        verified_detail_manifest=_detail_manifest(),
    )
    result = verify_offer_identity(Q, evidence, (cross,))

    assert result.status == OeVerificationStatus.AMBIGUOUS
    assert result.verified_matched_oe_norm is None


def test_verified_detail_compatible_number_creates_review_only_proposal() -> None:
    raw_offer = {
        "detail_evidence": {
            "field_sources": {},
            "motors": {
                "normalized_part_code": Y,
                "compatible_oe_numbers": [Q, Y],
            },
        }
    }
    detail_manifest = _detail_manifest()
    evidence = extract_oe_evidence(
        raw_offer,
        _manifest(),
        verified_detail_manifest=detail_manifest,
    )
    proposals = extract_prom_motors_cross_proposals(
        raw_offer,
        detail_manifest,
        search_oe_norm=Q,
    )
    result = verify_offer_identity(Q, evidence, (), proposals)

    assert len(proposals) == 1
    assert proposals[0].search_oe_norm == Q
    assert proposals[0].candidate_oe_norm == Y
    assert proposals[0].automatic_identity_eligible is False
    assert result.status == OeVerificationStatus.UNKNOWN
    assert result.verified_matched_oe_norm is None
    assert result.reason_codes == ("OE_CROSS_AWAITING_CONFIRMATION",)


def test_unverified_or_irrelevant_motors_cross_never_creates_proposal() -> None:
    raw_offer = {
        "detail_evidence": {
            "motors": {
                "normalized_part_code": Y,
                "compatible_oe_numbers": ["OTHER123"],
            }
        }
    }

    assert not extract_prom_motors_cross_proposals(
        raw_offer,
        None,
        search_oe_norm=Q,
    )
    assert not extract_prom_motors_cross_proposals(
        raw_offer,
        _detail_manifest(),
        search_oe_norm=Q,
    )


def test_confirmed_cross_can_bind_verified_detail_candidate_code() -> None:
    cross = ConfirmedCross(
        search_oe_norm=Q,
        candidate_oe_norm=Y,
        canonical_identity_key=canonical_cross_identity_key(Q, Y),
        confidence=Decimal("0.94"),
    )
    evidence = extract_oe_evidence(
        {
            "detail_evidence": {
                "field_sources": {},
                "motors": {"normalized_part_code": Y},
            }
        },
        _manifest(),
        verified_detail_manifest=_detail_manifest(),
    )
    result = verify_offer_identity(Q, evidence, (cross,))

    assert result.status == OeVerificationStatus.VERIFIED_CROSS
    assert result.verified_matched_oe_norm == Y
    assert result.confidence == Decimal("0.94")


def test_verified_detail_native_cross_outranks_compatible_reference_list() -> None:
    cross = ConfirmedCross(
        search_oe_norm=Q,
        candidate_oe_norm=Y,
        canonical_identity_key=canonical_cross_identity_key(Q, Y),
        confidence=Decimal("0.94"),
    )
    evidence = extract_oe_evidence(
        {
            "oe_raw": [Y, "7701044227", "99458402"],
            "detail_evidence": {
                "field_sources": {},
                "motors": {"normalized_part_code": Y},
            },
        },
        _manifest(),
        verified_detail_manifest=_detail_manifest(),
    )
    result = verify_offer_identity(Q, evidence, (cross,))

    assert result.status == OeVerificationStatus.VERIFIED_CROSS
    assert result.verified_matched_oe_norm == Y
    assert set(result.extracted_oe_norms) == {Y, "7701044227", "99458402"}
    assert result.reason_codes == (
        "OE_VERIFIED_DETAIL_NATIVE_CONFIRMED_CROSS",
    )


def test_detail_native_code_cannot_override_exact_query_conflict() -> None:
    cross = ConfirmedCross(
        search_oe_norm=Q,
        candidate_oe_norm=Y,
        canonical_identity_key=canonical_cross_identity_key(Q, Y),
        confidence=Decimal("0.94"),
    )
    evidence = extract_oe_evidence(
        {
            "oe_raw": Q,
            "detail_evidence": {
                "field_sources": {},
                "motors": {"normalized_part_code": Y},
            },
        },
        _manifest(),
        verified_detail_manifest=_detail_manifest(),
    )
    result = verify_offer_identity(Q, evidence, (cross,))

    assert result.status == OeVerificationStatus.AMBIGUOUS
    assert result.verified_matched_oe_norm is None


def test_detail_mpn_is_supporting_evidence_not_an_oe_claim() -> None:
    evidence = extract_oe_evidence(
        {
            "mpn": Q,
            "detail_evidence": {
                "field_sources": {"mpn": "$.result.product.identifiers.mpn"}
            },
        },
        _manifest(),
        verified_detail_manifest=_detail_manifest(),
    )
    result = verify_offer_identity(Q, evidence)

    assert evidence[0].source_kind == (
        OeEvidenceSourceKind.MANUFACTURER_PART_NUMBER
    )
    assert evidence[0].confidence == Decimal("0.88")
    assert evidence[0].raw_content_sha256 == "b" * 64
    assert result.status == OeVerificationStatus.UNKNOWN


def test_detail_derived_characteristic_never_inherits_listing_provenance() -> None:
    raw_offer = {
        "characteristics": [{"name": "OE", "value": Q}],
        "detail_evidence": {
            "field_sources": {
                "characteristics": "$.result.product.attributes[*].values[*].value"
            }
        },
    }
    unverified = extract_oe_evidence(raw_offer, _manifest())
    verified = extract_oe_evidence(
        raw_offer,
        _manifest(),
        verified_detail_manifest=_detail_manifest(),
    )

    assert unverified[0].confidence == 0
    assert unverified[0].raw_content_sha256 == ""
    assert verified[0].confidence == Decimal("0.97")
    assert verified[0].raw_content_sha256 == "b" * 64


def test_unlabeled_sku_is_below_automatic_threshold() -> None:
    _, result = _verify({"sku": "1K0-121-251"})

    assert result.status == OeVerificationStatus.UNKNOWN
    assert result.confidence == Decimal("0.7800")


def test_generic_part_code_characteristic_is_not_strong_oe_by_itself() -> None:
    evidence, result = _verify(
        {
            "characteristics": [
                {"name": "Код запчастини", "value": "1K0 121 251"}
            ]
        }
    )

    assert evidence[0].confidence == Decimal("0.88")
    assert evidence[0].source_kind == OeEvidenceSourceKind.CANDIDATE_PART_NUMBER
    assert result.status == OeVerificationStatus.UNKNOWN
    assert result.confidence == Decimal("0.8800")


def test_generic_part_code_plus_sku_is_independently_supported() -> None:
    evidence, result = _verify(
        {
            "sku": "1K0-121-251",
            "characteristics": [
                {"name": "Код запчастини", "value": "1K0 121 251, 77643"}
            ],
        }
    )

    assert result.status == OeVerificationStatus.VERIFIED_EXACT
    assert result.verified_matched_oe_norm == Q
    assert result.confidence >= Decimal("0.90")
    assert "77643" not in {item.normalized_value for item in evidence}


def test_explicit_cross_number_characteristic_is_strong_evidence() -> None:
    evidence, result = _verify(
        {
            "characteristics": [
                {"name": "Кросс-номери", "value": "1K0 121 251"}
            ]
        }
    )

    assert evidence[0].confidence == Decimal("0.97")
    assert result.status == OeVerificationStatus.VERIFIED_EXACT


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


def test_legacy_private_kemp_identity_cannot_be_revived_from_consistent_fields() -> None:
    from types import SimpleNamespace

    legacy = SimpleNamespace(
        search_oe_norm="776414",
        extracted_oe_norms=["776414"],
        verified_matched_oe_norm="776414",
        comparison_identity_key="776414",
        oe_verification_status="VERIFIED_EXACT",
        via_cross=False,
        cross_link_id=None,
    )

    assert persisted_identity_fields_consistent(legacy) is False


def test_mpn_namespace_cannot_be_revived_for_calibration_from_legacy_fields() -> None:
    from types import SimpleNamespace

    legacy = SimpleNamespace(
        search_oe_norm="313452",
        extracted_oe_norms=["313452"],
        verified_matched_oe_norm="313452",
        comparison_identity_key="MPN:313452",
        oe_verification_status="VERIFIED_EXACT",
        via_cross=False,
        cross_link_id=None,
    )

    assert persisted_identity_fields_consistent(legacy) is False


# The label a Prom card actually prints over its original numbers.  Measured on
# the customer's own storefront export of 2026-08-08: 11916 rows across 1316
# cards sit under «Оригінальні номери», and the same platform serves the Russian
# and abbreviated spellings.  Every one of these returned no confidence, so the
# whole characteristic was skipped and the strongest identity a competitor's
# card carries never became evidence at all.
@pytest.mark.parametrize(
    "label",
    [
        "Оригінальні номери",
        "Оригинальные номера",
        "Оригінальний номер",
        "Оригинальный номер",
        "Номер оригіналу",
        "Номера оригинала",
        "Оригінальний артикул",
        # Cyrillic ``ОЕ``.  The set carried Latin ``OE`` + Cyrillic ``НОМЕР``
        # (codepoints 0x4f 0x45 0x41d…), which a Cyrillic ``ОЕ`` never equals.
        "ОЕ номер",
        "OEM номери",
    ],
)
def test_an_original_number_label_is_read_in_the_spellings_prom_prints(label) -> None:
    """A spelling is not a trust tier.

    Whatever ``OE`` is worth on a candidate card, the same field spelled out in
    words is worth the same: it is one field under two names.  Changing what an
    OE-labelled list may do is a separate decision that would apply to ``OE``
    too.
    """

    evidence = extract_oe_evidence(
        {"characteristics": [{"name": label, "value": f"{Q}, {Y}"}]},
        _manifest(),
    )

    assert {item.normalized_value for item in evidence} == {Q, Y}
    assert {item.source_kind for item in evidence} == {
        OeEvidenceSourceKind.LABELED_CHARACTERISTIC
    }
    assert {item.confidence for item in evidence} == {Decimal("0.97")}


def test_an_original_number_label_is_not_a_compatible_reference_list() -> None:
    """«Крос-номери» describes a cross graph and stays behind the confirmed-cross
    boundary. «Оригінальні номери» names the part itself, like ``OE``."""

    original = extract_oe_evidence(
        {"characteristics": [{"name": "Оригінальні номери", "value": Q}]},
        _manifest(),
    )
    cross = extract_oe_evidence(
        {"characteristics": [{"name": "Крос-номери", "value": Q}]},
        _manifest(),
    )

    assert original[0].source_kind is OeEvidenceSourceKind.LABELED_CHARACTERISTIC
    assert cross[0].source_kind is OeEvidenceSourceKind.COMPATIBLE_REFERENCE_LIST


@pytest.mark.parametrize(
    "label",
    [
        "Не оригінальний номер",
        "Оригінальний номер аналога",
        "Сумісні моделі",
        "Замінник оригіналу",
    ],
)
def test_widening_the_label_set_does_not_swallow_a_qualified_claim(label) -> None:
    """Exact match, not substring: three of these contain «оригінал» and none
    of them says this number is the part's original."""

    evidence = extract_oe_evidence(
        {"characteristics": [{"name": label, "value": Q}]},
        _manifest(),
    )

    assert evidence == ()


def test_widening_the_label_set_moved_the_extractor_boundary() -> None:
    """Persisted observations carry the version that produced them.

    ``oe_reenrichment`` sweeps on ``oe_extractor_version != OE_EXTRACTOR_VERSION``
    (``services/oe_reenrichment.py:539``), so an extractor that now reads a
    label it used to skip has to move the boundary — otherwise every offer
    already stored keeps the verdict it got while the field was invisible.
    """

    assert OE_EXTRACTOR_VERSION == "oe-extractor-v6"
