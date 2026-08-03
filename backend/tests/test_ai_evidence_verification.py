"""Verifier: binding, exact citation, our normalization, bounded application.

The verifier is provider-independent, so these tests construct extraction
results directly and never involve a provider at all.  Builders are shared with
``test_ai_evidence_extraction`` (the ``tests`` directory is on ``pythonpath``).
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace
import uuid

import pytest

from marko.services.ai_evidence_extraction import (
    AiEvidenceExtractionResult,
    AiEvidenceOutcome,
    EvidenceFieldName,
    EvidenceSourceKind,
    FindingState,
    assert_no_authority_fields,
    build_extraction_input,
)
from marko.services.ai_evidence_verification import (
    AI_EVIDENCE_FILL_REASON_CODE,
    AI_FILLABLE_DIMENSIONS,
    BindingFailure,
    CitationRefusal,
    FillRefusal,
    ReportStatus,
    VerificationStatus,
    propose_evidence_fill,
    verify_ai_evidence,
)
from metis.pricing import (
    COMPARABILITY_POLICY_HASH,
    COMPARABILITY_POLICY_ID,
    ComparisonEvidence,
    DimensionEvidence,
    EvidenceState,
    HardGateResult,
    SellerIdentityEvidence,
    SourceProvenance,
)

from test_ai_evidence_extraction import (
    DESCRIPTION,
    TITLE,
    build_output,
    candidate_snapshot,
    capture_row,
    cited,
    full_listing_output,
    observation_row,
    runtime_config,
)


ALL_FIELDS = tuple(EvidenceFieldName)


def extraction_result(output=None, *, capture=None, observation=None, config=None):
    """A result bound exactly the way the extractor would have bound it."""

    capture = capture if capture is not None else capture_row()
    observation = observation if observation is not None else observation_row()
    config = config if config is not None else runtime_config()
    prepared = build_extraction_input(
        capture=capture,
        observation=observation,
        config=config,
        target_fields=ALL_FIELDS,
    )
    return AiEvidenceExtractionResult(
        outcome=AiEvidenceOutcome.EXTRACTED,
        target_fields=ALL_FIELDS,
        binding=prepared.binding,
        output=output if output is not None else full_listing_output(),
        provider_calls=1,
        model=config.model,
    )


def verify(output=None, *, capture=None, observation=None, config=None, result=None):
    capture = capture if capture is not None else capture_row()
    observation = observation if observation is not None else observation_row()
    config = config if config is not None else runtime_config()
    result = result if result is not None else extraction_result(output)
    return verify_ai_evidence(
        result, capture=capture, observation=observation, config=config
    )


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_exact_citations_verify_against_the_retained_document():
    report = verify()

    assert report.status is ReportStatus.VERIFIED
    assert report.binding_failures == ()
    assert report.bound is True

    verified = {item.field_name: item for item in report.verified_fields()}
    assert verified[EvidenceFieldName.OE_NUMBERS].canonical_values == ("1K0615301",)
    assert verified[EvidenceFieldName.CONDITION].canonical_values == ("NEW",)
    assert verified[EvidenceFieldName.SIDE].canonical_values == ("LEFT",)
    assert verified[EvidenceFieldName.INSTALLATION_POSITION].canonical_values == (
        "FRONT",
    )
    assert verified[EvidenceFieldName.PACKAGE_QUANTITY].canonical_values == ("4",)
    assert verified[EvidenceFieldName.UNIT_BASIS].canonical_values == ("PER_AXLE",)
    assert verified[EvidenceFieldName.BRAND].canonical_values == ("bosch",)

    not_found = report.field_result(EvidenceFieldName.VEHICLE_MAKE)
    assert not_found is not None
    assert not_found.status is VerificationStatus.NOT_FOUND


def test_offsets_are_verified_when_supplied():
    excerpt = "Состояние: новый"
    start = DESCRIPTION.index(excerpt)
    report = verify(
        build_output(
            CONDITION=(
                FindingState.FOUND,
                [
                    cited(
                        "новый", excerpt=excerpt, start=start, end=start + len(excerpt)
                    )
                ],
            )
        )
    )
    assert report.field_result(EvidenceFieldName.CONDITION).verified is True


def test_wrong_offsets_are_refused_even_when_the_text_exists():
    excerpt = "Состояние: новый"
    report = verify(
        build_output(
            CONDITION=(
                FindingState.FOUND,
                [cited("новый", excerpt=excerpt, start=0, end=len(excerpt))],
            )
        )
    )
    item = report.field_result(EvidenceFieldName.CONDITION)
    assert item.status is VerificationStatus.REJECTED
    assert CitationRefusal.EXCERPT_OFFSETS_INVALID.value in item.reason_codes


def test_report_dict_carries_no_decision_authority_keys():
    payload = verify().as_dict()
    assert_no_authority_fields(payload, where="test")
    encoded = str(payload)
    assert "automatic_eligible" not in encoded
    assert "verified_matched_oe_norm" not in encoded


# ---------------------------------------------------------------------------
# fabricated / unresolvable citations
# ---------------------------------------------------------------------------


def test_fabricated_excerpt_is_rejected():
    """Mutant guard: dropping the substring check must fail here."""

    report = verify(
        build_output(
            ENGINE=(
                FindingState.FOUND,
                [cited("2.0 TSI", excerpt="Двигатель 2.0 TSI бензин")],
            )
        )
    )
    item = report.field_result(EvidenceFieldName.ENGINE)
    assert item.status is VerificationStatus.REJECTED
    assert CitationRefusal.EXCERPT_NOT_SUBSTRING.value in item.reason_codes
    assert item.canonical_values == ()
    assert all(not citation.accepted for citation in item.citations)


def test_paraphrase_of_a_real_sentence_is_still_a_fabrication():
    report = verify(
        build_output(
            PART_TYPE=(
                FindingState.FOUND,
                [
                    cited(
                        "тормозные колодки",
                        kind=EvidenceSourceKind.TITLE,
                        path="/title",
                        excerpt="Тормозные колодки, передние",
                    )
                ],
            )
        )
    )
    item = report.field_result(EvidenceFieldName.PART_TYPE)
    assert item.status is VerificationStatus.REJECTED
    assert CitationRefusal.EXCERPT_NOT_SUBSTRING.value in item.reason_codes


def test_unresolvable_pointer_is_rejected():
    report = verify(
        build_output(
            ENGINE=(
                FindingState.FOUND,
                [
                    cited(
                        "2.0 TDI",
                        kind=EvidenceSourceKind.STRUCTURED_DATA,
                        path="/structured/engine",
                        excerpt="2.0 TDI",
                    )
                ],
            )
        )
    )
    item = report.field_result(EvidenceFieldName.ENGINE)
    assert item.status is VerificationStatus.REJECTED
    assert CitationRefusal.SOURCE_PATH_UNRESOLVED.value in item.reason_codes


def test_structured_reference_must_equal_the_retained_value_exactly():
    close_enough = verify(
        build_output(
            BRAND=(
                FindingState.FOUND,
                [
                    cited(
                        "Bosch",
                        kind=EvidenceSourceKind.STRUCTURED_DATA,
                        path="/structured/brand",
                        excerpt="bosch",
                    )
                ],
            )
        )
    )
    item = close_enough.field_result(EvidenceFieldName.BRAND)
    assert item.status is VerificationStatus.REJECTED
    assert CitationRefusal.STRUCTURED_VALUE_MISMATCH.value in item.reason_codes


def test_characteristic_pointer_resolves_by_index():
    report = verify(
        build_output(
            SIDE=(
                FindingState.FOUND,
                [
                    cited(
                        "Левый",
                        kind=EvidenceSourceKind.CHARACTERISTIC,
                        path="/characteristics/1/value",
                        excerpt="Левый",
                    )
                ],
            )
        )
    )
    assert report.field_result(EvidenceFieldName.SIDE).canonical_values == ("LEFT",)

    out_of_range = verify(
        build_output(
            SIDE=(
                FindingState.FOUND,
                [
                    cited(
                        "Левый",
                        kind=EvidenceSourceKind.CHARACTERISTIC,
                        path="/characteristics/9/value",
                        excerpt="Левый",
                    )
                ],
            )
        )
    )
    item = out_of_range.field_result(EvidenceFieldName.SIDE)
    assert CitationRefusal.SOURCE_PATH_UNRESOLVED.value in item.reason_codes


# ---------------------------------------------------------------------------
# binding: fail closed
# ---------------------------------------------------------------------------


def test_missing_capture_fails_closed():
    report = verify_ai_evidence(
        extraction_result(),
        capture=None,
        observation=observation_row(),
        config=runtime_config(),
    )
    assert report.status is ReportStatus.FAILED_CLOSED
    assert BindingFailure.CAPTURE_MISSING in report.binding_failures
    assert report.verified_fields() == ()


def test_tampered_capture_hash_fails_closed():
    report = verify(capture=capture_row(content_sha256="b" * 64))
    assert report.status is ReportStatus.FAILED_CLOSED
    assert BindingFailure.CAPTURE_HASH_MISMATCH in report.binding_failures
    assert report.verified_fields() == ()


def test_capture_swapped_for_another_row_fails_closed():
    report = verify(capture=capture_row(id=uuid.uuid4()))
    assert report.status is ReportStatus.FAILED_CLOSED
    assert BindingFailure.CAPTURE_ID_MISMATCH in report.binding_failures


def test_stale_observation_binding_fails_closed():
    relisted = observation_row(source_listing_id="listing-2")
    report = verify(observation=relisted)
    assert report.status is ReportStatus.FAILED_CLOSED
    assert BindingFailure.OBSERVATION_LISTING_STALE in report.binding_failures


def test_observation_rebound_to_another_capture_fails_closed():
    report = verify(observation=observation_row(raw_capture_id=uuid.uuid4()))
    assert report.status is ReportStatus.FAILED_CLOSED
    assert BindingFailure.OBSERVATION_CAPTURE_UNBOUND in report.binding_failures


def test_edited_candidate_snapshot_fails_closed():
    edited = observation_row(
        candidate_snapshot=candidate_snapshot(condition="Б/У"),
    )
    report = verify(observation=edited)
    assert report.status is ReportStatus.FAILED_CLOSED
    assert BindingFailure.CANDIDATE_SNAPSHOT_STALE in report.binding_failures


def test_missing_raw_offer_locator_fails_closed():
    snapshot = candidate_snapshot()
    snapshot.pop("source_locator")
    observation = observation_row(candidate_snapshot=snapshot)
    result = extraction_result(observation=observation)
    report = verify(observation=observation, result=result)
    assert report.status is ReportStatus.FAILED_CLOSED
    assert BindingFailure.SOURCE_LOCATOR_MISSING in report.binding_failures


def test_locator_cannot_be_rebound_to_another_offer_in_the_capture():
    snapshot = candidate_snapshot()
    snapshot["source_locator"]["raw_offer_index"] = 9
    observation = observation_row(candidate_snapshot=snapshot)
    result = extraction_result(observation=observation)
    report = verify(observation=observation, result=result)
    assert report.status is ReportStatus.FAILED_CLOSED
    assert BindingFailure.SOURCE_LOCATOR_MISMATCH in report.binding_failures


def test_self_consistent_locator_cannot_disagree_with_retained_offer_bytes():
    raw_offer = {
        "raw_offer_index": 0,
        "product": {
            "id": "listing-1",
            "name": TITLE,
            "description": DESCRIPTION,
            "price": "1450.00",
        },
    }
    offer_sha = hashlib.sha256(
        json.dumps(
            raw_offer,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    snapshot = candidate_snapshot()
    snapshot["source_locator"]["raw_offer_sha256"] = offer_sha
    observation = observation_row(candidate_snapshot=snapshot)
    original_capture = capture_row(payload={"candidate_records": [raw_offer]})
    result = extraction_result(
        capture=original_capture,
        observation=observation,
    )

    rebound = {
        "raw_offer_index": 0,
        "product": {
            "id": "listing-1",
            "name": "Different retained offer",
            "price": "999.00",
        },
    }
    report = verify(
        capture=capture_row(payload={"candidate_records": [rebound]}),
        observation=observation,
        result=result,
    )

    assert report.status is ReportStatus.FAILED_CLOSED
    assert BindingFailure.SOURCE_LOCATOR_MISMATCH in report.binding_failures


def test_document_tamper_that_keeps_the_snapshot_hash_still_fails_closed():
    """The snapshot hash is not the only thing bound; the document is too."""

    result = extraction_result()
    tampered = replace(
        result, binding=replace(result.binding, document_sha256="c" * 64)
    )
    report = verify(result=tampered)
    assert report.status is ReportStatus.FAILED_CLOSED
    assert BindingFailure.DOCUMENT_HASH_MISMATCH in report.binding_failures


def test_prompt_and_schema_version_drift_fail_closed():
    result = extraction_result()
    prompt_drift = replace(
        result, binding=replace(result.binding, prompt_version="marko-...-v2")
    )
    schema_drift = replace(
        result, binding=replace(result.binding, schema_version="marko-...-v9")
    )
    assert (
        BindingFailure.PROMPT_VERSION_MISMATCH
        in verify(result=prompt_drift).binding_failures
    )
    assert (
        BindingFailure.SCHEMA_VERSION_MISMATCH
        in verify(result=schema_drift).binding_failures
    )


def test_model_settings_drift_fails_closed():
    report = verify(config=runtime_config(pricing_ai_evidence_model="gpt-4o-mini"))
    assert report.status is ReportStatus.FAILED_CLOSED
    assert BindingFailure.MODEL_SETTINGS_MISMATCH in report.binding_failures


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model", "not-the-bound-model"),
        ("reasoning_effort", "high"),
        ("max_output_tokens", 1199),
        ("max_input_chars", 19_999),
        ("model_settings_sha256", "f" * 64),
    ],
)
def test_each_bound_model_setting_is_recomputed(field, value):
    result = extraction_result()
    tampered = replace(result, binding=replace(result.binding, **{field: value}))
    report = verify(result=tampered)
    assert report.status is ReportStatus.FAILED_CLOSED
    assert BindingFailure.MODEL_SETTINGS_MISMATCH in report.binding_failures


def test_input_digest_is_recomputed_from_rows_and_target_fields():
    result = extraction_result()
    tampered = replace(
        result,
        binding=replace(result.binding, input_sha256="f" * 64),
    )
    report = verify(result=tampered)
    assert report.status is ReportStatus.FAILED_CLOSED
    assert BindingFailure.INPUT_HASH_MISMATCH in report.binding_failures


def test_output_must_cover_exactly_the_bound_target_fields():
    output = full_listing_output()
    result = extraction_result(
        output.model_copy(update={"findings": output.findings[:1]})
    )
    report = verify(result=result)
    assert report.status is ReportStatus.FAILED_CLOSED
    assert BindingFailure.SCHEMA_DRIFT in report.binding_failures


def test_result_without_output_is_not_verifiable():
    empty = AiEvidenceExtractionResult(
        outcome=AiEvidenceOutcome.UNCONFIGURED, target_fields=ALL_FIELDS
    )
    report = verify(result=empty)
    assert report.status is ReportStatus.NO_OUTPUT
    assert report.bound is False
    assert report.verified_fields() == ()


# ---------------------------------------------------------------------------
# OE: our normalization, literally supported
# ---------------------------------------------------------------------------


def test_oe_is_normalized_by_our_code_not_by_the_model():
    """Mutant guard: canonicalizing ``normalized_value`` must fail here."""

    report = verify(
        build_output(
            OE_NUMBERS=(
                FindingState.FOUND,
                [
                    cited(
                        "1K0 615 301",
                        kind=EvidenceSourceKind.TITLE,
                        path="/title",
                        excerpt="1K0 615 301",
                        normalized="8K0698151A",
                    )
                ],
            )
        )
    )
    item = report.field_result(EvidenceFieldName.OE_NUMBERS)
    assert item.status is VerificationStatus.VERIFIED
    assert item.canonical_values == ("1K0615301",)
    citation = item.citations[0]
    assert citation.canonical_value == "1K0615301"
    assert citation.model_normalized_value == "8K0698151A"
    assert CitationRefusal.MODEL_NORMALIZED_VALUE_IGNORED.value in item.reason_codes
    assert "normalize_oe" in citation.normalization_method


def test_oe_absent_from_the_excerpt_is_refused():
    report = verify(
        build_output(
            OE_NUMBERS=(
                FindingState.FOUND,
                [
                    cited(
                        "8K0698151A",
                        excerpt="Оригинальный номер: 1K0615301",
                        normalized="8K0698151A",
                    )
                ],
            )
        )
    )
    item = report.field_result(EvidenceFieldName.OE_NUMBERS)
    assert item.status is VerificationStatus.REJECTED
    assert CitationRefusal.OE_NOT_SUPPORTED_BY_EXCERPT.value in item.reason_codes


def test_oe_too_short_to_normalize_is_refused():
    report = verify(
        build_output(
            OE_NUMBERS=(
                FindingState.FOUND,
                [cited("A1", excerpt="Оригинальный номер: 1K0615301")],
            )
        )
    )
    item = report.field_result(EvidenceFieldName.OE_NUMBERS)
    assert item.status is VerificationStatus.REJECTED
    assert CitationRefusal.OE_NORMALIZATION_REJECTED.value in item.reason_codes


def test_oe_fragment_inside_a_longer_token_is_refused():
    report = verify(
        build_output(
            OE_NUMBERS=(
                FindingState.FOUND,
                [cited("061", excerpt="1K0615301")],
            )
        )
    )
    item = report.field_result(EvidenceFieldName.OE_NUMBERS)
    assert item.status is VerificationStatus.REJECTED
    assert CitationRefusal.OE_NOT_SUPPORTED_BY_EXCERPT.value in item.reason_codes


@pytest.mark.parametrize("excerpt", ("061А", "061１", "061Ｋ", "061Α"))
def test_oe_fragment_next_to_unicode_alphanumeric_is_refused(excerpt: str):
    """NFKC, Cyrillic homoglyphs and other Unicode letters are token content."""

    observation = observation_row(
        candidate_snapshot=candidate_snapshot(description=DESCRIPTION + " " + excerpt)
    )
    output = build_output(
        OE_NUMBERS=(
            FindingState.FOUND,
            [cited("061", excerpt=excerpt)],
        )
    )
    report = verify(
        output,
        observation=observation,
        result=extraction_result(output, observation=observation),
    )

    item = report.field_result(EvidenceFieldName.OE_NUMBERS)
    assert item.status is VerificationStatus.REJECTED
    assert CitationRefusal.OE_NOT_SUPPORTED_BY_EXCERPT.value in item.reason_codes


def test_multiple_oe_numbers_are_all_kept():
    observation = observation_row(
        candidate_snapshot=candidate_snapshot(
            description=DESCRIPTION + " Кросс-код: 8K0 698 151 A."
        )
    )
    report = verify(
        build_output(
            OE_NUMBERS=(
                FindingState.FOUND,
                [
                    cited("1K0615301", excerpt="Оригинальный номер: 1K0615301"),
                    cited("8K0 698 151 A", excerpt="Кросс-код: 8K0 698 151 A"),
                ],
            )
        ),
        observation=observation,
        result=extraction_result(
            build_output(
                OE_NUMBERS=(
                    FindingState.FOUND,
                    [
                        cited("1K0615301", excerpt="Оригинальный номер: 1K0615301"),
                        cited("8K0 698 151 A", excerpt="Кросс-код: 8K0 698 151 A"),
                    ],
                )
            ),
            observation=observation,
        ),
    )
    item = report.field_result(EvidenceFieldName.OE_NUMBERS)
    assert item.status is VerificationStatus.VERIFIED
    assert item.canonical_values == ("1K0615301", "8K0698151A")


# ---------------------------------------------------------------------------
# lexicon / grammar acceptance and refusal
# ---------------------------------------------------------------------------


def test_condition_lexicon_accepts_supported_wording():
    for excerpt, expected in (
        ("Состояние: новый", "NEW"),
        ("Комплект 4 шт", None),
    ):
        report = verify(
            build_output(
                CONDITION=(FindingState.FOUND, [cited("новый", excerpt=excerpt)])
            )
        )
        item = report.field_result(EvidenceFieldName.CONDITION)
        if expected is None:
            assert item.status is VerificationStatus.AMBIGUOUS
            assert CitationRefusal.LEXICON_UNSUPPORTED.value in item.reason_codes
        else:
            assert item.canonical_values == (expected,)


def test_used_condition_is_recognised_in_both_languages():
    for text, wording in (
        (DESCRIPTION.replace("новый", "б/у"), "Состояние: б/у"),
        (DESCRIPTION.replace("новый", "вживаний"), "Состояние: вживаний"),
        (DESCRIPTION.replace("новый", "used"), "Состояние: used"),
    ):
        observation = observation_row(
            candidate_snapshot=candidate_snapshot(description=text)
        )
        result = extraction_result(
            build_output(
                CONDITION=(FindingState.FOUND, [cited("б/у", excerpt=wording)])
            ),
            observation=observation,
        )
        report = verify(observation=observation, result=result)
        item = report.field_result(EvidenceFieldName.CONDITION)
        assert item.canonical_values == ("USED_OR_REFURBISHED",), wording


def test_condition_inference_the_lexicon_cannot_support_is_manual_review():
    """A real excerpt, a plausible conclusion, no supporting wording."""

    report = verify(
        build_output(
            CONDITION=(
                FindingState.FOUND,
                [
                    cited(
                        "NEW",
                        kind=EvidenceSourceKind.TITLE,
                        path="/title",
                        excerpt="Тормозные колодки передние",
                        normalized="NEW",
                    )
                ],
            )
        )
    )
    item = report.field_result(EvidenceFieldName.CONDITION)
    assert item.status is VerificationStatus.AMBIGUOUS
    assert CitationRefusal.LEXICON_UNSUPPORTED.value in item.reason_codes
    assert item.canonical_values == ()


def test_condition_wording_contradicting_the_reported_value_is_refused():
    report = verify(
        build_output(
            CONDITION=(
                FindingState.FOUND,
                [cited("б/у", excerpt="Состояние: новый")],
            )
        )
    )
    item = report.field_result(EvidenceFieldName.CONDITION)
    assert item.status is VerificationStatus.AMBIGUOUS
    assert CitationRefusal.LEXICON_UNSUPPORTED.value in item.reason_codes


def test_quantity_requires_a_unit_word_next_to_the_number():
    supported = verify(
        build_output(
            PACKAGE_QUANTITY=(
                FindingState.FOUND,
                [cited("4", excerpt="Комплект 4 шт")],
            )
        )
    )
    assert supported.field_result(
        EvidenceFieldName.PACKAGE_QUANTITY
    ).canonical_values == ("4",)

    bare_number = verify(
        build_output(
            PACKAGE_QUANTITY=(
                FindingState.FOUND,
                [cited("2", excerpt="Двигатель 2.0 TDI")],
            )
        )
    )
    item = bare_number.field_result(EvidenceFieldName.PACKAGE_QUANTITY)
    assert item.status is VerificationStatus.AMBIGUOUS
    assert CitationRefusal.LEXICON_UNSUPPORTED.value in item.reason_codes


def test_quantity_the_excerpt_does_not_state_is_refused():
    report = verify(
        build_output(
            PACKAGE_QUANTITY=(
                FindingState.FOUND,
                [cited("2", excerpt="Комплект 4 шт")],
            )
        )
    )
    item = report.field_result(EvidenceFieldName.PACKAGE_QUANTITY)
    assert item.status is VerificationStatus.AMBIGUOUS
    assert CitationRefusal.LEXICON_UNSUPPORTED.value in item.reason_codes


def test_side_and_position_need_supporting_wording():
    ambiguous_side = observation_row(
        candidate_snapshot=candidate_snapshot(
            description="Сторона: левый и правый в комплекте."
        )
    )
    result = extraction_result(
        build_output(
            SIDE=(
                FindingState.FOUND,
                [cited("левый", excerpt="Сторона: левый и правый")],
            )
        ),
        observation=ambiguous_side,
    )
    report = verify(observation=ambiguous_side, result=result)
    item = report.field_result(EvidenceFieldName.SIDE)
    assert item.status is VerificationStatus.AMBIGUOUS
    assert CitationRefusal.LEXICON_AMBIGUOUS.value in item.reason_codes

    unsupported_position = verify(
        build_output(
            INSTALLATION_POSITION=(
                FindingState.FOUND,
                [cited("REAR", excerpt="Состояние: новый")],
            )
        )
    )
    item = unsupported_position.field_result(EvidenceFieldName.INSTALLATION_POSITION)
    assert item.status is VerificationStatus.AMBIGUOUS
    assert CitationRefusal.LEXICON_UNSUPPORTED.value in item.reason_codes


def test_year_must_be_printed_in_the_excerpt():
    observation = observation_row(
        candidate_snapshot=candidate_snapshot(
            description=DESCRIPTION + " Годы выпуска: 2005-2012."
        )
    )
    good = extraction_result(
        build_output(
            YEAR_FROM=(
                FindingState.FOUND,
                [cited("2005", excerpt="Годы выпуска: 2005-2012")],
            )
        ),
        observation=observation,
    )
    assert verify(observation=observation, result=good).field_result(
        EvidenceFieldName.YEAR_FROM
    ).canonical_values == ("2005",)

    invented = extraction_result(
        build_output(
            YEAR_FROM=(
                FindingState.FOUND,
                [cited("2004", excerpt="Годы выпуска: 2005-2012")],
            )
        ),
        observation=observation,
    )
    item = verify(observation=observation, result=invented).field_result(
        EvidenceFieldName.YEAR_FROM
    )
    assert item.status is VerificationStatus.AMBIGUOUS
    assert CitationRefusal.UNSUPPORTED_INFERENCE.value in item.reason_codes


def test_free_text_value_not_printed_in_the_excerpt_is_manual_review():
    report = verify(
        build_output(
            VEHICLE_MAKE=(
                FindingState.FOUND,
                [
                    cited(
                        "Volkswagen",
                        kind=EvidenceSourceKind.TITLE,
                        path="/title",
                        excerpt="Тормозные колодки передние",
                        normalized="VW",
                    )
                ],
            )
        )
    )
    item = report.field_result(EvidenceFieldName.VEHICLE_MAKE)
    assert item.status is VerificationStatus.AMBIGUOUS
    assert CitationRefusal.UNSUPPORTED_INFERENCE.value in item.reason_codes


# ---------------------------------------------------------------------------
# conflicts
# ---------------------------------------------------------------------------


def test_model_reported_conflict_preserves_both_citations():
    observation = observation_row(
        candidate_snapshot=candidate_snapshot(
            description="Состояние: новый. В другом месте: б/у восстановленный."
        )
    )
    result = extraction_result(
        build_output(
            CONDITION=(
                FindingState.CONFLICT,
                [
                    cited("новый", excerpt="Состояние: новый"),
                    cited("б/у", excerpt="В другом месте: б/у"),
                ],
            )
        ),
        observation=observation,
    )
    report = verify(observation=observation, result=result)
    item = report.field_result(EvidenceFieldName.CONDITION)
    assert item.status is VerificationStatus.CONFLICT
    assert len(item.citations) == 2
    assert {citation.canonical_value for citation in item.citations} == {
        "NEW",
        "USED_OR_REFURBISHED",
    }
    assert item.field_name not in {field for field in AI_FILLABLE_DIMENSIONS if False}


def test_two_verified_citations_that_disagree_become_a_conflict_not_a_pick():
    observation = observation_row(
        candidate_snapshot=candidate_snapshot(
            description="Двигатель 2.0 TDI. Также подходит 1.9 TDI."
        )
    )
    result = extraction_result(
        build_output(
            ENGINE=(
                FindingState.FOUND,
                [
                    cited("2.0 TDI", excerpt="Двигатель 2.0 TDI", confidence=0.99),
                    cited("1.9 TDI", excerpt="Также подходит 1.9 TDI", confidence=0.4),
                ],
            )
        ),
        observation=observation,
    )
    report = verify(observation=observation, result=result)
    item = report.field_result(EvidenceFieldName.ENGINE)
    assert item.status is VerificationStatus.CONFLICT
    assert set(item.canonical_values) == {"2.0 tdi", "1.9 tdi"}


def test_ambiguous_findings_are_never_verified():
    report = verify(
        build_output(
            FITMENT=(
                FindingState.AMBIGUOUS,
                [
                    cited(
                        "Двигатель 2.0 TDI",
                        excerpt="Двигатель 2.0 TDI",
                    )
                ],
            )
        )
    )
    item = report.field_result(EvidenceFieldName.FITMENT)
    assert item.status is VerificationStatus.AMBIGUOUS
    assert item.canonical_values == ()


# ---------------------------------------------------------------------------
# bounded application to comparison evidence
# ---------------------------------------------------------------------------


def comparison_evidence(**dimension_states) -> ComparisonEvidence:
    dimensions = {
        name: DimensionEvidence(state=EvidenceState.UNKNOWN)
        for name in (
            "oe_reference",
            "part_type",
            "brand_manufacturer",
            "fitment",
            "vehicle_generation",
            "year_interval",
            "engine",
            "body_variant",
            "side",
            "position",
            "condition",
            "package_quantity",
            "currency_presence",
        )
    }
    dimensions.update(dimension_states)
    return ComparisonEvidence(
        dimensions=dimensions,
        provenance=SourceProvenance(source_type="test_fixture", verified=True),
        seller_identity=SellerIdentityEvidence(stable_seller_id="s-1", verified=True),
        policy_id=COMPARABILITY_POLICY_ID,
        policy_hash=COMPARABILITY_POLICY_HASH,
        hard_gate_result=HardGateResult.MANUAL_REVIEW,
        reason_codes=("UNKNOWN_DIMENSION",),
    )


def test_verified_fields_fill_only_unknown_dimensions():
    report = verify()
    evidence = comparison_evidence()

    proposal = propose_evidence_fill(
        evidence,
        report,
        our_values={"condition": "NEW", "side": "LEFT", "position": "REAR"},
    )

    filled = proposal.evidence
    assert "condition" in proposal.filled_dimensions
    assert filled.dimensions["condition"].state is EvidenceState.MATCH
    assert filled.dimensions["condition"].reason_code == AI_EVIDENCE_FILL_REASON_CODE
    assert filled.dimensions["side"].state is EvidenceState.MATCH
    # Our value disagrees with the verified candidate value -> CONFLICT, and it
    # is the existing deterministic comparison that says so.
    assert filled.dimensions["position"].state is EvidenceState.CONFLICT
    # No ``our`` value to compare against stays UNKNOWN, never an optimistic match.
    assert filled.dimensions["package_quantity"].state is EvidenceState.UNKNOWN


def test_deterministic_conflict_cannot_be_overridden():
    """Mutant guard: removing the CONFLICT guard must fail here."""

    report = verify()
    evidence = comparison_evidence(
        condition=DimensionEvidence(
            state=EvidenceState.CONFLICT,
            raw_value="б/у",
            normalized_value="USED_OR_REFURBISHED",
            reason_code="DETERMINISTIC_PARSER",
        )
    )

    proposal = propose_evidence_fill(evidence, report, our_values={"condition": "NEW"})

    kept = proposal.evidence.dimensions["condition"]
    assert kept.state is EvidenceState.CONFLICT
    assert kept.reason_code == "DETERMINISTIC_PARSER"
    assert kept.normalized_value == "USED_OR_REFURBISHED"
    assert "condition" not in proposal.filled_dimensions
    assert ("condition", FillRefusal.DETERMINISTIC_CONFLICT) in proposal.refusals


def test_already_determined_dimensions_are_not_rewritten():
    report = verify()
    evidence = comparison_evidence(
        side=DimensionEvidence(
            state=EvidenceState.MATCH, normalized_value="right", reason_code="PARSER"
        )
    )
    proposal = propose_evidence_fill(evidence, report, our_values={"side": "LEFT"})
    assert proposal.evidence.dimensions["side"].state is EvidenceState.MATCH
    assert proposal.evidence.dimensions["side"].normalized_value == "right"
    assert ("side", FillRefusal.ALREADY_DETERMINED) in proposal.refusals


def test_identity_and_currency_dimensions_are_never_filled_by_ai():
    report = verify()
    evidence = comparison_evidence()
    proposal = propose_evidence_fill(
        evidence, report, our_values={"oe_reference": "1K0615301"}
    )

    assert "oe_reference" not in proposal.filled_dimensions
    assert "currency_presence" not in proposal.filled_dimensions
    assert proposal.evidence.dimensions["oe_reference"].state is EvidenceState.UNKNOWN
    assert (
        proposal.evidence.dimensions["currency_presence"].state is EvidenceState.UNKNOWN
    )
    assert (
        EvidenceFieldName.OE_NUMBERS.value,
        FillRefusal.NOT_FILLABLE_DIMENSION,
    ) in proposal.refusals
    assert "oe_reference" not in AI_FILLABLE_DIMENSIONS.values()
    assert "currency_presence" not in AI_FILLABLE_DIMENSIONS.values()


def test_shadow_fill_never_moves_eligibility_or_authority():
    """Mutant guard: setting ``automatic_eligible`` from confidence fails here."""

    report = verify()
    evidence = comparison_evidence()
    proposal = propose_evidence_fill(
        evidence,
        report,
        our_values={name: None for name in AI_FILLABLE_DIMENSIONS.values()},
    )

    assert proposal.authority_changes == {}
    assert_no_authority_fields(dict(proposal.authority_changes), where="proposal")
    assert proposal.evidence.hard_gate_result is HardGateResult.MANUAL_REVIEW
    assert proposal.evidence.hard_gate_result is evidence.hard_gate_result
    assert proposal.evidence.reason_codes == evidence.reason_codes
    assert proposal.evidence.policy_id == evidence.policy_id
    assert proposal.evidence.policy_hash == evidence.policy_hash
    assert proposal.evidence.provenance == evidence.provenance
    assert proposal.evidence.seller_identity == evidence.seller_identity
    # High model confidence buys nothing: the source object is untouched.
    assert evidence.dimensions["condition"].state is EvidenceState.UNKNOWN


def test_unbound_report_fills_nothing():
    report = verify(capture=capture_row(content_sha256="d" * 64))
    evidence = comparison_evidence()
    proposal = propose_evidence_fill(evidence, report, our_values={"condition": "NEW"})
    assert proposal.filled_dimensions == ()
    assert proposal.refusals == (("*", FillRefusal.NOT_BOUND),)
    assert proposal.evidence is evidence


def test_rejected_field_does_not_fill_its_dimension():
    result = extraction_result(
        build_output(
            CONDITION=(
                FindingState.FOUND,
                [cited("новый", excerpt="Состояние: совершенно новый")],
            )
        )
    )
    report = verify(result=result)
    proposal = propose_evidence_fill(
        comparison_evidence(), report, our_values={"condition": "NEW"}
    )
    assert "condition" not in proposal.filled_dimensions
    assert ("condition", FillRefusal.NOT_VERIFIED) in proposal.refusals


def test_fill_evidence_refs_point_back_at_the_bound_input():
    report = verify()
    proposal = propose_evidence_fill(
        comparison_evidence(), report, our_values={"condition": "NEW"}
    )
    refs = proposal.evidence.dimensions["condition"].evidence_refs
    assert refs
    assert all(ref.startswith("ai_evidence:") for ref in refs)
    assert any(report.binding.input_sha256[:16] in ref for ref in refs)


def test_none_evidence_is_passed_through():
    assert propose_evidence_fill(None, verify()).evidence is None


@pytest.mark.parametrize(
    "title_only",
    [TITLE, TITLE.upper()],
)
def test_verification_is_deterministic_across_repeated_runs(title_only):
    observation = observation_row(
        candidate_snapshot=candidate_snapshot(name=title_only)
    )
    result = extraction_result(
        build_output(
            PART_TYPE=(
                FindingState.FOUND,
                [
                    cited(
                        title_only[:17],
                        kind=EvidenceSourceKind.TITLE,
                        path="/title",
                        excerpt=title_only[:17],
                    )
                ],
            )
        ),
        observation=observation,
    )
    first = verify(observation=observation, result=result).as_dict()
    second = verify(observation=observation, result=result).as_dict()
    assert first == second


def test_verifier_needs_no_provider_and_no_settings_secret():
    config = runtime_config(pricing_llm_api_key="")
    result = extraction_result()
    # The key is irrelevant to verification: it is pure recomputation.
    report = verify_ai_evidence(
        result,
        capture=capture_row(),
        observation=observation_row(),
        config=replace(config, api_key_present=True),
    )
    assert report.status is ReportStatus.VERIFIED


def test_simple_namespace_observation_without_snapshot_fails_closed():
    bare = SimpleNamespace(
        id=observation_row().id,
        source_listing_id="listing-1",
        raw_capture_id=capture_row().id,
        title="",
        description=None,
        description_available=False,
        candidate_snapshot={},
    )
    result = extraction_result(build_output(), observation=bare)
    report = verify(observation=bare, result=result)
    assert report.status is ReportStatus.FAILED_CLOSED
    assert BindingFailure.SOURCE_LOCATOR_MISSING in report.binding_failures
    assert report.fields == ()
