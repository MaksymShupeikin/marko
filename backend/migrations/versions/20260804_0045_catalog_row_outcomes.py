"""Persist a complete terminal outcome for every catalog source row.

Revision ID: 20260804_0045
Revises: 20260804_0044
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260804_0045"
down_revision = "20260804_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "catalog_import_batches",
        sa.Column("row_outcomes_contract_version", sa.String(length=48), nullable=True),
    )
    op.add_column(
        "catalog_import_batches",
        sa.Column("row_outcomes_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "catalog_import_batches",
        sa.Column(
            "row_outcomes",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_catalog_import_batches_row_outcomes_sha256",
        "catalog_import_batches",
        ["row_outcomes_sha256"],
    )
    op.create_check_constraint(
        "ck_catalog_import_row_outcomes_contract",
        "catalog_import_batches",
        "(row_outcomes_contract_version IS NULL AND row_outcomes_sha256 IS NULL) OR "
        "(row_outcomes_contract_version = 'catalog-row-outcomes-v1' AND "
        "char_length(row_outcomes_sha256) = 64 AND "
        "json_array_length(row_outcomes) = total_rows)",
    )


def downgrade() -> None:
    bind = op.get_bind()
    manifested = int(
        bind.execute(
            sa.text(
                "SELECT count(*) FROM catalog_import_batches "
                "WHERE row_outcomes_contract_version IS NOT NULL"
            )
        ).scalar_one()
    )
    if manifested:
        raise RuntimeError(
            "IRREVERSIBLE_MIGRATION_20260804_0045: "
            f"{manifested} complete catalog row-outcome manifest(s) would be lost"
        )
    op.drop_constraint(
        "ck_catalog_import_row_outcomes_contract",
        "catalog_import_batches",
        type_="check",
    )
    op.drop_index(
        "ix_catalog_import_batches_row_outcomes_sha256",
        table_name="catalog_import_batches",
    )
    op.drop_column("catalog_import_batches", "row_outcomes")
    op.drop_column("catalog_import_batches", "row_outcomes_sha256")
    op.drop_column("catalog_import_batches", "row_outcomes_contract_version")
