"""Merge the unified-catalog and KEMP internal-code migration branches.

Revision ID: 20260810_0051
Revises: 20260807_0045, 20260809_0050
"""

from collections.abc import Sequence


revision: str = "20260810_0051"
down_revision: tuple[str, str] = ("20260807_0045", "20260809_0050")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join both already-applied schema branches."""


def downgrade() -> None:
    """Split the graph back into its two parent branches."""
