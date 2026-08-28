"""Persist owned sellers independently from removable store catalogs.

Revision ID: 20260828_0012
Revises: 20260826_0011
Create Date: 2026-08-28
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from urllib.parse import urlsplit

from alembic import op
import sqlalchemy as sa

revision: str = "20260828_0012"
down_revision: str | None = "20260826_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SELLER_SLUG_RE = re.compile(
    r"^/(?:[a-z]{2}/)?c\d+-(?P<slug>[\w-]+)\.html/?$",
    re.I,
)


def _normalized_slug(name: str | None, canonical_url: str, external_id: str) -> str:
    value = (name or "").strip().casefold()
    if value:
        return value
    match = _SELLER_SLUG_RE.fullmatch(urlsplit(canonical_url).path)
    if match is not None:
        return match.group("slug").casefold()
    return external_id.casefold()


def upgrade() -> None:
    exclusions = op.create_table(
        "competitor_seller_exclusions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("marketplace", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "marketplace",
            "external_id",
            name="uq_competitor_seller_exclusion",
        ),
    )
    op.create_index(
        "ix_competitor_seller_exclusions_workspace_id",
        "competitor_seller_exclusions",
        ["workspace_id"],
    )

    bind = op.get_bind()
    owned = bind.execute(
        sa.text(
            """
            SELECT DISTINCT
                ms.workspace_id,
                ms.marketplace,
                ms.external_id,
                ms.name,
                ms.canonical_url
            FROM marketplace_stores AS ms
            JOIN workspace_stores AS ws
              ON ws.store_id = ms.id
             AND ws.workspace_id = ms.workspace_id
            WHERE ws.kind = 'owned'
              AND lower(ms.marketplace) = 'prom'
            """
        )
    ).mappings()
    rows = [
        {
            "id": uuid.uuid4(),
            "workspace_id": row["workspace_id"],
            "marketplace": "prom",
            "external_id": str(row["external_id"]).strip(),
            "slug": _normalized_slug(
                row["name"], row["canonical_url"], str(row["external_id"])
            ),
            "canonical_url": str(row["canonical_url"]).strip(),
        }
        for row in owned
    ]
    if rows:
        op.bulk_insert(exclusions, rows)


def downgrade() -> None:
    op.drop_index(
        "ix_competitor_seller_exclusions_workspace_id",
        table_name="competitor_seller_exclusions",
    )
    op.drop_table("competitor_seller_exclusions")
