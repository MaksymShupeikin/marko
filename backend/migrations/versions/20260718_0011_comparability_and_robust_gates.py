"""Add fail-closed comparability evidence and robust decision trace.

Revision ID: 20260718_0011
Revises: 20260717_0010
Create Date: 2026-07-18
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260718_0011"
down_revision: str | None = "20260717_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in (
        sa.Column("currency_raw", sa.String(32)),
        sa.Column(
            "currency_inferred", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "evidence_contract_version",
            sa.String(80),
            server_default="legacy-unknown-v0",
            nullable=False,
        ),
        sa.Column("comparability_policy_id", sa.String(120)),
        sa.Column("comparability_policy_hash", sa.String(64)),
        sa.Column("comparison_evidence", sa.JSON()),
        sa.Column(
            "seller_identity_verified",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "source_provenance_verified",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "automatic_eligible",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    ):
        op.add_column("market_observations", column)

    # Legacy rows stay UNKNOWN. No backfill is allowed to synthesize MATCH or
    # verified provenance from a previously lossy row.
    op.create_check_constraint(
        "ck_market_observation_auto_evidence",
        "market_observations",
        "NOT automatic_eligible OR ("
        "currency_raw IS NOT NULL AND comparison_evidence IS NOT NULL AND "
        "comparability_policy_id IS NOT NULL AND comparability_policy_hash IS NOT NULL "
        "AND char_length(comparability_policy_hash) = 64 "
        "AND seller_identity_verified AND source_provenance_verified)",
    )
    op.create_index(
        "ix_market_observations_automatic_eligible",
        "market_observations",
        ["automatic_eligible"],
    )
    op.create_index(
        "ix_market_observation_comparability_policy",
        "market_observations",
        ["comparability_policy_id", "comparability_policy_hash"],
    )

    for column in (
        sa.Column(
            "automatic_eligible",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "verified_seller_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("comparability_policy_id", sa.String(120)),
        sa.Column("comparability_policy_hash", sa.String(64)),
        sa.Column("decision_fingerprint", sa.String(64)),
        sa.Column(
            "hard_gate_trace",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column("robust_diagnostic", sa.JSON()),
    ):
        op.add_column("pricing_recommendations", column)
    op.create_check_constraint(
        "ck_pricing_recommendation_verified_sellers",
        "pricing_recommendations",
        "verified_seller_count >= 0",
    )
    op.create_check_constraint(
        "ck_pricing_recommendation_auto_evidence",
        "pricing_recommendations",
        "NOT automatic_eligible OR (action_gates_passed AND "
        "action IN ('RAISE', 'HOLD', 'LOWER') AND "
        "comparability_policy_id IS NOT NULL AND comparability_policy_hash IS NOT NULL "
        "AND char_length(comparability_policy_hash) = 64 "
        "AND decision_fingerprint IS NOT NULL "
        "AND char_length(decision_fingerprint) = 64)",
    )
    op.create_index(
        "ix_pricing_recommendations_decision_fingerprint",
        "pricing_recommendations",
        ["decision_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pricing_recommendations_decision_fingerprint",
        table_name="pricing_recommendations",
    )
    op.drop_constraint(
        "ck_pricing_recommendation_auto_evidence",
        "pricing_recommendations",
        type_="check",
    )
    op.drop_constraint(
        "ck_pricing_recommendation_verified_sellers",
        "pricing_recommendations",
        type_="check",
    )
    for name in (
        "robust_diagnostic",
        "hard_gate_trace",
        "decision_fingerprint",
        "comparability_policy_hash",
        "comparability_policy_id",
        "verified_seller_count",
        "automatic_eligible",
    ):
        op.drop_column("pricing_recommendations", name)

    op.drop_index(
        "ix_market_observation_comparability_policy",
        table_name="market_observations",
    )
    op.drop_index(
        "ix_market_observations_automatic_eligible",
        table_name="market_observations",
    )
    op.drop_constraint(
        "ck_market_observation_auto_evidence",
        "market_observations",
        type_="check",
    )
    for name in (
        "automatic_eligible",
        "source_provenance_verified",
        "seller_identity_verified",
        "comparison_evidence",
        "comparability_policy_hash",
        "comparability_policy_id",
        "evidence_contract_version",
        "currency_inferred",
        "currency_raw",
    ):
        op.drop_column("market_observations", name)
