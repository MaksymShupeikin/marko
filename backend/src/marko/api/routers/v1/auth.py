"""Account information backed by a verified Firebase session."""
from fastapi import APIRouter

from marko.api.dependencies import CurrentUser
from marko.api.schemas.auth import AuthUserResponse

router = APIRouter()


@router.get("/me", response_model=AuthUserResponse)
async def me(current: CurrentUser) -> AuthUserResponse:
    return AuthUserResponse(
        id=current.user.id,
        email=current.user.email,
        display_name=current.user.display_name,
        avatar_url=current.user.avatar_url,
        workspace_id=current.workspace_id,
        workspace_role=current.workspace_role,
    )
