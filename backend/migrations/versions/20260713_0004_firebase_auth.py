"""Replace the legacy Supabase subject with a Firebase UID.

Revision ID: 20260713_0004
Revises: 20260713_0003
Create Date: 2026-07-13
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260713_0004"
down_revision: str | None = "20260713_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing business users/workspaces remain intact. They are linked by email
    # to a Firebase UID on the first verified Firebase request.
    op.add_column("users", sa.Column("firebase_uid", sa.String(128), nullable=True))
    op.create_index(
        "ix_users_firebase_uid", "users", ["firebase_uid"], unique=True
    )
    op.drop_index("ix_users_auth_subject", table_name="users")
    op.drop_column("users", "auth_subject")


def downgrade() -> None:
    op.add_column("users", sa.Column("auth_subject", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_users_auth_subject", "users", ["auth_subject"], unique=True
    )
    op.drop_index("ix_users_firebase_uid", table_name="users")
    op.drop_column("users", "firebase_uid")
