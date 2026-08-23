"""Магазин належить одному воркспейсу.

Раніше marketplace_stores був глобальним (unique marketplace+external_id), а
лістинги висять на store_id. Два акаунти з тим самим продавцем ділили один
рядок магазину — і бачили чужі товари. Тепер ключ включає workspace_id.

Дані: магазин лишається за найстарішим лінком; зайві лінки видаляються, і ці
воркспейси мають переімпортувати каталог.

Revision ID: 20260823_0007
Revises: 20260823_0006
Create Date: 2026-08-23
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260823_0007"
down_revision: str | None = "20260823_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "marketplace_stores", sa.Column("workspace_id", sa.Uuid(), nullable=True)
    )
    op.execute(
        """
        UPDATE marketplace_stores ms
        SET workspace_id = (
            SELECT ws.workspace_id
            FROM workspace_stores ws
            WHERE ws.store_id = ms.id
            ORDER BY ws.created_at, ws.id
            LIMIT 1
        )
        """
    )
    op.execute("DELETE FROM marketplace_stores WHERE workspace_id IS NULL")
    op.execute(
        """
        DELETE FROM workspace_stores ws
        USING marketplace_stores ms
        WHERE ms.id = ws.store_id AND ms.workspace_id <> ws.workspace_id
        """
    )
    op.alter_column("marketplace_stores", "workspace_id", nullable=False)
    op.create_index(
        "ix_marketplace_stores_workspace_id", "marketplace_stores", ["workspace_id"]
    )
    op.create_foreign_key(
        "fk_marketplace_stores_workspace_id",
        "marketplace_stores",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "uq_store_marketplace_external", "marketplace_stores", type_="unique"
    )
    op.create_unique_constraint(
        "uq_store_workspace_marketplace_external",
        "marketplace_stores",
        ["workspace_id", "marketplace", "external_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_store_workspace_marketplace_external", "marketplace_stores", type_="unique"
    )
    op.create_unique_constraint(
        "uq_store_marketplace_external",
        "marketplace_stores",
        ["marketplace", "external_id"],
    )
    op.drop_constraint(
        "fk_marketplace_stores_workspace_id", "marketplace_stores", type_="foreignkey"
    )
    op.drop_index("ix_marketplace_stores_workspace_id", "marketplace_stores")
    op.drop_column("marketplace_stores", "workspace_id")
