"""Add workspace-local catalog product edits and deletion.

Revision ID: 20260822_0005
Revises: 20260713_0004
Create Date: 2026-08-22
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260822_0005"
down_revision: str | None = "20260713_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_listing_overrides",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text()),
        sa.Column("sku", sa.String(255)),
        sa.Column("brand", sa.String(255)),
        sa.Column("current_price", sa.Numeric(14, 2)),
        sa.Column("is_available", sa.Boolean()),
        sa.Column("image_url", sa.Text()),
        sa.Column("oem_numbers", sa.JSON()),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("workspace_id", "listing_id"),
    )
    op.create_index(
        "ix_workspace_listing_overrides_listing_id",
        "workspace_listing_overrides",
        ["listing_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_listing_overrides_listing_id",
        table_name="workspace_listing_overrides",
    )
    op.drop_table("workspace_listing_overrides")
