"""Harden fitment source policy provenance and tier reliability.

Revision ID: 20260721_0018
Revises: 20260721_0017
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_0018"
down_revision: str | None = "20260721_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fitment_sources",
        sa.Column(
            "access_reference",
            sa.String(length=255),
            nullable=False,
            server_default="legacy-unreviewed",
        ),
    )
    op.alter_column("fitment_sources", "access_reference", server_default=None)

    # NOT VALID preserves append-only legacy rows while enforcing both contracts
    # for every new source policy row. A later policy-review migration may
    # validate the constraints once all legacy markers have been superseded.
    op.execute(
        """
        ALTER TABLE fitment_sources
        ADD CONSTRAINT ck_fit_source_tier_reliability
        CHECK (
            (source_tier = 'A' AND base_reliability BETWEEN 0.95 AND 1.00) OR
            (source_tier = 'B' AND base_reliability BETWEEN 0.75 AND 0.90) OR
            (source_tier = 'C' AND base_reliability BETWEEN 0.55 AND 0.75) OR
            (source_tier = 'D' AND base_reliability BETWEEN 0.30 AND 0.55) OR
            (source_tier = 'E' AND base_reliability BETWEEN 0.10 AND 0.35)
        ) NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE fitment_sources
        ADD CONSTRAINT ck_fit_source_approved_review
        CHECK (
            access_status NOT IN ('PERMITTED', 'OWNER_RISK_ACCEPTED') OR
            (
                char_length(trim(access_reference)) > 0 AND
                robots_checked AND
                terms_checked
            )
        ) NOT VALID
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_fit_source_approved_review", "fitment_sources", type_="check"
    )
    op.drop_constraint(
        "ck_fit_source_tier_reliability", "fitment_sources", type_="check"
    )
    op.drop_column("fitment_sources", "access_reference")
