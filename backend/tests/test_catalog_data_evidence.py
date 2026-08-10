from types import SimpleNamespace

from marko.services.catalog_data_evidence import catalog_data_evidence


def _item(**overrides):
    values = {
        "identity_status": "UNRESOLVED",
        "identity_reason": "CUSTOMER_IDENTITY_MISSING",
        "oe_norm": "",
        "internal_code_norm": "",
        "internal_code_raw": "",
        "raw_row": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_confirmed_oe_keeps_customer_provenance_and_is_not_review_only():
    evidence = catalog_data_evidence(
        _item(
            identity_status="OE_CONFIRMED",
            oe_norm="93818439",
            internal_code_norm="77643",
            raw_row={
                "Внутренний код": "77643",
                "Источники OE": "OWN_EXPORT_CODE, KEMP_REFERENCE_MAP_V2",
                "Другие подтверждённые номера": "93818439, 93818440",
                "Ссылка на подтверждение": "https://example.test/oe/93818439",
                "Кандидаты (не подтверждены)": "93818441",
            },
        )
    )

    assert evidence.status == "OE_CONFIRMED"
    assert evidence.review_only is False
    assert evidence.internal_code == "77643"
    assert evidence.oe_sources == (
        "OWN_EXPORT_CODE",
        "KEMP_REFERENCE_MAP_V2",
    )
    assert evidence.confirmed_cross_numbers == ("93818439", "93818440")
    assert evidence.candidate_numbers == ("93818441",)
    assert evidence.evidence_url == "https://example.test/oe/93818439"


def test_candidate_number_is_explicit_manual_review_and_never_promotes_identity():
    evidence = catalog_data_evidence(
        _item(
            identity_status="MPN_ONLY",
            oe_norm="",
            raw_row={
                "MPN": "115070",
                "Кандидаты (не подтверждены)": "93818439; 93818440",
                "Почему нет OE": "нужна независимая проверка",
            },
        )
    )

    assert evidence.status == "CANDIDATE_REVIEW"
    assert evidence.review_only is True
    assert evidence.candidate_numbers == ("93818439", "93818440")
    assert evidence.no_oe_reason == "нужна независимая проверка"


def test_malformed_confirmed_row_fails_closed_without_oe():
    evidence = catalog_data_evidence(
        _item(
            identity_status="OE_CONFIRMED",
            oe_norm="",
            raw_row={
                "Ссылка на подтверждение": "javascript:alert(1)",
                "Источники OE": "KEMP_SITE",
            },
        )
    )

    assert evidence.status == "NO_OE_REVIEW"
    assert evidence.review_only is True
    assert evidence.evidence_url is None
    assert evidence.oe_sources == ("KEMP_SITE",)


def test_reparse_provenance_is_available_when_export_columns_are_absent():
    evidence = catalog_data_evidence(
        _item(
            identity_status="OE_CONFIRMED",
            oe_norm="93818439",
            raw_row={
                "identity_provenance": {
                    "canonical_sources": ["KEMP_REFERENCE_MAP_V2"],
                    "canonical_source": "OWN_EXPORT_CODE",
                }
            },
        )
    )

    assert evidence.status == "OE_CONFIRMED"
    assert evidence.oe_sources == (
        "KEMP_REFERENCE_MAP_V2",
        "OWN_EXPORT_CODE",
    )
