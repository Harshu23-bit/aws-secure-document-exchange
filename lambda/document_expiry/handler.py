import hashlib
import logging
import os
import re
from datetime import UTC, datetime, timedelta

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

DEFAULT_SHARD_COUNT = 4
DEFAULT_MAX_ITEMS = 100
MAX_ALLOWED_ITEMS = 100
MAX_DOCUMENT_SIZE = 10 * 1024 * 1024
TIME_BUFFER_MS = 5_000
CLEANUP_GRACE_HOURS = 24

TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,255}$")
INDEX_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,255}$")


class ConfigurationError(ValueError):
    """Raised when Lambda configuration is invalid."""


class CandidateValidationError(ValueError):
    """Raised when an expiry-index candidate is malformed."""


def get_config() -> dict:
    """Load and validate the Lambda configuration."""

    table_name = os.environ.get("TABLE_NAME", "")
    index_name = os.environ.get(
        "EXPIRY_INDEX",
        "PendingDocumentExpiryIndex",
    )

    if not TABLE_NAME_PATTERN.fullmatch(table_name):
        raise ConfigurationError("Invalid TABLE_NAME")

    if not INDEX_NAME_PATTERN.fullmatch(index_name):
        raise ConfigurationError("Invalid EXPIRY_INDEX")

    try:
        shard_count = int(os.environ.get("SHARD_COUNT", str(DEFAULT_SHARD_COUNT)))
        max_items = int(os.environ.get("MAX_ITEMS", str(DEFAULT_MAX_ITEMS)))
    except ValueError as exc:
        raise ConfigurationError("Invalid numeric Lambda configuration") from exc

    if not 1 <= shard_count <= 16:
        raise ConfigurationError("SHARD_COUNT must be between 1 and 16")

    if not 1 <= max_items <= MAX_ALLOWED_ITEMS:
        raise ConfigurationError(f"MAX_ITEMS must be between 1 and {MAX_ALLOWED_ITEMS}")

    return {
        "table_name": table_name,
        "index_name": index_name,
        "shard_count": shard_count,
        "max_items": max_items,
    }


def format_utc_timestamp(value: datetime) -> str:
    """Format a timezone-aware UTC datetime canonically."""

    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("A timezone-aware UTC datetime is required")

    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_canonical_utc_timestamp(value: object) -> datetime:
    """Parse a canonical UTC timestamp or reject it."""

    if not isinstance(value, str) or not value.endswith("Z"):
        raise CandidateValidationError("Invalid expiry timestamp")

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CandidateValidationError("Invalid expiry timestamp") from exc

    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise CandidateValidationError("Expiry timestamp is not UTC")

    if format_utc_timestamp(parsed) != value:
        raise CandidateValidationError("Expiry timestamp is not canonical")

    return parsed


def get_document_expiry_shard(
    document_id: str,
    shard_count: int,
) -> int:
    """Reproduce the application's deterministic expiry shard."""

    digest = hashlib.sha256(document_id.encode("utf-8")).digest()

    return digest[0] % shard_count


def decode_number_attribute(item: dict, name: str) -> int:
    """Decode a positive integer from a low-level DynamoDB item."""

    attribute = item.get(name)

    if not isinstance(attribute, dict):
        raise CandidateValidationError(f"Missing {name}")

    value = attribute.get("N")

    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
        raise CandidateValidationError(f"Invalid {name}")

    number = int(value)

    if number > MAX_DOCUMENT_SIZE:
        raise CandidateValidationError(f"{name} exceeds the document size limit")

    return number


def decode_string_attribute(item: dict, name: str) -> str:
    """Decode a non-empty string from a low-level DynamoDB item."""

    attribute = item.get(name)

    if not isinstance(attribute, dict):
        raise CandidateValidationError(f"Missing {name}")

    value = attribute.get("S")

    if not isinstance(value, str) or not value:
        raise CandidateValidationError(f"Invalid {name}")

    return value


def validate_candidate(
    item: dict,
    shard: int,
    shard_count: int,
    now: datetime,
) -> dict:
    """
    Validate an expiry-index candidate before constructing a transaction.

    Never trust GSI data alone. GSI reads are eventually consistent.
    """

    if not isinstance(item, dict):
        raise CandidateValidationError("Invalid candidate")

    tenant_id = decode_string_attribute(item, "tenant_id")
    submission_id = decode_string_attribute(item, "submission_id")
    document_id = decode_string_attribute(item, "document_id")
    object_key = decode_string_attribute(item, "object_key")
    status = decode_string_attribute(item, "status")
    expires_at = decode_string_attribute(item, "expires_at")

    size_bytes = decode_number_attribute(item, "size_bytes")

    partition_key = decode_string_attribute(item, "PK")
    sort_key = decode_string_attribute(item, "SK")
    expiry_partition_key = decode_string_attribute(item, "GSI3PK")
    expiry_sort_key = decode_string_attribute(item, "GSI3SK")

    if status != "PENDING_UPLOAD":
        raise CandidateValidationError("Candidate is not pending")

    expected_document_pk = f"TENANT#{tenant_id}#SUBMISSION#{submission_id}"
    expected_document_sk = f"DOCUMENT#{document_id}"
    expected_object_key = (
        f"tenants/{tenant_id}/submissions/{submission_id}/{document_id}"
    )

    if object_key != expected_object_key:
        raise CandidateValidationError("Unexpected document object key")

    if partition_key != expected_document_pk:
        raise CandidateValidationError("Unexpected document partition key")

    if sort_key != expected_document_sk:
        raise CandidateValidationError("Unexpected document sort key")

    expected_shard = get_document_expiry_shard(
        document_id,
        shard_count,
    )

    if shard != expected_shard:
        raise CandidateValidationError("Unexpected expiry shard")

    expected_gsi_pk = f"PENDING_UPLOAD#{expected_shard:02d}"

    parsed_expiry = parse_canonical_utc_timestamp(expires_at)

    if parsed_expiry > now:
        raise CandidateValidationError("Candidate has not expired")

    cleanup_after = format_utc_timestamp(
        parsed_expiry + timedelta(hours=CLEANUP_GRACE_HOURS)
    )

    expected_gsi_sk = f"{expires_at}#{document_id}"
    cleanup_partition_key = f"CLEANUP_PENDING#{expected_shard:02d}"
    cleanup_sort_key = f"{cleanup_after}#{document_id}"

    if expiry_partition_key != expected_gsi_pk:
        raise CandidateValidationError("Unexpected expiry partition key")

    if expiry_sort_key != expected_gsi_sk:
        raise CandidateValidationError("Unexpected expiry sort key")

    return {
        "tenant_id": tenant_id,
        "submission_id": submission_id,
        "document_id": document_id,
        "object_key": object_key,
        "size_bytes": size_bytes,
        "expires_at": expires_at,
        "cleanup_after": cleanup_after,
        "gsi3pk": expected_gsi_pk,
        "gsi3sk": expected_gsi_sk,
        "gsi4pk": cleanup_partition_key,
        "gsi4sk": cleanup_sort_key,
        "document_pk": expected_document_pk,
        "document_sk": expected_document_sk,
    }


def build_cleanup_transaction(
    table_name: str,
    candidate: dict,
    cutoff: str,
) -> list:
    """
    Atomically reconcile submission counters and transition an expired
    document into the durable CLEANUP_PENDING state.
    """

    tenant_id = candidate["tenant_id"]
    submission_id = candidate["submission_id"]
    document_id = candidate["document_id"]
    size_bytes = candidate["size_bytes"]

    return [
        {
            "Update": {
                "TableName": table_name,
                "Key": {
                    "PK": {"S": f"TENANT#{tenant_id}"},
                    "SK": {"S": f"SUBMISSION#{submission_id}"},
                },
                "UpdateExpression": (
                    "SET #pending_count = #pending_count - :one, "
                    "#pending_bytes = #pending_bytes - :size, "
                    "#total_count = #total_count - :one, "
                    "#total_bytes = #total_bytes - :size"
                ),
                "ConditionExpression": (
                    "attribute_exists(#pending_count) "
                    "AND attribute_type(#pending_count, :number_type) "
                    "AND #pending_count > :zero "
                    "AND attribute_exists(#pending_bytes) "
                    "AND attribute_type(#pending_bytes, :number_type) "
                    "AND #pending_bytes >= :size "
                    "AND attribute_exists(#total_count) "
                    "AND attribute_type(#total_count, :number_type) "
                    "AND #total_count > :zero "
                    "AND attribute_exists(#total_bytes) "
                    "AND attribute_type(#total_bytes, :number_type) "
                    "AND #total_bytes >= :size"
                ),
                "ExpressionAttributeNames": {
                    "#pending_count": "pending_document_count",
                    "#pending_bytes": "pending_document_bytes",
                    "#total_count": "total_document_count",
                    "#total_bytes": "total_document_bytes",
                },
                "ExpressionAttributeValues": {
                    ":one": {"N": "1"},
                    ":zero": {"N": "0"},
                    ":size": {"N": str(size_bytes)},
                    ":number_type": {"S": "N"},
                },
            }
        },
        {
            "Update": {
                "TableName": table_name,
                "Key": {
                    "PK": {"S": candidate["document_pk"]},
                    "SK": {"S": candidate["document_sk"]},
                },
                "UpdateExpression": (
                    "SET #status = :cleanup_pending, "
                    "GSI4PK = :gsi4pk, "
                    "GSI4SK = :gsi4sk, "
                    "cleanup_after = :cleanup_after, "
                    "cleanup_attempts = :zero "
                    "REMOVE GSI3PK, GSI3SK"
                ),
                "ConditionExpression": (
                    "#status = :pending "
                    "AND entity_type = :entity_type "
                    "AND tenant_id = :tenant "
                    "AND submission_id = :submission "
                    "AND document_id = :document "
                    "AND object_key = :object_key "
                    "AND size_bytes = :size "
                    "AND expires_at = :expires_at "
                    "AND expires_at <= :cutoff "
                    "AND GSI3PK = :gsi3pk "
                    "AND GSI3SK = :gsi3sk"
                ),
                "ExpressionAttributeNames": {
                    "#status": "status",
                },
                "ExpressionAttributeValues": {
                    ":pending": {"S": "PENDING_UPLOAD"},
                    ":cleanup_pending": {"S": "CLEANUP_PENDING"},
                    ":entity_type": {"S": "DOCUMENT"},
                    ":tenant": {"S": tenant_id},
                    ":submission": {"S": submission_id},
                    ":document": {"S": document_id},
                    ":object_key": {"S": candidate["object_key"]},
                    ":size": {"N": str(size_bytes)},
                    ":expires_at": {"S": candidate["expires_at"]},
                    ":cutoff": {"S": cutoff},
                    ":gsi3pk": {"S": candidate["gsi3pk"]},
                    ":gsi3sk": {"S": candidate["gsi3sk"]},
                    ":gsi4pk": {"S": candidate["gsi4pk"]},
                    ":gsi4sk": {"S": candidate["gsi4sk"]},
                    ":cleanup_after": {"S": candidate["cleanup_after"]},
                    ":zero": {"N": "0"},
                },
            }
        },
    ]


def is_expected_transaction_cancellation(exc: ClientError) -> bool:
    """
    Identify conditional races and transaction conflicts.

    Unknown cancellation reasons must not be silently swallowed.
    """

    reasons = exc.response.get("CancellationReasons")

    if not isinstance(reasons, list):
        return False

    failure_codes = {
        reason.get("Code")
        for reason in reasons
        if isinstance(reason, dict) and reason.get("Code") not in (None, "None")
    }

    if not failure_codes:
        return False

    return failure_codes.issubset(
        {
            "ConditionalCheckFailed",
            "TransactionConflict",
        }
    )


def transition_expired_candidate(
    dynamodb,
    table_name: str,
    candidate: dict,
    cutoff: str,
) -> bool:
    """
    Transition an expired reservation into CLEANUP_PENDING.

    Returns False for expected races. Unexpected errors propagate.
    """

    transaction = build_cleanup_transaction(
        table_name,
        candidate,
        cutoff,
    )

    try:
        dynamodb.transact_write_items(
            TransactItems=transaction,
        )

        return True

    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")

        if (
            error_code == "TransactionCanceledException"
            and is_expected_transaction_cancellation(exc)
        ):
            logger.info("Skipped stale or concurrently modified expiry candidate")
            return False

        raise


def has_time_remaining(context) -> bool:
    """Stop before the Lambda execution deadline."""

    if context is None:
        return True

    remaining_method = getattr(
        context,
        "get_remaining_time_in_millis",
        None,
    )

    if not callable(remaining_method):
        return True

    return remaining_method() > TIME_BUFFER_MS


def query_shard(
    dynamodb,
    table_name: str,
    index_name: str,
    shard: int,
    shard_count: int,
    max_items: int,
    now: datetime,
    context=None,
) -> dict:
    """Query and process one shard using bounded pagination."""

    timestamp = format_utc_timestamp(now)
    cutoff_key = f"{timestamp}#\uffff"

    shard_key = f"PENDING_UPLOAD#{shard:02d}"

    processed = 0
    transitioned = 0
    skipped = 0
    invalid = 0

    exclusive_start_key = None

    while processed < max_items and has_time_remaining(context):
        remaining = max_items - processed

        query_arguments = {
            "TableName": table_name,
            "IndexName": index_name,
            "KeyConditionExpression": ("#gsi_pk = :shard AND #gsi_sk <= :cutoff_key"),
            "ExpressionAttributeNames": {
                "#gsi_pk": "GSI3PK",
                "#gsi_sk": "GSI3SK",
                "#pk": "PK",
                "#sk": "SK",
                "#tenant": "tenant_id",
                "#submission": "submission_id",
                "#document": "document_id",
                "#object_key": "object_key",
                "#size": "size_bytes",
                "#expires": "expires_at",
                "#status": "status",
            },
            "ExpressionAttributeValues": {
                ":shard": {"S": shard_key},
                ":cutoff_key": {"S": cutoff_key},
            },
            "ProjectionExpression": (
                "#pk, #sk, #tenant, #submission, #document, "
                "#object_key, #size, #expires, #status, GSI3PK, GSI3SK"
            ),
            "Limit": remaining,
        }

        if exclusive_start_key:
            query_arguments["ExclusiveStartKey"] = exclusive_start_key

        response = dynamodb.query(**query_arguments)

        items = response.get("Items", [])

        if not isinstance(items, list):
            raise TypeError("DynamoDB returned an invalid query result")

        for item in items:
            if processed >= max_items:
                break

            processed += 1

            try:
                candidate = validate_candidate(item, shard, shard_count, now)
            except CandidateValidationError:
                invalid += 1
                logger.warning("Skipped malformed document expiry candidate")
                continue

            if transition_expired_candidate(
                dynamodb,
                table_name,
                candidate,
                timestamp,
            ):
                transitioned += 1
            else:
                skipped += 1

        if processed >= max_items or not has_time_remaining(context):
            break

        exclusive_start_key = response.get("LastEvaluatedKey")

        if not exclusive_start_key:
            break

    return {
        "processed": processed,
        "transitioned": transitioned,
        "skipped": skipped,
        "invalid": invalid,
    }


def cleanup_expired_documents(
    dynamodb,
    config: dict,
    now: datetime,
    context=None,
) -> dict:
    """Process expiry candidates across all configured shards."""

    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("A timezone-aware UTC datetime is required")

    totals = {
        "processed": 0,
        "transitioned": 0,
        "skipped": 0,
        "invalid": 0,
    }

    for shard in range(config["shard_count"]):
        if totals["processed"] >= config["max_items"]:
            break

        if not has_time_remaining(context):
            break

        result = query_shard(
            dynamodb=dynamodb,
            table_name=config["table_name"],
            index_name=config["index_name"],
            shard=shard,
            shard_count=config["shard_count"],
            max_items=(config["max_items"] - totals["processed"]),
            now=now,
            context=context,
        )

        for key in totals:
            totals[key] += result[key]

    return totals


def handler(event, context):
    """Scheduled Lambda entry point."""

    config = get_config()

    dynamodb = boto3.client(
        "dynamodb",
        region_name=os.environ.get("AWS_REGION"),
    )

    now = datetime.now(UTC).replace(microsecond=0)

    result = cleanup_expired_documents(
        dynamodb=dynamodb,
        config=config,
        now=now,
        context=context,
    )

    logger.info(
        "Document expiry processing completed: "
        "processed=%d transitioned=%d skipped=%d invalid=%d",
        result["processed"],
        result["transitioned"],
        result["skipped"],
        result["invalid"],
    )

    return {
        "status": "success",
        **result,
    }
