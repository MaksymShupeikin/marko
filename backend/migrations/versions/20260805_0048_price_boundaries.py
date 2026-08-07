"""Keep active sale prices below crossed-out reference prices.

Revision ID: 20260805_0048
Revises: 20260805_0047

The parser stores the current (possibly discounted) value separately from the
older crossed-out value.  A malformed adapter must never be able to persist a
sale price above its reference price: that would inflate a market cohort even
when the runtime normalizer is correct.  Existing violating rows are evidence
of a write-path defect, so the migration stops and reports them instead of
rewriting history.
"""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa


revision = "20260805_0048"
down_revision: str | None = "20260805_0047"
branch_labels = None
depends_on = None


def _reject_inverted_price_boundaries() -> None:
    market_sql = (
        "SELECT id FROM market_observations "
        "WHERE sale_price IS NOT NULL AND reference_price IS NOT NULL "
        "AND sale_price > reference_price"
    )
    discovery_sql = (
        "SELECT id FROM catalog_discovery_offers "
        "WHERE reference_price IS NOT NULL AND sale_price > reference_price"
    )
    if context.is_offline_mode():
        op.execute(
            sa.text(
                """
                DO $marko_price_boundary_guard$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM market_observations
                        WHERE sale_price IS NOT NULL
                          AND reference_price IS NOT NULL
                          AND sale_price > reference_price
                    ) OR EXISTS (
                        SELECT 1 FROM catalog_discovery_offers
                        WHERE reference_price IS NOT NULL
                          AND sale_price > reference_price
                    ) THEN
                        RAISE EXCEPTION
                            'BLOCKED_MIGRATION_20260805_0048: sale_price exceeds '
                            'reference_price; repair the source write path and '
                            'adjudicate existing evidence before migration';
                    END IF;
                END
                $marko_price_boundary_guard$
                """
            )
        )
        return

    connection = op.get_bind()
    market_rows = connection.execute(sa.text(market_sql)).fetchmany(20)
    discovery_rows = connection.execute(sa.text(discovery_sql)).fetchmany(20)
    if market_rows or discovery_rows:
        detail = (
            f"market_observations={len(market_rows)}"
            f"; catalog_discovery_offers={len(discovery_rows)}"
        )
        raise RuntimeError(
            "BLOCKED_MIGRATION_20260805_0048: sale_price exceeds "
            "reference_price in existing evidence (up to 20 rows per table: "
            f"{detail}). Repair the source write path and adjudicate the rows "
            "before migration; this migration never rewrites pricing evidence."
        )


def upgrade() -> None:
    _reject_inverted_price_boundaries()
    op.create_check_constraint(
        "ck_market_observation_sale_not_above_reference",
        "market_observations",
        "reference_price IS NULL OR sale_price IS NULL OR "
        "sale_price <= reference_price",
    )
    op.create_check_constraint(
        "ck_catalog_discovery_offer_sale_not_above_reference",
        "catalog_discovery_offers",
        "reference_price IS NULL OR sale_price <= reference_price",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_catalog_discovery_offer_sale_not_above_reference",
        "catalog_discovery_offers",
        type_="check",
    )
    op.drop_constraint(
        "ck_market_observation_sale_not_above_reference",
        "market_observations",
        type_="check",
    )
