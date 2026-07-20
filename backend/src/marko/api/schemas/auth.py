"""Request and response schemas for Marko authentication."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr

from marko.infrastructure.db.models import WorkspaceRole


class AuthUserResponse(BaseModel):
    id: UUID
    email: EmailStr
    display_name: str | None
    avatar_url: str | None
    workspace_id: UUID
    workspace_role: WorkspaceRole
