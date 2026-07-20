"""Add append-only AES-GCM protected catalog cost records.

Revision ID: 20260718_0013
Revises: 20260718_0012
Create Date: 2026-07-18

The encryption key is deliberately not stored in this table, migration, or
repository.  Existing legacy plaintext columns remain ignored and redacted;
they are not silently migrated without an owner-approved retention operation.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260718_0013"
down_revision: str | None = "20260718_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_item_cost_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "sequence_no",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_item_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=8), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("nonce", sa.LargeBinary(), nullable=True),
        sa.Column("key_id", sa.String(length=64), nullable=True),
        sa.Column("algorithm", sa.String(length=32), nullable=True),
        sa.Column("format_version", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('SET', 'CLEAR')",
            name="ck_catalog_item_cost_record_action",
        ),
        sa.CheckConstraint(
            "(action = 'SET' AND ciphertext IS NOT NULL AND nonce IS NOT NULL "
            "AND octet_length(nonce) = 12 "
            "AND octet_length(ciphertext) BETWEEN 20 AND 31 "
            "AND key_id IS NOT NULL AND algorithm = 'AES-256-GCM' "
            "AND format_version = 1) OR "
            "(action = 'CLEAR' AND ciphertext IS NULL AND nonce IS NULL "
            "AND key_id IS NULL AND algorithm IS NULL AND format_version IS NULL)",
            name="ck_catalog_item_cost_record_payload",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"], ["catalog_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sequence_no", name="uq_catalog_item_cost_record_sequence"
        ),
        sa.UniqueConstraint(
            "key_id", "nonce", name="uq_catalog_item_cost_record_key_nonce"
        ),
    )
    op.create_index(
        "ix_catalog_item_cost_records_workspace_id",
        "catalog_item_cost_records",
        ["workspace_id"],
    )
    op.create_index(
        "ix_catalog_item_cost_records_catalog_item_id",
        "catalog_item_cost_records",
        ["catalog_item_id"],
    )
    op.create_index(
        "ix_catalog_item_cost_records_user_id",
        "catalog_item_cost_records",
        ["user_id"],
    )
    op.create_index(
        "ix_catalog_item_cost_record_current",
        "catalog_item_cost_records",
        ["workspace_id", "catalog_item_id", "sequence_no"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_item_cost_record_current",
        table_name="catalog_item_cost_records",
    )
    op.drop_index(
        "ix_catalog_item_cost_records_user_id",
        table_name="catalog_item_cost_records",
    )
    op.drop_index(
        "ix_catalog_item_cost_records_catalog_item_id",
        table_name="catalog_item_cost_records",
    )
    op.drop_index(
        "ix_catalog_item_cost_records_workspace_id",
        table_name="catalog_item_cost_records",
    )
    op.drop_table("catalog_item_cost_records")
