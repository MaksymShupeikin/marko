"""Make owned-catalog discovery captures append-only (F2-0014).

Revision ID: 20260729_0026
Revises: 20260729_0025
Create Date: 2026-07-29

A measured rollback probe deleted one ``catalog_discovery_runs`` row and took
10 captures and 290 offers with it. The offers are derived and may cascade, but
a capture is the record binding a stored evidence blob to the URL, status code
and sequence number that produced it. ``scrape_evidence_blobs`` was already
protected by ``RESTRICT``, so the bytes survived while the meaning of those
bytes did not: an orphaned blob cannot be attributed to a request.

Two changes, both reversible:

1. ``catalog_discovery_captures.discovery_run_id`` becomes ``RESTRICT``, so a
   populated discovery run can no longer be deleted silently. No application
   code deletes discovery runs today, so nothing legitimate starts failing;
   an operator who really means to drop a run must delete its captures first
   and will hit the trigger below.
2. ``UPDATE`` and ``DELETE`` on captures are refused by the existing
   ``marko_reject_append_only_mutation`` trigger function, the same guard used
   for market observations and fitment evidence.

``catalog_discovery_offers`` keeps ``CASCADE``: parsed candidates are derived
from the captures and can be rebuilt from them.
"""

from __future__ import annotations

from alembic import op


revision = "20260729_0026"
down_revision = "20260729_0025"
branch_labels = None
depends_on = None

_FK = "catalog_discovery_captures_discovery_run_id_fkey"


def upgrade() -> None:
    op.drop_constraint(_FK, "catalog_discovery_captures", type_="foreignkey")
    op.create_foreign_key(
        _FK,
        "catalog_discovery_captures",
        "catalog_discovery_runs",
        ["discovery_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        "CREATE TRIGGER trg_catalog_discovery_captures_append_only "
        "BEFORE UPDATE OR DELETE ON catalog_discovery_captures FOR EACH ROW "
        "EXECUTE FUNCTION marko_reject_append_only_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_catalog_discovery_captures_append_only "
        "ON catalog_discovery_captures"
    )
    op.drop_constraint(_FK, "catalog_discovery_captures", type_="foreignkey")
    op.create_foreign_key(
        _FK,
        "catalog_discovery_captures",
        "catalog_discovery_runs",
        ["discovery_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
