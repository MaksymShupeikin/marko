"""Скасування імпорту: статус cancelled для sync_runs.

Revision ID: 20260824_0008
Revises: 20260823_0007
Create Date: 2026-08-24
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260824_0008"
down_revision: str | None = "20260823_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE sync_status ADD VALUE IF NOT EXISTS 'cancelled'")


def downgrade() -> None:
    # Postgres не вміє прибирати значення з enum; лишаємо як є.
    pass
