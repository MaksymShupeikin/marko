"""The long-lived identity graph must remain safe after extractor changes."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from marko.infrastructure.db.models import CatalogIdentityLink
from marko.services.catalog_identity_safety import (
    active_identity_graph_config,
    active_identity_runtime_sha256,
    catalog_identity_pair_has_safe_shape,
    catalog_identity_tokens,
    confirmed_catalog_identity_conditions,
    identity_runtime_config_sha256,
    identity_runtime_implementation_sha256s,
    is_internal_catalog_code,
)
from marko.services import catalog_identity_safety


def test_private_kemp_code_is_not_a_public_part_identity() -> None:
    assert is_internal_catalog_code("776 415") is True
    assert is_internal_catalog_code("1086282") is False
    assert catalog_identity_pair_has_safe_shape("1086282", "776415") is False
    assert catalog_identity_pair_has_safe_shape("1086282", "TH652688J") is True


def test_malformed_or_self_referential_pairs_fail_closed() -> None:
    assert catalog_identity_pair_has_safe_shape("", "1086282") is False
    assert catalog_identity_pair_has_safe_shape("1086-282", "1086282") is False
    assert catalog_identity_pair_has_safe_shape("1086282", "MG") is False
    assert catalog_identity_pair_has_safe_shape("1086282", "0") is False
    assert catalog_identity_pair_has_safe_shape("1086282", "KL2") is True


def test_sql_boundary_rejects_anomalies_and_cross_item_fanout() -> None:
    statement = select(CatalogIdentityLink).where(
        *confirmed_catalog_identity_conditions(uuid4())
    )
    rendered = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "catalog_identity_links.validation_status = 'CONFIRMED'" in rendered
    assert "catalog_identity_links.anomaly IS NULL" in rendered
    active = active_identity_graph_config()
    assert (
        f"catalog_identity_links.method_version = '{active.method_version}'" in rendered
    )
    assert (
        f"catalog_identity_links.config_sha256 = '{active_identity_runtime_sha256()}'"
    ) in rendered
    assert "UNION ALL" in rendered
    assert "count(distinct" in rendered.lower()
    assert "ambiguous_catalog_identity_numbers" in rendered


def test_runtime_hash_binds_every_identity_implementation_file() -> None:
    hashes = dict(identity_runtime_implementation_sha256s())

    assert set(hashes) == {
        "src/metis/pricing/identity_graph.py",
        "src/marko/services/catalog_identity_reparse.py",
        "src/marko/services/semantic_candidate_features.py",
    }
    assert all(len(value) == 64 for value in hashes.values())


def test_runtime_hash_changes_when_identity_implementation_changes(
    monkeypatch,
) -> None:
    graph = active_identity_graph_config()
    tokens = catalog_identity_tokens()
    baseline = identity_runtime_config_sha256(graph, tokens)

    monkeypatch.setattr(
        catalog_identity_safety,
        "identity_runtime_implementation_sha256s",
        lambda: (("changed.py", "0" * 64),),
    )

    assert identity_runtime_config_sha256(graph, tokens) != baseline
