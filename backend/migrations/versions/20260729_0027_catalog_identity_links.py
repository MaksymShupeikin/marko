"""The number graph of our own catalog items (WP-3).

Revision ID: 20260729_0027
Revises: 20260729_0026
Create Date: 2026-07-29

A separate table rather than a nullable ``cross_links.pricing_run_id``.  These
links belong to no pricing run — they come from our own catalogue, the KEMP
reference map and kemp.ua cards, none of which were observed while pricing
anything.  Relaxing ``cross_links.pricing_run_id`` to nullable would weaken the
append-only invariant that every row there names the run that produced it, and
would mix two lifecycles: a run's links die with the run's evidence, these
outlive every run.  ``_confirmed_cross_oems`` reads the union of the two.

Nothing is backfilled.  Seeding is the idempotent reparse of WP-6.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_0027"
down_revision: str | None = "20260729_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_identity_links",
        sa.Column(
            "id", sa.Uuid(), primary_key=True, nullable=False
        ),
        sa.Column("sequence_no", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_item_id", sa.Uuid(), nullable=False),
        sa.Column("our_oem_norm", sa.String(length=255), nullable=False),
        sa.Column("extracted_oem_norm", sa.String(length=255), nullable=False),
        sa.Column("extracted_raw", sa.Text(), nullable=False),
        sa.Column("raw_context", sa.Text(), nullable=False),
        sa.Column("extraction_method", sa.String(length=50), nullable=False),
        sa.Column("validation_status", sa.String(length=16), nullable=False),
        sa.Column("anomaly", sa.String(length=40), nullable=True),
        sa.Column(
            "corroborating_sources",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "validation_details", sa.JSON(), server_default="{}", nullable=False
        ),
        sa.Column("method_version", sa.String(length=80), nullable=False),
        sa.Column("config_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"], ["catalog_items.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "catalog_item_id",
            "our_oem_norm",
            "extracted_oem_norm",
            "extraction_method",
            name="uq_catalog_identity_link_pair_source",
        ),
        sa.UniqueConstraint(
            "sequence_no", name="uq_catalog_identity_link_sequence"
        ),
        sa.CheckConstraint(
            "our_oem_norm <> '' AND extracted_oem_norm <> '' "
            "AND our_oem_norm <> extracted_oem_norm",
            name="ck_catalog_identity_link_distinct_oems",
        ),
        sa.CheckConstraint(
            "validation_status IN ('CONFIRMED', 'REVIEW')",
            name="ck_catalog_identity_link_status",
        ),
        sa.CheckConstraint(
            "anomaly IS NULL OR anomaly IN "
            "('OE_SOURCE_CONFLICT', 'SHARED_ARTICLE_FANOUT')",
            name="ck_catalog_identity_link_anomaly",
        ),
        sa.CheckConstraint(
            "anomaly IS NULL OR validation_status = 'REVIEW'",
            name="ck_catalog_identity_link_anomaly_under_review",
        ),
    )
    op.create_index(
        "ix_catalog_identity_links_workspace_id",
        "catalog_identity_links",
        ["workspace_id"],
    )
    op.create_index(
        "ix_catalog_identity_links_catalog_item_id",
        "catalog_identity_links",
        ["catalog_item_id"],
    )
    op.create_index(
        "ix_catalog_identity_link_workspace_pair",
        "catalog_identity_links",
        ["workspace_id", "our_oem_norm", "extracted_oem_norm"],
    )
    op.create_index(
        "ix_catalog_identity_link_workspace_extracted",
        "catalog_identity_links",
        ["workspace_id", "extracted_oem_norm"],
    )
    op.create_index(
        "ix_catalog_identity_link_anomaly",
        "catalog_identity_links",
        ["workspace_id", "anomaly"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_identity_link_anomaly", table_name="catalog_identity_links"
    )
    op.drop_index(
        "ix_catalog_identity_link_workspace_extracted",
        table_name="catalog_identity_links",
    )
    op.drop_index(
        "ix_catalog_identity_link_workspace_pair",
        table_name="catalog_identity_links",
    )
    op.drop_index(
        "ix_catalog_identity_links_catalog_item_id",
        table_name="catalog_identity_links",
    )
    op.drop_index(
        "ix_catalog_identity_links_workspace_id",
        table_name="catalog_identity_links",
    )
    op.drop_table("catalog_identity_links")
