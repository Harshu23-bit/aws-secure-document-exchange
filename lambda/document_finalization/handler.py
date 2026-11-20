import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError


logger = logging.getLogger()
logger.setLevel(logging.INFO)

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
)
IDENTIFIER_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)

S3_PAGE_SIZE = 1000
TIME_BUFFER_MS = 5000
FINALIZATION_GRACE = timedelta(hours=24)

RESULT_KEYS = (
    "processed",
    "deleted",
    "requeued",
    "skipped",
    "invalid",
    "failed",
)


class CandidateValidationError(ValueError):
    pass


class S3InspectionError(RuntimeError):
    pass


def parse_utc_timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp must be a string")

    if not TIMESTAMP_PATTERN.fullmatch(value):
        raise ValueError("Timestamp must use canonical UTC format")

    try:
        parsed = datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise ValueError("Invalid UTC timestamp") from exc

    return parsed.replace(tzinfo=timezone.utc)


def format_utc_timestamp(value):
    if not isinstance(value, datetime):
        raise ValueError("Expected datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Datetime must be timezone-aware")

    return value.astimezone(timezone.utc).strftime(TIMESTAMP_FORMAT)


def get_document_cleanup_shard(document_id, shard_count):
    if (
        not isinstance(document_id, str)
        or not IDENTIFIER_PATTERN.fullmatch(document_id)
    ):
        raise ValueError("Invalid document ID")

    if (
        isinstance(shard_count, bool)
        or not isinstance(shard_count, int)
        or not 1 <= shard_count <= 16
    ):
        raise ValueError("Invalid shard count")

    digest = hashlib.sha256(document_id.encode("utf-8")).digest()
    return digest[0] % shard_count


def _string_attribute(item, name):
    value = item.get(name)

    if not isinstance(value, dict) or set(value) != {"S"}:
        raise CandidateValidationError(
            f"Invalid DynamoDB string attribute: {name}"
        )

    result = value["S"]

    if not isinstance(result, str) or not result:
        raise CandidateValidationError(
            f"Empty DynamoDB string attribute: {name}"
        )

    return result


def _validate_identifier(value, name):
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise CandidateValidationError(f"Invalid {name}")


def validate_candidate(item, shard, shard_count, now):
    if not isinstance(item, dict):
        raise CandidateValidationError("Candidate must be a DynamoDB item")

    if not isinstance(now, datetime):
        raise ValueError("now must be a datetime")

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    if (
        isinstance(shard, bool)
        or not isinstance(shard, int)
        or not 0 <= shard < shard_count
    ):
        raise CandidateValidationError("Invalid shard")

    tenant_id = _string_attribute(item, "tenant_id")
    submission_id = _string_attribute(item, "submission_id")
    document_id = _string_attribute(item, "document_id")
    object_key = _string_attribute(item, "object_key")
    status = _string_attribute(item, "status")

    expires_at = _string_attribute(item, "expires_at")
    cleanup_after = _string_attribute(item, "cleanup_after")
    cleanup_completed_at = _string_attribute(
        item,
        "cleanup_completed_at",
    )
    finalize_after = _string_attribute(item, "finalize_after")

    pk = _string_attribute(item, "PK")
    sk = _string_attribute(item, "SK")
    gsi4pk = _string_attribute(item, "GSI4PK")
    gsi4sk = _string_attribute(item, "GSI4SK")

    for value, name in (
        (tenant_id, "tenant ID"),
        (submission_id, "submission ID"),
        (document_id, "document ID"),
    ):
        _validate_identifier(value, name)

    expected_pk = (
        f"TENANT#{tenant_id}#SUBMISSION#{submission_id}"
    )
    expected_sk = f"DOCUMENT#{document_id}"
    expected_key = (
        f"tenants/{tenant_id}/submissions/"
        f"{submission_id}/{document_id}"
    )

    if pk != expected_pk or sk != expected_sk:
        raise CandidateValidationError("Invalid document primary key")

    if object_key != expected_key:
        raise CandidateValidationError("Noncanonical S3 object key")

    if status != "CLEANUP_COMPLETE":
        raise CandidateValidationError("Document is not cleanup complete")

    expected_shard = get_document_cleanup_shard(
        document_id,
        shard_count,
    )

    if shard != expected_shard:
        raise CandidateValidationError("Document belongs to another shard")

    expected_gsi4pk = f"CLEANUP_COMPLETE#{shard:02d}"

    if gsi4pk != expected_gsi4pk:
        raise CandidateValidationError("Invalid completed GSI partition")

    expires_dt = parse_utc_timestamp(expires_at)
    cleanup_dt = parse_utc_timestamp(cleanup_after)
    completed_dt = parse_utc_timestamp(cleanup_completed_at)
    finalize_dt = parse_utc_timestamp(finalize_after)

    if cleanup_dt != expires_dt + FINALIZATION_GRACE:
        raise CandidateValidationError("Invalid cleanup grace deadline")

    if finalize_dt != completed_dt + FINALIZATION_GRACE:
        raise CandidateValidationError(
            "Invalid finalization grace deadline"
        )

    if cleanup_dt > completed_dt:
        raise CandidateValidationError(
            "Cleanup completed before cleanup eligibility"
        )

    if finalize_dt > now.astimezone(timezone.utc):
        raise CandidateValidationError(
            "Finalization grace period has not elapsed"
        )

    expected_gsi4sk = f"{finalize_after}#{document_id}"

    if gsi4sk != expected_gsi4sk:
        raise CandidateValidationError("Invalid completed GSI sort key")

    return {
        "pk": pk,
        "sk": sk,
        "tenant_id": tenant_id,
        "submission_id": submission_id,
        "document_id": document_id,
        "object_key": object_key,
        "status": status,
        "expires_at": expires_at,
        "cleanup_after": cleanup_after,
        "cleanup_completed_at": cleanup_completed_at,
        "finalize_after": finalize_after,
        "gsi4pk": gsi4pk,
        "gsi4sk": gsi4sk,
        "shard": shard,
    }


def get_exact_key_versions(page, object_key):
    if not isinstance(page, dict):
        raise S3InspectionError("Invalid S3 ListObjectVersions response")

    matching = []

    for collection_name in ("Versions", "DeleteMarkers"):
        entries = page.get(collection_name, [])

        if not isinstance(entries, list):
            raise S3InspectionError("Invalid S3 version collection")

        for entry in entries:
            if not isinstance(entry, dict):
                raise S3InspectionError("Invalid S3 version entry")

            if entry.get("Key") != object_key:
                continue

            version_id = entry.get("VersionId")

            if not isinstance(version_id, str) or not version_id:
                raise S3InspectionError(
                    "Exact-key S3 entry has no VersionId"
                )

            matching.append(
                {
                    "Key": object_key,
                    "VersionId": version_id,
                }
            )

    return matching


def list_object_versions_page(
    s3,
    bucket_name,
    object_key,
    key_marker=None,
    version_id_marker=None,
):
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


def verify_object_key_empty(s3, bucket_name, object_key):
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

        truncated = page.get("IsTruncated", False)

        if not isinstance(truncated, bool):
            raise S3InspectionError("Invalid S3 pagination indicator")

        if not truncated:
            return True

        next_key_marker = page.get("NextKeyMarker")
        next_version_marker = page.get("NextVersionIdMarker")

        if not isinstance(next_key_marker, str) or not next_key_marker:
            raise S3InspectionError(
                "Truncated S3 response has no next key marker"
            )

        if next_version_marker is not None and (
            not isinstance(next_version_marker, str)
            or not next_version_marker
        ):
            raise S3InspectionError(
                "Invalid S3 next version marker"
            )

        if (
            next_key_marker == key_marker
            and next_version_marker == version_id_marker
        ):
            raise S3InspectionError("S3 pagination marker did not advance")

        key_marker = next_key_marker
        version_id_marker = next_version_marker


def requeue_document(dynamodb, table_name, candidate, now):
    pending_partition = (
        f"CLEANUP_PENDING#{candidate['shard']:02d}"
    )
    pending_sort_key = (
        f"{candidate['cleanup_after']}#{candidate['document_id']}"
    )

    try:
        dynamodb.update_item(
            TableName=table_name,
            Key={
                "PK": {"S": candidate["pk"]},
                "SK": {"S": candidate["sk"]},
            },
            UpdateExpression=(
                "SET #status = :pending, "
                "#gsi4pk = :gsi4pk, "
                "#gsi4sk = :gsi4sk, "
                "#requeued_at = :requeued_at "
                "REMOVE #finalize_after, #cleanup_completed_at"
            ),
            ConditionExpression=(
                "#status = :complete "
                "AND #tenant_id = :tenant_id "
                "AND #submission_id = :submission_id "
                "AND #document_id = :document_id "
                "AND #object_key = :object_key "
                "AND #expires_at = :expires_at "
                "AND #cleanup_after = :cleanup_after "
                "AND #finalize_after = :finalize_after "
                "AND #gsi4pk = :old_gsi4pk "
                "AND #gsi4sk = :old_gsi4sk"
            ),
            ExpressionAttributeNames={
                "#status": "status",
                "#gsi4pk": "GSI4PK",
                "#gsi4sk": "GSI4SK",
                "#requeued_at": "finalization_requeued_at",
                "#finalize_after": "finalize_after",
                "#cleanup_completed_at": "cleanup_completed_at",
                "#tenant_id": "tenant_id",
                "#submission_id": "submission_id",
                "#document_id": "document_id",
                "#object_key": "object_key",
                "#expires_at": "expires_at",
                "#cleanup_after": "cleanup_after",
            },
            ExpressionAttributeValues={
                ":pending": {"S": "CLEANUP_PENDING"},
                ":complete": {"S": "CLEANUP_COMPLETE"},
                ":gsi4pk": {"S": pending_partition},
                ":gsi4sk": {"S": pending_sort_key},
                ":requeued_at": {"S": now},
                ":tenant_id": {"S": candidate["tenant_id"]},
                ":submission_id": {"S": candidate["submission_id"]},
                ":document_id": {"S": candidate["document_id"]},
                ":object_key": {"S": candidate["object_key"]},
                ":expires_at": {"S": candidate["expires_at"]},
                ":cleanup_after": {"S": candidate["cleanup_after"]},
                ":finalize_after": {"S": candidate["finalize_after"]},
                ":old_gsi4pk": {"S": candidate["gsi4pk"]},
                ":old_gsi4sk": {"S": candidate["gsi4sk"]},
            },
        )

        return True

    except ClientError as exc:
        if (
            exc.response.get("Error", {}).get("Code")
            == "ConditionalCheckFailedException"
        ):
            return False
        raise


def delete_finalized_document(
    dynamodb,
    table_name,
    candidate,
    now,
):
    try:
        dynamodb.delete_item(
            TableName=table_name,
            Key={
                "PK": {"S": candidate["pk"]},
                "SK": {"S": candidate["sk"]},
            },
            ConditionExpression=(
                "#status = :complete "
                "AND #tenant_id = :tenant_id "
                "AND #submission_id = :submission_id "
                "AND #document_id = :document_id "
                "AND #object_key = :object_key "
                "AND #expires_at = :expires_at "
                "AND #cleanup_after = :cleanup_after "
                "AND #cleanup_completed_at = :cleanup_completed_at "
                "AND #finalize_after = :finalize_after "
                "AND #gsi4pk = :gsi4pk "
                "AND #gsi4sk = :gsi4sk "
                "AND #finalize_after <= :now"
            ),
            ExpressionAttributeNames={
                "#status": "status",
                "#tenant_id": "tenant_id",
                "#submission_id": "submission_id",
                "#document_id": "document_id",
                "#object_key": "object_key",
                "#expires_at": "expires_at",
                "#cleanup_after": "cleanup_after",
                "#cleanup_completed_at": "cleanup_completed_at",
                "#finalize_after": "finalize_after",
                "#gsi4pk": "GSI4PK",
                "#gsi4sk": "GSI4SK",
            },
            ExpressionAttributeValues={
                ":complete": {"S": "CLEANUP_COMPLETE"},
                ":tenant_id": {"S": candidate["tenant_id"]},
                ":submission_id": {"S": candidate["submission_id"]},
                ":document_id": {"S": candidate["document_id"]},
                ":object_key": {"S": candidate["object_key"]},
                ":expires_at": {"S": candidate["expires_at"]},
                ":cleanup_after": {"S": candidate["cleanup_after"]},
                ":cleanup_completed_at": {
                    "S": candidate["cleanup_completed_at"]
                },
                ":finalize_after": {"S": candidate["finalize_after"]},
                ":gsi4pk": {"S": candidate["gsi4pk"]},
                ":gsi4sk": {"S": candidate["gsi4sk"]},
                ":now": {"S": now},
            },
        )

        return True

    except ClientError as exc:
        if (
            exc.response.get("Error", {}).get("Code")
            == "ConditionalCheckFailedException"
        ):
            return False
        raise


def finalize_candidate(
    dynamodb,
    s3,
    config,
    candidate,
    now,
):
    now_string = format_utc_timestamp(now)

    is_empty = verify_object_key_empty(
        s3,
        config["bucket_name"],
        candidate["object_key"],
    )

    if not is_empty:
        if requeue_document(
            dynamodb,
            config["table_name"],
            candidate,
            now_string,
        ):
            return "requeued"

        return "skipped"

    if delete_finalized_document(
        dynamodb,
        config["table_name"],
        candidate,
        now_string,
    ):
        return "deleted"

    return "skipped"


def _empty_result():
    return {key: 0 for key in RESULT_KEYS}


def _time_remaining(context):
    if context is None:
        return True

    return (
        context.get_remaining_time_in_millis() > TIME_BUFFER_MS
    )


def query_finalization_shard(
    dynamodb,
    s3,
    config,
    shard,
    max_items,
    now,
    context=None,
):
    result = _empty_result()
    exclusive_start_key = None

    while (
        result["processed"] < max_items
        and _time_remaining(context)
    ):
        remaining = max_items - result["processed"]

        query_arguments = {
            "TableName": config["table_name"],
            "IndexName": config["index_name"],
            "KeyConditionExpression": (
                "GSI4PK = :shard AND GSI4SK <= :cutoff"
            ),
            "ExpressionAttributeValues": {
                ":shard": {"S": f"CLEANUP_COMPLETE#{shard:02d}"},
                ":cutoff": {
                    "S": f"{format_utc_timestamp(now)}#\uffff"
                },
            },
            "Limit": remaining,
        }

        if exclusive_start_key:
            query_arguments["ExclusiveStartKey"] = (
                exclusive_start_key
            )

        response = dynamodb.query(**query_arguments)
        items = response.get("Items", [])

        if not isinstance(items, list):
            raise RuntimeError(
                "DynamoDB returned an invalid query result"
            )

        for item in items:
            if result["processed"] >= max_items:
                break

            if not _time_remaining(context):
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
                    "Skipped invalid finalization candidate"
                )
                continue

            try:
                outcome = finalize_candidate(
                    dynamodb,
                    s3,
                    config,
                    candidate,
                    now,
                )

                if outcome == "deleted":
                    result["deleted"] += 1
                elif outcome == "requeued":
                    result["requeued"] += 1
                else:
                    result["skipped"] += 1

            except Exception:
                result["failed"] += 1
                logger.exception(
                    "Document finalization failed for document %s",
                    candidate["document_id"],
                )

        if (
            result["processed"] >= max_items
            or not _time_remaining(context)
        ):
            break

        exclusive_start_key = response.get("LastEvaluatedKey")

        if not exclusive_start_key:
            break

    return result


def finalize_completed_documents(
    dynamodb,
    s3,
    config,
    now,
    context=None,
):
    if not isinstance(now, datetime):
        raise ValueError("now must be a datetime")

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    total = _empty_result()

    for shard in range(config["shard_count"]):
        if total["processed"] >= config["max_items"]:
            break

        if not _time_remaining(context):
            break

        remaining = config["max_items"] - total["processed"]

        shard_result = query_finalization_shard(
            dynamodb=dynamodb,
            s3=s3,
            config=config,
            shard=shard,
            max_items=remaining,
            now=now,
            context=context,
        )

        for key in RESULT_KEYS:
            total[key] += shard_result[key]

    return total


def load_config():
    table_name = os.environ.get("TABLE_NAME", "").strip()
    index_name = os.environ.get(
        "FINALIZATION_INDEX",
        "PendingDocumentCleanupIndex",
    ).strip()
    bucket_name = os.environ.get("BUCKET_NAME", "").strip()

    try:
        shard_count = int(os.environ.get("SHARD_COUNT", "4"))
        max_items = int(os.environ.get("MAX_ITEMS", "50"))
    except ValueError as exc:
        raise ValueError("SHARD_COUNT and MAX_ITEMS must be integers") from exc

    if not table_name:
        raise ValueError("TABLE_NAME is required")

    if index_name != "PendingDocumentCleanupIndex":
        raise ValueError("Unexpected finalization index")

    if not bucket_name:
        raise ValueError("BUCKET_NAME is required")

    if not 1 <= shard_count <= 16:
        raise ValueError("SHARD_COUNT must be between 1 and 16")

    if not 1 <= max_items <= 100:
        raise ValueError("MAX_ITEMS must be between 1 and 100")

    return {
        "table_name": table_name,
        "index_name": index_name,
        "bucket_name": bucket_name,
        "shard_count": shard_count,
        "max_items": max_items,
    }


def handler(event, context):
    config = load_config()

    dynamodb = boto3.client("dynamodb")
    s3 = boto3.client("s3")

    now = datetime.now(timezone.utc)

    result = finalize_completed_documents(
        dynamodb,
        s3,
        config,
        now,
        context,
    )

    logger.info(
        "Document finalization result: %s",
        json.dumps(result, sort_keys=True),
    )

    if result["failed"]:
        raise RuntimeError(
            f"{result['failed']} document finalization operation(s) failed"
        )

    return result


lambda_handler = handler
