import asyncio
import io
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import jwt
import pytest
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.jwks import (
    JWKSProvider,
    JWKSUnavailableError,
)

BUCKET = "test-jwks-bucket"
OBJECT_KEY = "security/jwks.json"
REGION = "ap-south-1"


def create_rsa_key():
    return rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )


def create_jwk(private_key, kid="test-key"):
    public_numbers = private_key.public_key().public_numbers()

    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": jwt.utils.to_base64url_uint(public_numbers.n).decode(),
        "e": jwt.utils.to_base64url_uint(public_numbers.e).decode(),
    }


def create_jwks(*keys):
    return {"keys": list(keys)}


def create_provider(monkeypatch, jwks, last_modified=None):
    if last_modified is None:
        last_modified = datetime.now(UTC)

    s3 = MagicMock()

    provider = JWKSProvider(
        aws_region=REGION,
        bucket_name=BUCKET,
        object_key=OBJECT_KEY,
        s3_client=s3,
    )

    monkeypatch.setattr(
        provider,
        "_read_snapshot",
        lambda: (jwks, last_modified),
    )

    return provider, s3


def expire_unknown_kid_cooldown(provider):
    provider._unknown_kid_refresh_at = (
        time.monotonic() - provider.UNKNOWN_KID_REFRESH_COOLDOWN - 1
    )


def test_provider_rejects_invalid_region():
    with pytest.raises(ValueError, match="region"):
        JWKSProvider(
            aws_region="https://malicious.example",
            bucket_name=BUCKET,
            s3_client=MagicMock(),
        )


def test_provider_rejects_invalid_bucket():
    with pytest.raises(ValueError, match="bucket"):
        JWKSProvider(
            aws_region=REGION,
            bucket_name="INVALID_BUCKET",
            s3_client=MagicMock(),
        )


def test_provider_rejects_invalid_object_key():
    with pytest.raises(ValueError, match="object key"):
        JWKSProvider(
            aws_region=REGION,
            bucket_name=BUCKET,
            object_key="/security/jwks.json",
            s3_client=MagicMock(),
        )


def test_initial_s3_retrieval_and_cache(monkeypatch):
    private_key = create_rsa_key()
    jwks = create_jwks(create_jwk(private_key))

    provider, _ = create_provider(monkeypatch, jwks)

    calls = 0
    original_read = provider._read_snapshot

    def counted_read():
        nonlocal calls
        calls += 1
        return original_read()

    monkeypatch.setattr(provider, "_read_snapshot", counted_read)

    first = asyncio.run(provider.get_signing_key("test-key"))

    second = asyncio.run(provider.get_signing_key("test-key"))

    assert first is not None
    assert first is second
    assert calls == 1


def test_cache_ttl_expiry_refreshes_s3(monkeypatch):
    private_key = create_rsa_key()
    jwks = create_jwks(create_jwk(private_key))

    provider, _ = create_provider(monkeypatch, jwks)

    calls = 0

    def read_snapshot():
        nonlocal calls
        calls += 1
        return jwks, datetime.now(UTC)

    monkeypatch.setattr(
        provider,
        "_read_snapshot",
        read_snapshot,
    )

    first = asyncio.run(provider.get_signing_key("test-key"))

    provider._expires_at = 0

    second = asyncio.run(provider.get_signing_key("test-key"))

    assert first is not None
    assert second is not None
    assert calls == 2


def test_unknown_kid_triggers_rotation_refresh(monkeypatch):
    old_private_key = create_rsa_key()
    new_private_key = create_rsa_key()

    old_jwks = create_jwks(create_jwk(old_private_key, "old-key"))

    rotated_jwks = create_jwks(
        create_jwk(old_private_key, "old-key"),
        create_jwk(new_private_key, "new-key"),
    )

    provider, _ = create_provider(monkeypatch, old_jwks)

    calls = 0

    def read_snapshot():
        nonlocal calls
        calls += 1

        if calls == 1:
            return old_jwks, datetime.now(UTC)

        return rotated_jwks, datetime.now(UTC)

    monkeypatch.setattr(
        provider,
        "_read_snapshot",
        read_snapshot,
    )

    old_key = asyncio.run(provider.get_signing_key("old-key"))

    expire_unknown_kid_cooldown(provider)

    new_key = asyncio.run(provider.get_signing_key("new-key"))

    assert old_key is not None
    assert new_key is not None
    assert calls == 2


def test_unknown_kid_returns_none_after_successful_refresh(
    monkeypatch,
):
    private_key = create_rsa_key()
    jwks = create_jwks(create_jwk(private_key))

    provider, _ = create_provider(monkeypatch, jwks)

    result = asyncio.run(provider.get_signing_key("unknown-key"))

    assert result is None


def test_unknown_kid_refresh_is_rate_limited(monkeypatch):
    private_key = create_rsa_key()
    jwks = create_jwks(create_jwk(private_key))

    provider, _ = create_provider(monkeypatch, jwks)

    calls = 0

    def read_snapshot():
        nonlocal calls
        calls += 1
        return jwks, datetime.now(UTC)

    monkeypatch.setattr(
        provider,
        "_read_snapshot",
        read_snapshot,
    )

    assert asyncio.run(provider.get_signing_key("unknown-1")) is None

    assert asyncio.run(provider.get_signing_key("unknown-2")) is None

    assert calls == 1


def test_unknown_kid_refresh_failure_returns_unavailable(
    monkeypatch,
):
    private_key = create_rsa_key()
    jwks = create_jwks(create_jwk(private_key))

    provider, _ = create_provider(monkeypatch, jwks)

    calls = 0

    def read_snapshot():
        nonlocal calls
        calls += 1

        if calls == 1:
            return jwks, datetime.now(UTC)

        raise JWKSUnavailableError("Simulated S3 outage")

    monkeypatch.setattr(
        provider,
        "_read_snapshot",
        read_snapshot,
    )

    existing = asyncio.run(provider.get_signing_key("test-key"))

    assert existing is not None

    expire_unknown_kid_cooldown(provider)

    with pytest.raises(JWKSUnavailableError):
        asyncio.run(provider.get_signing_key("unknown-key"))

    with pytest.raises(JWKSUnavailableError):
        asyncio.run(provider.get_signing_key("unknown-key"))

    assert calls == 2


def test_fresh_cached_key_remains_usable_during_s3_outage(
    monkeypatch,
):
    private_key = create_rsa_key()
    jwks = create_jwks(create_jwk(private_key))

    provider, _ = create_provider(monkeypatch, jwks)

    calls = 0

    def read_snapshot():
        nonlocal calls
        calls += 1

        if calls == 1:
            return jwks, datetime.now(UTC)

        raise JWKSUnavailableError("S3 unavailable")

    monkeypatch.setattr(
        provider,
        "_read_snapshot",
        read_snapshot,
    )

    original = asyncio.run(provider.get_signing_key("test-key"))

    provider._expires_at = 0

    cached = asyncio.run(provider.get_signing_key("test-key"))

    assert original is not None
    assert cached is original
    assert calls == 2


def test_stale_snapshot_is_rejected(monkeypatch):
    private_key = create_rsa_key()
    jwks = create_jwks(create_jwk(private_key))

    stale_timestamp = datetime.now(UTC) - timedelta(
        seconds=JWKSProvider.MAX_SNAPSHOT_AGE_SECONDS + 1
    )

    provider, _ = create_provider(
        monkeypatch,
        jwks,
        stale_timestamp,
    )

    with pytest.raises(JWKSUnavailableError, match="older"):
        asyncio.run(provider.get_signing_key("test-key"))


def test_future_snapshot_beyond_clock_skew_is_rejected(
    monkeypatch,
):
    private_key = create_rsa_key()
    jwks = create_jwks(create_jwk(private_key))

    future_timestamp = datetime.now(UTC) + timedelta(
        seconds=JWKSProvider.MAX_FUTURE_CLOCK_SKEW_SECONDS + 1
    )

    provider, _ = create_provider(
        monkeypatch,
        jwks,
        future_timestamp,
    )

    with pytest.raises(JWKSUnavailableError, match="future"):
        asyncio.run(provider.get_signing_key("test-key"))


def test_naive_last_modified_is_rejected(monkeypatch):
    private_key = create_rsa_key()
    jwks = create_jwks(create_jwk(private_key))

    provider, _ = create_provider(
        monkeypatch,
        jwks,
        datetime.now(),
    )

    with pytest.raises(JWKSUnavailableError, match="timestamp"):
        asyncio.run(provider.get_signing_key("test-key"))


def test_missing_last_modified_is_rejected(monkeypatch):
    private_key = create_rsa_key()
    jwks = create_jwks(create_jwk(private_key))

    provider, _ = create_provider(monkeypatch, jwks)

    monkeypatch.setattr(
        provider,
        "_read_snapshot",
        lambda: (jwks, None),
    )

    with pytest.raises(JWKSUnavailableError):
        asyncio.run(provider.get_signing_key("test-key"))


def test_duplicate_kid_is_rejected(monkeypatch):
    private_key = create_rsa_key()
    jwk = create_jwk(private_key)

    provider, _ = create_provider(
        monkeypatch,
        create_jwks(jwk, jwk),
    )

    with pytest.raises(JWKSUnavailableError, match="Duplicate"):
        asyncio.run(provider.get_signing_key("test-key"))


def test_invalid_rsa_material_is_rejected(monkeypatch):
    invalid_jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": "invalid-key",
        "n": "not-a-valid-modulus",
        "e": "AQAB",
    }

    provider, _ = create_provider(
        monkeypatch,
        create_jwks(invalid_jwk),
    )

    with pytest.raises(JWKSUnavailableError):
        asyncio.run(provider.get_signing_key("invalid-key"))


def test_private_rsa_parameters_are_rejected(monkeypatch):
    private_key = create_rsa_key()
    jwk = create_jwk(private_key)
    jwk["d"] = "private-material"

    provider, _ = create_provider(
        monkeypatch,
        create_jwks(jwk),
    )

    with pytest.raises(JWKSUnavailableError, match="private"):
        asyncio.run(provider.get_signing_key("test-key"))


def test_excessive_key_count_is_rejected(monkeypatch):
    private_key = create_rsa_key()

    keys = [
        create_jwk(private_key, f"key-{index}")
        for index in range(JWKSProvider.MAX_KEYS + 1)
    ]

    provider, _ = create_provider(
        monkeypatch,
        create_jwks(*keys),
    )

    with pytest.raises(JWKSUnavailableError):
        asyncio.run(provider.get_signing_key("key-0"))


def test_oversized_kid_in_snapshot_is_rejected(monkeypatch):
    private_key = create_rsa_key()

    jwk = create_jwk(
        private_key,
        "k" * (JWKSProvider.MAX_KID_LENGTH + 1),
    )

    provider, _ = create_provider(
        monkeypatch,
        create_jwks(jwk),
    )

    with pytest.raises(JWKSUnavailableError, match="key ID"):
        asyncio.run(provider.get_signing_key("valid-requested-key"))


def test_oversized_s3_object_is_rejected(monkeypatch):
    provider = JWKSProvider(
        aws_region=REGION,
        bucket_name=BUCKET,
        s3_client=MagicMock(),
    )

    body = MagicMock()
    body.read.return_value = b"x" * (JWKSProvider.MAX_RESPONSE_SIZE + 1)

    body.close = MagicMock()

    provider._s3.get_object.return_value = {
        "Body": body,
        "ContentLength": JWKSProvider.MAX_RESPONSE_SIZE + 1,
        "LastModified": datetime.now(UTC),
    }

    with pytest.raises(JWKSUnavailableError, match="size"):
        provider._read_snapshot()

    body.close.assert_called_once()


@pytest.mark.parametrize(
    "content_length",
    [
        True,
        False,
        -1,
        JWKSProvider.MAX_RESPONSE_SIZE + 1,
    ],
)
def test_invalid_s3_content_length_is_rejected(content_length):
    provider = JWKSProvider(
        aws_region=REGION,
        bucket_name=BUCKET,
        s3_client=MagicMock(),
    )

    body = MagicMock()

    provider._s3.get_object.return_value = {
        "Body": body,
        "ContentLength": content_length,
        "LastModified": datetime.now(UTC),
    }

    with pytest.raises(JWKSUnavailableError, match="size"):
        provider._read_snapshot()

    body.read.assert_not_called()
    body.close.assert_called_once()


def test_missing_s3_content_length_is_rejected():
    provider = JWKSProvider(
        aws_region=REGION,
        bucket_name=BUCKET,
        s3_client=MagicMock(),
    )

    body = MagicMock()

    provider._s3.get_object.return_value = {
        "Body": body,
        "LastModified": datetime.now(UTC),
    }

    with pytest.raises(JWKSUnavailableError, match="size"):
        provider._read_snapshot()

    body.read.assert_not_called()
    body.close.assert_called_once()


@pytest.mark.parametrize(
    "declared_length_offset",
    [-1, 1],
)
def test_s3_body_length_mismatch_is_rejected(
    declared_length_offset,
):
    provider = JWKSProvider(
        aws_region=REGION,
        bucket_name=BUCKET,
        s3_client=MagicMock(),
    )

    data = b'{"keys":[{"kty":"RSA"}]}'
    body = io.BytesIO(data)

    provider._s3.get_object.return_value = {
        "Body": body,
        "ContentLength": len(data) + declared_length_offset,
        "LastModified": datetime.now(UTC),
    }

    with pytest.raises(
        JWKSUnavailableError,
        match="body length",
    ):
        provider._read_snapshot()

    assert body.closed


def test_matching_s3_content_length_is_accepted():
    provider = JWKSProvider(
        aws_region=REGION,
        bucket_name=BUCKET,
        s3_client=MagicMock(),
    )

    data = b'{"keys":[{"kty":"RSA"}]}'
    body = io.BytesIO(data)
    last_modified = datetime.now(UTC)

    provider._s3.get_object.return_value = {
        "Body": body,
        "ContentLength": len(data),
        "LastModified": last_modified,
    }

    document, timestamp = provider._read_snapshot()

    assert document == {"keys": [{"kty": "RSA"}]}
    assert timestamp == last_modified
    assert body.closed


def test_invalid_json_is_rejected(monkeypatch):
    provider = JWKSProvider(
        aws_region=REGION,
        bucket_name=BUCKET,
        s3_client=MagicMock(),
    )

    body = io.BytesIO(b"{invalid-json")

    provider._s3.get_object.return_value = {
        "Body": body,
        "ContentLength": 13,
        "LastModified": datetime.now(UTC),
    }

    with pytest.raises(JWKSUnavailableError, match="JSON"):
        provider._read_snapshot()

    assert body.closed


def test_s3_client_error_is_mapped_to_unavailable(monkeypatch):
    provider = JWKSProvider(
        aws_region=REGION,
        bucket_name=BUCKET,
        s3_client=MagicMock(),
    )

    provider._s3.get_object.side_effect = ClientError(
        {
            "Error": {
                "Code": "AccessDenied",
                "Message": "Access denied",
            }
        },
        "GetObject",
    )

    with pytest.raises(JWKSUnavailableError):
        provider._read_snapshot()


def test_leading_zero_rsa_integer_is_rejected():
    with pytest.raises(JWKSUnavailableError):
        JWKSProvider._decode_base64url_uint("AAAB")
