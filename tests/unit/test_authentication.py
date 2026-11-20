import asyncio
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import Settings
from app.core.jwks import JWKSProvider, JWKSUnavailableError
from app.core.security import verify_access_token

KID = "test-signing-key"


@pytest.fixture
def signing_keys():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    public_numbers = private_key.public_key().public_numbers()

    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": KID,
                "n": jwt.utils.to_base64url_uint(public_numbers.n).decode(),
                "e": jwt.utils.to_base64url_uint(public_numbers.e).decode(),
            }
        ]
    }

    return private_key, jwks


@pytest.fixture
def settings():
    return Settings(
        aws_region="ap-south-1",
        jwks_bucket_name="test-jwks-bucket",
        jwks_object_key="security/jwks.json",
        cognito_region="ap-south-1",
        cognito_user_pool_id="ap-south-1_TESTPOOL",
        cognito_api_client_id="test-api-client",
    )


@pytest.fixture
def jwks_provider(signing_keys):
    _, jwks = signing_keys

    provider = JWKSProvider(
        aws_region="ap-south-1",
        bucket_name="test-jwks-bucket",
        object_key="security/jwks.json",
        s3_client=MagicMock(),
    )

    provider._read_snapshot = lambda: (
        jwks,
        datetime.now(UTC),
    )

    return provider


def create_token(
    private_key,
    settings,
    **overrides,
):
    now = int(time.time())

    claims = {
        "iss": settings.cognito_issuer,
        "sub": "test-user-123",
        "client_id": settings.cognito_api_client_id,
        "token_use": "access",
        "iat": now,
        "exp": now + 300,
        "scope": "openid email cloudsec-api/access",
    }

    claims.update(overrides)

    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": KID},
    )


def test_valid_access_token(
    signing_keys,
    settings,
    jwks_provider,
):
    private_key, _ = signing_keys

    token = create_token(private_key, settings)

    user = asyncio.run(verify_access_token(token, settings, jwks_provider))

    assert user.sub == "test-user-123"
    assert user.client_id == "test-api-client"
    assert user.token_use == "access"
    assert user.scope == "openid email cloudsec-api/access"


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 60},
        {"iss": "https://invalid-issuer.example.com"},
        {"token_use": "id"},
        {"client_id": "another-client"},
        {"sub": ""},
    ],
)
def test_invalid_access_token_claims(
    signing_keys,
    settings,
    jwks_provider,
    overrides,
):
    private_key, _ = signing_keys

    token = create_token(
        private_key,
        settings,
        **overrides,
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        asyncio.run(verify_access_token(token, settings, jwks_provider))

    assert exc.value.status_code == 401


def test_invalid_signature(settings, jwks_provider):

    another_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    token = create_token(another_key, settings)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        asyncio.run(verify_access_token(token, settings, jwks_provider))

    assert exc.value.status_code == 401


def test_missing_required_claim(signing_keys, settings, jwks_provider):
    private_key, _ = signing_keys

    token = create_token(
        private_key,
        settings,
        sub=None,
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        asyncio.run(verify_access_token(token, settings, jwks_provider))

    assert exc.value.status_code == 401


def test_unknown_signing_key(signing_keys, settings, jwks_provider):
    private_key, _ = signing_keys

    token = jwt.encode(
        {
            "iss": settings.cognito_issuer,
            "sub": "test-user-123",
            "client_id": settings.cognito_api_client_id,
            "token_use": "access",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "unknown-key"},
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        asyncio.run(verify_access_token(token, settings, jwks_provider))

    assert exc.value.status_code == 401


def test_jwks_unavailable_returns_503(
    signing_keys,
    settings,
):
    private_key, _ = signing_keys

    provider = JWKSProvider(
        aws_region="ap-south-1",
        bucket_name="test-jwks-bucket",
        s3_client=MagicMock(),
    )

    def mock_read():
        raise JWKSUnavailableError("Simulated S3 failure")

    provider._read_snapshot = mock_read

    token = create_token(private_key, settings)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        asyncio.run(verify_access_token(token, settings, provider))

    assert exc.value.status_code == 503


def test_oversized_access_token_rejected(settings, jwks_provider):
    from fastapi import HTTPException

    from app.core.security import MAX_ACCESS_TOKEN_LENGTH

    token = "a" * (MAX_ACCESS_TOKEN_LENGTH + 1)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(verify_access_token(token, settings, jwks_provider))

    assert exc.value.status_code == 401


@pytest.mark.parametrize(
    "scope",
    [
        123,
        [],
        {},
        True,
    ],
)
def test_non_string_scope_rejected(
    signing_keys,
    settings,
    jwks_provider,
    scope,
):
    private_key, _ = signing_keys

    token = create_token(
        private_key,
        settings,
        scope=scope,
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        asyncio.run(verify_access_token(token, settings, jwks_provider))

    assert exc.value.status_code == 401


def test_oversized_kid_rejected(
    signing_keys,
    settings,
    jwks_provider,
):
    private_key, _ = signing_keys

    token = jwt.encode(
        {
            "iss": settings.cognito_issuer,
            "sub": "test-user-123",
            "client_id": settings.cognito_api_client_id,
            "token_use": "access",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "k" * 257},
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        asyncio.run(verify_access_token(token, settings, jwks_provider))

    assert exc.value.status_code == 401


@pytest.mark.parametrize(
    "scope",
    [
        "openid email",
        "openid cloudsec-api/other",
        "cloudsec-api/access-extra",
        "",
    ],
)
def test_missing_or_insufficient_api_scope(
    signing_keys,
    settings,
    jwks_provider,
    scope,
):
    private_key, _ = signing_keys

    token = create_token(
        private_key,
        settings,
        scope=scope,
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        asyncio.run(verify_access_token(token, settings, jwks_provider))

    assert exc.value.status_code == 401
