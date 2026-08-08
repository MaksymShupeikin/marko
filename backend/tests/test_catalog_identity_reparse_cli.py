"""The source-only identity artifact must identify the code that built it."""

from __future__ import annotations

from pathlib import Path

import marko.catalog_identity_reparse_cli as cli
from marko.catalog_identity_reparse_cli import _contract_summary
from marko.services.catalog_identity_safety import (
    identity_runtime_config_sha256,
)
from marko.services.semantic_candidate_features import (
    SEMANTIC_FEATURE_EXTRACTOR_VERSION,
)
from metis.pricing.identity_graph import load_identity_graph_config
from metis.pricing.kemp_site import load_kemp_site_tokens


BACKEND = Path(__file__).resolve().parents[1]


def test_contract_summary_pins_config_tokens_extractor_and_implementation() -> None:
    graph = load_identity_graph_config(BACKEND / "config/identity_graph.yaml")
    tokens = load_kemp_site_tokens(BACKEND / "config/kemp_site_tokens.yaml")

    contract = _contract_summary(graph, tokens)

    assert contract["identity_graph_method_version"] == "identity-graph-v6"
    assert contract["identity_graph_config_sha256"] == graph.source_sha256
    assert contract["token_config_sha256"] == tokens.source_sha256
    assert (
        contract["semantic_feature_extractor_version"]
        == SEMANTIC_FEATURE_EXTRACTOR_VERSION
    )
    assert set(contract["implementation_sha256s"]) == {
        "src/metis/pricing/identity_graph.py",
        "src/marko/services/catalog_identity_reparse.py",
        "src/marko/services/parser_models.py",
        "src/marko/parsers/prom/gateway.py",
        "src/marko/services/semantic_candidate_features.py",
    }
    assert contract["runtime_config_sha256"] == identity_runtime_config_sha256(
        graph, tokens
    )


def test_the_plan_reads_the_shipped_spareto_confirmations_by_default(monkeypatch) -> None:
    """A dataset that ships in data/ but that nothing loads is not a source.

    The confirmations are pinned by sha256 in identity_graph.yaml and worth 178
    codes; before this the only way to see them was a hand-written harness.
    """

    captured: dict[str, object] = {}

    def _capture(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(cli, "build_source_index", _capture)

    cli._build_index(cli._parser().parse_args(["plan"]))
    assert [Path(str(path)).name for path in captured["spareto_paths"]] == [
        "spareto_oe_confirmations.csv"
    ]

    captured.clear()
    cli._build_index(cli._parser().parse_args(["plan", "--no-spareto"]))
    assert captured["spareto_paths"] == []
