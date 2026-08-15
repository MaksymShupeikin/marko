"""Add reference-only workbook evidence and append-only KEMP links.

Revision ID: 20260812_0052
Revises: 20260810_0051
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260812_0052"
down_revision: str | None = "20260810_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_reference_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("import_batch_id", sa.Uuid(), nullable=False),
        sa.Column("source_sheet", sa.String(255), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("internal_code_raw", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "internal_code_norm", sa.String(255), server_default="", nullable=False
        ),
        sa.Column("original_raw", sa.Text(), server_default="", nullable=False),
        sa.Column("original_norm", sa.String(255), server_default="", nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("oe_sources", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("confirmed_numbers", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("anomalies", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("evidence_url", sa.Text()),
        sa.Column("raw_row", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(content_sha256) = 64",
            name="ck_catalog_reference_content_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id"], ["catalog_import_batches.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "import_batch_id",
            "source_sheet",
            "source_row",
            name="uq_catalog_reference_batch_sheet_row",
        ),
    )
    op.create_index(
        "ix_catalog_reference_items_workspace_id",
        "catalog_reference_items",
        ["workspace_id"],
    )
    op.create_index(
        "ix_catalog_reference_items_import_batch_id",
        "catalog_reference_items",
        ["import_batch_id"],
    )
    op.create_index(
        "ix_catalog_reference_items_content_sha256",
        "catalog_reference_items",
        ["content_sha256"],
    )
    op.create_index(
        "ix_catalog_reference_workspace_internal_code",
        "catalog_reference_items",
        ["workspace_id", "internal_code_norm"],
    )

    op.create_table(
        "catalog_kemp_link_resolutions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("import_batch_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_item_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(48), nullable=False),
        sa.Column("internal_code_raw", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "internal_code_norm", sa.String(255), server_default="", nullable=False
        ),
        sa.Column("method", sa.String(80), nullable=False),
        sa.Column("method_version", sa.String(80), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("listing_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('LINKED_OWNED_LISTING_GROUP', 'KEMP_CODE_MISSING', "
            "'NO_CURRENT_OWNED_LISTING', 'AMBIGUOUS_LISTING_INTERNAL_CODES', "
            "'DUPLICATE_CATALOG_INTERNAL_CODE', 'SOURCE_EVIDENCE_MISSING', "
            "'SOURCE_ACCESS_BLOCKED')",
            name="ck_catalog_kemp_link_resolution_status",
        ),
        sa.CheckConstraint(
            "char_length(input_sha256) = 64 AND char_length(evidence_sha256) = 64",
            name="ck_catalog_kemp_link_resolution_hashes",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id"], ["catalog_import_batches.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"], ["catalog_items.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "catalog_item_id",
            "input_sha256",
            name="uq_catalog_kemp_link_resolution_input",
        ),
    )
    op.create_index(
        "ix_catalog_kemp_link_resolutions_workspace_id",
        "catalog_kemp_link_resolutions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_catalog_kemp_link_resolutions_import_batch_id",
        "catalog_kemp_link_resolutions",
        ["import_batch_id"],
    )
    op.create_index(
        "ix_catalog_kemp_link_resolutions_catalog_item_id",
        "catalog_kemp_link_resolutions",
        ["catalog_item_id"],
    )
    op.create_index(
        "ix_catalog_kemp_link_resolutions_status",
        "catalog_kemp_link_resolutions",
        ["status"],
    )
    op.create_index(
        "ix_catalog_kemp_link_resolutions_evidence_sha256",
        "catalog_kemp_link_resolutions",
        ["evidence_sha256"],
    )
    op.create_index(
        "ix_catalog_kemp_resolution_batch_item_time",
        "catalog_kemp_link_resolutions",
        ["import_batch_id", "catalog_item_id", "created_at"],
    )

    op.create_table(
        "catalog_kemp_owned_listing_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resolution_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_item_id", sa.Uuid(), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("source_listing_id", sa.String(255), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("internal_code_raw", sa.Text(), nullable=False),
        sa.Column("internal_code_norm", sa.String(255), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(evidence_sha256) = 64", name="ck_catalog_kemp_owned_link_hash"
        ),
        sa.ForeignKeyConstraint(
            ["resolution_id"], ["catalog_kemp_link_resolutions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"], ["catalog_items.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["store_id"], ["marketplace_stores.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "resolution_id", "listing_id", name="uq_catalog_kemp_link_listing"
        ),
    )
    for column in (
        "resolution_id",
        "workspace_id",
        "catalog_item_id",
        "listing_id",
        "store_id",
        "evidence_sha256",
    ):
        op.create_index(
            f"ix_catalog_kemp_owned_listing_links_{column}",
            "catalog_kemp_owned_listing_links",
            [column],
        )
    for table_name in (
        "catalog_reference_items",
        "catalog_kemp_link_resolutions",
        "catalog_kemp_owned_listing_links",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table_name} FOR EACH ROW "
            "EXECUTE FUNCTION marko_reject_append_only_mutation()"
        )


def downgrade() -> None:
    op.drop_table("catalog_kemp_owned_listing_links")
    op.drop_table("catalog_kemp_link_resolutions")
    op.drop_table("catalog_reference_items")
