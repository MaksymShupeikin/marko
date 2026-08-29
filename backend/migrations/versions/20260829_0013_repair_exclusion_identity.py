"""Repair the exclusion identity constraint after a diverged 0012.

Дві гілки створили ревізію 20260828_0012 під одним номером, але з різними
іменами унікального обмеження. Alembic вважає ревізію застосованою і не
переграє її, тому база лишалася з чужим ім'ям, а код падав на
``ON CONFLICT ON CONSTRAINT uq_competitor_seller_exclusion_identity`` —
у користувача це виглядало як «Failed to fetch» при імпорті XLSX.

Міграція ідемпотентна: на базі, створеній «своєю» 0012, вона нічого не робить.

Revision ID: 20260829_0013
Revises: 20260828_0012
Create Date: 2026-08-29
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260829_0013"
down_revision: str | None = "20260828_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "competitor_seller_exclusions"
_OLD = "uq_competitor_seller_exclusion"
_NEW = "uq_competitor_seller_exclusion_identity"


def _rename(source: str, target: str) -> str:
    return f"""
        DO $$
        BEGIN
            IF to_regclass('{_TABLE}') IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM pg_constraint
                   WHERE conname = '{source}'
                     AND conrelid = '{_TABLE}'::regclass
               )
               AND NOT EXISTS (
                   SELECT 1 FROM pg_constraint
                   WHERE conname = '{target}'
                     AND conrelid = '{_TABLE}'::regclass
               )
            THEN
                ALTER TABLE {_TABLE}
                    RENAME CONSTRAINT {source} TO {target};
            END IF;
        END $$;
    """


def upgrade() -> None:
    op.execute(_rename(_OLD, _NEW))
    # Модель тримає slug необов'язковим; чужа 0012 зробила його NOT NULL.
    # DROP NOT NULL не помиляється, коли колонка вже дозволяє NULL.
    op.execute(f"ALTER TABLE {_TABLE} ALTER COLUMN slug DROP NOT NULL")


def downgrade() -> None:
    op.execute(_rename(_NEW, _OLD))
