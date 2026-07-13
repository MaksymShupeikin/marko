from datetime import UTC, datetime, timedelta
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from marko.core.config import Settings
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
        "shared-secret-with-at-least-32-bytes",
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
        await auth.verify_firebase_id_token(
            _token(private_key, email_verified=False)
        )
