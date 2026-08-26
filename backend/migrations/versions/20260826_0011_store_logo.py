"""Store the seller's logo scraped from its Prom page.

Revision ID: 20260826_0011
Revises: 20260825_0010
Create Date: 2026-08-26
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260826_0011"
down_revision: str | None = "20260825_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "marketplace_stores",
        sa.Column("logo_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("marketplace_stores", "logo_url")
