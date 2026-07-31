"""Two editions of one reference book are one voice a year apart (2026-07-30).

Both reference files used to be loaded under a single ``KEMP_REFERENCE_MAP``
source, so a number that changed between them looked exactly like two sources
contradicting each other. That is why 158 positions carried
``OE_SOURCE_CONFLICT`` with no way to settle it: nothing in the data said which
file was current.

The customer said it — "the first file is a year old, the second is from
yesterday" — and that is a resolution rule we did not have. It is recorded as an
ordinal, not a date: his sentence fixes the order of the two files and nothing
finer, and inventing a delivery date from it would be inventing evidence.

What recency does and does not buy is worth stating plainly. It decides *whose
number to prefer*. It does not prove the two numbers are the same part, so the
superseded number is not deleted and not confirmed — a number can be replaced and
still be a real number the part was sold under, which a competitor may well be
listing it by today.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from metis.pricing.identity_graph import (
    Anomaly,
    IdentityGraphConfigError,
    LinkStatus,
    SourceNumbers,
    build_identity_graph,
    load_identity_graph_config,
)

BACKEND = Path(__file__).resolve().parents[1]
CONFIG_PATH = BACKEND / "config/identity_graph.yaml"

OWN = "OWN_EXPORT_CHARACTERISTIC"
NEW = "KEMP_REFERENCE_MAP_V2"
OLD = "KEMP_REFERENCE_MAP_V1"
SITE = "KEMP_SITE"


@pytest.fixture(scope="module")
def config():
    return load_identity_graph_config(CONFIG_PATH)


def _build(config, own_code="77647977", **by_source):
    return build_identity_graph(
        own_code=own_code,
        sources=[
            SourceNumbers(
                extraction_method=name,
                numbers=tuple(numbers),
                raw_context=f"{name} context",
            )
            for name, numbers in by_source.items()
        ],
        config=config,
    )


def _link(graph, number):
    return next(link for link in graph.links if link.extracted_oem_norm == number)


# ------------------------------------------------------------- the supersession


def test_the_two_editions_disagreeing_is_no_longer_a_conflict(config) -> None:
    graph = _build(config, **{NEW: ("7701059269",), OLD: ("7701050685",)})

    assert Anomaly.OE_SOURCE_CONFLICT.value not in graph.anomalies


def test_the_current_edition_anchors_the_graph(config) -> None:
    graph = _build(config, **{NEW: ("7701059269",), OLD: ("7701050685",)})

    assert graph.canonical == "7701059269"
    assert graph.canonical_source == NEW


def test_the_replaced_number_is_kept_flagged_and_kept_out_of_pricing(config) -> None:
    graph = _build(config, **{NEW: ("7701059269",), OLD: ("7701050685",)})

    link = _link(graph, "7701050685")
    assert link.anomaly == Anomaly.OE_SUPERSEDED_BY_NEWER_REFERENCE.value
    assert link.validation_status is LinkStatus.REVIEW
    assert link.is_confirmed is False
    assert Anomaly.OE_SUPERSEDED_BY_NEWER_REFERENCE.value in graph.anomalies


def test_the_current_edition_still_confirms_its_own_numbers(config) -> None:
    """This is the unblocking: a current-book number is as good as it ever was."""

    graph = _build(config, own_code="77641229", **{NEW: ("1K0413031BK", "1K0413031BJ")})

    # Both are genuine OEs of one part, so the tie falls to the lexicographic
    # rule rather than to a pretence that one is more specific than the other.
    assert graph.canonical == "1K0413031BJ"
    assert graph.confirmed_numbers == ("1K0413031BK",)


def test_a_number_both_editions_name_is_not_superseded(config) -> None:
    graph = _build(
        config,
        own_code="77641229",
        **{NEW: ("1K0413031BK", "8D0598625"), OLD: ("8D0598625",)},
    )

    link = _link(graph, "8D0598625")
    assert link.anomaly is None
    assert link.validation_status is LinkStatus.CONFIRMED


def test_the_older_edition_alone_supersedes_nothing(config) -> None:
    """Absence of data is not disproof — the same rule that bars REJECTED here.

    If the current book says nothing about this item, the year-old number is all
    anyone has, and it is not made worse by the existence of a newer file.
    """

    graph = _build(config, own_code="77641229", **{OLD: ("1K0413031BK", "8D0598625")})

    link = _link(graph, "8D0598625")
    assert link.anomaly is None
    assert link.validation_status is LinkStatus.CONFIRMED
    assert graph.anomalies == ()


# ------------------------------------------- what recency deliberately does not do


def test_the_site_disagreeing_with_the_book_is_still_a_conflict(config) -> None:
    """Different publishers is the case recency says nothing about."""

    graph = _build(config, **{NEW: ("7701059269",), SITE: ("7701050685",)})

    assert Anomaly.OE_SOURCE_CONFLICT.value in graph.anomalies


def test_a_superseded_edition_no_longer_argues_with_the_site(config) -> None:
    """Otherwise the year-old number would reopen the case recency just closed."""

    graph = _build(
        config,
        **{NEW: ("7701059269",), OLD: ("7701050685",), SITE: ("7701059269",)},
    )

    assert Anomaly.OE_SOURCE_CONFLICT.value not in graph.anomalies
    assert _link(graph, "7701050685").anomaly == (
        Anomaly.OE_SUPERSEDED_BY_NEWER_REFERENCE.value
    )


def test_a_cross_list_is_still_not_an_objection(config) -> None:
    graph = _build(
        config,
        own_code="77641229",
        **{NEW: ("1K0413031BK",), OWN: ("27C06F",)},
    )

    assert graph.anomalies == ()


# ------------------------------------------------------------ the dataset registry


def test_both_shipped_reference_files_resolve_to_their_own_source(config) -> None:
    """The hash in the config must be the hash of the file on disk.

    A stale hash here is the quiet failure this test exists for: the loader would
    refuse the real file, or worse, a replaced file would inherit the standing of
    the one that was checked against a control sample.
    """

    expected = {
        "kemp_reference_map.csv": OLD,
        "kemp_oe_map.csv": NEW,
    }
    for filename, source in expected.items():
        digest = hashlib.sha256(
            (BACKEND / "data" / filename).read_bytes()
        ).hexdigest()
        assert config.source_for_dataset(digest) == source


def test_an_unrecognised_reference_file_is_refused_not_trusted(config) -> None:
    with pytest.raises(IdentityGraphConfigError, match="No declared dataset"):
        config.source_for_dataset("0" * 64)


def test_a_hash_is_matched_case_insensitively(config) -> None:
    digest = hashlib.sha256(
        (BACKEND / "data" / "kemp_oe_map.csv").read_bytes()
    ).hexdigest()

    assert config.source_for_dataset(digest.upper()) == NEW


# ------------------------------------------------------------ config validation

_HEADER = "schema_version: metis-identity-graph-v1\nmethod_version: t\n"
_CANONICAL = (
    "canonical:\n"
    f"  source_preference: [{NEW}, {OLD}]\n"
    "  rules: [SOURCE_PREFERENCE, LEXICOGRAPHIC]\n"
)
_ANOMALIES = (
    "anomalies:\n"
    "  - {name: OE_SOURCE_CONFLICT, review_required: true}\n"
    "  - {name: SHARED_ARTICLE_FANOUT, review_required: true}\n"
    "  - {name: OE_SUPERSEDED_BY_NEWER_REFERENCE, review_required: true}\n"
)


def _write(tmp_path, sources: str, datasets: str = "") -> Path:
    path = tmp_path / "graph.yaml"
    path.write_text(_HEADER + sources + _CANONICAL + _ANOMALIES + datasets, "utf-8")
    return path


def _pair(new_vintage: int = 2, old_vintage: int = 1) -> str:
    return (
        "sources:\n"
        f"  - {{name: {NEW}, status: CONFIRMED, asserts_oe: true,"
        f" publisher: book, vintage: {new_vintage}}}\n"
        f"  - {{name: {OLD}, status: CONFIRMED, asserts_oe: true,"
        f" publisher: book, vintage: {old_vintage}}}\n"
    )


def test_two_editions_sharing_a_vintage_are_refused(tmp_path) -> None:
    """A tie inside one publisher leaves the direction of supersession undefined."""

    with pytest.raises(IdentityGraphConfigError, match="share publisher"):
        load_identity_graph_config(_write(tmp_path, _pair(new_vintage=1)))


@pytest.mark.parametrize(
    "field",
    ("publisher: book, ", "vintage: 2, "),
)
def test_a_source_without_publisher_or_vintage_is_refused(tmp_path, field) -> None:
    sources = (
        "sources:\n"
        f"  - {{name: {NEW}, status: CONFIRMED, asserts_oe: true,"
        f" {field.replace(', ', '')}}}\n"
        f"  - {{name: {OLD}, status: CONFIRMED, asserts_oe: true,"
        " publisher: book, vintage: 1}\n"
    )

    with pytest.raises(IdentityGraphConfigError):
        load_identity_graph_config(_write(tmp_path, sources))


@pytest.mark.parametrize(
    "digest",
    ("abc", "z" * 64, ""),
)
def test_a_malformed_dataset_hash_is_refused(tmp_path, digest) -> None:
    datasets = f'datasets:\n  - {{sha256: "{digest}", source: {NEW}}}\n'

    with pytest.raises(IdentityGraphConfigError):
        load_identity_graph_config(_write(tmp_path, _pair(), datasets))


def test_a_dataset_naming_an_undeclared_source_is_refused(tmp_path) -> None:
    datasets = f"datasets:\n  - {{sha256: {'a' * 64}, source: SOMETHING_ELSE}}\n"

    with pytest.raises(IdentityGraphConfigError, match="undeclared source"):
        load_identity_graph_config(_write(tmp_path, _pair(), datasets))


def test_two_datasets_with_the_same_hash_are_refused(tmp_path) -> None:
    datasets = (
        "datasets:\n"
        f"  - {{sha256: {'a' * 64}, source: {NEW}}}\n"
        f"  - {{sha256: {'a' * 64}, source: {OLD}}}\n"
    )

    with pytest.raises(IdentityGraphConfigError, match="Duplicate dataset"):
        load_identity_graph_config(_write(tmp_path, _pair(), datasets))
