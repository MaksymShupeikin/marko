"""Пейвол: лічильник перевірок, білий список, запит повного доступу.

Revision ID: 20260825_0010
Revises: 20260824_0009
Create Date: 2026-08-25
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0010"
down_revision: str | None = "20260824_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("checks_used", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "workspaces",
        sa.Column(
            "has_free_access", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.add_column(
        "workspaces",
        sa.Column("access_requested_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "access_requested_at")
    op.drop_column("workspaces", "has_free_access")
    op.drop_column("workspaces", "checks_used")
