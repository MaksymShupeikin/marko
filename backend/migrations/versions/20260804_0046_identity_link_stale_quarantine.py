"""Allow stale identity evidence to be preserved but quarantined.

Revision ID: 20260804_0046
Revises: 20260804_0045

An identity reparse is atomic and append-preserving.  Before rebuilding a
workspace graph it marks every historical edge REVIEW/STALE_AFTER_REPARSE, then
upserts the edges reproduced by the current inputs back to their computed
status.  This prevents a removed or newly rejected edge from remaining active
under an unchanged method/config fingerprint.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "20260804_0046"
down_revision: str | None = "20260804_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_catalog_identity_link_anomaly"
_TABLE = "catalog_identity_links"
_ANOMALIES_BEFORE = (
    "OE_SOURCE_CONFLICT",
    "SHARED_ARTICLE_FANOUT",
    "OE_SUPERSEDED_BY_NEWER_REFERENCE",
)
_ANOMALIES_AFTER = (*_ANOMALIES_BEFORE, "STALE_AFTER_REPARSE")


def _condition(names: tuple[str, ...]) -> str:
    listed = ", ".join(f"'{name}'" for name in names)
    return f"anomaly IS NULL OR anomaly IN ({listed})"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _condition(_ANOMALIES_AFTER))


def downgrade() -> None:
    stale = int(
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM catalog_identity_links "
            "WHERE anomaly = 'STALE_AFTER_REPARSE'"
        )
        .scalar_one()
    )
    if stale:
        raise RuntimeError(
            f"{stale} link(s) carry STALE_AFTER_REPARSE; preserve or resolve "
            "them deliberately before downgrading"
        )
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _condition(_ANOMALIES_BEFORE))
