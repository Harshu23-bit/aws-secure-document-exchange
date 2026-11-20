import importlib.util
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HANDLER_PATH = PROJECT_ROOT / "lambda" / "document_finalization" / "handler.py"

spec = importlib.util.spec_from_file_location(
    "document_finalization_integration_handler",
    HANDLER_PATH,
)

handler_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler_module)

TABLE_NAME = "cloudsec-test-submissions"
INDEX_NAME = "PendingDocumentCleanupIndex"
SHARD_COUNT = 4
DYNAMODB_ENDPOINT = "http://127.0.0.1:8000"

TENANT_ID = "tenant-finalization"
SUBMISSION_ID = "submission-finalization-001"
DOCUMENT_ID = "document-finalization-001"

CONFIG = {
    "table_name": TABLE_NAME,
    "index_name": INDEX_NAME,
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
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_completed_document(
    *,
    document_id=DOCUMENT_ID,
    tenant_id=TENANT_ID,
    submission_id=SUBMISSION_ID,
):
    now = datetime.now(UTC).replace(microsecond=0)

    expires_at = utc_timestamp(now - timedelta(hours=50))
    cleanup_after = utc_timestamp(now - timedelta(hours=26))
    cleanup_completed_at = utc_timestamp(now - timedelta(hours=25))
    finalize_after = utc_timestamp(now - timedelta(hours=1))

    shard = handler_module.get_document_cleanup_shard(
        document_id,
        SHARD_COUNT,
    )

    return {
        "PK": (f"TENANT#{tenant_id}#SUBMISSION#{submission_id}"),
        "SK": f"DOCUMENT#{document_id}",
        "entity_type": "DOCUMENT",
        "tenant_id": tenant_id,
        "submission_id": submission_id,
        "document_id": document_id,
        "object_key": (
            f"tenants/{tenant_id}/submissions/{submission_id}/{document_id}"
        ),
        "expires_at": expires_at,
        "cleanup_after": cleanup_after,
        "cleanup_completed_at": cleanup_completed_at,
        "finalize_after": finalize_after,
        "cleanup_attempts": 1,
        "status": "CLEANUP_COMPLETE",
        "GSI4PK": f"CLEANUP_COMPLETE#{shard:02d}",
        "GSI4SK": f"{finalize_after}#{document_id}",
    }


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


def wait_for_completed_index(
    client,
    document,
    timeout_seconds=5,
):
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        response = client.query(
            TableName=TABLE_NAME,
            IndexName=INDEX_NAME,
            KeyConditionExpression=("GSI4PK = :pk AND GSI4SK = :sk"),
            ExpressionAttributeValues={
                ":pk": {"S": document["GSI4PK"]},
                ":sk": {"S": document["GSI4SK"]},
            },
        )

        if response.get("Items"):
            return response["Items"][0]

        time.sleep(0.05)

    raise AssertionError("Document did not become visible in the completed GSI")


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
    assert item is not None

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


class FakeS3:
    def __init__(self, entries=None):
        self.entries = entries or []
        self.calls = []

    def list_object_versions(self, **kwargs):
        self.calls.append(kwargs)

        matching = [
            entry
            for entry in self.entries
            if entry.get("Key", "").startswith(kwargs["Prefix"])
        ]

        return {
            "Versions": [entry for entry in matching if "VersionId" in entry],
            "DeleteMarkers": [
                entry
                for entry in matching
                if "VersionId" in entry and entry.get("DeleteMarker", False)
            ],
            "IsTruncated": False,
        }


def make_candidate_and_seed(dynamodb_local, document=None):
    document = document or make_completed_document()
    seed_document(dynamodb_local, document)

    client = make_low_level_client()
    projected_item = wait_for_completed_index(client, document)

    now = datetime.now(UTC).replace(microsecond=0)

    candidate = handler_module.validate_candidate(
        projected_item,
        handler_module.get_document_cleanup_shard(
            document["document_id"],
            SHARD_COUNT,
        ),
        SHARD_COUNT,
        now,
    )

    return document, candidate, now


def test_completed_gsi_projects_all_finalization_attributes(
    dynamodb_local,
):
    document = make_completed_document()
    seed_document(dynamodb_local, document)

    projected = wait_for_completed_index(
        make_low_level_client(),
        document,
    )

    assert projected["cleanup_completed_at"]["S"] == (document["cleanup_completed_at"])
    assert projected["finalize_after"]["S"] == (document["finalize_after"])
    assert projected["status"]["S"] == "CLEANUP_COMPLETE"


def test_finalization_deletes_empty_document_record(
    dynamodb_local,
):
    _, candidate, now = make_candidate_and_seed(dynamodb_local)

    s3 = FakeS3()
    dynamodb = make_low_level_client()

    result = handler_module.finalize_candidate(
        dynamodb,
        s3,
        CONFIG,
        candidate,
        now,
    )

    assert result == "deleted"
    assert len(s3.calls) == 1
    assert read_document(dynamodb_local) is None


def test_finalization_requeues_document_when_version_exists(
    dynamodb_local,
):
    document, candidate, now = make_candidate_and_seed(dynamodb_local)

    s3 = FakeS3(
        entries=[
            {
                "Key": document["object_key"],
                "VersionId": "version-001",
            }
        ]
    )

    result = handler_module.finalize_candidate(
        make_low_level_client(),
        s3,
        CONFIG,
        candidate,
        now,
    )

    assert result == "requeued"

    stored = read_document(dynamodb_local)

    shard = handler_module.get_document_cleanup_shard(
        document["document_id"],
        SHARD_COUNT,
    )

    assert stored["status"] == "CLEANUP_PENDING"
    assert stored["GSI4PK"] == f"CLEANUP_PENDING#{shard:02d}"
    assert stored["GSI4SK"] == (
        f"{document['cleanup_after']}#{document['document_id']}"
    )
    assert stored["finalization_requeued_at"] == utc_timestamp(now)
    assert "finalize_after" not in stored
    assert "cleanup_completed_at" not in stored


def test_finalization_requeues_document_when_delete_marker_exists(
    dynamodb_local,
):
    document, candidate, now = make_candidate_and_seed(dynamodb_local)

    s3 = FakeS3(
        entries=[
            {
                "Key": document["object_key"],
                "VersionId": "marker-001",
                "DeleteMarker": True,
            }
        ]
    )

    result = handler_module.finalize_candidate(
        make_low_level_client(),
        s3,
        CONFIG,
        candidate,
        now,
    )

    assert result == "requeued"
    assert read_document(dynamodb_local)["status"] == "CLEANUP_PENDING"


def test_requeue_does_not_change_stale_or_modified_document(
    dynamodb_local,
):
    document, candidate, now = make_candidate_and_seed(dynamodb_local)

    client = make_low_level_client()

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

    assert not handler_module.requeue_document(
        client,
        TABLE_NAME,
        candidate,
        utc_timestamp(now),
    )

    stored = read_document(dynamodb_local)

    assert stored["status"] == "CLEANUP_COMPLETE"
    assert stored["object_key"] == "tenants/modified/object"


def test_conditional_delete_rejects_modified_document(
    dynamodb_local,
):
    document, candidate, now = make_candidate_and_seed(dynamodb_local)

    client = make_low_level_client()

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

    assert not handler_module.delete_finalized_document(
        client,
        TABLE_NAME,
        candidate,
        utc_timestamp(now),
    )

    stored = read_document(dynamodb_local)

    assert stored is not None
    assert stored["object_key"] == "tenants/modified/object"


def test_requeued_document_returns_to_pending_gsi(
    dynamodb_local,
):
    document, candidate, now = make_candidate_and_seed(dynamodb_local)

    s3 = FakeS3(
        entries=[
            {
                "Key": document["object_key"],
                "VersionId": "version-002",
            }
        ]
    )

    client = make_low_level_client()

    result = handler_module.finalize_candidate(
        client,
        s3,
        CONFIG,
        candidate,
        now,
    )

    assert result == "requeued"

    stored = read_document(dynamodb_local)

    response = client.query(
        TableName=TABLE_NAME,
        IndexName=INDEX_NAME,
        KeyConditionExpression=("GSI4PK = :pk AND GSI4SK = :sk"),
        ExpressionAttributeValues={
            ":pk": {"S": stored["GSI4PK"]},
            ":sk": {"S": stored["GSI4SK"]},
        },
    )

    assert len(response["Items"]) == 1
    assert response["Items"][0]["status"]["S"] == "CLEANUP_PENDING"


def test_finalization_query_deletes_eligible_empty_document(
    dynamodb_local,
):
    document = make_completed_document()
    seed_document(dynamodb_local, document)

    now = datetime.now(UTC).replace(microsecond=0)

    result = handler_module.query_finalization_shard(
        make_low_level_client(),
        FakeS3(),
        CONFIG,
        handler_module.get_document_cleanup_shard(
            document["document_id"],
            SHARD_COUNT,
        ),
        50,
        now,
    )

    assert result["processed"] == 1
    assert result["deleted"] == 1
    assert result["failed"] == 0
    assert read_document(dynamodb_local) is None


def test_s3_inspection_failure_does_not_delete_document(
    dynamodb_local,
):
    _, candidate, now = make_candidate_and_seed(dynamodb_local)

    class FailingS3:
        def list_object_versions(self, **kwargs):
            raise RuntimeError("Simulated S3 failure")

    with pytest.raises(RuntimeError):
        handler_module.finalize_candidate(
            make_low_level_client(),
            FailingS3(),
            CONFIG,
            candidate,
            now,
        )

    assert read_document(dynamodb_local) is not None


def test_invalid_candidate_is_not_finalized(
    dynamodb_local,
):
    document = make_completed_document()
    document["object_key"] = "tenants/incorrect/key"
    seed_document(dynamodb_local, document)

    projected = wait_for_completed_index(
        make_low_level_client(),
        document,
    )

    now = datetime.now(UTC).replace(microsecond=0)

    with pytest.raises(handler_module.CandidateValidationError):
        handler_module.validate_candidate(
            projected,
            handler_module.get_document_cleanup_shard(
                document["document_id"],
                SHARD_COUNT,
            ),
            SHARD_COUNT,
            now,
        )

    assert read_document(dynamodb_local) is not None
