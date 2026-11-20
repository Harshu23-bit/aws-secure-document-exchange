import importlib.util
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HANDLER_PATH = PROJECT_ROOT / "lambda" / "document_cleanup" / "handler.py"

spec = importlib.util.spec_from_file_location(
    "document_cleanup_integration_handler",
    HANDLER_PATH,
)

handler_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler_module)

TABLE_NAME = "cloudsec-test-submissions"
INDEX_NAME = "PendingDocumentCleanupIndex"
SHARD_COUNT = 4
DYNAMODB_ENDPOINT = "http://127.0.0.1:8000"

TENANT_ID = "tenant-cleanup"
SUBMISSION_ID = "submission-cleanup-001"
DOCUMENT_ID = "document-cleanup-001"

CONFIG = {
    "table_name": TABLE_NAME,
    "cleanup_index": INDEX_NAME,
    "bucket_name": "cloudsec-test-application-bucket",
    "shard_count": SHARD_COUNT,
    "max_items": 50,
}


def make_low_level_client():
    return boto3.client(
        "dynamodb",
        region_name="ap-south-1",
        endpoint_url=DYNAMODB_ENDPOINT,
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )


def utc_timestamp(value):
    return value.isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )


def make_document(
    *,
    document_id=DOCUMENT_ID,
    tenant_id=TENANT_ID,
    submission_id=SUBMISSION_ID,
    expires_at=None,
    cleanup_after=None,
    cleanup_attempts=0,
    status="CLEANUP_PENDING",
    include_cleanup_index=True,
    entity_type="DOCUMENT",
):
    now = datetime.now(UTC).replace(microsecond=0)

    if expires_at is None:
        expires_at = utc_timestamp(now - timedelta(hours=26))

    if cleanup_after is None:
        expiry = datetime.strptime(
            expires_at,
            "%Y-%m-%dT%H:%M:%SZ",
        ).replace(tzinfo=UTC)

        cleanup_after = utc_timestamp(expiry + timedelta(hours=24))

    shard = handler_module.get_document_cleanup_shard(
        document_id,
        SHARD_COUNT,
    )

    document = {
        "PK": (f"TENANT#{tenant_id}#SUBMISSION#{submission_id}"),
        "SK": f"DOCUMENT#{document_id}",
        "entity_type": entity_type,
        "tenant_id": tenant_id,
        "submission_id": submission_id,
        "document_id": document_id,
        "object_key": (
            f"tenants/{tenant_id}/submissions/{submission_id}/{document_id}"
        ),
        "expires_at": expires_at,
        "cleanup_after": cleanup_after,
        "cleanup_attempts": cleanup_attempts,
        "status": status,
    }

    if include_cleanup_index:
        document["GSI4PK"] = f"CLEANUP_PENDING#{shard:02d}"
        document["GSI4SK"] = f"{cleanup_after}#{document_id}"

    return document


def seed_document(dynamodb_local, document):
    dynamodb_local.Table(TABLE_NAME).put_item(
        Item=document,
    )


def read_document(
    dynamodb_local,
    document_id=DOCUMENT_ID,
    tenant_id=TENANT_ID,
    submission_id=SUBMISSION_ID,
):
    return (
        dynamodb_local.Table(TABLE_NAME)
        .get_item(
            Key={
                "PK": (f"TENANT#{tenant_id}#SUBMISSION#{submission_id}"),
                "SK": f"DOCUMENT#{document_id}",
            },
            ConsistentRead=True,
        )
        .get("Item")
    )


def wait_for_cleanup_index(
    dynamodb_client,
    document,
    timeout_seconds=5,
):
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        response = dynamodb_client.query(
            TableName=TABLE_NAME,
            IndexName=INDEX_NAME,
            KeyConditionExpression=("GSI4PK = :pk AND GSI4SK = :sk"),
            ExpressionAttributeValues={
                ":pk": {"S": document["GSI4PK"]},
                ":sk": {"S": document["GSI4SK"]},
            },
        )

        if response.get("Items"):
            return

        time.sleep(0.05)

    raise AssertionError("Document did not become visible in the cleanup GSI")


def get_candidate(document, now):
    client = make_low_level_client()

    response = client.get_item(
        TableName=TABLE_NAME,
        Key={
            "PK": {"S": document["PK"]},
            "SK": {"S": document["SK"]},
        },
        ConsistentRead=True,
    )

    item = response.get("Item")
    assert item is not None, "Seeded document was not found"

    shard = handler_module.get_document_cleanup_shard(
        document["document_id"],
        SHARD_COUNT,
    )

    return handler_module.validate_candidate(
        item,
        shard,
        SHARD_COUNT,
        now,
    )


def test_cleanup_index_returns_only_eligible_pending_documents(
    dynamodb_local,
):
    client = make_low_level_client()

    eligible = make_document()
    seed_document(dynamodb_local, eligible)

    wait_for_cleanup_index(client, eligible)

    result = client.query(
        TableName=TABLE_NAME,
        IndexName=INDEX_NAME,
        KeyConditionExpression=("GSI4PK = :pk AND GSI4SK <= :cutoff"),
        ExpressionAttributeValues={
            ":pk": {"S": eligible["GSI4PK"]},
            ":cutoff": {"S": (utc_timestamp(datetime.now(UTC)) + "#\uffff")},
        },
    )

    returned_ids = {item["document_id"]["S"] for item in result["Items"]}

    assert DOCUMENT_ID in returned_ids

    stored = read_document(dynamodb_local)

    assert stored["status"] == "CLEANUP_PENDING"
    assert stored["GSI4PK"] == eligible["GSI4PK"]
    assert stored["GSI4SK"] == eligible["GSI4SK"]


def test_cleanup_attempt_increments_attempt_counter(
    dynamodb_local,
):
    client = make_low_level_client()
    now = datetime.now(UTC).replace(microsecond=0)
    timestamp = utc_timestamp(now)

    document = make_document()
    seed_document(dynamodb_local, document)

    wait_for_cleanup_index(client, document)

    candidate = get_candidate(document, now)

    assert handler_module.record_cleanup_attempt(
        client,
        TABLE_NAME,
        candidate,
        timestamp,
    )

    stored = read_document(dynamodb_local)

    assert stored["cleanup_attempts"] == 1
    assert stored["last_cleanup_attempt_at"] == timestamp
    assert stored["status"] == "CLEANUP_PENDING"
    assert stored["GSI4PK"] == document["GSI4PK"]
    assert stored["GSI4SK"] == document["GSI4SK"]


def test_cleanup_attempt_rejects_stale_document_state(
    dynamodb_local,
):
    client = make_low_level_client()
    now = datetime.now(UTC).replace(microsecond=0)

    document = make_document()
    seed_document(dynamodb_local, document)

    wait_for_cleanup_index(client, document)

    candidate = get_candidate(document, now)

    client.update_item(
        TableName=TABLE_NAME,
        Key={
            "PK": {"S": document["PK"]},
            "SK": {"S": document["SK"]},
        },
        UpdateExpression="SET #status = :uploaded",
        ExpressionAttributeNames={
            "#status": "status",
        },
        ExpressionAttributeValues={
            ":uploaded": {"S": "UPLOADED"},
        },
    )

    assert not handler_module.record_cleanup_attempt(
        client,
        TABLE_NAME,
        candidate,
        utc_timestamp(now),
    )

    stored = read_document(dynamodb_local)

    assert stored["status"] == "UPLOADED"
    assert stored["cleanup_attempts"] == 0


def test_cleanup_complete_transition_updates_status_and_gsi(
    dynamodb_local,
):
    client = make_low_level_client()
    now = datetime.now(UTC).replace(microsecond=0)
    timestamp = utc_timestamp(now)

    document = make_document()
    seed_document(dynamodb_local, document)

    wait_for_cleanup_index(client, document)

    candidate = get_candidate(document, now)

    assert handler_module.record_cleanup_attempt(
        client,
        TABLE_NAME,
        candidate,
        timestamp,
    )

    assert handler_module.transition_cleanup_complete(
        client,
        TABLE_NAME,
        candidate,
        timestamp,
    )

    stored = read_document(dynamodb_local)

    expected_finalize_after = utc_timestamp(now + timedelta(hours=24))

    shard = handler_module.get_document_cleanup_shard(
        DOCUMENT_ID,
        SHARD_COUNT,
    )

    assert stored["status"] == "CLEANUP_COMPLETE"
    assert stored["cleanup_attempts"] == 1
    assert stored["cleanup_completed_at"] == timestamp
    assert stored["finalize_after"] == expected_finalize_after
    assert stored["GSI4PK"] == f"CLEANUP_COMPLETE#{shard:02d}"
    assert stored["GSI4SK"] == (f"{expected_finalize_after}#{DOCUMENT_ID}")
    assert "last_cleanup_error" not in stored


def test_cleanup_complete_transition_is_conditional(
    dynamodb_local,
):
    client = make_low_level_client()
    now = datetime.now(UTC).replace(microsecond=0)
    timestamp = utc_timestamp(now)

    document = make_document()
    seed_document(dynamodb_local, document)

    wait_for_cleanup_index(client, document)

    candidate = get_candidate(document, now)

    assert handler_module.record_cleanup_attempt(
        client,
        TABLE_NAME,
        candidate,
        timestamp,
    )

    assert handler_module.transition_cleanup_complete(
        client,
        TABLE_NAME,
        candidate,
        timestamp,
    )

    assert not handler_module.transition_cleanup_complete(
        client,
        TABLE_NAME,
        candidate,
        timestamp,
    )

    stored = read_document(dynamodb_local)

    assert stored["status"] == "CLEANUP_COMPLETE"
    assert stored["cleanup_attempts"] == 1


def test_cleanup_complete_transition_rejects_modified_object_key(
    dynamodb_local,
):
    client = make_low_level_client()
    now = datetime.now(UTC).replace(microsecond=0)
    timestamp = utc_timestamp(now)

    document = make_document()
    seed_document(dynamodb_local, document)

    wait_for_cleanup_index(client, document)

    candidate = get_candidate(document, now)

    assert handler_module.record_cleanup_attempt(
        client,
        TABLE_NAME,
        candidate,
        timestamp,
    )

    client.update_item(
        TableName=TABLE_NAME,
        Key={
            "PK": {"S": document["PK"]},
            "SK": {"S": document["SK"]},
        },
        UpdateExpression="SET object_key = :key",
        ExpressionAttributeValues={
            ":key": {"S": "tenants/modified/object"},
        },
    )

    assert not handler_module.transition_cleanup_complete(
        client,
        TABLE_NAME,
        candidate,
        timestamp,
    )

    stored = read_document(dynamodb_local)

    assert stored["status"] == "CLEANUP_PENDING"
    assert stored["object_key"] == "tenants/modified/object"


def test_completed_document_moves_out_of_pending_gsi_partition(
    dynamodb_local,
):
    client = make_low_level_client()
    now = datetime.now(UTC).replace(microsecond=0)
    timestamp = utc_timestamp(now)

    document = make_document()
    seed_document(dynamodb_local, document)

    wait_for_cleanup_index(client, document)

    candidate = get_candidate(document, now)

    assert handler_module.record_cleanup_attempt(
        client,
        TABLE_NAME,
        candidate,
        timestamp,
    )

    assert handler_module.transition_cleanup_complete(
        client,
        TABLE_NAME,
        candidate,
        timestamp,
    )

    pending_query = client.query(
        TableName=TABLE_NAME,
        IndexName=INDEX_NAME,
        KeyConditionExpression="GSI4PK = :pk",
        ExpressionAttributeValues={
            ":pk": {"S": document["GSI4PK"]},
        },
    )

    pending_ids = {item["document_id"]["S"] for item in pending_query["Items"]}

    assert DOCUMENT_ID not in pending_ids

    stored = read_document(dynamodb_local)

    completed_query = client.query(
        TableName=TABLE_NAME,
        IndexName=INDEX_NAME,
        KeyConditionExpression=("GSI4PK = :pk AND GSI4SK = :sk"),
        ExpressionAttributeValues={
            ":pk": {"S": stored["GSI4PK"]},
            ":sk": {"S": stored["GSI4SK"]},
        },
    )

    assert len(completed_query["Items"]) == 1
    assert completed_query["Items"][0]["status"]["S"] == "CLEANUP_COMPLETE"


def test_candidate_validation_rejects_incorrect_cleanup_schedule(
    dynamodb_local,
):
    now = datetime.now(UTC).replace(microsecond=0)

    document = make_document(
        cleanup_after=utc_timestamp(now - timedelta(hours=1)),
    )

    seed_document(dynamodb_local, document)

    with pytest.raises(handler_module.CandidateValidationError):
        get_candidate(document, now)
