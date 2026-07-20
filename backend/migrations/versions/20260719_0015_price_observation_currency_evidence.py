"""Add fail-closed currency evidence to store price observations.

Revision ID: 20260719_0015
Revises: 20260719_0014
Create Date: 2026-07-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260719_0015"
down_revision: str | None = "20260719_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_observations",
        sa.Column("currency_raw", sa.String(length=32), nullable=True),
    )
    # Existing rows did not preserve the raw source value. Mark them inferred
    # instead of manufacturing evidence from the normalized currency column.
    op.add_column(
        "price_observations",
        sa.Column(
            "currency_inferred",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.alter_column(
        "price_observations",
        "currency_inferred",
        server_default=sa.text("false"),
    )


def downgrade() -> None:
    op.drop_column("price_observations", "currency_inferred")
    op.drop_column("price_observations", "currency_raw")
