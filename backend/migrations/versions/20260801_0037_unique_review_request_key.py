"""Согласовать уникальность ``ix_candidate_comparability_reviews_request_key``.

``alembic check`` на чистой базе устойчиво показывал расхождение: модель
объявляет индекс уникальным, в базе он создан обычным. Расхождение жило дольше
трёх раундов ревью и каждый раз зашумляло проверку, из-за чего настоящий дрейф
в ней было бы не видно.

``request_key`` — ключ идемпотентности проверки сопоставимости: два ряда с одним
значением означают, что одна и та же заявка была просужена дважды и какая из
двух записей «настоящая», определить нельзя.

Дубликаты **не удаляются**. Миграция сначала считает их и при находке
останавливается с перечнем — расчистка чужих доказательств не дело миграции
(таблица к тому же append-only). Оператор разбирается и запускает снова.

Revision ID: 20260801_0037
Revises: 20260801_0036
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260801_0037"
down_revision = "20260801_0036"
branch_labels = None
depends_on = None

_INDEX = "ix_candidate_comparability_reviews_request_key"
_TABLE = "candidate_comparability_reviews"


def upgrade() -> None:
    connection = op.get_bind()
    duplicates = connection.execute(
        sa.text(
            f"SELECT request_key, count(*) AS n FROM {_TABLE} "
            "GROUP BY request_key HAVING count(*) > 1 ORDER BY n DESC LIMIT 20"
        )
    ).all()
    if duplicates:
        listed = ", ".join(f"{row[0]}×{row[1]}" for row in duplicates)
        raise RuntimeError(
            "BLOCKED_MIGRATION_20260801_0037: request_key must be unique before "
            f"the index can be, but duplicates exist: {listed}. "
            "This migration deliberately does not deduplicate: the table is "
            "append-only evidence and choosing which review survives is an "
            "owner decision, not a schema step."
        )
    op.drop_index(_INDEX, table_name=_TABLE)
    op.create_index(_INDEX, _TABLE, ["request_key"], unique=True)


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
    op.create_index(_INDEX, _TABLE, ["request_key"], unique=False)
