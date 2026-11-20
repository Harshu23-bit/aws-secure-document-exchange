import json
import logging
import os
import re
import ssl
import urllib.error
import urllib.request
import base64
import binascii

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config


logger = logging.getLogger()
logger.setLevel(logging.INFO)

MAX_RESPONSE_BYTES = 65_536
MAX_KEYS = 10
MAX_KID_LENGTH = 256

MIN_RSA_BITS = 2048
MAX_RSA_BITS = 8192
MAX_RSA_EXPONENT = (2**32) - 1

HTTP_TIMEOUT_SECONDS = 10

PRIVATE_RSA_PARAMETERS = {
    "d",
    "p",
    "q",
    "dp",
    "dq",
    "qi",
    "oth",
}


class JWKSValidationError(Exception):
    """Raised when the retrieved JWKS document is invalid."""


class RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects rather than following an unexpected destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def build_jwks_url(region: str, user_pool_id: str) -> str:
    """Build the expected Cognito JWKS URL from trusted configuration."""

    if not isinstance(region, str) or not re.fullmatch(
        r"[a-z0-9-]+",
        region,
    ):
        raise ValueError("Invalid AWS region configuration")

    if not isinstance(user_pool_id, str) or not re.fullmatch(
        r"[a-z0-9-]+_[A-Za-z0-9]+",
        user_pool_id,
    ):
        raise ValueError("Invalid Cognito User Pool ID")

    pool_region = user_pool_id.split("_", 1)[0]

    if pool_region != region:
        raise ValueError(
            "Cognito User Pool region does not match AWS region"
        )

    return (
        f"https://cognito-idp.{region}.amazonaws.com/"
        f"{user_pool_id}/.well-known/jwks.json"
    )


def decode_base64url_uint(value) -> int:
    """Decode a canonical, unpadded Base64URL-encoded RSA integer."""

    if not isinstance(value, str):
        raise JWKSValidationError("Invalid RSA integer")

    if not value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise JWKSValidationError("Invalid Base64URL RSA integer")

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

        canonical = base64.urlsafe_b64encode(
            decoded
        ).rstrip(b"=").decode("ascii")

        if canonical != value:
            raise ValueError("Non-canonical encoding")

        return int.from_bytes(decoded, "big")

    except (ValueError, binascii.Error) as exc:
        raise JWKSValidationError(
            "Invalid Base64URL RSA integer"
        ) from exc


def validate_rsa_jwk(key: dict) -> None:
    """Validate the public RSA signing-key parameters."""

    modulus = decode_base64url_uint(key.get("n"))
    exponent = decode_base64url_uint(key.get("e"))

    if not MIN_RSA_BITS <= modulus.bit_length() <= MAX_RSA_BITS:
        raise JWKSValidationError("Invalid RSA modulus size")

    if modulus % 2 == 0:
        raise JWKSValidationError("RSA modulus must be odd")

    if (
        exponent < 3
        or exponent > MAX_RSA_EXPONENT
        or exponent % 2 == 0
    ):
        raise JWKSValidationError("Invalid RSA public exponent")


def validate_jwks(document: dict) -> int:
    """Validate the structure and public RSA signing-key parameters."""

    if not isinstance(document, dict):
        raise JWKSValidationError("JWKS root must be a JSON object")

    keys = document.get("keys")

    if not isinstance(keys, list) or not keys:
        raise JWKSValidationError(
            "JWKS must contain a non-empty keys array"
        )

    if len(keys) > MAX_KEYS:
        raise JWKSValidationError("Unexpectedly large JWKS key set")

    seen_kids = set()

    for key in keys:
        if not isinstance(key, dict):
            raise JWKSValidationError("Invalid JWKS key entry")

        required_fields = {"kid", "kty", "alg", "use", "n", "e"}

        if not required_fields.issubset(key):
            raise JWKSValidationError(
                "JWKS key is missing required fields"
            )

        kid = key["kid"]

        if (
            not isinstance(kid, str)
            or not kid
            or len(kid) > MAX_KID_LENGTH
        ):
            raise JWKSValidationError("Invalid signing key ID")

        if kid in seen_kids:
            raise JWKSValidationError("Duplicate signing key ID")

        seen_kids.add(kid)

        if key["kty"] != "RSA":
            raise JWKSValidationError("Unexpected signing key type")

        if key["alg"] != "RS256":
            raise JWKSValidationError("Unexpected signing algorithm")

        if key["use"] != "sig":
            raise JWKSValidationError("Unexpected signing key usage")

        if PRIVATE_RSA_PARAMETERS.intersection(key):
            raise JWKSValidationError(
                "JWKS unexpectedly contains private RSA parameters"
            )

        validate_rsa_jwk(key)

    return len(keys)


def fetch_jwks(url: str) -> bytes:
    """Retrieve JWKS over HTTPS with redirects disabled."""

    expected_url = re.fullmatch(
        r"https://cognito-idp\.([a-z0-9-]+)\.amazonaws\.com/"
        r"([a-z0-9-]+_[A-Za-z0-9]+)/\.well-known/jwks\.json",
        url,
    )

    if not expected_url:
        raise ValueError("Unexpected Cognito JWKS endpoint")

    if expected_url.group(1) != expected_url.group(2).split("_", 1)[0]:
        raise ValueError("JWKS endpoint region mismatch")

    opener = urllib.request.build_opener(
        RejectRedirectHandler(),
        urllib.request.HTTPSHandler(
            context=ssl.create_default_context()
        ),
    )

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "cloudsec-jwks-sync/1.0",
        },
        method="GET",
    )

    try:
        with opener.open(
            request,
            timeout=HTTP_TIMEOUT_SECONDS,
        ) as response:

            if response.status != 200:
                raise JWKSValidationError(
                    f"Unexpected JWKS HTTP status: {response.status}"
                )

            content = response.read(MAX_RESPONSE_BYTES + 1)

    except urllib.error.HTTPError as exc:
        raise JWKSValidationError(
            f"JWKS endpoint returned HTTP {exc.code}"
        ) from exc

    if len(content) > MAX_RESPONSE_BYTES:
        raise JWKSValidationError("JWKS response exceeds size limit")

    return content


def reject_duplicate_json_keys(pairs):
    """Reject JSON objects containing duplicate property names."""

    result = {}

    for key, value in pairs:
        if key in result:
            raise JWKSValidationError(
                "JWKS contains duplicate JSON properties"
            )

        result[key] = value

    return result


def reject_json_constant(value):
    """Reject non-standard JSON constants such as NaN and Infinity."""

    raise JWKSValidationError(
        f"JWKS contains an invalid JSON constant: {value}"
    )


def canonicalize_jwks(raw_document: bytes) -> tuple[bytes, int]:
    """Parse, validate and produce deterministic JSON."""

    if not isinstance(raw_document, bytes):
        raise JWKSValidationError("JWKS response must be bytes")

    try:
        decoded_document = raw_document.decode("utf-8")

        document = json.loads(
            decoded_document,
            object_pairs_hook=reject_duplicate_json_keys,
            parse_constant=reject_json_constant,
        )

    except JWKSValidationError:
        raise

    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
        RecursionError,
    ) as exc:
        raise JWKSValidationError(
            "JWKS response is not valid JSON"
        ) from exc

    key_count = validate_jwks(document)

    canonical_document = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    return canonical_document, key_count

def get_existing_object(s3, bucket: str, key: str):
    """Retrieve the current object, returning None when it doesn't exist."""

    try:
        response = s3.get_object(
            Bucket=bucket,
            Key=key,
        )

        body = response["Body"]

        try:
            content_length = response.get("ContentLength")

            if (
                not isinstance(content_length, int)
                or isinstance(content_length, bool)
                or content_length < 0
            ):
                raise ValueError("S3 object has an invalid ContentLength")

            if content_length > MAX_RESPONSE_BYTES:
                raise ValueError("Existing JWKS object exceeds the maximum size")

            data = body.read(MAX_RESPONSE_BYTES + 1)

            if len(data) > MAX_RESPONSE_BYTES:
                raise ValueError("Existing JWKS object exceeds the maximum size")

            if len(data) != content_length:
                raise ValueError("S3 object body length does not match ContentLength")

            return data

        finally:
            body.close()

    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")

        if error_code in {"NoSuchKey", "404", "NotFound"}:
            return None

        raise


def publish_jwks(s3, bucket: str, key: str, document: bytes) -> bool:
    """
    Publish a validated JWKS snapshot.
    The object is written on every successful synchronization so
    LastModified represents the latest successful synchronization,
    even when the key material has not changed.
    Returns True only when the document contents changed.
    """
    existing_document = get_existing_object(
        s3,
        bucket,
        key,
    )
    changed = existing_document != document
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=document,
        ContentType="application/json",
        ServerSideEncryption="AES256",
    )
    logger.info(
        "Published JWKS snapshot: changed=%s",
        changed,
    )
    return changed


def emit_success_metric(cloudwatch, namespace: str, user_pool_id: str):
    """Emit a heartbeat after successful retrieval and validation."""

    cloudwatch.put_metric_data(
        Namespace=namespace,
        MetricData=[
            {
                "MetricName": "SyncSuccess",
                "Dimensions": [
                    {
                        "Name": "UserPoolId",
                        "Value": user_pool_id,
                    }
                ],
                "Value": 1,
                "Unit": "Count",
            }
        ],
    )


def handler(event, context):
    """Lambda entry point."""

    try:
        region = os.environ["AWS_REGION"]
        user_pool_id = os.environ["USER_POOL_ID"]
        bucket = os.environ["JWKS_BUCKET"]

        object_key = "security/jwks.json"

        metric_namespace = os.environ.get(
            "METRIC_NAMESPACE",
            "CloudSec/JWKS",
        )

        url = build_jwks_url(
            region,
            user_pool_id,
        )

        aws_config = Config(
            connect_timeout=2,
            read_timeout=3,
            retries={
                "mode": "standard",
                "total_max_attempts": 2,
            },
        )

        s3 = boto3.client(
            "s3",
            config=aws_config,
        )

        cloudwatch = boto3.client(
            "cloudwatch",
            config=aws_config,
        )

        logger.info("Starting Cognito JWKS synchronization")

        raw_document = fetch_jwks(url)

        document, key_count = canonicalize_jwks(
            raw_document,
        )

        changed = publish_jwks(
            s3,
            bucket,
            object_key,
            document,
        )

        emit_success_metric(
            cloudwatch,
            metric_namespace,
            user_pool_id,
        )

        logger.info(
            "JWKS synchronization successful: "
            "key_count=%s changed=%s",
            key_count,
            changed,
        )

        return {
            "status": "success",
            "changed": changed,
            "key_count": key_count,
        }

    except Exception:
        logger.exception("JWKS synchronization failed")
        raise
