"""Track when a workspace product was last re-read from its link.

``updated_at`` moves on every edit, so it cannot answer "коли синхронізовано".

Revision ID: 20260823_0006
Revises: 20260822_0005
Create Date: 2026-08-23
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260823_0006"
down_revision: str | None = "20260822_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace_listing_overrides",
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspace_listing_overrides", "synced_at")
