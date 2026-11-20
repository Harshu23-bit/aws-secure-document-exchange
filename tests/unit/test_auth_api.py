from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings, get_settings
from app.core.jwks import JWKSProvider
from app.core.security import (
    AuthenticatedUser,
    get_current_user,
    get_jwks_provider,
)
from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def configured_settings():
    return Settings(
        aws_region="ap-south-1",
        jwks_bucket_name="test-jwks-bucket",
        jwks_object_key="security/jwks.json",
        cognito_region="ap-south-1",
        cognito_user_pool_id="ap-south-1_TESTPOOL",
        cognito_api_client_id="test-api-client",
    )


@pytest.fixture
def jwks_provider():
    return JWKSProvider(
        aws_region="ap-south-1",
        bucket_name="test-jwks-bucket",
        object_key="security/jwks.json",
        s3_client=MagicMock(),
    )


@pytest.fixture
async def client():
    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_authenticated_user_endpoint(client):
    async def mock_current_user():
        return AuthenticatedUser(
            sub="test-user-123",
            client_id="test-api-client",
            token_use="access",
            scope="openid email cloudsec-api/access",
        )

    app.dependency_overrides[get_current_user] = mock_current_user

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "sub": "test-user-123",
        "client_id": "test-api-client",
        "token_use": "access",
        "scope": "openid email cloudsec-api/access",
    }


@pytest.mark.anyio
async def test_missing_bearer_token_returns_401(
    client,
    configured_settings,
    jwks_provider,
):
    app.dependency_overrides[get_settings] = lambda: configured_settings
    app.dependency_overrides[get_jwks_provider] = lambda: jwks_provider

    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "http_error"
    assert response.json()["error"]["message"] == ("Authentication required")
    assert "request_id" in response.json()
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.anyio
async def test_malformed_bearer_token_returns_401(
    client,
    configured_settings,
    jwks_provider,
):
    app.dependency_overrides[get_settings] = lambda: configured_settings
    app.dependency_overrides[get_jwks_provider] = lambda: jwks_provider

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "http_error"
    assert response.json()["error"]["message"] == ("Invalid or expired access token")
    assert "request_id" in response.json()
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.anyio
async def test_missing_token_returns_401_when_cognito_unconfigured(
    client,
):
    app.dependency_overrides[get_settings] = lambda: Settings()

    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["message"] == ("Authentication required")
    assert response.headers["www-authenticate"] == "Bearer"
