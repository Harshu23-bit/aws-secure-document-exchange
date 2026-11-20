import asyncio
import base64
import binascii
import json
import re
import time
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from jwt import PyJWK

PRIVATE_RSA_PARAMETERS = {
    "d",
    "p",
    "q",
    "dp",
    "dq",
    "qi",
    "oth",
}


class JWKSUnavailableError(Exception):
    """Raised when the JWKS snapshot cannot be retrieved or trusted."""


class JWKSProvider:
    MAX_RESPONSE_SIZE = 65_536
    MAX_KEYS = 10
    MAX_KID_LENGTH = 256

    MIN_RSA_BITS = 2048
    MAX_RSA_BITS = 8192
    MAX_RSA_EXPONENT = (2**32) - 1

    CACHE_TTL_SECONDS = 300
    MAX_SNAPSHOT_AGE_SECONDS = 10_800
    MAX_FUTURE_CLOCK_SKEW_SECONDS = 300

    UNKNOWN_KID_REFRESH_COOLDOWN = 30

    AWS_REGION_PATTERN = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-\d+$")
    BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")

    def __init__(
        self,
        aws_region: str,
        bucket_name: str,
        object_key: str = "security/jwks.json",
        s3_client=None,
    ):
        if not isinstance(aws_region, str) or not self.AWS_REGION_PATTERN.fullmatch(
            aws_region
        ):
            raise ValueError("Invalid AWS region")

        if not isinstance(bucket_name, str) or not self.BUCKET_PATTERN.fullmatch(
            bucket_name
        ):
            raise ValueError("Invalid JWKS S3 bucket name")

        if (
            not isinstance(object_key, str)
            or not object_key
            or object_key.startswith("/")
            or "\x00" in object_key
        ):
            raise ValueError("Invalid JWKS S3 object key")

        self.aws_region = aws_region
        self.bucket_name = bucket_name
        self.object_key = object_key

        self._s3 = s3_client or boto3.client(
            "s3",
            region_name=aws_region,
            config=Config(
                connect_timeout=2,
                read_timeout=3,
                retries={
                    "mode": "standard",
                    "total_max_attempts": 2,
                },
            ),
        )

        self._keys: dict[str, Any] = {}
        self._snapshot_last_modified: datetime | None = None

        self._expires_at = 0.0
        self._unknown_kid_refresh_at = 0.0
        self._unknown_kid_refresh_failed = False

        self._lock = asyncio.Lock()

    @staticmethod
    def _decode_base64url_uint(value: Any) -> int:
        if not isinstance(value, str):
            raise JWKSUnavailableError("Invalid RSA integer")

        if not value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise JWKSUnavailableError("Invalid Base64URL RSA integer")

        try:
            padded = value + "=" * (-len(value) % 4)

            decoded = base64.b64decode(
                padded,
                altchars=b"-_",
                validate=True,
            )

            if not decoded:
                raise ValueError("Empty integer")

            if decoded[0] == 0:
                raise ValueError("Non-minimal integer encoding")

            canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")

            if canonical != value:
                raise ValueError("Non-canonical encoding")

            return int.from_bytes(decoded, "big")

        except (ValueError, binascii.Error) as exc:
            raise JWKSUnavailableError("Invalid Base64URL RSA integer") from exc

    @classmethod
    def _validate_rsa_jwk(cls, item: dict[str, Any]) -> None:
        if item.get("kty") != "RSA":
            raise JWKSUnavailableError("Unsupported JWKS key type")

        if item.get("alg") != "RS256":
            raise JWKSUnavailableError("Unsupported JWKS algorithm")

        if item.get("use") != "sig":
            raise JWKSUnavailableError("Unsupported JWKS key usage")

        kid = item.get("kid")

        if not isinstance(kid, str) or not kid or len(kid) > cls.MAX_KID_LENGTH:
            raise JWKSUnavailableError("Invalid JWKS key ID")

        if PRIVATE_RSA_PARAMETERS.intersection(item):
            raise JWKSUnavailableError("JWKS contains private RSA parameters")

        modulus = cls._decode_base64url_uint(item.get("n"))
        exponent = cls._decode_base64url_uint(item.get("e"))

        if not cls.MIN_RSA_BITS <= modulus.bit_length() <= cls.MAX_RSA_BITS:
            raise JWKSUnavailableError("Invalid RSA modulus size")

        if modulus % 2 == 0:
            raise JWKSUnavailableError("RSA modulus must be odd")

        if exponent < 3 or exponent > cls.MAX_RSA_EXPONENT or exponent % 2 == 0:
            raise JWKSUnavailableError("Invalid RSA public exponent")

    @staticmethod
    def _validate_last_modified(value: Any) -> datetime:
        if not isinstance(value, datetime):
            raise JWKSUnavailableError("JWKS snapshot is missing LastModified metadata")

        if value.tzinfo is None or value.utcoffset() is None:
            raise JWKSUnavailableError(
                "JWKS snapshot has an invalid LastModified timestamp"
            )

        return value.astimezone(UTC)

    @classmethod
    def _validate_snapshot_age(cls, last_modified: datetime) -> None:
        now = datetime.now(UTC)

        age = (now - last_modified).total_seconds()

        if age < -cls.MAX_FUTURE_CLOCK_SKEW_SECONDS:
            raise JWKSUnavailableError(
                "JWKS snapshot timestamp is unexpectedly in the future"
            )

        if age > cls.MAX_SNAPSHOT_AGE_SECONDS:
            raise JWKSUnavailableError(
                "JWKS snapshot is older than the permitted freshness limit"
            )

    def _read_snapshot(self) -> tuple[dict[str, Any], datetime]:
        """Retrieve a bounded JWKS document and its S3 timestamp."""

        body = None

        try:
            response = self._s3.get_object(
                Bucket=self.bucket_name,
                Key=self.object_key,
            )

            # Capture the streaming body immediately so every subsequent
            # validation failure still closes the response.
            body = response["Body"]

            content_length = response.get("ContentLength")

            if (
                not isinstance(content_length, int)
                or isinstance(content_length, bool)
                or content_length < 0
                or content_length > self.MAX_RESPONSE_SIZE
            ):
                raise JWKSUnavailableError(
                    "JWKS snapshot has an invalid or excessive size"
                )

            last_modified = self._validate_last_modified(response.get("LastModified"))

            raw_document = body.read(self.MAX_RESPONSE_SIZE + 1)

            if len(raw_document) > self.MAX_RESPONSE_SIZE:
                raise JWKSUnavailableError("JWKS snapshot exceeds size limit")

            if len(raw_document) != content_length:
                raise JWKSUnavailableError(
                    "JWKS snapshot body length does not match ContentLength"
                )

            try:
                document = json.loads(raw_document)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise JWKSUnavailableError("JWKS snapshot is not valid JSON") from exc

            if not isinstance(document, dict):
                raise JWKSUnavailableError("Invalid JWKS document")

            keys = document.get("keys")

            if not isinstance(keys, list) or not keys or len(keys) > self.MAX_KEYS:
                raise JWKSUnavailableError("Invalid JWKS key collection")

            return document, last_modified

        except JWKSUnavailableError:
            raise

        except (ClientError, BotoCoreError, KeyError, OSError) as exc:
            raise JWKSUnavailableError(
                "Unable to retrieve JWKS snapshot from S3"
            ) from exc

        finally:
            if body is not None:
                with suppress(Exception):
                    body.close()

    async def _refresh(self) -> None:
        try:
            document, last_modified = await asyncio.to_thread(self._read_snapshot)

            last_modified = self._validate_last_modified(last_modified)
            self._validate_snapshot_age(last_modified)

            if (
                not isinstance(document, dict)
                or not isinstance(document.get("keys"), list)
                or not document["keys"]
                or len(document["keys"]) > self.MAX_KEYS
            ):
                raise JWKSUnavailableError("Invalid JWKS key collection")

            new_keys: dict[str, Any] = {}

            for item in document["keys"]:
                if not isinstance(item, dict):
                    raise JWKSUnavailableError("Invalid JWKS key")

                self._validate_rsa_jwk(item)

                kid = item["kid"]

                if kid in new_keys:
                    raise JWKSUnavailableError("Duplicate JWKS key ID")

                try:
                    signing_key = PyJWK.from_dict(
                        item,
                        algorithm="RS256",
                    ).key

                except Exception as exc:
                    raise JWKSUnavailableError(
                        "Invalid RSA public key in JWKS"
                    ) from exc

                new_keys[kid] = signing_key

            if not new_keys:
                raise JWKSUnavailableError("No usable signing keys found")

            self._keys = new_keys
            self._snapshot_last_modified = last_modified
            self._expires_at = time.monotonic() + self.CACHE_TTL_SECONDS
            self._unknown_kid_refresh_failed = False

        except JWKSUnavailableError:
            raise

        except Exception as exc:
            raise JWKSUnavailableError("Unable to refresh JWKS snapshot") from exc

    def _cached_snapshot_is_fresh(self) -> bool:
        if self._snapshot_last_modified is None:
            return False

        try:
            self._validate_snapshot_age(self._snapshot_last_modified)
            return True

        except JWKSUnavailableError:
            return False

    async def get_signing_key(self, kid: str) -> Any | None:
        if not isinstance(kid, str) or not kid or len(kid) > self.MAX_KID_LENGTH:
            return None

        async with self._lock:
            now = time.monotonic()

            cache_exists = bool(self._keys)
            cache_fresh = self._cached_snapshot_is_fresh()
            cache_ttl_valid = now < self._expires_at

            refreshed = False

            # A missing or over-age snapshot is never usable.
            if not cache_exists or not cache_fresh:
                self._unknown_kid_refresh_at = now

                try:
                    await self._refresh()
                    refreshed = True

                except JWKSUnavailableError:
                    self._unknown_kid_refresh_failed = True
                    raise

            # Refresh when the short in-memory cache expires.
            elif not cache_ttl_valid:
                self._unknown_kid_refresh_at = now

                try:
                    await self._refresh()
                    refreshed = True

                except JWKSUnavailableError:
                    self._unknown_kid_refresh_failed = True

                    # A previously validated snapshot can remain usable
                    # during an S3 outage, but only within the hard
                    # freshness limit.
                    if not self._cached_snapshot_is_fresh():
                        raise

            key = self._keys.get(kid)

            if key is not None:
                return key

            # A successful refresh already checked the latest snapshot.
            if refreshed:
                return None

            now = time.monotonic()

            if now - self._unknown_kid_refresh_at < self.UNKNOWN_KID_REFRESH_COOLDOWN:
                if self._unknown_kid_refresh_failed:
                    raise JWKSUnavailableError(
                        "JWKS refresh is temporarily unavailable"
                    )

                return None

            # Unknown kid: check S3 for possible key rotation.
            self._unknown_kid_refresh_at = now

            try:
                await self._refresh()

            except JWKSUnavailableError:
                self._unknown_kid_refresh_failed = True
                raise

            return self._keys.get(kid)
