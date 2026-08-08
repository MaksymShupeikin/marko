"""Remove catalog read models orphaned by earlier store deletions.

Revision ID: 20260807_0045
Revises: 20260807_0044
"""

from __future__ import annotations

from alembic import op


revision = "20260807_0045"
down_revision = "20260807_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Before 0045 deleting a store removed only workspace_stores. The generic
    # source_id on catalog_products intentionally has no marketplace-store FK,
    # so those rows (and their attention items) survived. Deleting the product
    # activates the existing CASCADEs for price_assessments and attention_items.
    op.execute(
        """
        DELETE FROM catalog_products AS product
        WHERE product.source_kind = 'PROM_STORE'
          AND NOT EXISTS (
            SELECT 1
            FROM workspace_stores AS workspace_store
            WHERE workspace_store.workspace_id = product.workspace_id
              AND workspace_store.store_id = product.source_id
              AND workspace_store.kind = 'owned'
          )
        """
    )


def downgrade() -> None:
    # Deleted read models can be rebuilt by a fresh store synchronization, but
    # cannot be reconstructed faithfully by a schema downgrade.
    pass
