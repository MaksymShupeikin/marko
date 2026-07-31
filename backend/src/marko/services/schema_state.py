"""Compare the schema the running code expects with the one the database has.

A stale container image produced a silent split-brain: the image's migration
graph ended at ``20260728_0024``, the persistent volume was at the same
revision, and the source tree was already at ``20260729_0025``. Every service
reported healthy while running against a schema the code no longer described
(F2-0015). Readiness now fails instead, because a schema mismatch is not a
degraded mode: it is a deployment that did not happen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import marko


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchemaRevisionStatus:
    code_head: str | None
    database_revision: str | None

    @property
    def in_sync(self) -> bool:
        return (
            self.code_head is not None
            and self.database_revision is not None
            and self.code_head == self.database_revision
        )

    def as_dict(self) -> dict[str, str | bool | None]:
        return {
            "code_head": self.code_head,
            "database_revision": self.database_revision,
            "in_sync": self.in_sync,
        }


def migrations_directory() -> Path:
    """Locate ``migrations/`` next to the installed package.

    Holds both in the image (``/app/src/marko`` → ``/app/migrations``) and in a
    source checkout (``backend/src/marko`` → ``backend/migrations``).
    """

    return Path(marko.__file__).resolve().parents[2] / "migrations"


@lru_cache(maxsize=1)
def code_schema_head() -> str | None:
    """Head revision of the migration scripts shipped with this code."""

    directory = migrations_directory()
    try:
        heads = ScriptDirectory(str(directory)).get_heads()
    except Exception:  # noqa: BLE001 - readiness must not raise on a bad layout
        log.exception("Не удалось прочитать граф миграций в %s", directory)
        return None
    if len(heads) != 1:
        log.error("Ожидалась одна head-ревизия, найдено %d: %s", len(heads), heads)
        return None
    return heads[0]


async def schema_revision_status(session: AsyncSession) -> SchemaRevisionStatus:
    """Revision recorded in the database against the one the code ships."""

    try:
        database_revision = await session.scalar(
            text("SELECT version_num FROM alembic_version")
        )
    except Exception:  # noqa: BLE001 - missing table means "not migrated yet"
        log.exception("Не удалось прочитать alembic_version")
        database_revision = None
    return SchemaRevisionStatus(
        code_head=code_schema_head(),
        database_revision=database_revision,
    )


__all__ = [
    "SchemaRevisionStatus",
    "code_schema_head",
    "migrations_directory",
    "schema_revision_status",
]
