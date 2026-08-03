"""Сохранять утверждение источника об идентичности первым классом.

Признак расширения и номер, по которому взят рынок, жили только внутри
``comparison_evidence``. Кодек этого JSON выбрасывает незнакомые ключи при
повторном обогащении (``oe_reenrichment``), поэтому ``via_oe_number`` терялся, а
само заявление нельзя было перепроверить после того, как его один раз приняли.

Четыре колонки хранят заявление вместе с происхождением, на которое оно
опирается: номер запроса, способ извлечения, SHA-256 неизменяемого захвата и
уверенность. Два ограничения не дают записать заявление без происхождения и
уверенность вне ``[0, 1]``.

Колонки добавляются NULL-able: наблюдения, собранные до этой миграции, заявления
не несли, и придумывать его задним числом миграция не должна.

Revision ID: 20260801_0034
Revises: 20260801_0033
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260801_0034"
down_revision = "20260801_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "market_observations",
        sa.Column("via_oe_number", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "market_observations",
        sa.Column(
            "source_assertion_retrieval_kind", sa.String(length=48), nullable=True
        ),
    )
    op.add_column(
        "market_observations",
        sa.Column(
            "source_assertion_capture_sha256", sa.String(length=64), nullable=True
        ),
    )
    op.add_column(
        "market_observations",
        sa.Column(
            "source_assertion_confidence", sa.Numeric(precision=5, scale=4), nullable=True
        ),
    )
    op.create_index(
        "ix_market_observations_via_oe_number",
        "market_observations",
        ["via_oe_number"],
    )
    op.create_check_constraint(
        "ck_market_observation_source_assertion_confidence",
        "market_observations",
        "source_assertion_confidence IS NULL OR "
        "(source_assertion_confidence >= 0 AND source_assertion_confidence <= 1)",
    )
    op.create_check_constraint(
        "ck_market_observation_source_assertion_provenance",
        "market_observations",
        "source_assertion_retrieval_kind IS NULL OR "
        "source_assertion_capture_sha256 IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_market_observation_source_assertion_provenance",
        "market_observations",
        type_="check",
    )
    op.drop_constraint(
        "ck_market_observation_source_assertion_confidence",
        "market_observations",
        type_="check",
    )
    op.drop_index(
        "ix_market_observations_via_oe_number", table_name="market_observations"
    )
    for column in (
        "source_assertion_confidence",
        "source_assertion_capture_sha256",
        "source_assertion_retrieval_kind",
        "via_oe_number",
    ):
        op.drop_column("market_observations", column)
