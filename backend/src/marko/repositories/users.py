from __future__ import annotations

import uuid
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email))


async def get_user_by_firebase_uid(
    session: AsyncSession, firebase_uid: str
) -> User | None:
    return await session.scalar(select(User).where(User.firebase_uid == firebase_uid))


async def create_user(
    session: AsyncSession,
    *,
    firebase_uid: str,
    email: str,
    display_name: str | None = None,
    avatar_url: str | None = None,
    is_active: bool = True,
) -> User:
    user = User(
        firebase_uid=firebase_uid,
        email=email,
        display_name=display_name,
        avatar_url=avatar_url,
        is_active=is_active,
    )
    session.add(user)
    return user


async def get_workspace_member(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> WorkspaceMember | None:
    return await session.get(WorkspaceMember, (workspace_id, user_id))


async def get_first_workspace_id_by_user_id(
    session: AsyncSession, user_id: uuid.UUID
) -> uuid.UUID | None:
    member = await get_first_workspace_member_by_user_id(session, user_id)
    return member.workspace_id if member is not None else None


async def get_first_workspace_member_by_user_id(
    session: AsyncSession, user_id: uuid.UUID
) -> WorkspaceMember | None:
    return await session.scalar(
        select(WorkspaceMember)
        .where(WorkspaceMember.user_id == user_id)
        .order_by(WorkspaceMember.created_at)
        .limit(1)
    )


async def create_workspace(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    name: str,
    slug: str,
) -> Workspace:
    workspace = Workspace(id=workspace_id, name=name, slug=slug)
    session.add(workspace)
    return workspace


async def create_workspace_member(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    role: WorkspaceRole,
) -> WorkspaceMember:
    member = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role)
    session.add(member)
    return member


async def ensure_default_workspace(
    session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    statement = insert(Workspace).values(
        id=workspace_id,
        name="Development Workspace",
        slug="development",
    )
    await session.execute(statement.on_conflict_do_nothing())
