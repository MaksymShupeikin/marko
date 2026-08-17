"""Book what a no-OE discovery review actually cost.

The no-OE lane calls the paid provider once per candidate offer and stored the
verdict without a single number about the call: no token usage, no cost
estimate, no ledger row.  A run therefore reported the OE lane's spend as if it
were the whole bill -- on 2026-08-17 the panel showed $0.157 while the
discovery lane was still POSTing to the provider every two minutes.  That is
the lane the product is sold on, so its cost has to be visible.

Revision ID: 20260818_0055
Revises: 20260815_0054
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260818_0055"
down_revision: str | None = "20260815_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pricing_discovery_reviews",
        sa.Column(
            "usage",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.add_column(
        "pricing_discovery_reviews",
        sa.Column(
            "estimated_cost",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.add_column(
        "pricing_discovery_reviews",
        sa.Column("rate_card_version", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pricing_discovery_reviews", "rate_card_version")
    op.drop_column("pricing_discovery_reviews", "estimated_cost")
    op.drop_column("pricing_discovery_reviews", "usage")
