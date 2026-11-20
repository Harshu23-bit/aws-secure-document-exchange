import importlib.util
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HANDLER_PATH = PROJECT_ROOT / "lambda" / "document_expiry" / "handler.py"

spec = importlib.util.spec_from_file_location(
    "document_expiry_integration_handler",
    HANDLER_PATH,
)

handler_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler_module)

TABLE_NAME = "cloudsec-test-submissions"
INDEX_NAME = "PendingDocumentExpiryIndex"
SHARD_COUNT = 4
DYNAMODB_ENDPOINT = "http://127.0.0.1:8000"

serializer = TypeSerializer()
deserializer = TypeDeserializer()


def make_low_level_client():
    """Create an independent low-level client without resource serializers."""

    return boto3.client(
        "dynamodb",
        region_name="ap-south-1",
        endpoint_url=DYNAMODB_ENDPOINT,
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )


def to_dynamodb_item(item):
    return {key: serializer.serialize(value) for key, value in item.items()}


def from_dynamodb_item(item):
    return {key: deserializer.deserialize(value) for key, value in item.items()}


def utc_timestamp(value):
    return value.isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )


def make_document(
    *,
    document_id="document-expiry-001",
    tenant_id="tenant-expiry",
    submission_id="submission-expiry-001",
    size_bytes=1024,
    expires_at=None,
    status="PENDING_UPLOAD",
    include_expiry_index=True,
    entity_type="DOCUMENT",
):
    shard = handler_module.get_document_expiry_shard(
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
        "owner_id": "user-expiry",
        "file_name": "test-document.pdf",
        "content_type": "application/pdf",
        "size_bytes": size_bytes,
        "status": status,
        "created_at": "2026-11-14T10:00:00Z",
    }

    if expires_at is not None:
        document["expires_at"] = expires_at

    if include_expiry_index and expires_at is not None:
        document["GSI3PK"] = f"PENDING_UPLOAD#{shard:02d}"
        document["GSI3SK"] = f"{expires_at}#{document_id}"

    return document


def make_submission(
    *,
    tenant_id="tenant-expiry",
    submission_id="submission-expiry-001",
    document_count=1,
    document_bytes=1024,
):
    return {
        "PK": f"TENANT#{tenant_id}",
        "SK": f"SUBMISSION#{submission_id}",
        "entity_type": "SUBMISSION",
        "tenant_id": tenant_id,
        "submission_id": submission_id,
        "owner_id": "user-expiry",
        "title": "Expiry integration test",
        "status": "DRAFT",
        "created_at": "2026-11-14T10:00:00Z",
        "updated_at": "2026-11-14T10:00:00Z",
        "version": 1,
        "total_document_count": document_count,
        "total_document_bytes": document_bytes,
        "pending_document_count": document_count,
        "pending_document_bytes": document_bytes,
        "uploaded_document_count": 0,
        "uploaded_document_bytes": 0,
    }


def seed_records(
    dynamodb_local,
    submission,
    documents,
):
    table = dynamodb_local.Table(TABLE_NAME)

    table.put_item(Item=submission)

    for document in documents:
        table.put_item(Item=document)


def wait_for_expiry_index(
    dynamodb_client,
    document,
    timeout_seconds=5,
):
    """Wait for the eventually consistent GSI to expose a document."""

    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        response = dynamodb_client.query(
            TableName=TABLE_NAME,
            IndexName=INDEX_NAME,
            KeyConditionExpression=("GSI3PK = :pk AND GSI3SK = :sk"),
            ExpressionAttributeValues={
                ":pk": {"S": document["GSI3PK"]},
                ":sk": {"S": document["GSI3SK"]},
            },
        )

        if response.get("Items"):
            return

        time.sleep(0.05)

    raise AssertionError("Document did not become visible in the expiry GSI")


def read_submission(
    dynamodb_local,
    tenant_id,
    submission_id,
):
    return (
        dynamodb_local.Table(TABLE_NAME)
        .get_item(
            Key={
                "PK": f"TENANT#{tenant_id}",
                "SK": f"SUBMISSION#{submission_id}",
            },
            ConsistentRead=True,
        )
        .get("Item")
    )


def read_document(
    dynamodb_local,
    tenant_id,
    submission_id,
    document_id,
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


def run_cleanup(
    dynamodb_client,
    now,
    max_items=100,
):
    return handler_module.cleanup_expired_documents(
        dynamodb=dynamodb_client,
        config={
            "table_name": TABLE_NAME,
            "index_name": INDEX_NAME,
            "shard_count": SHARD_COUNT,
            "max_items": max_items,
        },
        now=now,
    )


def test_expired_document_transitions_to_cleanup_pending_and_reconciles_counters(
    dynamodb_local,
):
    client = make_low_level_client()

    now = datetime.now(UTC).replace(microsecond=0)
    expires_at = utc_timestamp(now - timedelta(minutes=5))

    document = make_document(expires_at=expires_at)
    submission = make_submission()

    seed_records(
        dynamodb_local,
        submission,
        [document],
    )

    wait_for_expiry_index(client, document)

    result = run_cleanup(client, now)

    assert result["processed"] == 1
    assert result["transitioned"] == 1
    assert result["invalid"] == 0

    stored = read_document(
        dynamodb_local,
        "tenant-expiry",
        "submission-expiry-001",
        "document-expiry-001",
    )

    assert stored is not None
    assert stored["status"] == "CLEANUP_PENDING"
    assert stored["object_key"] == (
        "tenants/tenant-expiry/submissions/submission-expiry-001/document-expiry-001"
    )
    assert "GSI3PK" not in stored
    assert "GSI3SK" not in stored
    assert stored["GSI4PK"].startswith("CLEANUP_PENDING#")
    assert stored["GSI4SK"].endswith("#document-expiry-001")

    expected_cleanup_after = utc_timestamp(
        datetime.fromisoformat(expires_at) + timedelta(hours=24)
    )
    assert stored["cleanup_after"] == expected_cleanup_after
    assert stored["cleanup_attempts"] == 0

    updated = read_submission(
        dynamodb_local,
        "tenant-expiry",
        "submission-expiry-001",
    )

    assert updated["pending_document_count"] == 0
    assert updated["pending_document_bytes"] == 0
    assert updated["total_document_count"] == 0
    assert updated["total_document_bytes"] == 0
    assert updated["uploaded_document_count"] == 0
    assert updated["uploaded_document_bytes"] == 0


def test_non_expired_document_is_not_deleted(
    dynamodb_local,
):
    client = make_low_level_client()

    now = datetime.now(UTC).replace(microsecond=0)
    expires_at = utc_timestamp(now + timedelta(minutes=30))

    document = make_document(expires_at=expires_at)

    seed_records(
        dynamodb_local,
        make_submission(),
        [document],
    )

    result = run_cleanup(client, now)

    assert result["transitioned"] == 0

    assert (
        read_document(
            dynamodb_local,
            "tenant-expiry",
            "submission-expiry-001",
            "document-expiry-001",
        )
        is not None
    )

    unchanged = read_submission(
        dynamodb_local,
        "tenant-expiry",
        "submission-expiry-001",
    )

    assert unchanged["pending_document_count"] == 1
    assert unchanged["pending_document_bytes"] == 1024
    assert unchanged["total_document_count"] == 1
    assert unchanged["total_document_bytes"] == 1024


def test_uploaded_document_without_expiry_index_is_not_selected(
    dynamodb_local,
):
    client = make_low_level_client()

    now = datetime.now(UTC).replace(microsecond=0)

    document = make_document(
        status="UPLOADED",
        include_expiry_index=False,
    )

    document["version_id"] = "version-123"
    document["uploaded_at"] = utc_timestamp(now)

    seed_records(
        dynamodb_local,
        make_submission(),
        [document],
    )

    result = run_cleanup(client, now)

    assert result["processed"] == 0
    assert result["transitioned"] == 0

    stored = read_document(
        dynamodb_local,
        "tenant-expiry",
        "submission-expiry-001",
        "document-expiry-001",
    )

    assert stored is not None
    assert stored["status"] == "UPLOADED"


def test_cleanup_transition_is_idempotent(
    dynamodb_local,
):
    client = make_low_level_client()

    now = datetime.now(UTC).replace(microsecond=0)
    expires_at = utc_timestamp(now - timedelta(minutes=5))

    document = make_document(expires_at=expires_at)

    seed_records(
        dynamodb_local,
        make_submission(),
        [document],
    )

    wait_for_expiry_index(client, document)

    first_result = run_cleanup(client, now)
    second_result = run_cleanup(client, now)

    assert first_result["transitioned"] == 1
    assert second_result["transitioned"] == 0

    updated = read_submission(
        dynamodb_local,
        "tenant-expiry",
        "submission-expiry-001",
    )

    assert updated["pending_document_count"] == 0
    assert updated["pending_document_bytes"] == 0
    assert updated["total_document_count"] == 0
    assert updated["total_document_bytes"] == 0


def test_cleanup_respects_global_max_items_limit(
    dynamodb_local,
):
    client = make_low_level_client()

    now = datetime.now(UTC).replace(microsecond=0)
    expires_at = utc_timestamp(now - timedelta(minutes=5))

    documents = [
        make_document(
            document_id=f"document-expiry-{index:03d}",
            expires_at=expires_at,
        )
        for index in range(3)
    ]

    submission = make_submission(
        document_count=3,
        document_bytes=3 * 1024,
    )

    seed_records(
        dynamodb_local,
        submission,
        documents,
    )

    for document in documents:
        wait_for_expiry_index(client, document)

    result = run_cleanup(client, now, max_items=2)

    assert result["processed"] == 2
    assert result["transitioned"] == 2

    statuses = [
        read_document(
            dynamodb_local,
            "tenant-expiry",
            "submission-expiry-001",
            f"document-expiry-{index:03d}",
        )["status"]
        for index in range(3)
    ]
    assert statuses.count("CLEANUP_PENDING") == 2
    assert statuses.count("PENDING_UPLOAD") == 1

    updated = read_submission(
        dynamodb_local,
        "tenant-expiry",
        "submission-expiry-001",
    )

    assert updated["pending_document_count"] == 1
    assert updated["pending_document_bytes"] == 1024
    assert updated["total_document_count"] == 1
    assert updated["total_document_bytes"] == 1024
