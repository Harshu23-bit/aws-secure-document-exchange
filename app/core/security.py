from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.jwks import JWKSProvider, JWKSUnavailableError

MAX_ACCESS_TOKEN_LENGTH = 16_384
MAX_KID_LENGTH = 256
REQUIRED_API_SCOPE = "cloudsec-api/access"

bearer_scheme = HTTPBearer(auto_error=False)


def require_bearer_credentials(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> HTTPAuthorizationCredentials:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials


@dataclass(frozen=True)
class AuthenticatedUser:
    sub: str
    client_id: str
    token_use: str
    scope: str | None = None


@lru_cache(maxsize=8)
def _cached_jwks_provider(
    aws_region: str,
    bucket_name: str,
    object_key: str,
) -> JWKSProvider:
    return JWKSProvider(
        aws_region=aws_region,
        bucket_name=bucket_name,
        object_key=object_key,
    )


def get_jwks_provider() -> JWKSProvider:
    configured_settings = get_settings()

    if not configured_settings.jwks_bucket_name:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        )

    return _cached_jwks_provider(
        configured_settings.aws_region,
        configured_settings.jwks_bucket_name,
        configured_settings.jwks_object_key,
    )


async def verify_access_token(
    token: str,
    settings: Settings,
    jwks_provider: JWKSProvider,
) -> AuthenticatedUser:
    try:
        if (
            not isinstance(token, str)
            or not token
            or len(token) > MAX_ACCESS_TOKEN_LENGTH
        ):
            raise jwt.InvalidTokenError("Invalid token size")

        if not settings.cognito_api_client_id:
            raise ValueError("Cognito API client ID is missing")

        issuer = settings.cognito_issuer

        header = jwt.get_unverified_header(token)

        if header.get("alg") != "RS256":
            raise jwt.InvalidTokenError("Unsupported signing algorithm")

        kid = header.get("kid")

        if not isinstance(kid, str) or not kid or len(kid) > MAX_KID_LENGTH:
            raise jwt.InvalidTokenError("Invalid signing key ID")

        signing_key = await jwks_provider.get_signing_key(kid)

        if signing_key is None:
            raise jwt.InvalidTokenError("Unknown signing key")

        claims = jwt.decode(
            token,
            key=signing_key,
            algorithms=["RS256"],
            issuer=issuer,
            options={
                "require": [
                    "exp",
                    "iat",
                    "sub",
                    "iss",
                    "token_use",
                    "client_id",
                ],
                "verify_aud": False,
            },
            leeway=30,
        )

        if claims.get("token_use") != "access":
            raise jwt.InvalidTokenError("Expected an access token")

        if claims.get("client_id") != settings.cognito_api_client_id:
            raise jwt.InvalidTokenError("Invalid token client")

        scope = claims.get("scope")

        if not isinstance(scope, str):
            raise jwt.InvalidTokenError("Invalid scope claim")

        token_scopes = scope.split()

        if REQUIRED_API_SCOPE not in token_scopes:
            raise jwt.InvalidTokenError("Missing required API scope")

        sub = claims.get("sub")

        if not isinstance(sub, str) or not sub:
            raise jwt.InvalidTokenError("Invalid subject")

        return AuthenticatedUser(
            sub=sub,
            client_id=claims["client_id"],
            token_use=claims["token_use"],
            scope=scope,
        )

    except JWKSUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc

    except (jwt.InvalidTokenError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials,
        Depends(require_bearer_credentials),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    jwks_provider: Annotated[JWKSProvider, Depends(get_jwks_provider)],
) -> AuthenticatedUser:
    return await verify_access_token(
        credentials.credentials,
        settings,
        jwks_provider,
    )
