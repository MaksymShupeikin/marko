"""Долговечный счётчик вызовов провайдера на позицию прогона.

Ревью 2026-08-01 (второй проход), F9: бюджет жил только в памяти внутри обхода
когорты, поэтому админский путь ``force=true`` уходил к провайдеру мимо него —
замер: при бюджете 1 сделано 5 вызовов, при 2 и восьми одновременных запросах —
8. Счётчик в памяти к тому же обнуляется перезапуском процесса.

Таблица — изменяемый счётчик, а не улика: строка обновляется на месте, поэтому
append-only триггеры на неё не ставятся. Она сознательно живёт вне
``Base.metadata`` (объявлена в ``marko.services.llm_call_budget``), чтобы не
попасть под режим неизменяемости и не столкнуться с ORM-классом.

Резервирование атомарно одним оператором: ``INSERT … ON CONFLICT DO UPDATE SET
spent = spent + 1 WHERE spent < call_limit RETURNING``. Пустой результат
означает исчерпанный бюджет; чтение и инкремент разделить нельзя.

``ON DELETE CASCADE`` от позиции прогона: счётчик не переживает то, что считал.
``RESTRICT`` от воркспейса: удалить воркспейс, не разобравшись с прогонами,
нельзя и без него.

Revision ID: 20260801_0036
Revises: 20260801_0035
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260801_0036"
down_revision = "20260801_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_provider_call_budget",
        sa.Column(
            "pricing_run_item_id",
            sa.Uuid(),
            sa.ForeignKey("pricing_run_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("spent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("call_limit", sa.Integer(), nullable=False),
        sa.Column(
            "first_reserved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("spent >= 0", name="ck_llm_provider_call_budget_spent"),
        sa.CheckConstraint("call_limit > 0", name="ck_llm_provider_call_budget_limit"),
    )


def downgrade() -> None:
    op.drop_table("llm_provider_call_budget")
