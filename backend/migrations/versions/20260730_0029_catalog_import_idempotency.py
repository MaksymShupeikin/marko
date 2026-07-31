"""Make identical catalog imports idempotent within a workspace.

Revision ID: 20260730_0029
Revises: 20260730_0028
Create Date: 2026-07-30

Existing snapshots predate the request-fingerprint contract and deliberately
remain NULL. New imports always persist the application-computed SHA-256 over
the workbook hash, selected sheet and resolved column mapping.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260730_0029"
down_revision: str | None = "20260730_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "catalog_import_batches",
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_catalog_import_workspace_fingerprint",
        "catalog_import_batches",
        ["workspace_id", "request_fingerprint"],
    )


def downgrade() -> None:
    fingerprinted_batches = int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*)
                FROM catalog_import_batches
                WHERE request_fingerprint IS NOT NULL
                """
            )
        )
        .scalar_one()
    )
    if fingerprinted_batches:
        raise RuntimeError(
            "IRREVERSIBLE_MIGRATION_20260730_0029: "
            f"{fingerprinted_batches} catalog import fingerprint(s) would be erased; "
            "restore the pre-migration PostgreSQL backup instead of downgrading"
        )
    op.drop_constraint(
        "uq_catalog_import_workspace_fingerprint",
        "catalog_import_batches",
        type_="unique",
    )
    op.drop_column("catalog_import_batches", "request_fingerprint")
