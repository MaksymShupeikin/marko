"""Пейвол: повна або обмежена версія.

Модель проста: перші `free_check_limit` перевірок цін безкоштовні, далі — 402.
Повний доступ (`has_free_access`) вмикається вручну в БД після того, як
користувач надішле запит «зв'яжіться зі мною» — запит фіксується на воркспейсі
без дублів.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from marko.core.config import get_settings
from marko.infrastructure.db.models import Workspace

PAYWALL_DETAIL = (
    "Безкоштовні перевірки закінчилися. Надішліть запит на повний доступ."
)


def has_access(checks_used: int, has_free_access: bool, limit: int) -> bool:
    """Чи дозволена перевірка з номером `checks_used` (вже після інкременту)."""
    return has_free_access or checks_used <= limit


async def try_consume_check(session: AsyncSession, workspace_id: UUID) -> bool:
    """Списує одну перевірку і каже, чи вона була дозволена.

    Інкремент атомарний на рівні SQL, тож паралельні запити не гублять
    лічильник. Лічильник росте й у повній версії — це просто статистика.

    Окремо від ``consume_check``, бо фоновий прогін переоцінки не має права
    кидати HTTP-виняток: він мусить дорахувати те, що вже почав, і чесно
    написати в рядку, що ліміт вичерпано.
    """
    settings = get_settings()
    result = await session.execute(
        update(Workspace)
        .where(Workspace.id == workspace_id)
        .values(checks_used=Workspace.checks_used + 1)
        .returning(Workspace.checks_used, Workspace.has_free_access)
    )
    row = result.one()
    await session.commit()
    return has_access(row.checks_used, row.has_free_access, settings.free_check_limit)


async def checks_remaining(session: AsyncSession, workspace_id: UUID) -> int | None:
    """Скільки перевірок лишилось; ``None`` — необмежено (повний доступ)."""
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        return 0
    if workspace.has_free_access:
        return None
    left = get_settings().free_check_limit - workspace.checks_used
    return max(left, 0)


async def consume_check(session: AsyncSession, workspace_id: UUID) -> None:
    """Списує одну перевірку цін; кидає 402, коли ліміт вичерпано."""
    if not await try_consume_check(session, workspace_id):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=PAYWALL_DETAIL,
        )


async def request_full_access(session: AsyncSession, workspace_id: UUID) -> None:
    """Фіксує запит на повний доступ. Повторні виклики не перетирають перший."""
    await session.execute(
        update(Workspace)
        .where(
            Workspace.id == workspace_id,
            Workspace.access_requested_at.is_(None),
        )
        .values(access_requested_at=func.now())
    )
    await session.commit()


async def access_requested(session: AsyncSession, workspace_id: UUID) -> bool:
    workspace = await session.get(Workspace, workspace_id)
    return workspace is not None and workspace.access_requested_at is not None
