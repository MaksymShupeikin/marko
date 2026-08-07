"""The source-only identity artifact must identify the code that built it."""

from __future__ import annotations

from pathlib import Path

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

    assert contract["identity_graph_method_version"] == "identity-graph-v4"
    assert contract["identity_graph_config_sha256"] == graph.source_sha256
    assert contract["token_config_sha256"] == tokens.source_sha256
    assert (
        contract["semantic_feature_extractor_version"]
        == SEMANTIC_FEATURE_EXTRACTOR_VERSION
    )
    assert set(contract["implementation_sha256s"]) == {
        "src/metis/pricing/identity_graph.py",
        "src/marko/services/catalog_identity_reparse.py",
        "src/marko/services/semantic_candidate_features.py",
    }
    assert contract["runtime_config_sha256"] == identity_runtime_config_sha256(
        graph, tokens
    )
