"""Multi-key public search expansion stays fail-closed on private codes."""

from __future__ import annotations

from marko.services.pricing_runs import (
    customer_identity_available,
    customer_identity_query,
    customer_public_search_keys,
)
from marko.services.public_search_keys import (
    build_public_search_keys,
    public_search_key_numbers,
)


def test_oe_confirmed_primary_matches_single_query_and_lists_crosses() -> None:
    keys = build_public_search_keys(
        identity_status="OE_CONFIRMED",
        oe_norm="1086282",
        mpn_norm="TH652688J",
        part_numbers_norm=("115070",),
        confirmed_identity_links=(
            {
                "our_oem_norm": "1086282",
                "extracted_oem_norm": "1300152",
                "validation_status": "CONFIRMED",
                "anomaly": None,
                "extraction_method": "KEMP_REFERENCE_MAP_V2",
                "validation_details": {"automatic_eligible": True, "confidence": "0.9"},
            },
        ),
        primary_query="1086282",
    )
    numbers = [key.number for key in keys]
    assert numbers[0] == "1086282"
    assert "1300152" in numbers
    assert "TH652688J" in numbers
    assert "115070" in numbers
    primary = next(key for key in keys if key.pricing_primary)
    assert primary.number == "1086282" and primary.role == "OE"
    cross = next(key for key in keys if key.number == "1300152")
    assert cross.role == "CROSS"
    assert cross.pricing_primary is False


def test_private_kemp_codes_never_appear_as_search_keys() -> None:
    keys = build_public_search_keys(
        identity_status="MPN_ONLY",
        oe_norm="77646059",
        mpn_norm="77646059",
        part_numbers_norm=("7764 6059", "A6383240604"),
        confirmed_identity_links=(
            {
                "our_oem_norm": "77646059",
                "extracted_oem_norm": "A6383240604",
                "validation_status": "CONFIRMED",
                "anomaly": None,
                "extraction_method": "KEMP_REFERENCE_MAP_V2",
                "validation_details": {"automatic_eligible": True},
            },
        ),
    )
    numbers = public_search_key_numbers(keys)
    assert "77646059" not in numbers
    assert "A6383240604" in numbers
    assert all(not n.startswith("776") for n in numbers)


def test_review_or_anomalous_links_do_not_expand_keys() -> None:
    keys = build_public_search_keys(
        identity_status="OE_CONFIRMED",
        oe_norm="1086282",
        confirmed_identity_links=(
            {
                "our_oem_norm": "1086282",
                "extracted_oem_norm": "9999999A",
                "validation_status": "REVIEW",
                "anomaly": None,
                "extraction_method": "KEMP_SITE",
            },
            {
                "our_oem_norm": "1086282",
                "extracted_oem_norm": "8888888B",
                "validation_status": "CONFIRMED",
                "anomaly": "SHARED_ARTICLE_FANOUT",
                "extraction_method": "KEMP_SITE",
            },
            {
                "our_oem_norm": "1086282",
                "extracted_oem_norm": "7777777C",
                "validation_status": "CONFIRMED",
                "anomaly": None,
                "extraction_method": "KEMP_SITE",
                "validation_details": {"automatic_eligible": False},
            },
        ),
    )
    numbers = set(public_search_key_numbers(keys))
    assert numbers == {"1086282"}


def test_mpn_only_uses_characteristics_and_never_pricing_primary() -> None:
    keys = build_public_search_keys(
        identity_status="MPN_ONLY",
        oe_norm="776414",
        mpn_norm="115",
        part_numbers_norm=("115070", "LM11749"),
    )
    assert public_search_key_numbers(keys)[0] == "115070"
    assert "LM11749" in public_search_key_numbers(keys)
    assert all(not key.pricing_primary for key in keys)
    assert not any(key.role == "OE" for key in keys)


def test_short_numeric_prefix_alone_yields_empty_keys() -> None:
    keys = build_public_search_keys(
        identity_status="MPN_ONLY",
        oe_norm="776414",
        mpn_norm="115",
        part_numbers_norm=(),
    )
    assert keys == ()


def test_unsafe_pair_shape_is_ignored() -> None:
    keys = build_public_search_keys(
        identity_status="OE_CONFIRMED",
        oe_norm="1086282",
        confirmed_identity_links=(
            {
                "our_oem_norm": "1086282",
                "extracted_oem_norm": "MG",
                "validation_status": "CONFIRMED",
                "anomaly": None,
                "extraction_method": "KEMP_REFERENCE_MAP_V2",
                "validation_details": {"automatic_eligible": True},
            },
        ),
    )
    assert public_search_key_numbers(keys) == ("1086282",)


def test_scope_candidate_wrapper_aligns_with_single_query(monkeypatch) -> None:
    # Lightweight stand-in: ScopeCandidate is a dataclass; import helper via
    # a simple namespace object matching the fields the wrapper reads.
    from types import SimpleNamespace

    candidate = SimpleNamespace(
        identity_status="OE_CONFIRMED",
        oe_norm="06A121012X",
        mpn_norm="",
        part_numbers_norm=(),
        confirmed_identity_links=(),
    )
    assert customer_identity_query(candidate) == "06A121012X"
    assert customer_identity_available(candidate) is True
    keys = customer_public_search_keys(candidate)
    assert keys[0].number == "06A121012X"
    assert keys[0].pricing_primary is True


def test_dedupe_keeps_stronger_role() -> None:
    keys = build_public_search_keys(
        identity_status="OE_CONFIRMED",
        oe_norm="1086282",
        mpn_norm="1086282",
        part_numbers_norm=("1086282",),
    )
    assert len(keys) == 1
    assert keys[0].role == "OE"
    assert keys[0].pricing_primary is True


def test_retrieval_only_queries_are_the_keys_that_assert_nothing() -> None:
    """The complement of ``declared_widenings``, and never overlapping it.

    A confirmed cross carries source and provenance and may widen the priced
    market. A public MPN or a characteristic part number carries neither: it
    is safe to *search* and must never describe the identity of what it finds.
    The two lists are frozen separately so the persistence boundary can tell
    which of the two retrieved a row.
    """

    from types import SimpleNamespace

    from marko.services.pricing_runs import declared_widenings, retrieval_only_queries

    candidate = SimpleNamespace(
        identity_status="OE_CONFIRMED",
        oe_norm="1086282",
        mpn_norm="TH652688J",
        part_numbers_norm=("115070",),
        confirmed_identity_links=(
            {
                "our_oem_norm": "1086282",
                "extracted_oem_norm": "1300152",
                "validation_status": "CONFIRMED",
                "anomaly": None,
                "extraction_method": "KEMP_REFERENCE_MAP_V2",
                "validation_details": {"automatic_eligible": True},
            },
        ),
    )

    assert declared_widenings(candidate) == ("1300152",)
    assert retrieval_only_queries(candidate) == ("TH652688J", "115070")
    assert not set(declared_widenings(candidate)) & set(
        retrieval_only_queries(candidate)
    )


def test_a_private_shelf_code_is_not_a_retrieval_only_query() -> None:
    """``build_public_search_keys`` already drops it; prove it stays dropped."""

    from types import SimpleNamespace

    from marko.services.pricing_runs import retrieval_only_queries

    candidate = SimpleNamespace(
        identity_status="MPN_ONLY",
        oe_norm="77646059",
        mpn_norm="77646059",
        part_numbers_norm=("7764 6059", "A6383240604"),
        confirmed_identity_links=(),
    )

    assert retrieval_only_queries(candidate) == ("A6383240604",)
