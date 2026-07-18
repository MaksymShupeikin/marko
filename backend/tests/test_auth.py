from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from marko.api.schemas.auth import AuthUserResponse
from marko.core.config import Settings
from marko.infrastructure.db.models import WorkspaceRole
from marko.services import auth


class _SigningKey:
    def __init__(self, key: object) -> None:
        self.key = key


class _JwksClient:
    def __init__(self, key: object) -> None:
        self._key = key

    def get_signing_key_from_jwt(self, token: str) -> _SigningKey:
        return _SigningKey(self._key)


@pytest.fixture
def signing_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _token(private_key: object, **overrides: object) -> str:
    now = datetime.now(UTC)
    timestamp = int(now.timestamp())
    payload = {
        "sub": "firebase-user-uid-001",
        "email": "Seller@Example.COM",
        "email_verified": True,
        "aud": "marko-test",
        "iss": "https://securetoken.google.com/marko-test",
        "auth_time": timestamp,
        "iat": timestamp,
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "name": "Prom Seller",
        "picture": "https://example.com/avatar.png",
        "firebase": {
            "sign_in_provider": "google.com",
            "identities": {"google.com": ["google-subject"]},
        },
    }
    payload.update(overrides)
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "test"})


@pytest.mark.asyncio
async def test_firebase_token_verification_returns_identity(monkeypatch, signing_keys):
    private_key, public_key = signing_keys
    settings = Settings(firebase_project_id="marko-test")
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "_jwks_client", lambda _: _JwksClient(public_key))

    identity = await auth.verify_firebase_id_token(_token(private_key))

    assert identity.subject == "firebase-user-uid-001"
    assert identity.email == "seller@example.com"
    assert identity.display_name == "Prom Seller"
    assert identity.avatar_url == "https://example.com/avatar.png"


@pytest.mark.asyncio
async def test_firebase_token_rejects_wrong_issuer(monkeypatch, signing_keys):
    private_key, public_key = signing_keys
    settings = Settings(firebase_project_id="marko-test")
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "_jwks_client", lambda _: _JwksClient(public_key))

    with pytest.raises(auth.InvalidTokenError):
        await auth.verify_firebase_id_token(
            _token(private_key, iss="https://securetoken.google.com/attacker")
        )


@pytest.mark.asyncio
async def test_firebase_token_requires_rs256_signing_key(monkeypatch):
    settings = Settings(firebase_project_id="marko-test")
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    token = jwt.encode(
        {"sub": "firebase-user-uid-001"},
        "test_secret_key_for_jwt_auth_" + "x" * 8,
        algorithm="HS256",
    )

    with pytest.raises(auth.InvalidTokenError, match="Unsupported"):
        await auth.verify_firebase_id_token(token)


@pytest.mark.asyncio
async def test_firebase_project_id_must_be_configured(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", lambda: Settings())

    with pytest.raises(auth.AuthConfigurationError, match="FIREBASE_PROJECT_ID"):
        await auth.verify_firebase_id_token("not-a-token")


@pytest.mark.asyncio
async def test_firebase_token_requires_verified_email(monkeypatch, signing_keys):
    private_key, public_key = signing_keys
    settings = Settings(firebase_project_id="marko-test")
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "_jwks_client", lambda _: _JwksClient(public_key))

    with pytest.raises(auth.InvalidTokenError, match="not verified"):
        await auth.verify_firebase_id_token(_token(private_key, email_verified=False))


@pytest.mark.asyncio
async def test_e2e_bearer_provider_is_environment_and_token_scoped(monkeypatch):
    token = "synthetic-e2e-token-" + "x" * 32
    settings = Settings(
        environment="e2e",
        e2e_auth_bypass=True,
        e2e_auth_token=token,
    )
    monkeypatch.setattr(auth, "get_settings", lambda: settings)

    identity = await auth.verify_bearer_token(token)

    assert identity.subject == "marko-e2e-user-v1"
    assert identity.email == "marko-e2e@example.com"
    response = AuthUserResponse(
        id=uuid4(),
        email=identity.email,
        display_name=identity.display_name,
        avatar_url=identity.avatar_url,
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.owner,
    )
    assert str(response.email) == identity.email
    with pytest.raises(auth.InvalidTokenError):
        await auth.verify_bearer_token(token + "-wrong")


def test_e2e_bearer_provider_cannot_be_configured_outside_e2e() -> None:
    with pytest.raises(ValueError, match="ENVIRONMENT=e2e"):
        Settings(
            environment="production",
            allowed_hosts="api.example.invalid",
            cors_origins="https://app.example.invalid",
            firebase_project_id="marko-production",
            e2e_auth_bypass=True,
            e2e_auth_token="synthetic-e2e-token-" + "x" * 32,
        )
    with pytest.raises(ValueError, match="at least 32"):
        Settings(environment="e2e", e2e_auth_bypass=True, e2e_auth_token="short")
