"""Keep the provider answer a validator rejected.

A FAILED comparability review stored a synthesized placeholder, so the citation
that cost a paid call and was then discarded left nothing behind but a truncated
``error_detail``.  That is not enough to separate a prompt defect from a model
one, and the first ``required`` run had to be diagnosed from error strings alone.

Revision ID: 20260815_0054
Revises: 20260812_0053
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260815_0054"
down_revision: str | None = "20260812_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_comparability_reviews",
        sa.Column("rejected_output", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidate_comparability_reviews", "rejected_output")
