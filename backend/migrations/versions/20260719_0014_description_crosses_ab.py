"""Add append-only description-cross evidence and observation provenance.

Revision ID: 20260719_0014
Revises: 20260718_0013
Create Date: 2026-07-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260719_0014"
down_revision: str | None = "20260718_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cross_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sequence_no", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("pricing_run_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_item_id", sa.Uuid(), nullable=False),
        sa.Column("our_oem_norm", sa.String(length=255), nullable=False),
        sa.Column("extracted_oem_norm", sa.String(length=255), nullable=False),
        sa.Column("source_listing_url", sa.Text(), nullable=False),
        sa.Column("source_seller", sa.String(length=255), nullable=False),
        sa.Column("raw_context", sa.Text(), nullable=False),
        sa.Column("extraction_method", sa.String(length=50), nullable=False),
        sa.Column("validation_status", sa.String(length=16), nullable=False),
        sa.Column("rejection_reason", sa.String(length=50), nullable=True),
        sa.Column("reciprocal_evidence_url", sa.Text(), nullable=True),
        sa.Column("source_evidence", sa.JSON(), nullable=False),
        sa.Column("validation_details", sa.JSON(), nullable=False),
        sa.Column("method_version", sa.String(length=80), nullable=False),
        sa.Column("config_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "extracted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "our_oem_norm <> '' AND extracted_oem_norm <> '' "
            "AND our_oem_norm <> extracted_oem_norm",
            name="ck_cross_link_distinct_oems",
        ),
        sa.CheckConstraint(
            "validation_status IN ('CONFIRMED', 'REVIEW', 'REJECTED', 'UNKNOWN')",
            name="ck_cross_link_validation_status",
        ),
        sa.CheckConstraint(
            "(validation_status = 'REJECTED' AND rejection_reason IS NOT NULL) OR "
            "(validation_status <> 'REJECTED' AND rejection_reason IS NULL)",
            name="ck_cross_link_rejection_reason",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["pricing_run_id"], ["pricing_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"], ["catalog_items.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pricing_run_id",
            "our_oem_norm",
            "extracted_oem_norm",
            name="uq_cross_link_run_pair",
        ),
        sa.UniqueConstraint("sequence_no", name="uq_cross_link_sequence"),
    )
    op.create_index(
        "ix_cross_link_workspace_pair",
        "cross_links",
        ["workspace_id", "our_oem_norm", "extracted_oem_norm"],
    )
    op.create_index(
        "ix_cross_link_run_status",
        "cross_links",
        ["pricing_run_id", "validation_status"],
    )
    op.create_index("ix_cross_links_workspace_id", "cross_links", ["workspace_id"])
    op.create_index("ix_cross_links_pricing_run_id", "cross_links", ["pricing_run_id"])
    op.create_index(
        "ix_cross_links_catalog_item_id", "cross_links", ["catalog_item_id"]
    )

    op.add_column(
        "market_observations",
        sa.Column(
            "via_cross",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "market_observations",
        sa.Column("cross_link_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_market_observation_cross_link",
        "market_observations",
        "cross_links",
        ["cross_link_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_market_observations_via_cross",
        "market_observations",
        ["via_cross"],
    )
    op.create_index(
        "ix_market_observations_cross_link_id",
        "market_observations",
        ["cross_link_id"],
    )
    op.create_check_constraint(
        "ck_market_observation_cross_provenance",
        "market_observations",
        "(via_cross AND cross_link_id IS NOT NULL) OR "
        "(NOT via_cross AND cross_link_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_market_observation_cross_provenance",
        "market_observations",
        type_="check",
    )
    op.drop_index(
        "ix_market_observations_cross_link_id", table_name="market_observations"
    )
    op.drop_index("ix_market_observations_via_cross", table_name="market_observations")
    op.drop_constraint(
        "fk_market_observation_cross_link",
        "market_observations",
        type_="foreignkey",
    )
    op.drop_column("market_observations", "cross_link_id")
    op.drop_column("market_observations", "via_cross")

    op.drop_index("ix_cross_links_catalog_item_id", table_name="cross_links")
    op.drop_index("ix_cross_links_pricing_run_id", table_name="cross_links")
    op.drop_index("ix_cross_links_workspace_id", table_name="cross_links")
    op.drop_index("ix_cross_link_run_status", table_name="cross_links")
    op.drop_index("ix_cross_link_workspace_pair", table_name="cross_links")
    op.drop_table("cross_links")
