"""Record whether a catalog row's OE was decided, and on what grounds (WP-2).

Revision ID: 20260729_0025
Revises: 20260728_0024
Create Date: 2026-07-29

``oe_norm`` and ``mpn_norm`` already exist; what was missing is the difference
between "the brand beside this article says it is a supplier number" and
"nobody has looked at this row yet".  Both leave ``oe_norm`` empty, and only
the first is a judgement.

Existing rows are therefore not backfilled: they become ``UNRESOLVED``, which
is what they are.  Assigning them ``MPN_ONLY`` would claim 4646 decisions that
were never made.  The reparse is a separate idempotent operation (WP-6).

The ``ck_catalog_item_identity_oe_present`` constraint holds trivially at
upgrade time, since every existing row is ``UNRESOLVED``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0025"
down_revision: str | None = "20260728_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "catalog_items",
        sa.Column(
            "identity_status",
            sa.String(length=20),
            server_default="UNRESOLVED",
            nullable=False,
        ),
    )
    op.add_column(
        "catalog_items",
        sa.Column("identity_reason", sa.String(length=40), nullable=True),
    )
    op.create_check_constraint(
        "ck_catalog_item_identity_status",
        "catalog_items",
        "identity_status IN ('OE_CONFIRMED', 'MPN_ONLY', 'UNRESOLVED')",
    )
    op.create_check_constraint(
        "ck_catalog_item_identity_oe_present",
        "catalog_items",
        "identity_status <> 'OE_CONFIRMED' OR (oe_norm IS NOT NULL AND oe_norm <> '')",
    )
    # WP-2 makes lookup by supplier number a first-class path: positions whose
    # article is an MPN are exactly the ones with no OE to search by.
    op.create_index(
        "ix_catalog_item_workspace_mpn", "catalog_items", ["workspace_id", "mpn_norm"]
    )


def downgrade() -> None:
    reviewed_rows = int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*)
                FROM catalog_items
                WHERE identity_status <> 'UNRESOLVED'
                   OR identity_reason IS NOT NULL
                """
            )
        )
        .scalar_one()
    )
    if reviewed_rows:
        raise RuntimeError(
            "IRREVERSIBLE_MIGRATION_20260729_0025: "
            f"{reviewed_rows} catalog identity review row(s) would be erased; "
            "restore the pre-migration PostgreSQL backup instead of downgrading"
        )
    op.drop_index("ix_catalog_item_workspace_mpn", table_name="catalog_items")
    op.drop_constraint(
        "ck_catalog_item_identity_oe_present", "catalog_items", type_="check"
    )
    op.drop_constraint("ck_catalog_item_identity_status", "catalog_items", type_="check")
    op.drop_column("catalog_items", "identity_reason")
    op.drop_column("catalog_items", "identity_status")
