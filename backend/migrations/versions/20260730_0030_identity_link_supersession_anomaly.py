"""Allow the supersession anomaly on catalog identity links.

Revision ID: 20260730_0030
Revises: 20260730_0029
Create Date: 2026-07-30

The check constraint was written when two anomalies existed. WP-3A added a
third: the customer told us on 2026-07-30 that one reference file is a year old
and the other is from yesterday, so a number that changed between the two
editions is a supersession with a known direction rather than a conflict with
no way to settle it.

Nothing is rewritten. The table is still empty — WP-6 is its first writer — so
this widens a constraint ahead of the rows that would otherwise violate it, and
an existing row could not have carried the new value anyway.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "20260730_0030"
down_revision: str | None = "20260730_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_catalog_identity_link_anomaly"
_TABLE = "catalog_identity_links"

_ANOMALIES_BEFORE = ("OE_SOURCE_CONFLICT", "SHARED_ARTICLE_FANOUT")
_ANOMALIES_AFTER = (
    "OE_SOURCE_CONFLICT",
    "SHARED_ARTICLE_FANOUT",
    "OE_SUPERSEDED_BY_NEWER_REFERENCE",
)


def _condition(names: tuple[str, ...]) -> str:
    listed = ", ".join(f"'{name}'" for name in names)
    return f"anomaly IS NULL OR anomaly IN ({listed})"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _condition(_ANOMALIES_AFTER))


def downgrade() -> None:
    superseded = int(
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM catalog_identity_links "
            "WHERE anomaly = 'OE_SUPERSEDED_BY_NEWER_REFERENCE'"
        )
        .scalar_one()
    )
    if superseded:
        # Narrowing the constraint under existing rows would either fail loudly
        # or, worse, invite a silent DELETE of evidence a human still has to
        # judge.  Say what is in the way instead.
        raise RuntimeError(
            f"{superseded} link(s) carry OE_SUPERSEDED_BY_NEWER_REFERENCE; "
            "resolve or delete them deliberately before downgrading"
        )
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _condition(_ANOMALIES_BEFORE))
