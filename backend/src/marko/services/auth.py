"""Firebase ID-token verification and local account provisioning."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

import jwt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from marko.core.config import Settings, get_settings
from marko.infrastructure.db.models import User, WorkspaceRole
import marko.repositories.users as users_repo


class AuthError(RuntimeError):
    pass


class AuthConfigurationError(AuthError):
    pass


class InvalidTokenError(AuthError):
    pass


class AuthConflictError(AuthError):
    pass


@dataclass(frozen=True)
class AuthContext:
    user: User
    workspace_id: UUID


@dataclass(frozen=True)
class FirebaseIdentity:
    subject: str
    email: str
    display_name: str | None
    avatar_url: str | None


async def verify_firebase_id_token(token: str) -> FirebaseIdentity:
    settings = get_settings()
    _require_firebase_settings(settings)
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise InvalidTokenError("Unsupported Firebase token signing key")
        signing_key = await asyncio.to_thread(
            _jwks_client(settings.firebase_jwks_url).get_signing_key_from_jwt,
            token,
        )
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.firebase_project_id,
            issuer=settings.firebase_auth_issuer,
            options={
                "require": [
                    "sub",
                    "email",
                    "email_verified",
                    "auth_time",
                    "iat",
                    "exp",
                    "iss",
                    "aud",
                ]
            },
        )
        subject = str(payload["sub"]).strip()
        if not subject or len(subject) > 128:
            raise InvalidTokenError("Firebase token does not contain a valid uid")
        if payload["email_verified"] is not True:
            raise InvalidTokenError("Firebase email is not verified")
        auth_time = payload["auth_time"]
        now = int(datetime.now(UTC).timestamp())
        if not isinstance(auth_time, (int, float)) or auth_time > now + 60:
            raise InvalidTokenError("Firebase token has an invalid auth_time")
        email = str(payload["email"]).strip().casefold()
        if not email or "@" not in email:
            raise InvalidTokenError("Firebase token does not contain a valid email")
        return FirebaseIdentity(
            subject=subject,
            email=email,
            display_name=_optional_string(
                payload.get("name"),
                max_length=160,
            ),
            avatar_url=_optional_string(payload.get("picture")),
        )
    except InvalidTokenError:
        raise
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise InvalidTokenError("Firebase ID token is invalid or expired") from exc


async def get_or_create_auth_context(
    session: AsyncSession, identity: FirebaseIdentity
) -> AuthContext:
    user = await users_repo.get_user_by_firebase_uid(session, identity.subject)
    needs_commit = False
    if user is None:
        existing_email = await users_repo.get_user_by_email(session, identity.email)
        if existing_email is not None:
            if existing_email.firebase_uid is not None:
                raise AuthConflictError("This email belongs to another Marko account")
            # Links accounts created before Firebase without losing their data.
            existing_email.firebase_uid = identity.subject
            user = existing_email
            needs_commit = True
        else:
            user = await users_repo.create_user(
                session,
                firebase_uid=identity.subject,
                email=identity.email,
                display_name=identity.display_name,
                avatar_url=identity.avatar_url,
                is_active=True,
            )
            session.add(user)
            try:
                await session.flush()
            except IntegrityError as exc:
                await session.rollback()
                concurrent = await _concurrent_auth_context(session, identity.subject)
                if concurrent is not None:
                    return concurrent
                raise AuthConflictError(
                    "Marko account could not be linked to Firebase"
                ) from exc
            needs_commit = True

    if not user.is_active:
        raise InvalidTokenError("Marko account is disabled")

    # The name and picture live in Firebase: keep our copy in step, otherwise
    # accounts created before a Google link never get one.
    if identity.display_name and user.display_name != identity.display_name:
        user.display_name = identity.display_name
        needs_commit = True
    if identity.avatar_url and user.avatar_url != identity.avatar_url:
        user.avatar_url = identity.avatar_url
        needs_commit = True

    workspace_id = await users_repo.get_first_workspace_id_by_user_id(session, user.id)
    if workspace_id is None:
        workspace_id = await _create_workspace(session, user)
        needs_commit = True

    if not needs_commit:
        return AuthContext(user=user, workspace_id=workspace_id)

    try:
        await session.commit()
        await session.refresh(user)
    except IntegrityError as exc:
        await session.rollback()
        concurrent = await _concurrent_auth_context(session, identity.subject)
        if concurrent is not None:
            return concurrent
        raise AuthConflictError("Marko account could not be linked to Firebase") from exc
    return AuthContext(user=user, workspace_id=workspace_id)


async def _concurrent_auth_context(
    session: AsyncSession, subject: str
) -> AuthContext | None:
    user = await users_repo.get_user_by_firebase_uid(session, subject)
    if user is None or not user.is_active:
        return None
    workspace_id = await users_repo.get_first_workspace_id_by_user_id(session, user.id)
    if workspace_id is None:
        return None
    return AuthContext(user=user, workspace_id=workspace_id)


async def _create_workspace(session: AsyncSession, user: User) -> UUID:
    workspace_id = uuid4()
    local_part = user.email.split("@", 1)[0]
    slug_base = re.sub(r"[^a-z0-9]+", "-", local_part.casefold()).strip("-")
    await users_repo.create_workspace(
        session,
        workspace_id=workspace_id,
        name=f"{local_part}'s workspace",
        slug=f"{slug_base or 'workspace'}-{workspace_id.hex[:8]}",
    )
    await users_repo.create_workspace_member(
        session,
        workspace_id=workspace_id,
        user_id=user.id,
        role=WorkspaceRole.owner,
    )
    return workspace_id


def _require_firebase_settings(settings: Settings) -> None:
    if not settings.firebase_project_id.strip():
        raise AuthConfigurationError("FIREBASE_PROJECT_ID must be configured")


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=600)


def _optional_string(value: Any, *, max_length: int | None = None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    return normalized[:max_length] if max_length is not None else normalized
