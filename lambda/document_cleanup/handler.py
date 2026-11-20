import hashlib
import logging
import os
import re
from datetime import UTC, datetime, timedelta

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_SHARD_COUNT = 16
MAX_ITEMS_LIMIT = 100
S3_PAGE_SIZE = 1000
MINIMUM_REMAINING_TIME_MS = 5000


class ConfigurationError(ValueError):
    """Raised when Lambda configuration is invalid."""


class CandidateValidationError(ValueError):
    """Raised when a DynamoDB cleanup candidate is malformed."""


class S3CleanupError(RuntimeError):
    """Raised when S3 version deletion or verification fails."""


def get_config():
    """Read and validate Lambda configuration."""

    table_name = os.environ.get("TABLE_NAME", "").strip()
    index_name = os.environ.get(
        "CLEANUP_INDEX",
        "PendingDocumentCleanupIndex",
    ).strip()
    bucket_name = os.environ.get("BUCKET_NAME", "").strip()

    if not table_name or not re.fullmatch(
        r"[A-Za-z0-9_.-]{3,255}",
        table_name,
    ):
        raise ConfigurationError("Invalid TABLE_NAME")

    if index_name != "PendingDocumentCleanupIndex":
        raise ConfigurationError("Invalid CLEANUP_INDEX")

    if not bucket_name or not re.fullmatch(
        r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]",
        bucket_name,
    ):
        raise ConfigurationError("Invalid BUCKET_NAME")

    try:
        shard_count = int(os.environ.get("SHARD_COUNT", "4"))
        max_items = int(os.environ.get("MAX_ITEMS", "50"))
    except ValueError as exc:
        raise ConfigurationError("SHARD_COUNT and MAX_ITEMS must be integers") from exc

    if not 1 <= shard_count <= MAX_SHARD_COUNT:
        raise ConfigurationError("Invalid SHARD_COUNT")

    if not 1 <= max_items <= MAX_ITEMS_LIMIT:
        raise ConfigurationError("Invalid MAX_ITEMS")

    return {
        "table_name": table_name,
        "index_name": index_name,
        "bucket_name": bucket_name,
        "shard_count": shard_count,
        "max_items": max_items,
    }


def format_utc_timestamp(value):
    """Format a UTC datetime into the canonical DynamoDB timestamp."""

    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("A timezone-aware UTC datetime is required")

    return value.strftime(TIMESTAMP_FORMAT)


def parse_utc_timestamp(value):
    """Parse only canonical UTC timestamps."""

    if not isinstance(value, str):
        raise CandidateValidationError("Invalid timestamp")

    try:
        parsed = datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise CandidateValidationError("Invalid timestamp") from exc

    if parsed.strftime(TIMESTAMP_FORMAT) != value:
        raise CandidateValidationError("Noncanonical timestamp")

    return parsed.replace(tzinfo=UTC)


def get_document_cleanup_shard(document_id, shard_count):
    """Return a deterministic shard for a document."""

    digest = hashlib.sha256(document_id.encode("utf-8")).digest()
    return digest[0] % shard_count


def decode_string_attribute(item, name):
    value = item.get(name)

    if not isinstance(value, dict):
        raise CandidateValidationError(f"Missing {name}")

    result = value.get("S")

    if not isinstance(result, str) or not result:
        raise CandidateValidationError(f"Invalid {name}")

    return result


def decode_number_attribute(item, name):
    value = item.get(name)

    if not isinstance(value, dict):
        raise CandidateValidationError(f"Missing {name}")

    raw = value.get("N")

    if not isinstance(raw, str):
        raise CandidateValidationError(f"Invalid {name}")

    try:
        number = int(raw)
    except ValueError as exc:
        raise CandidateValidationError(f"Invalid {name}") from exc

    return number


def validate_identifier(value, name):
    if (
        not isinstance(value, str)
        or not IDENTIFIER_PATTERN.fullmatch(value)
        or value in {".", ".."}
    ):
        raise CandidateValidationError(f"Invalid {name}")

    return value


def validate_candidate(item, shard, shard_count, now):
    """Validate a cleanup candidate before any S3 operation."""

    if not isinstance(item, dict):
        raise CandidateValidationError("Invalid candidate")

    tenant_id = validate_identifier(
        decode_string_attribute(item, "tenant_id"),
        "tenant_id",
    )
    submission_id = validate_identifier(
        decode_string_attribute(item, "submission_id"),
        "submission_id",
    )
    document_id = validate_identifier(
        decode_string_attribute(item, "document_id"),
        "document_id",
    )

    object_key = decode_string_attribute(item, "object_key")
    status = decode_string_attribute(item, "status")
    expires_at = decode_string_attribute(item, "expires_at")
    cleanup_after = decode_string_attribute(item, "cleanup_after")

    cleanup_attempts = decode_number_attribute(
        item,
        "cleanup_attempts",
    )

    pk = decode_string_attribute(item, "PK")
    sk = decode_string_attribute(item, "SK")
    gsi4pk = decode_string_attribute(item, "GSI4PK")
    gsi4sk = decode_string_attribute(item, "GSI4SK")

    expected_pk = f"TENANT#{tenant_id}#SUBMISSION#{submission_id}"
    expected_sk = f"DOCUMENT#{document_id}"

    expected_object_key = (
        f"tenants/{tenant_id}/submissions/{submission_id}/{document_id}"
    )

    expected_shard = get_document_cleanup_shard(
        document_id,
        shard_count,
    )

    expected_gsi4pk = f"CLEANUP_PENDING#{expected_shard:02d}"

    parsed_expiry = parse_utc_timestamp(expires_at)
    parsed_cleanup_after = parse_utc_timestamp(cleanup_after)

    if pk != expected_pk or sk != expected_sk:
        raise CandidateValidationError("Invalid document identity")

    if object_key != expected_object_key:
        raise CandidateValidationError("Invalid object key")

    if status != "CLEANUP_PENDING":
        raise CandidateValidationError("Invalid document status")

    if shard != expected_shard:
        raise CandidateValidationError("Incorrect cleanup shard")

    if gsi4pk != expected_gsi4pk:
        raise CandidateValidationError("Incorrect cleanup partition")

    if gsi4sk != f"{cleanup_after}#{document_id}":
        raise CandidateValidationError("Incorrect cleanup sort key")

    expected_cleanup_after = parsed_expiry + timedelta(hours=24)

    if parsed_cleanup_after != expected_cleanup_after:
        raise CandidateValidationError("Invalid cleanup schedule")

    if parsed_cleanup_after > now:
        raise CandidateValidationError("Cleanup grace period not elapsed")

    if cleanup_attempts < 0:
        raise CandidateValidationError("Invalid cleanup attempt count")

    return {
        "tenant_id": tenant_id,
        "submission_id": submission_id,
        "document_id": document_id,
        "object_key": object_key,
        "status": status,
        "expires_at": expires_at,
        "cleanup_after": cleanup_after,
        "cleanup_attempts": cleanup_attempts,
        "pk": pk,
        "sk": sk,
        "gsi4pk": gsi4pk,
        "gsi4sk": gsi4sk,
        "shard": shard,
    }


def has_time_remaining(context):
    if context is None:
        return True

    remaining = context.get_remaining_time_in_millis()

    return remaining > MINIMUM_REMAINING_TIME_MS


def record_cleanup_attempt(
    dynamodb,
    table_name,
    candidate,
    timestamp,
):
    """Claim a cleanup attempt using a conditional DynamoDB update."""

    try:
        dynamodb.update_item(
            TableName=table_name,
            Key={
                "PK": {"S": candidate["pk"]},
                "SK": {"S": candidate["sk"]},
            },
            UpdateExpression=(
                "SET cleanup_attempts = "
                "if_not_exists(cleanup_attempts, :zero) + :one, "
                "last_cleanup_attempt_at = :timestamp"
            ),
            ConditionExpression=(
                "#status = :pending "
                "AND entity_type = :document "
                "AND object_key = :object_key "
                "AND GSI4PK = :gsi4pk "
                "AND GSI4SK = :gsi4sk "
                "AND cleanup_after <= :timestamp "
                "AND tenant_id = :tenant "
                "AND submission_id = :submission "
                "AND document_id = :document_id"
            ),
            ExpressionAttributeNames={
                "#status": "status",
            },
            ExpressionAttributeValues={
                ":zero": {"N": "0"},
                ":one": {"N": "1"},
                ":timestamp": {"S": timestamp},
                ":pending": {"S": "CLEANUP_PENDING"},
                ":document": {"S": "DOCUMENT"},
                ":object_key": {"S": candidate["object_key"]},
                ":gsi4pk": {"S": candidate["gsi4pk"]},
                ":gsi4sk": {"S": candidate["gsi4sk"]},
                ":tenant": {"S": candidate["tenant_id"]},
                ":submission": {"S": candidate["submission_id"]},
                ":document_id": {"S": candidate["document_id"]},
            },
        )

        return True

    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == (
            "ConditionalCheckFailedException"
        ):
            return False

        raise


def list_object_versions_page(
    s3,
    bucket_name,
    object_key,
    key_marker=None,
    version_id_marker=None,
):
    """Retrieve one page of versions and delete markers."""

    arguments = {
        "Bucket": bucket_name,
        "Prefix": object_key,
        "MaxKeys": S3_PAGE_SIZE,
    }

    if key_marker is not None:
        arguments["KeyMarker"] = key_marker

    if version_id_marker is not None:
        arguments["VersionIdMarker"] = version_id_marker

    return s3.list_object_versions(**arguments)


def get_exact_key_versions(page, object_key):
    """Filter out keys that merely share the requested prefix."""

    objects = []

    for version in page.get("Versions", []):
        if version.get("Key") == object_key:
            version_id = version.get("VersionId")

            if not isinstance(version_id, str):
                raise S3CleanupError("S3 returned a version without a version ID")

            objects.append(
                {
                    "Key": object_key,
                    "VersionId": version_id,
                }
            )

    for marker in page.get("DeleteMarkers", []):
        if marker.get("Key") == object_key:
            version_id = marker.get("VersionId")

            if not isinstance(version_id, str):
                raise S3CleanupError("S3 returned a delete marker without a version ID")

            objects.append(
                {
                    "Key": object_key,
                    "VersionId": version_id,
                }
            )

    return objects


def delete_exact_key_versions(
    s3,
    bucket_name,
    object_key,
):
    """Delete every version and delete marker for one exact object key."""

    key_marker = None
    version_id_marker = None

    while True:
        page = list_object_versions_page(
            s3,
            bucket_name,
            object_key,
            key_marker,
            version_id_marker,
        )

        objects = get_exact_key_versions(page, object_key)

        if objects:
            response = s3.delete_objects(
                Bucket=bucket_name,
                Delete={
                    "Objects": objects,
                    "Quiet": True,
                },
            )

            errors = response.get("Errors", [])

            if errors:
                error_codes = sorted(
                    {str(error.get("Code", "Unknown"))[:64] for error in errors}
                )

                raise S3CleanupError(
                    "S3 version deletion failed: " + ",".join(error_codes)
                )

        if not page.get("IsTruncated", False):
            break

        next_key_marker = page.get("NextKeyMarker")
        next_version_marker = page.get("NextVersionIdMarker")

        if not next_key_marker:
            raise S3CleanupError("S3 returned truncated results without a key marker")

        key_marker = next_key_marker
        version_id_marker = next_version_marker

    return True


def verify_object_key_empty(
    s3,
    bucket_name,
    object_key,
):
    """Verify no versions or delete markers remain for the exact key."""

    key_marker = None
    version_id_marker = None

    while True:
        page = list_object_versions_page(
            s3,
            bucket_name,
            object_key,
            key_marker,
            version_id_marker,
        )

        if get_exact_key_versions(page, object_key):
            return False

        if not page.get("IsTruncated", False):
            return True

        next_key_marker = page.get("NextKeyMarker")
        next_version_marker = page.get("NextVersionIdMarker")

        if not next_key_marker:
            raise S3CleanupError(
                "S3 returned truncated verification without a key marker"
            )

        key_marker = next_key_marker
        version_id_marker = next_version_marker


def transition_cleanup_complete(
    dynamodb,
    table_name,
    candidate,
    timestamp,
):
    """Move a verified-clean document into the finalization grace period."""

    completed_at = timestamp

    finalize_after = format_utc_timestamp(
        datetime.strptime(
            timestamp,
            TIMESTAMP_FORMAT,
        ).replace(tzinfo=UTC)
        + timedelta(hours=24)
    )

    shard = candidate["shard"]

    try:
        dynamodb.update_item(
            TableName=table_name,
            Key={
                "PK": {"S": candidate["pk"]},
                "SK": {"S": candidate["sk"]},
            },
            UpdateExpression=(
                "SET #status = :complete, "
                "GSI4PK = :gsi4pk, "
                "GSI4SK = :gsi4sk, "
                "cleanup_completed_at = :completed_at, "
                "finalize_after = :finalize_after "
                "REMOVE last_cleanup_error"
            ),
            ConditionExpression=(
                "#status = :pending "
                "AND entity_type = :document "
                "AND object_key = :object_key "
                "AND GSI4PK = :pending_gsi4pk "
                "AND GSI4SK = :pending_gsi4sk "
                "AND tenant_id = :tenant "
                "AND submission_id = :submission "
                "AND document_id = :document_id"
            ),
            ExpressionAttributeNames={
                "#status": "status",
            },
            ExpressionAttributeValues={
                ":complete": {"S": "CLEANUP_COMPLETE"},
                ":pending": {"S": "CLEANUP_PENDING"},
                ":document": {"S": "DOCUMENT"},
                ":object_key": {"S": candidate["object_key"]},
                ":gsi4pk": {"S": f"CLEANUP_COMPLETE#{shard:02d}"},
                ":gsi4sk": {"S": f"{finalize_after}#{candidate['document_id']}"},
                ":completed_at": {"S": completed_at},
                ":finalize_after": {"S": finalize_after},
                ":pending_gsi4pk": {"S": candidate["gsi4pk"]},
                ":pending_gsi4sk": {"S": candidate["gsi4sk"]},
                ":tenant": {"S": candidate["tenant_id"]},
                ":submission": {"S": candidate["submission_id"]},
                ":document_id": {"S": candidate["document_id"]},
            },
        )

        return True

    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == (
            "ConditionalCheckFailedException"
        ):
            return False

        raise


def record_cleanup_error(
    dynamodb,
    table_name,
    candidate,
    timestamp,
    error_code,
):
    """Record a bounded error code without storing raw service messages."""

    dynamodb.update_item(
        TableName=table_name,
        Key={
            "PK": {"S": candidate["pk"]},
            "SK": {"S": candidate["sk"]},
        },
        UpdateExpression=(
            "SET last_cleanup_error = :error, last_cleanup_error_at = :timestamp"
        ),
        ConditionExpression=(
            "#status = :pending AND GSI4PK = :gsi4pk AND GSI4SK = :gsi4sk"
        ),
        ExpressionAttributeNames={
            "#status": "status",
        },
        ExpressionAttributeValues={
            ":error": {"S": error_code[:64]},
            ":timestamp": {"S": timestamp},
            ":pending": {"S": "CLEANUP_PENDING"},
            ":gsi4pk": {"S": candidate["gsi4pk"]},
            ":gsi4sk": {"S": candidate["gsi4sk"]},
        },
    )


def cleanup_candidate(
    dynamodb,
    s3,
    config,
    candidate,
    now,
):
    """Delete and verify one document's complete S3 version history."""

    timestamp = format_utc_timestamp(now)

    claimed = record_cleanup_attempt(
        dynamodb,
        config["table_name"],
        candidate,
        timestamp,
    )

    if not claimed:
        return "skipped"

    try:
        delete_exact_key_versions(
            s3,
            config["bucket_name"],
            candidate["object_key"],
        )

        if not verify_object_key_empty(
            s3,
            config["bucket_name"],
            candidate["object_key"],
        ):
            raise S3CleanupError("S3 object versions remain after deletion")

    except (S3CleanupError, ClientError, BotoCoreError) as exc:
        if isinstance(exc, ClientError):
            error_code = exc.response.get("Error", {}).get("Code", "S3ClientError")
        elif isinstance(exc, BotoCoreError):
            error_code = type(exc).__name__
        else:
            error_code = "S3CleanupError"

        error_code = re.sub(
            r"[^A-Za-z0-9_.-]",
            "_",
            str(error_code),
        )[:64]

        record_cleanup_error(
            dynamodb,
            config["table_name"],
            candidate,
            timestamp,
            error_code,
        )

        logger.warning(
            "Document cleanup failed for document_id=%s error=%s",
            candidate["document_id"],
            error_code,
        )

        return "failed"

    completed = transition_cleanup_complete(
        dynamodb,
        config["table_name"],
        candidate,
        timestamp,
    )

    return "completed" if completed else "skipped"


def query_cleanup_shard(
    dynamodb,
    s3,
    config,
    shard,
    max_items,
    now,
    context=None,
):
    """Query and process eligible documents from one cleanup shard."""

    timestamp = format_utc_timestamp(now)
    cutoff_key = f"{timestamp}#\uffff"
    shard_key = f"CLEANUP_PENDING#{shard:02d}"

    result = {
        "processed": 0,
        "completed": 0,
        "skipped": 0,
        "invalid": 0,
        "failed": 0,
    }

    exclusive_start_key = None

    while result["processed"] < max_items:
        if not has_time_remaining(context):
            break

        remaining = max_items - result["processed"]

        arguments = {
            "TableName": config["table_name"],
            "IndexName": config["index_name"],
            "KeyConditionExpression": ("#gsi_pk = :shard AND #gsi_sk <= :cutoff"),
            "ExpressionAttributeNames": {
                "#gsi_pk": "GSI4PK",
                "#gsi_sk": "GSI4SK",
                "#pk": "PK",
                "#sk": "SK",
                "#tenant": "tenant_id",
                "#submission": "submission_id",
                "#document": "document_id",
                "#object_key": "object_key",
                "#expires": "expires_at",
                "#cleanup_after": "cleanup_after",
                "#attempts": "cleanup_attempts",
                "#status": "status",
            },
            "ExpressionAttributeValues": {
                ":shard": {"S": shard_key},
                ":cutoff": {"S": cutoff_key},
            },
            "ProjectionExpression": (
                "#pk, #sk, #tenant, #submission, #document, "
                "#object_key, #expires, #cleanup_after, "
                "#attempts, #status, GSI4PK, GSI4SK"
            ),
            "Limit": remaining,
        }

        if exclusive_start_key:
            arguments["ExclusiveStartKey"] = exclusive_start_key

        response = dynamodb.query(**arguments)
        items = response.get("Items", [])

        if not isinstance(items, list):
            raise TypeError("DynamoDB returned an invalid query result")

        for item in items:
            if result["processed"] >= max_items:
                break

            if not has_time_remaining(context):
                break

            result["processed"] += 1

            try:
                candidate = validate_candidate(
                    item,
                    shard,
                    config["shard_count"],
                    now,
                )
            except CandidateValidationError:
                result["invalid"] += 1
                logger.warning(
                    "Skipped malformed cleanup candidate in shard %02d",
                    shard,
                )
                continue

            outcome = cleanup_candidate(
                dynamodb,
                s3,
                config,
                candidate,
                now,
            )

            if outcome == "completed":
                result["completed"] += 1
            elif outcome == "failed":
                result["failed"] += 1
            else:
                result["skipped"] += 1

        if result["processed"] >= max_items:
            break

        if not has_time_remaining(context):
            break

        exclusive_start_key = response.get("LastEvaluatedKey")

        if not exclusive_start_key:
            break

    return result


def cleanup_pending_documents(
    dynamodb,
    s3,
    config,
    now,
    context=None,
):
    """Process eligible cleanup candidates across all configured shards."""

    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("A timezone-aware UTC datetime is required")

    totals = {
        "processed": 0,
        "completed": 0,
        "skipped": 0,
        "invalid": 0,
        "failed": 0,
    }

    for shard in range(config["shard_count"]):
        if totals["processed"] >= config["max_items"]:
            break

        if not has_time_remaining(context):
            break

        result = query_cleanup_shard(
            dynamodb=dynamodb,
            s3=s3,
            config=config,
            shard=shard,
            max_items=config["max_items"] - totals["processed"],
            now=now,
            context=context,
        )

        for key in totals:
            totals[key] += result[key]

    return totals


def handler(event, context):
    """Scheduled Lambda entry point."""

    config = get_config()

    region = os.environ.get("AWS_REGION")

    dynamodb = boto3.client(
        "dynamodb",
        region_name=region,
    )

    s3 = boto3.client(
        "s3",
        region_name=region,
    )

    now = datetime.now(UTC).replace(microsecond=0)

    result = cleanup_pending_documents(
        dynamodb=dynamodb,
        s3=s3,
        config=config,
        now=now,
        context=context,
    )

    logger.info(
        "Document cleanup completed: "
        "processed=%d completed=%d skipped=%d invalid=%d failed=%d",
        result["processed"],
        result["completed"],
        result["skipped"],
        result["invalid"],
        result["failed"],
    )

    if result["failed"] > 0:
        raise RuntimeError(f"{result['failed']} document cleanup operation(s) failed")

    return {
        "status": "success",
        **result,
    }
