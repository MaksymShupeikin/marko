"""Fail-closed read policy for the long-lived catalog identity graph.

The graph is evidence history, not a mutable cache.  Older reparses therefore
remain in ``catalog_identity_links`` even after an extractor is corrected.  A
reader must apply the current safety policy before a historical edge is allowed
to widen candidate retrieval or enter a pricing run.

Two observed failure classes are rejected here:

* KEMP's private shelf codes (``776...``) are join keys, not public part
  identities.  The 2026-08-04 production audit found 3,374 such values on
  otherwise CONFIRMED edges.
* A number attached to more than one catalog item is ambiguous.  Some cases are
  harmless duplicate rows, but others join different part families or left and
  right variants.  Precision wins: no fan-out number may move a price until it
  is resolved explicitly.
"""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, not_, or_, select, union_all

from marko.infrastructure.db.models import CatalogIdentityLink
from marko.services.semantic_candidate_features import (
    SEMANTIC_FEATURE_EXTRACTOR_VERSION,
)
from metis.pricing.crosses import normalize_cross_oem
from metis.pricing.identity_graph import (
    IdentityGraphConfig,
    is_safe_public_number_shape,
    load_identity_graph_config,
)
from metis.pricing.kemp_site import KempSiteTokensConfig, load_kemp_site_tokens


BACKEND_ROOT = Path(__file__).resolve().parents[3]
_IDENTITY_IMPLEMENTATION_FILES = (
    "src/metis/pricing/identity_graph.py",
    "src/marko/services/catalog_identity_reparse.py",
    "src/marko/services/semantic_candidate_features.py",
)


@lru_cache(maxsize=1)
def catalog_identity_tokens() -> KempSiteTokensConfig:
    """Load the same hashed token contract used by the identity reparse."""

    return load_kemp_site_tokens(BACKEND_ROOT / "config/kemp_site_tokens.yaml")


@lru_cache(maxsize=1)
def active_identity_graph_config() -> IdentityGraphConfig:
    """The exact algorithm/config version a historical edge must match."""

    return load_identity_graph_config(BACKEND_ROOT / "config/identity_graph.yaml")


def identity_runtime_config_sha256(
    graph: IdentityGraphConfig,
    tokens: KempSiteTokensConfig,
) -> str:
    """Fingerprint every config byte that changes identity semantics."""

    payload = {
        "contract": "catalog-identity-runtime-v3",
        "identity_graph_sha256": graph.source_sha256,
        "token_config_sha256": tokens.source_sha256,
        "semantic_feature_extractor_version": (
            SEMANTIC_FEATURE_EXTRACTOR_VERSION
        ),
        "implementation_sha256s": dict(
            identity_runtime_implementation_sha256s()
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@lru_cache(maxsize=1)
def identity_runtime_implementation_sha256s() -> tuple[tuple[str, str], ...]:
    """Hash every implementation file that can change a persisted graph.

    Config hashes alone are insufficient: tokenizer expansion and deterministic
    semantic conflict extraction live in Python.  If any of those algorithms
    changes, old edges must fail the current-read predicate until a new atomic
    reparse recreates them.
    """

    result: list[tuple[str, str]] = []
    for relative in _IDENTITY_IMPLEMENTATION_FILES:
        path = BACKEND_ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"identity implementation file is missing: {path}")
        result.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    return tuple(result)


@lru_cache(maxsize=1)
def active_identity_runtime_sha256() -> str:
    return identity_runtime_config_sha256(
        active_identity_graph_config(), catalog_identity_tokens()
    )


def is_internal_catalog_code(
    value: Any, *, tokens: KempSiteTokensConfig | None = None
) -> bool:
    """Whether ``value`` is a private KEMP shelf code, after normalization."""

    normalized = normalize_cross_oem("" if value is None else str(value))
    if not normalized:
        return False
    contract = tokens or catalog_identity_tokens()
    return contract.internal_code_pattern.fullmatch(normalized) is not None


def catalog_identity_pair_has_safe_shape(
    left: Any,
    right: Any,
    *,
    tokens: KempSiteTokensConfig | None = None,
) -> bool:
    """Reject private or malformed identities before they leave persistence."""

    left_norm = normalize_cross_oem("" if left is None else str(left))
    right_norm = normalize_cross_oem("" if right is None else str(right))
    if (
        not is_safe_public_number_shape(left_norm)
        or not is_safe_public_number_shape(right_norm)
        or left_norm == right_norm
    ):
        return False
    contract = tokens or catalog_identity_tokens()
    return not (
        contract.internal_code_pattern.fullmatch(left_norm)
        or contract.internal_code_pattern.fullmatch(right_norm)
    )


def confirmed_catalog_identity_conditions(workspace_id: UUID) -> tuple[Any, ...]:
    """SQL predicates for current, non-anomalous, non-fan-out evidence.

    The membership CTE includes both orientations of every edge.  Grouping only
    ``extracted_oem_norm`` misses a number that is an anchor for one item and a
    cross for another, which is exactly the ambiguous case this boundary must
    stop.
    """

    active = active_identity_graph_config()
    confirmed = (
        CatalogIdentityLink.workspace_id == workspace_id,
        CatalogIdentityLink.validation_status == "CONFIRMED",
        CatalogIdentityLink.anomaly.is_(None),
        CatalogIdentityLink.method_version == active.method_version,
        CatalogIdentityLink.config_sha256 == active_identity_runtime_sha256(),
    )
    memberships = union_all(
        select(
            CatalogIdentityLink.catalog_item_id.label("catalog_item_id"),
            CatalogIdentityLink.our_oem_norm.label("number"),
        ).where(*confirmed),
        select(
            CatalogIdentityLink.catalog_item_id.label("catalog_item_id"),
            CatalogIdentityLink.extracted_oem_norm.label("number"),
        ).where(*confirmed),
    ).cte("confirmed_catalog_identity_memberships")
    ambiguous = (
        select(memberships.c.number)
        .group_by(memberships.c.number)
        .having(func.count(func.distinct(memberships.c.catalog_item_id)) > 1)
        .cte("ambiguous_catalog_identity_numbers")
    )
    ambiguous_numbers = select(ambiguous.c.number)
    return (
        *confirmed,
        not_(
            or_(
                CatalogIdentityLink.our_oem_norm.in_(ambiguous_numbers),
                CatalogIdentityLink.extracted_oem_norm.in_(ambiguous_numbers),
            )
        ),
    )


__all__ = [
    "active_identity_graph_config",
    "active_identity_runtime_sha256",
    "catalog_identity_pair_has_safe_shape",
    "catalog_identity_tokens",
    "confirmed_catalog_identity_conditions",
    "is_internal_catalog_code",
    "identity_runtime_config_sha256",
    "identity_runtime_implementation_sha256s",
]
