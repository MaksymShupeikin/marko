"""Reusable FastAPI dependencies."""
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from marko.services.auth import (
    AuthConfigurationError,
    AuthConflictError,
    AuthContext,
    InvalidTokenError,
    get_or_create_auth_context,
    verify_bearer_token,
)
from marko.infrastructure.db.models import WorkspaceRole

from marko.infrastructure.db.session import get_session

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthContext:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise unauthorized
    try:
        identity = await verify_bearer_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise unauthorized from exc
    except AuthConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    try:
        return await get_or_create_auth_context(session, identity)
    except InvalidTokenError as exc:
        raise unauthorized from exc
    except AuthConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


CurrentUser = Annotated[AuthContext, Depends(get_current_user)]


async def require_workspace_admin(current: CurrentUser) -> AuthContext:
    if current.workspace_role not in {WorkspaceRole.owner, WorkspaceRole.admin}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "INSUFFICIENT_WORKSPACE_ROLE",
                "required_roles": [
                    WorkspaceRole.owner.value,
                    WorkspaceRole.admin.value,
                ],
                "actual_role": current.workspace_role.value,
            },
        )
    return current


WorkspaceAdmin = Annotated[AuthContext, Depends(require_workspace_admin)]

__all__ = [
    "CurrentUser",
    "WorkspaceAdmin",
    "get_current_user",
    "get_session",
    "require_workspace_admin",
]
