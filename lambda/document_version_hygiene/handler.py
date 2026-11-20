import hashlib
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError


logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
IDENTIFIER_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)

MAX_SHARD_COUNT = 16
MAX_ITEMS_LIMIT = 100
S3_PAGE_SIZE = 1000
S3_DELETE_BATCH_SIZE = 1000
MAX_S3_VERSIONS_PER_DOCUMENT = 5000
TIME_BUFFER_MS = 5000
UPLOAD_HYGIENE_GRACE = timedelta(hours=24)

RESULT_KEYS = (
    "processed",
    "cleaned",
    "skipped",
    "invalid",
    "failed",
)


class ConfigurationError(ValueError):
    pass


class CandidateValidationError(ValueError):
    pass


class S3HygieneError(RuntimeError):
    pass


def get_config():
    table_name = os.environ.get("TABLE_NAME", "").strip()
    index_name = os.environ.get(
        "HYGIENE_INDEX",
        "PendingDocumentExpiryIndex",
    ).strip()
    bucket_name = os.environ.get("BUCKET_NAME", "").strip()

    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,255}", table_name):
        raise ConfigurationError("Invalid TABLE_NAME")

    if index_name != "PendingDocumentExpiryIndex":
        raise ConfigurationError("Invalid HYGIENE_INDEX")

    if not re.fullmatch(
        r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]",
        bucket_name,
    ):
        raise ConfigurationError("Invalid BUCKET_NAME")

    try:
        shard_count = int(os.environ.get("SHARD_COUNT", "4"))
        max_items = int(os.environ.get("MAX_ITEMS", "50"))
    except ValueError as exc:
        raise ConfigurationError(
            "SHARD_COUNT and MAX_ITEMS must be integers"
        ) from exc

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
    if not isinstance(value, datetime):
        raise ValueError("Expected datetime")

    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("A timezone-aware UTC datetime is required")

    return value.strftime(TIMESTAMP_FORMAT)


def parse_utc_timestamp(value):
    if not isinstance(value, str):
        raise CandidateValidationError("Invalid timestamp")

    try:
        parsed = datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise CandidateValidationError(
            "Invalid timestamp"
        ) from exc

    if parsed.strftime(TIMESTAMP_FORMAT) != value:
        raise CandidateValidationError("Noncanonical timestamp")

    return parsed.replace(tzinfo=timezone.utc)


def get_document_hygiene_shard(document_id, shard_count):
    if (
        not isinstance(document_id, str)
        or not IDENTIFIER_PATTERN.fullmatch(document_id)
        or document_id in {".", ".."}
    ):
        raise ValueError("Invalid document ID")

    if (
        isinstance(shard_count, bool)
        or not isinstance(shard_count, int)
        or not 1 <= shard_count <= MAX_SHARD_COUNT
    ):
        raise ValueError("Invalid shard count")

    digest = hashlib.sha256(
        document_id.encode("utf-8")
    ).digest()

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
    if (
        not IDENTIFIER_PATTERN.fullmatch(value)
        or value in {".", ".."}
    ):
        raise CandidateValidationError(f"Invalid {name}")


def validate_candidate(item, shard, shard_count, now):
    if not isinstance(item, dict):
        raise CandidateValidationError("Invalid DynamoDB candidate")

    if not isinstance(now, datetime):
        raise ValueError("now must be a datetime")

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    entity_type = _string_attribute(item, "entity_type")

    if entity_type != "DOCUMENT":
        raise CandidateValidationError(
            "Candidate is not a document entity"
        )

    tenant_id = _string_attribute(item, "tenant_id")
    submission_id = _string_attribute(item, "submission_id")
    document_id = _string_attribute(item, "document_id")

    object_key = _string_attribute(item, "object_key")
    status = _string_attribute(item, "status")

    expires_at = _string_attribute(item, "expires_at")
    upload_url_expires_at = _string_attribute(
        item,
        "upload_url_expires_at",
    )
    upload_hygiene_after = _string_attribute(
        item,
        "upload_hygiene_after",
    )
    version_id = _string_attribute(item, "version_id")

    pk = _string_attribute(item, "PK")
    sk = _string_attribute(item, "SK")
    gsi3pk = _string_attribute(item, "GSI3PK")
    gsi3sk = _string_attribute(item, "GSI3SK")

    for value, name in (
        (tenant_id, "tenant ID"),
        (submission_id, "submission ID"),
        (document_id, "document ID"),
    ):
        _validate_identifier(value, name)

    if version_id == "null":
        raise CandidateValidationError(
            "Accepted S3 version ID is not valid"
        )

    expected_pk = (
        f"TENANT#{tenant_id}#SUBMISSION#{submission_id}"
    )
    expected_sk = f"DOCUMENT#{document_id}"

    expected_object_key = (
        f"tenants/{tenant_id}/submissions/"
        f"{submission_id}/{document_id}"
    )

    if pk != expected_pk or sk != expected_sk:
        raise CandidateValidationError("Invalid document identity")

    if object_key != expected_object_key:
        raise CandidateValidationError("Noncanonical S3 object key")

    if status != "UPLOADED":
        raise CandidateValidationError("Document is not UPLOADED")

    expected_shard = get_document_hygiene_shard(
        document_id,
        shard_count,
    )

    if (
        isinstance(shard, bool)
        or not isinstance(shard, int)
        or shard != expected_shard
    ):
        raise CandidateValidationError("Incorrect hygiene shard")

    expected_gsi3pk = f"UPLOADED#{expected_shard:02d}"

    if gsi3pk != expected_gsi3pk:
        raise CandidateValidationError("Invalid hygiene partition")

    expires_dt = parse_utc_timestamp(expires_at)
    upload_expiry_dt = parse_utc_timestamp(upload_url_expires_at)
    hygiene_dt = parse_utc_timestamp(upload_hygiene_after)

    if upload_expiry_dt >= expires_dt:
        raise CandidateValidationError(
            "Upload URL expiry must precede reservation expiry"
        )

    if hygiene_dt != upload_expiry_dt + UPLOAD_HYGIENE_GRACE:
        raise CandidateValidationError("Invalid hygiene deadline")

    if hygiene_dt > now.astimezone(timezone.utc):
        raise CandidateValidationError(
            "Upload hygiene grace period has not elapsed"
        )

    expected_gsi3sk = (
        f"{upload_hygiene_after}#{document_id}"
    )

    if gsi3sk != expected_gsi3sk:
        raise CandidateValidationError(
            "Invalid hygiene sort key"
        )

    return {
        "pk": pk,
        "sk": sk,
        "tenant_id": tenant_id,
        "submission_id": submission_id,
        "document_id": document_id,
        "object_key": object_key,
        "status": status,
        "expires_at": expires_at,
        "upload_url_expires_at": upload_url_expires_at,
        "upload_hygiene_after": upload_hygiene_after,
        "version_id": version_id,
        "gsi3pk": gsi3pk,
        "gsi3sk": gsi3sk,
        "shard": shard,
    }


def has_time_remaining(context):
    if context is None:
        return True

    return (
        context.get_remaining_time_in_millis()
        > TIME_BUFFER_MS
    )


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


def get_exact_key_versions(page, object_key):
    if not isinstance(page, dict):
        raise S3HygieneError("Invalid S3 listing response")

    result = {
        "versions": [],
        "delete_markers": [],
    }

    collections = (
        ("Versions", "versions"),
        ("DeleteMarkers", "delete_markers"),
    )

    for collection_name, result_name in collections:
        entries = page.get(collection_name, [])

        if not isinstance(entries, list):
            raise S3HygieneError(
                "Invalid S3 version collection"
            )

        for entry in entries:
            if not isinstance(entry, dict):
                raise S3HygieneError(
                    "Invalid S3 version entry"
                )

            if entry.get("Key") != object_key:
                continue

            version_id = entry.get("VersionId")

            if not isinstance(version_id, str) or not version_id:
                raise S3HygieneError(
                    "Exact-key entry has no version ID"
                )

            result[result_name].append({
                "Key": object_key,
                "VersionId": version_id,
            })

    return result


def collect_exact_key_versions(
    s3,
    bucket_name,
    object_key,
    context=None,
):
    """Collect exact-key versions and delete markers before deletion."""

    key_marker = None
    version_id_marker = None

    collected = {
        "versions": [],
        "delete_markers": [],
    }

    while True:
        if not has_time_remaining(context):
            raise S3HygieneError(
                "Insufficient Lambda execution time for S3 pagination"
            )

        page = list_object_versions_page(
            s3,
            bucket_name,
            object_key,
            key_marker,
            version_id_marker,
        )

        page_entries = get_exact_key_versions(
            page,
            object_key,
        )

        page_version_count = (
            len(page_entries["versions"])
            + len(page_entries["delete_markers"])
        )

        collected_version_count = (
            len(collected["versions"])
            + len(collected["delete_markers"])
        )

        if (
            collected_version_count + page_version_count
            > MAX_S3_VERSIONS_PER_DOCUMENT
        ):
            raise S3HygieneError(
                "S3 version history exceeds configured limit"
            )

        collected["versions"].extend(
            page_entries["versions"]
        )

        collected["delete_markers"].extend(
            page_entries["delete_markers"]
        )

        truncated = page.get("IsTruncated", False)

        if not isinstance(truncated, bool):
            raise S3HygieneError(
                "Invalid S3 pagination indicator"
            )

        if not truncated:
            break

        next_key_marker = page.get("NextKeyMarker")
        next_version_marker = page.get("NextVersionIdMarker")

        if not isinstance(next_key_marker, str) or not next_key_marker:
            raise S3HygieneError(
                "Truncated S3 response has no next key marker"
            )

        if next_version_marker is not None and (
            not isinstance(next_version_marker, str)
            or not next_version_marker
        ):
            raise S3HygieneError(
                "Invalid S3 next version marker"
            )

        if (
            next_key_marker == key_marker
            and next_version_marker == version_id_marker
        ):
            raise S3HygieneError(
                "S3 pagination marker did not advance"
            )

        key_marker = next_key_marker
        version_id_marker = next_version_marker

    return collected


def verify_accepted_version_exists(
    collected,
    accepted_version_id,
):
    if not isinstance(collected, dict):
        raise S3HygieneError(
            "Invalid collected S3 version data"
        )

    versions = collected.get("versions")

    if not isinstance(versions, list):
        raise S3HygieneError(
            "Invalid S3 versions collection"
        )

    return any(
        version["VersionId"] == accepted_version_id
        for version in versions
    )


def delete_unaccepted_versions(
    s3,
    bucket_name,
    object_key,
    versions,
    accepted_version_id,
    delete_markers=None,
    context=None,
):
    if not isinstance(versions, list):
        raise S3HygieneError(
            "Invalid S3 versions collection"
        )

    if delete_markers is None:
        delete_markers = []

    if not isinstance(delete_markers, list):
        raise S3HygieneError(
            "Invalid S3 delete markers collection"
        )

    objects_to_delete = [
        version
        for version in versions
        if version["VersionId"] != accepted_version_id
    ]

    objects_to_delete.extend(delete_markers)

    for offset in range(
        0,
        len(objects_to_delete),
        S3_DELETE_BATCH_SIZE,
    ):
        if not has_time_remaining(context):
            raise S3HygieneError(
                "Insufficient Lambda execution time for S3 deletion"
            )

        batch = objects_to_delete[
            offset:offset + S3_DELETE_BATCH_SIZE
        ]

        response = s3.delete_objects(
            Bucket=bucket_name,
            Delete={
                "Objects": batch,
                "Quiet": False,
            },
        )

        if not isinstance(response, dict):
            raise S3HygieneError(
                "Invalid S3 deletion response"
            )

        errors = response.get("Errors", [])

        if not isinstance(errors, list):
            raise S3HygieneError(
                "Invalid S3 deletion response"
            )

        if errors:
            error_codes = sorted({
                str(error.get("Code", "Unknown"))[:64]
                for error in errors
                if isinstance(error, dict)
            })

            raise S3HygieneError(
                "S3 version deletion failed: "
                + ",".join(error_codes)
            )


def verify_accepted_version_only(
    s3,
    bucket_name,
    object_key,
    accepted_version_id,
    context=None,
):
    remaining = collect_exact_key_versions(
        s3,
        bucket_name,
        object_key,
        context=context,
    )

    versions = remaining["versions"]
    delete_markers = remaining["delete_markers"]

    if len(versions) != 1:
        raise S3HygieneError(
            "Unexpected S3 versions remain after hygiene"
        )

    if versions[0]["VersionId"] != accepted_version_id:
        raise S3HygieneError(
            "Accepted S3 version is not the only remaining version"
        )

    if delete_markers:
        raise S3HygieneError(
            "Unexpected S3 delete markers remain after hygiene"
        )

    return True


def remove_hygiene_index(
    dynamodb,
    table_name,
    candidate,
):
    """Remove the sparse GSI3 entry after successful S3 verification."""

    try:
        dynamodb.update_item(
            TableName=table_name,
            Key={
                "PK": {"S": candidate["pk"]},
                "SK": {"S": candidate["sk"]},
            },
            UpdateExpression=(
                "REMOVE GSI3PK, GSI3SK"
            ),
            ConditionExpression=(
                "#status = :uploaded "
                "AND entity_type = :document "
                "AND tenant_id = :tenant "
                "AND submission_id = :submission "
                "AND document_id = :document_id "
                "AND object_key = :object_key "
                "AND version_id = :version_id "
                "AND expires_at = :expires_at "
                "AND upload_url_expires_at = :upload_url_expires_at "
                "AND upload_hygiene_after = :upload_hygiene_after "
                "AND GSI3PK = :gsi3pk "
                "AND GSI3SK = :gsi3sk"
            ),
            ExpressionAttributeNames={
                "#status": "status",
            },
            ExpressionAttributeValues={
                ":uploaded": {"S": "UPLOADED"},
                ":document": {"S": "DOCUMENT"},
                ":tenant": {"S": candidate["tenant_id"]},
                ":submission": {"S": candidate["submission_id"]},
                ":document_id": {"S": candidate["document_id"]},
                ":object_key": {"S": candidate["object_key"]},
                ":version_id": {"S": candidate["version_id"]},
                ":expires_at": {"S": candidate["expires_at"]},
                ":upload_url_expires_at": {
                    "S": candidate["upload_url_expires_at"]
                },
                ":upload_hygiene_after": {
                    "S": candidate["upload_hygiene_after"]
                },
                ":gsi3pk": {"S": candidate["gsi3pk"]},
                ":gsi3sk": {"S": candidate["gsi3sk"]},
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


def cleanup_candidate(
    dynamodb,
    s3,
    config,
    candidate,
    context=None,
):
    """Preserve the accepted version and remove all other exact-key versions."""

    collected = collect_exact_key_versions(
        s3,
        config["bucket_name"],
        candidate["object_key"],
        context=context,
    )

    versions = collected["versions"]
    delete_markers = collected["delete_markers"]

    accepted_version_id = candidate["version_id"]

    if not verify_accepted_version_exists(
        collected,
        accepted_version_id,
    ):
        raise S3HygieneError(
            "Accepted S3 version is missing; no versions were deleted"
        )

    delete_unaccepted_versions(
        s3,
        config["bucket_name"],
        candidate["object_key"],
        versions,
        accepted_version_id,
        delete_markers,
        context=context,
    )

    verify_accepted_version_only(
        s3,
        config["bucket_name"],
        candidate["object_key"],
        accepted_version_id,
        context=context,
    )

    return remove_hygiene_index(
        dynamodb,
        config["table_name"],
        candidate,
    )


def _empty_result():
    return {key: 0 for key in RESULT_KEYS}


def query_hygiene_shard(
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
        and has_time_remaining(context)
    ):
        remaining = max_items - result["processed"]

        query_arguments = {
            "TableName": config["table_name"],
            "IndexName": config["index_name"],
            "KeyConditionExpression": (
                "GSI3PK = :shard AND GSI3SK <= :cutoff"
            ),
            "ExpressionAttributeValues": {
                ":shard": {
                    "S": f"UPLOADED#{shard:02d}"
                },
                ":cutoff": {
                    "S": (
                        f"{format_utc_timestamp(now)}#\uffff"
                    )
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
                    "Skipped invalid document hygiene candidate"
                )
                continue

            try:
                cleaned = cleanup_candidate(
                    dynamodb,
                    s3,
                    config,
                    candidate,
                    context=context,
                )

                if cleaned:
                    result["cleaned"] += 1
                else:
                    result["skipped"] += 1

            except Exception:
                result["failed"] += 1
                logger.exception(
                    "Document version hygiene failed for document %s",
                    candidate["document_id"],
                )

        if (
            result["processed"] >= max_items
            or not has_time_remaining(context)
        ):
            break

        exclusive_start_key = response.get("LastEvaluatedKey")

        if not exclusive_start_key:
            break

    return result

def run_document_version_hygiene(
    dynamodb,
    s3,
    config,
    now,
    context=None,
):
    result = _empty_result()

    for shard in range(config["shard_count"]):
        if not has_time_remaining(context):
            break

        shard_result = query_hygiene_shard(
            dynamodb,
            s3,
            config,
            shard,
            config["max_items"] - result["processed"],
            now,
            context,
        )

        for key in RESULT_KEYS:
            result[key] += shard_result[key]

        if result["processed"] >= config["max_items"]:
            break

    return result


def handler(event, context):
    config = get_config()

    dynamodb = boto3.client("dynamodb")
    s3 = boto3.client("s3")

    now = datetime.now(timezone.utc).replace(microsecond=0)

    result = run_document_version_hygiene(
        dynamodb,
        s3,
        config,
        now,
        context,
    )

    logger.info(
        "Document version hygiene completed: %s",
        result,
    )

    if result["failed"]:
        raise RuntimeError(
            "One or more document version hygiene operations failed"
        )

    return result


def lambda_handler(event, context):
    return handler(event, context)
