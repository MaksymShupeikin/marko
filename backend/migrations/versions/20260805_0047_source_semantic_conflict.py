"""Quarantine identity edges whose source revisions describe different parts.

Revision ID: 20260805_0047
Revises: 20260804_0046

The two customer reference revisions contain private catalogue keys whose old
and new titles explicitly disagree on physical identity (for example left vs
right).  The rows remain auditable, but their edges must be REVIEW and may not
widen a pricing cohort until adjudicated.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "20260805_0047"
down_revision: str | None = "20260804_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_catalog_identity_link_anomaly"
_TABLE = "catalog_identity_links"
_ANOMALIES_BEFORE = (
    "OE_SOURCE_CONFLICT",
    "SHARED_ARTICLE_FANOUT",
    "OE_SUPERSEDED_BY_NEWER_REFERENCE",
    "STALE_AFTER_REPARSE",
)
_ANOMALIES_AFTER = (
    *_ANOMALIES_BEFORE,
    "SOURCE_SEMANTIC_CONFLICT",
    "PUBLIC_NUMBER_SEMANTIC_FANOUT",
)


def _condition(names: tuple[str, ...]) -> str:
    listed = ", ".join(f"'{name}'" for name in names)
    return f"anomaly IS NULL OR anomaly IN ({listed})"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _condition(_ANOMALIES_AFTER))


def downgrade() -> None:
    conflicting = int(
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM catalog_identity_links "
            "WHERE anomaly IN "
            "('SOURCE_SEMANTIC_CONFLICT', 'PUBLIC_NUMBER_SEMANTIC_FANOUT')"
        )
        .scalar_one()
    )
    if conflicting:
        raise RuntimeError(
            f"{conflicting} link(s) carry SOURCE_SEMANTIC_CONFLICT or "
            "PUBLIC_NUMBER_SEMANTIC_FANOUT; preserve or adjudicate them "
            "deliberately before downgrading"
        )
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _condition(_ANOMALIES_BEFORE))
