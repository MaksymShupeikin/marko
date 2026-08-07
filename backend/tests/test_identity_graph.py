"""The number graph of one catalog item (WP-3).

What is under test is mostly restraint: the graph must not fuse parts it cannot
prove are the same, must not reject a pair merely because one source is silent
about it, and must produce the same edges on two runs over the same data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from metis.pricing.crosses import normalize_cross_oem
from metis.pricing.identity_graph import (
    DISCARD_EMPTY_AFTER_NORMALIZATION,
    DISCARD_SELF_REFERENCE,
    DISCARD_UNSAFE_PUBLIC_NUMBER_SHAPE,
    DISCARD_UNKNOWN_SOURCE,
    IDENTITY_GRAPH_SCHEMA_VERSION,
    Anomaly,
    IdentityGraphConfigError,
    LinkStatus,
    SourceNumbers,
    build_identity_graph,
    load_identity_graph_config,
    shared_article_numbers,
)

BACKEND = Path(__file__).resolve().parents[1]
CONFIG_PATH = BACKEND / "config/identity_graph.yaml"

OWN = "OWN_EXPORT_CHARACTERISTIC"
MAP = "KEMP_REFERENCE_MAP_V2"
#: The year-old edition of the same book, kept as its own source since 2026-07-30.
MAP_OLD = "KEMP_REFERENCE_MAP_V1"
SITE = "KEMP_SITE"


@pytest.fixture(scope="module")
def config():
    return load_identity_graph_config(CONFIG_PATH)


def _build(config, own_code="77641229", shared=frozenset(), **by_source):
    sources = [
        SourceNumbers(
            extraction_method=name,
            numbers=tuple(numbers),
            raw_context=f"{name} context",
        )
        for name, numbers in by_source.items()
    ]
    return build_identity_graph(
        own_code=own_code,
        sources=sources,
        config=config,
        shared_article_numbers=shared,
    )


def _link(graph, number):
    return next(
        link for link in graph.links if link.extracted_oem_norm == number
    )


# --- the configuration ------------------------------------------------------


#: The reference book's article column: the same file, but a claim about a cross
#: rather than about the OE, so it is its own source with ``asserts_oe: false``.
ARTICLE = "KEMP_REFERENCE_ARTICLE"


def test_the_shipped_config_declares_its_sources_newest_edition_first(config) -> None:
    assert config.trust_order == (OWN, "OWN_EXPORT_CODE", MAP, MAP_OLD, ARTICLE, SITE)
    assert config.sources[ARTICLE].asserts_oe is False
    assert config.sources[OWN].status is LinkStatus.CONFIRMED
    assert config.sources[MAP].status is LinkStatus.CONFIRMED
    assert config.sources[SITE].status is LinkStatus.REVIEW


def test_only_oe_asserting_sources_can_contradict(config) -> None:
    """The seller's cross list is not a claim about which OE the part has, so
    its silence about a number is not an objection to it."""

    assert config.sources[OWN].asserts_oe is False
    assert config.sources[MAP].asserts_oe is True
    assert config.sources[SITE].asserts_oe is True


def test_anchor_preference_differs_from_status_trust(config) -> None:
    """Two different questions: who is reliable, and which number identifies the
    part. The reference map's OE anchors the graph even though the seller's own
    export is the more reliable statement."""

    assert config.trust_order[0] == OWN
    assert config.canonical_source_preference[0] == MAP


def test_config_is_hashed(config) -> None:
    assert len(config.source_sha256) == 64
    assert config.method_version == "identity-graph-v4"


def test_source_semantic_conflict_quarantines_every_edge(config) -> None:
    graph = build_identity_graph(
        own_code="PRIVATE",
        sources=[
            SourceNumbers("KEMP_REFERENCE_MAP_V2", ("OE-1-NEW",), "new right"),
            SourceNumbers("KEMP_REFERENCE_ARTICLE", ("CROSS-1",), "old left"),
        ],
        config=config,
        source_semantic_conflict=True,
    )

    assert graph.anomalies == (Anomaly.SOURCE_SEMANTIC_CONFLICT.value,)
    assert graph.links
    assert all(link.validation_status is LinkStatus.REVIEW for link in graph.links)
    assert all(
        link.anomaly == Anomaly.SOURCE_SEMANTIC_CONFLICT.value
        for link in graph.links
    )


def test_public_semantic_fanout_quarantines_a_canonical_only_graph(config) -> None:
    graph = build_identity_graph(
        own_code="PRIVATE",
        sources=[SourceNumbers("KEMP_REFERENCE_MAP_V2", ("1K0905851",), "lock")],
        config=config,
        public_number_semantic_fanout=frozenset({"1K0905851"}),
    )

    assert graph.canonical == "1K0905851"
    assert graph.links == ()
    assert graph.anomalies == (Anomaly.PUBLIC_NUMBER_SEMANTIC_FANOUT.value,)


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "graph.yaml"
    path.write_text(body, encoding="utf-8")
    return path


HEAD = f"schema_version: {IDENTITY_GRAPH_SCHEMA_VERSION}\nmethod_version: t\n"
SOURCES = (
    "sources:\n"
    f"  - {{name: {OWN}, status: CONFIRMED, asserts_oe: false,"
    " publisher: own, vintage: 1}\n"
    f"  - {{name: {MAP}, status: CONFIRMED, asserts_oe: true,"
    " publisher: book, vintage: 2}\n"
    f"  - {{name: {SITE}, status: REVIEW, asserts_oe: true,"
    " publisher: site, vintage: 1}\n"
)
CANONICAL = (
    "canonical:\n"
    f"  source_preference: [{MAP}, {OWN}, {SITE}]\n"
    "  rules: [SOURCE_PREFERENCE, LEXICOGRAPHIC]\n"
)
ANOMALIES = (
    "anomalies:\n"
    "  - {name: OE_SOURCE_CONFLICT, review_required: true}\n"
    "  - {name: SHARED_ARTICLE_FANOUT, review_required: true}\n"
)


def test_missing_config_raises(tmp_path) -> None:
    with pytest.raises(IdentityGraphConfigError):
        load_identity_graph_config(tmp_path / "absent.yaml")


def test_unknown_schema_raises(tmp_path) -> None:
    body = "schema_version: other\nmethod_version: t\n" + SOURCES + CANONICAL + ANOMALIES

    with pytest.raises(IdentityGraphConfigError, match="schema"):
        load_identity_graph_config(_write(tmp_path, body))


def test_a_source_declared_rejected_is_refused(tmp_path) -> None:
    """REJECTED is not merely unsupported, it is forbidden: these sources can be
    silent about a link but cannot disprove it."""

    body = (
        HEAD
        + "sources:\n"
        + f"  - {{name: {MAP}, status: REJECTED, asserts_oe: true}}\n"
        + f"canonical:\n  source_preference: [{MAP}]\n  rules: [LEXICOGRAPHIC]\n"
        + ANOMALIES
    )

    with pytest.raises(IdentityGraphConfigError, match="CONFIRMED or REVIEW"):
        load_identity_graph_config(_write(tmp_path, body))


def test_rules_not_ending_in_a_total_order_are_refused(tmp_path) -> None:
    """Otherwise two numbers the earlier rules cannot separate get ordered by
    whatever the input happened to look like, and the graph stops being
    reproducible across runs."""

    body = (
        HEAD
        + SOURCES
        + f"canonical:\n  source_preference: [{MAP}, {OWN}, {SITE}]\n"
        "  rules: [SOURCE_PREFERENCE]\n"
        + ANOMALIES
    )

    with pytest.raises(IdentityGraphConfigError, match="fully orders"):
        load_identity_graph_config(_write(tmp_path, body))


def test_a_source_absent_from_the_anchor_preference_is_refused(tmp_path) -> None:
    body = (
        HEAD
        + SOURCES
        + f"canonical:\n  source_preference: [{MAP}, {OWN}]\n"
        "  rules: [SOURCE_PREFERENCE, LEXICOGRAPHIC]\n"
        + ANOMALIES
    )

    with pytest.raises(IdentityGraphConfigError, match="every source exactly once"):
        load_identity_graph_config(_write(tmp_path, body))


def test_an_anomaly_that_needs_no_review_is_refused(tmp_path) -> None:
    """An anomaly nobody has to look at is a note nobody reads."""

    body = (
        HEAD
        + SOURCES
        + CANONICAL
        + "anomalies:\n  - {name: OE_SOURCE_CONFLICT, review_required: false}\n"
    )

    with pytest.raises(IdentityGraphConfigError, match="review_required"):
        load_identity_graph_config(_write(tmp_path, body))


def test_an_unknown_anomaly_name_is_refused(tmp_path) -> None:
    body = (
        HEAD
        + SOURCES
        + CANONICAL
        + "anomalies:\n  - {name: SOMETHING_NEW, review_required: true}\n"
    )

    with pytest.raises(IdentityGraphConfigError, match="Unknown anomaly"):
        load_identity_graph_config(_write(tmp_path, body))


def test_duplicate_canonical_rule_is_refused(tmp_path) -> None:
    body = (
        HEAD
        + SOURCES
        + f"canonical:\n  source_preference: [{MAP}, {OWN}, {SITE}]\n"
        "  rules: [LEXICOGRAPHIC, LEXICOGRAPHIC]\n"
        + ANOMALIES
    )

    with pytest.raises(IdentityGraphConfigError, match="Duplicate canonical rule"):
        load_identity_graph_config(_write(tmp_path, body))


# --- statuses ---------------------------------------------------------------


def test_own_export_numbers_are_confirmed(config) -> None:
    graph = _build(config, **{OWN: ("27C06F", "1K0413031BK")})

    assert {link.validation_status for link in graph.links} == {LinkStatus.CONFIRMED}
    assert graph.links[0].extraction_method == OWN


def test_reference_map_numbers_are_confirmed(config) -> None:
    graph = _build(config, **{MAP: ("1K0413031BK", "1K0413031BJ")})

    assert {link.validation_status for link in graph.links} == {LinkStatus.CONFIRMED}


def test_site_numbers_are_born_under_review(config) -> None:
    """The card's field labels are unreliable (NO_9) and the site was never
    checked against a control sample, so its edges move no price by themselves."""

    graph = _build(config, **{SITE: ("1K0413031BK", "8D0598625")})

    assert {link.validation_status for link in graph.links} == {LinkStatus.REVIEW}


def test_nothing_from_these_sources_is_ever_rejected(config) -> None:
    graph = _build(
        config,
        shared=frozenset({"8D0598625"}),
        **{OWN: ("27C06F",), MAP: ("1K0413031BK",), SITE: ("8D0598625",)},
    )

    assert {link.validation_status for link in graph.links} <= {
        LinkStatus.CONFIRMED,
        LinkStatus.REVIEW,
    }


def test_two_sources_naming_the_same_pair_promote_it_out_of_review(config) -> None:
    """The only automatic route out of REVIEW: an unverified source agreeing
    with a verified one is evidence; one source alone is not."""

    graph = _build(config, **{MAP: ("8D0598625",), SITE: ("8D0598625", "7L0498287")})

    assert _link(graph, "7L0498287").validation_status is LinkStatus.REVIEW
    assert graph.canonical == "8D0598625"


def test_corroboration_is_recorded_on_the_link(config) -> None:
    graph = _build(
        config,
        **{
            MAP: ("1K0413031BK",),
            OWN: ("27C06F",),
            SITE: ("1K0413031BK", "27C06F"),
        },
    )

    assert _link(graph, "27C06F").corroborating_sources == (OWN, SITE)
    assert _link(graph, "27C06F").validation_status is LinkStatus.CONFIRMED


# --- the anchor -------------------------------------------------------------


def test_the_reference_oe_anchors_the_graph_over_a_sellers_cross(config) -> None:
    """A cross list can hold a supplier number; the anchor should be the OE."""

    graph = _build(config, **{OWN: ("27C06F", "115 070"), MAP: ("1K0413031BK",)})

    assert graph.canonical == "1K0413031BK"
    assert graph.canonical_source == MAP


def test_the_anchor_is_not_repeated_as_an_edge(config) -> None:
    graph = _build(config, **{MAP: ("1K0413031BK",), OWN: ("27C06F",)})

    assert graph.canonical == "1K0413031BK"
    assert [link.extracted_oem_norm for link in graph.links] == ["27C06F"]


def test_every_edge_starts_at_the_anchor_so_the_graph_is_a_star(config) -> None:
    """No edge between two non-anchor numbers: transitivity is not introduced
    here, because one wrong fusion prices our part off somebody else's."""

    graph = _build(config, **{MAP: ("1K0413031BK",), OWN: ("27C06F", "115070", "9A9")})

    assert {link.our_oem_norm for link in graph.links} == {"1K0413031BK"}


def test_two_oes_from_one_source_are_ordered_not_judged(config) -> None:
    """Between two genuine factory numbers there is no substantive winner, so
    the tie is broken stably rather than by pretending to judge."""

    graph = _build(config, **{MAP: ("056121113D", "050121113C")})

    assert graph.canonical == "050121113C"
    assert graph.all_numbers == ("050121113C", "056121113D")


def test_the_anchor_does_not_depend_on_input_order(config) -> None:
    forward = _build(config, **{MAP: ("056121113D", "050121113C")})
    backward = _build(config, **{MAP: ("050121113C", "056121113D")})

    assert forward.canonical == backward.canonical
    assert forward.links == backward.links


def test_an_item_with_no_numbers_yields_an_empty_graph(config) -> None:
    graph = _build(config)

    assert graph.canonical == ""
    assert graph.canonical_source is None
    assert graph.links == ()


def test_a_site_only_item_is_anchored_on_an_unverified_number(config) -> None:
    """Recording the limit: with the site as the only source the anchor itself
    was never verified, and ``canonical_source`` is how a caller can tell."""

    graph = _build(config, **{SITE: ("8D0598625", "7L0498287")})

    assert graph.canonical_source == SITE
    assert graph.confirmed_numbers == ()


# --- what never enters the graph --------------------------------------------


def test_our_own_code_is_discarded_as_a_self_reference(config) -> None:
    graph = _build(config, own_code="77641229", **{SITE: ("77641229",)})

    assert graph.links == ()
    assert graph.discarded["77641229"] == DISCARD_SELF_REFERENCE


def test_a_self_reference_written_with_a_space_is_still_caught(config) -> None:
    """``115 070`` and ``115070`` are one number (WP-1), and so are these."""

    graph = _build(config, own_code="77641229", **{OWN: ("7764 1229",)})

    assert graph.discarded["7764 1229"] == DISCARD_SELF_REFERENCE


def test_punctuation_only_values_are_reported_not_silently_dropped(config) -> None:
    graph = _build(config, **{OWN: ("---", "1K0413031BK")})

    assert graph.discarded["---"] == DISCARD_EMPTY_AFTER_NORMALIZATION
    assert graph.all_numbers == ("1K0413031BK",)


@pytest.mark.parametrize(
    "raw",
    ("0", "000", "MG", "Fiat/Alfa/Lancia", "L"),
)
def test_unsafe_public_number_shapes_are_reported_and_discarded(
    config, raw: str
) -> None:
    graph = _build(config, **{ARTICLE: (raw,)})

    assert graph.links == ()
    assert graph.discarded[raw] == DISCARD_UNSAFE_PUBLIC_NUMBER_SHAPE


@pytest.mark.parametrize("raw", ("KL2", "S5G", "04", "A1"))
def test_short_public_numbers_with_digits_are_preserved(config, raw: str) -> None:
    graph = _build(config, **{ARTICLE: (raw,)})

    assert graph.all_numbers == (raw,)


def test_numbers_from_an_undeclared_source_are_refused_and_reported(config) -> None:
    """A source nobody assigned a status to must not default into the graph."""

    graph = build_identity_graph(
        own_code="77641229",
        sources=[SourceNumbers("SOME_NEW_SOURCE", ("1K0413031BK",))],
        config=config,
    )

    assert graph.links == ()
    assert graph.discarded["1K0413031BK"] == DISCARD_UNKNOWN_SOURCE


# --- anomalies --------------------------------------------------------------


def test_disjoint_oe_claims_are_flagged_as_a_conflict(config) -> None:
    """Position 77647977: the map says 7701059269, the card says 7701050685.
    One may supersede the other; nothing in our data can tell."""

    graph = _build(
        config,
        own_code="77647977",
        **{MAP: ("7701059269",), SITE: ("7701050685",)},
    )

    assert graph.anomalies == (Anomaly.OE_SOURCE_CONFLICT.value,)
    assert graph.canonical == "7701059269"
    conflicting = _link(graph, "7701050685")
    assert conflicting.anomaly == Anomaly.OE_SOURCE_CONFLICT.value
    assert conflicting.validation_status is LinkStatus.REVIEW


def test_the_conflicting_number_is_kept_not_dropped(config) -> None:
    """Silently keeping one would lose the case where the number was superseded
    and the other source is the right one."""

    graph = _build(
        config,
        own_code="77647977",
        **{MAP: ("7701059269",), SITE: ("7701050685",)},
    )

    assert "7701050685" in graph.all_numbers


def test_overlapping_claims_are_agreement_not_conflict(config) -> None:
    graph = _build(config, **{MAP: ("1K0413031BK",), SITE: ("1K0413031BK", "8D0598625")})

    assert graph.anomalies == ()


def test_a_silent_cross_list_does_not_create_a_conflict(config) -> None:
    """The reference map routinely supplies an OE the seller never wrote down —
    that is the whole reason it exists, not a disagreement."""

    graph = _build(config, **{OWN: ("27C06F",), MAP: ("1K0413031BK",)})

    assert graph.anomalies == ()
    assert _link(graph, "27C06F").validation_status is LinkStatus.CONFIRMED


def test_several_oes_from_one_source_are_not_a_conflict(config) -> None:
    """One part really does ship under several factory numbers."""

    graph = _build(config, **{MAP: ("056121113D", "050121113C")})

    assert graph.anomalies == ()


def test_a_shared_article_is_flagged_and_demoted(config) -> None:
    """151 articles of the reference map belong to several internal codes.
    Merging them automatically leads straight to comparing our price against a
    different part (M9)."""

    graph = _build(
        config,
        shared=frozenset({"606554"}),
        **{OWN: ("606554",), MAP: ("1K0413031BK",)},
    )

    assert graph.anomalies == (Anomaly.SHARED_ARTICLE_FANOUT.value,)
    link = _link(graph, "606554")
    assert link.anomaly == Anomaly.SHARED_ARTICLE_FANOUT.value
    assert link.validation_status is LinkStatus.REVIEW


def test_a_shared_anchor_taints_every_edge(config) -> None:
    graph = _build(
        config,
        shared=frozenset({"1K0413031BK"}),
        **{MAP: ("1K0413031BK",), OWN: ("27C06F", "115070")},
    )

    assert all(
        link.anomaly == Anomaly.SHARED_ARTICLE_FANOUT.value for link in graph.links
    )


def test_shared_article_detection_finds_the_fanout(config) -> None:
    shared = shared_article_numbers(
        {
            "77641229": ["27C06F"],
            "77641230": ["27C06F"],
            "77641231": ["606554"],
        }
    )

    assert shared == frozenset({"27C06F"})


def test_shared_article_detection_normalizes_before_comparing() -> None:
    shared = shared_article_numbers(
        {"77641229": ["115 070"], "77641230": ["115070"]}
    )

    assert shared == frozenset({"115070"})


# --- audit evidence ---------------------------------------------------------


def test_each_link_carries_the_text_it_was_read_from(config) -> None:
    graph = build_identity_graph(
        own_code="77641229",
        sources=[
            SourceNumbers(OWN, ("27C06F", "115 070"), "Кросс-номери: 27C06F, 115 070"),
            SourceNumbers(MAP, ("1K0413031BK",), "справочник, строка 77641229"),
        ],
        config=config,
    )

    assert _link(graph, "115070").raw_context == "Кросс-номери: 27C06F, 115 070"
    assert _link(graph, "115070").extracted_raw == "115 070"


def test_the_raw_form_survives_normalization(config) -> None:
    """``6455.EE`` carries its punctuation as a marque signal that
    normalization erases, so the original is kept beside it."""

    graph = _build(config, **{MAP: ("6455.EE", "1K0413031BK")})

    assert _link(graph, "6455EE").extracted_raw == "6455.EE"


# --- the normalization trap -------------------------------------------------


def test_the_two_normalizers_in_the_repo_still_agree() -> None:
    """``normalize_cross_oem`` seeds the graph and ``norm_oem`` reads it back.
    Both delegate to one identifier contract; this assertion protects the
    public wrappers used on the write and read sides of the graph."""

    from metis.pricing import normalize_candidate_oem

    for value in (
        "115 070",
        "6455.EE",
        "1k0413031bk",
        "ОЕ-123",
        "OP-WP-5571",
        "А123",
        "4А0807345A",
        "",
    ):
        assert normalize_cross_oem(value) == normalize_candidate_oem(value)
