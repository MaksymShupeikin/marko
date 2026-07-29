"""Persist the Prom characteristics block as structured catalog identity.

Revision ID: 20260728_0023
Revises: 20260725_0022
Create Date: 2026-07-28

Existing rows are not backfilled here.  The columns default to empty, so a
catalog imported before this revision reports "no cross numbers" rather than
inventing them; reparsing is a separate, idempotent operation.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260728_0023"
down_revision: str | None = "20260725_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in (
        "part_numbers_raw",
        "part_numbers_norm",
        "applicability_brands",
        "applicability_models",
    ):
        op.add_column(
            "catalog_items",
            sa.Column(name, sa.JSON(), server_default="[]", nullable=False),
        )
    op.add_column(
        "catalog_items",
        sa.Column(
            "characteristics_raw", sa.JSON(), server_default="{}", nullable=False
        ),
    )
    op.add_column(
        "catalog_import_batches",
        sa.Column(
            "characteristics_report", sa.JSON(), server_default="{}", nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("catalog_import_batches", "characteristics_report")
    for name in (
        "characteristics_raw",
        "applicability_models",
        "applicability_brands",
        "part_numbers_norm",
        "part_numbers_raw",
    ):
        op.drop_column("catalog_items", name)
