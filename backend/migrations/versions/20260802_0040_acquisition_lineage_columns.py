"""Родословная приобретения первым классом: источник, метод, запрос, URL, хеш.

Ревью round 5 (F6): граница принимала ``retrieval_kind=prom_oe_page`` вместе с
``acquisition.source=SEARCH`` и без улик OE, а запрос для заявления брался из
``CatalogItem.oe_norm``. Наблюдение при этом сохранялось как ``VERIFIED_EXACT``,
хотя площадка ничего не утверждала: «подтверждение» состояло из нашего же
собственного номера.

Сервис уже пишет эти пять полей, но до появления колонок они никуда не
доезжают. Два ограничения закрывают состояния, ради которых всё и делалось:
способ извлечения без источника/метода/запроса — заявление без основания, а
источником заявления может быть только страница кода детали.

Обратного заполнения нет и быть не может: старые строки не записывали ни
запрошенный номер, ни URL. Оставить их NULL — единственное честное прочтение,
и повторное обогащение такие строки не повышает.

Revision ID: 20260802_0040
Revises: 20260802_0039
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260802_0040"
down_revision = "20260802_0039"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("source_assertion_source", sa.String(length=32)),
    ("source_assertion_method", sa.String(length=48)),
    ("source_assertion_queried_oe_norm", sa.String(length=255)),
    ("source_assertion_source_url", sa.String(length=2048)),
    ("source_assertion_input_hash", sa.String(length=64)),
)


def upgrade() -> None:
    for name, kind in _COLUMNS:
        op.add_column("market_observations", sa.Column(name, kind, nullable=True))
    op.create_check_constraint(
        "ck_market_observation_source_assertion_lineage",
        "market_observations",
        "source_assertion_retrieval_kind IS NULL "
        "OR (source_assertion_source IS NOT NULL "
        "AND source_assertion_method IS NOT NULL "
        "AND source_assertion_queried_oe_norm IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_market_observation_source_assertion_source",
        "market_observations",
        "source_assertion_source IS NULL "
        "OR source_assertion_source = 'PROM_OE_PAGE'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_market_observation_source_assertion_source",
        "market_observations",
        type_="check",
    )
    op.drop_constraint(
        "ck_market_observation_source_assertion_lineage",
        "market_observations",
        type_="check",
    )
    for name, _ in reversed(_COLUMNS):
        op.drop_column("market_observations", name)
