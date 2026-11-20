import importlib.util
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HANDLER_PATH = PROJECT_ROOT / "lambda" / "document_version_hygiene" / "handler.py"

spec = importlib.util.spec_from_file_location(
    "document_version_hygiene_integration_handler",
    HANDLER_PATH,
)

handler_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler_module)


TABLE_NAME = "cloudsec-test-submissions"
INDEX_NAME = "PendingDocumentExpiryIndex"
SHARD_COUNT = 4
DYNAMODB_ENDPOINT = "http://127.0.0.1:8000"

TENANT_ID = "tenant-hygiene"
SUBMISSION_ID = "submission-hygiene-001"
DOCUMENT_ID = "document-hygiene-001"

ACCEPTED_VERSION_ID = "accepted-version-001"
EXTRA_VERSION_ID = "extra-version-001"
DELETE_MARKER_ID = "delete-marker-001"

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


def make_uploaded_document(
    *,
    document_id=DOCUMENT_ID,
    tenant_id=TENANT_ID,
    submission_id=SUBMISSION_ID,
):
    now = datetime.now(UTC).replace(microsecond=0)

    expires_at_dt = now - timedelta(hours=26)
    upload_expiry_dt = expires_at_dt - timedelta(minutes=25)
    hygiene_after_dt = upload_expiry_dt + timedelta(hours=24)

    expires_at = utc_timestamp(expires_at_dt)
    upload_url_expires_at = utc_timestamp(upload_expiry_dt)
    upload_hygiene_after = utc_timestamp(hygiene_after_dt)

    shard = handler_module.get_document_hygiene_shard(
        document_id,
        SHARD_COUNT,
    )

    object_key = f"tenants/{tenant_id}/submissions/{submission_id}/{document_id}"

    return {
        "PK": (f"TENANT#{tenant_id}#SUBMISSION#{submission_id}"),
        "SK": f"DOCUMENT#{document_id}",
        "entity_type": "DOCUMENT",
        "tenant_id": tenant_id,
        "submission_id": submission_id,
        "document_id": document_id,
        "object_key": object_key,
        "size_bytes": 1024,
        "expires_at": expires_at,
        "upload_url_expires_at": upload_url_expires_at,
        "upload_hygiene_after": upload_hygiene_after,
        "version_id": ACCEPTED_VERSION_ID,
        "status": "UPLOADED",
        "GSI3PK": f"UPLOADED#{shard:02d}",
        "GSI3SK": f"{upload_hygiene_after}#{document_id}",
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


def wait_for_hygiene_index(
    client,
    document,
    timeout_seconds=5,
):
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        response = client.query(
            TableName=TABLE_NAME,
            IndexName=INDEX_NAME,
            KeyConditionExpression=("GSI3PK = :pk AND GSI3SK = :sk"),
            ExpressionAttributeValues={
                ":pk": {"S": document["GSI3PK"]},
                ":sk": {"S": document["GSI3SK"]},
            },
        )

        if response.get("Items"):
            return response["Items"][0]

        time.sleep(0.05)

    raise AssertionError("Document did not become visible in the hygiene GSI")


def make_client_error(code, operation):
    return ClientError(
        {
            "Error": {
                "Code": code,
                "Message": "Integration-test failure",
            }
        },
        operation,
    )


class FakeS3:
    """In-memory S3 version listing and deletion test double."""

    def __init__(
        self,
        entries=None,
        list_error=None,
        delete_error=None,
    ):
        self.entries = list(entries or [])
        self.list_error = list_error
        self.delete_error = delete_error
        self.list_calls = []
        self.delete_calls = []

    def list_object_versions(self, **kwargs):
        self.list_calls.append(kwargs)

        if self.list_error is not None:
            raise self.list_error

        prefix = kwargs["Prefix"]

        matching = [entry for entry in self.entries if entry["Key"].startswith(prefix)]

        return {
            "Versions": [
                {
                    "Key": entry["Key"],
                    "VersionId": entry["VersionId"],
                }
                for entry in matching
                if not entry.get("DeleteMarker", False)
            ],
            "DeleteMarkers": [
                {
                    "Key": entry["Key"],
                    "VersionId": entry["VersionId"],
                }
                for entry in matching
                if entry.get("DeleteMarker", False)
            ],
            "IsTruncated": False,
        }

    def delete_objects(self, **kwargs):
        self.delete_calls.append(kwargs)

        if self.delete_error is not None:
            raise self.delete_error

        requested = kwargs["Delete"]["Objects"]

        for target in requested:
            self.entries = [
                entry
                for entry in self.entries
                if not (
                    entry["Key"] == target["Key"]
                    and entry["VersionId"] == target["VersionId"]
                )
            ]

        return {
            "Deleted": requested,
            "Errors": [],
        }


def make_s3_entries(object_key):
    return [
        {
            "Key": object_key,
            "VersionId": ACCEPTED_VERSION_ID,
        },
        {
            "Key": object_key,
            "VersionId": EXTRA_VERSION_ID,
        },
        {
            "Key": object_key,
            "VersionId": DELETE_MARKER_ID,
            "DeleteMarker": True,
        },
        {
            "Key": object_key + "-lookalike",
            "VersionId": "unrelated-version",
        },
    ]


def test_hygiene_gsi_projects_all_required_attributes(
    dynamodb_local,
):
    document = make_uploaded_document()
    seed_document(dynamodb_local, document)

    projected = wait_for_hygiene_index(
        make_low_level_client(),
        document,
    )

    assert projected["tenant_id"]["S"] == TENANT_ID
    assert projected["submission_id"]["S"] == SUBMISSION_ID
    assert projected["document_id"]["S"] == DOCUMENT_ID
    assert projected["object_key"]["S"] == document["object_key"]
    assert projected["status"]["S"] == "UPLOADED"

    assert projected["version_id"]["S"] == ACCEPTED_VERSION_ID
    assert (
        projected["upload_url_expires_at"]["S"] == (document["upload_url_expires_at"])
    )
    assert projected["upload_hygiene_after"]["S"] == (document["upload_hygiene_after"])


def test_hygiene_query_finds_and_processes_eligible_document(
    dynamodb_local,
):
    document = make_uploaded_document()
    seed_document(dynamodb_local, document)

    wait_for_hygiene_index(
        make_low_level_client(),
        document,
    )

    s3 = FakeS3(
        entries=[
            {
                "Key": document["object_key"],
                "VersionId": ACCEPTED_VERSION_ID,
            }
        ]
    )

    result = handler_module.query_hygiene_shard(
        make_low_level_client(),
        s3,
        CONFIG,
        handler_module.get_document_hygiene_shard(
            DOCUMENT_ID,
            SHARD_COUNT,
        ),
        CONFIG["max_items"],
        datetime.now(UTC).replace(microsecond=0),
    )

    assert result["processed"] == 1
    assert result["cleaned"] == 1
    assert result["invalid"] == 0
    assert result["failed"] == 0

    stored = read_document(dynamodb_local)

    assert stored["status"] == "UPLOADED"
    assert stored["version_id"] == ACCEPTED_VERSION_ID
    assert "GSI3PK" not in stored
    assert "GSI3SK" not in stored


def test_successful_hygiene_preserves_accepted_version_and_document(
    dynamodb_local,
):
    document = make_uploaded_document()
    seed_document(dynamodb_local, document)

    wait_for_hygiene_index(
        make_low_level_client(),
        document,
    )

    s3 = FakeS3(
        entries=make_s3_entries(document["object_key"]),
    )

    result = handler_module.run_document_version_hygiene(
        make_low_level_client(),
        s3,
        CONFIG,
        datetime.now(UTC).replace(microsecond=0),
    )

    assert result["processed"] == 1
    assert result["cleaned"] == 1
    assert result["failed"] == 0
    assert result["invalid"] == 0

    remaining = [
        entry for entry in s3.entries if entry["Key"] == document["object_key"]
    ]

    assert remaining == [
        {
            "Key": document["object_key"],
            "VersionId": ACCEPTED_VERSION_ID,
        }
    ]

    lookalikes = [
        entry for entry in s3.entries if entry["Key"] != document["object_key"]
    ]

    assert len(lookalikes) == 1
    assert lookalikes[0]["VersionId"] == "unrelated-version"

    stored = read_document(dynamodb_local)

    assert stored is not None
    assert stored["status"] == "UPLOADED"
    assert stored["version_id"] == ACCEPTED_VERSION_ID
    assert stored["object_key"] == document["object_key"]
    assert stored["expires_at"] == document["expires_at"]
    assert stored["upload_url_expires_at"] == (document["upload_url_expires_at"])
    assert stored["upload_hygiene_after"] == (document["upload_hygiene_after"])

    assert "GSI3PK" not in stored
    assert "GSI3SK" not in stored

    query = make_low_level_client().query(
        TableName=TABLE_NAME,
        IndexName=INDEX_NAME,
        KeyConditionExpression="GSI3PK = :pk",
        ExpressionAttributeValues={
            ":pk": {"S": document["GSI3PK"]},
        },
    )

    returned_ids = {item["document_id"]["S"] for item in query.get("Items", [])}

    assert DOCUMENT_ID not in returned_ids


def test_missing_accepted_version_fails_closed(
    dynamodb_local,
):
    document = make_uploaded_document()
    seed_document(dynamodb_local, document)

    wait_for_hygiene_index(
        make_low_level_client(),
        document,
    )

    s3 = FakeS3(
        entries=[
            {
                "Key": document["object_key"],
                "VersionId": EXTRA_VERSION_ID,
            },
        ]
    )

    result = handler_module.run_document_version_hygiene(
        make_low_level_client(),
        s3,
        CONFIG,
        datetime.now(UTC).replace(microsecond=0),
    )

    assert result["failed"] == 1
    assert s3.delete_calls == []

    stored = read_document(dynamodb_local)

    assert stored["status"] == "UPLOADED"
    assert stored["version_id"] == ACCEPTED_VERSION_ID
    assert stored["GSI3PK"] == document["GSI3PK"]
    assert stored["GSI3SK"] == document["GSI3SK"]


def test_s3_listing_failure_preserves_hygiene_index(
    dynamodb_local,
):
    document = make_uploaded_document()
    seed_document(dynamodb_local, document)

    wait_for_hygiene_index(
        make_low_level_client(),
        document,
    )

    s3 = FakeS3(
        list_error=make_client_error(
            "AccessDenied",
            "ListObjectVersions",
        )
    )

    result = handler_module.run_document_version_hygiene(
        make_low_level_client(),
        s3,
        CONFIG,
        datetime.now(UTC).replace(microsecond=0),
    )

    assert result["failed"] == 1

    stored = read_document(dynamodb_local)

    assert stored["GSI3PK"] == document["GSI3PK"]
    assert stored["GSI3SK"] == document["GSI3SK"]


def test_s3_deletion_failure_preserves_hygiene_index(
    dynamodb_local,
):
    document = make_uploaded_document()
    seed_document(dynamodb_local, document)

    wait_for_hygiene_index(
        make_low_level_client(),
        document,
    )

    s3 = FakeS3(
        entries=make_s3_entries(document["object_key"]),
        delete_error=make_client_error(
            "AccessDenied",
            "DeleteObjects",
        ),
    )

    result = handler_module.run_document_version_hygiene(
        make_low_level_client(),
        s3,
        CONFIG,
        datetime.now(UTC).replace(microsecond=0),
    )

    assert result["failed"] == 1

    stored = read_document(dynamodb_local)

    assert stored["GSI3PK"] == document["GSI3PK"]
    assert stored["GSI3SK"] == document["GSI3SK"]
    assert stored["version_id"] == ACCEPTED_VERSION_ID


def test_conditional_update_rejects_changed_document(
    dynamodb_local,
):
    document = make_uploaded_document()
    seed_document(dynamodb_local, document)

    wait_for_hygiene_index(
        make_low_level_client(),
        document,
    )

    now = datetime.now(UTC).replace(microsecond=0)

    candidate = handler_module.validate_candidate(
        make_low_level_client().get_item(
            TableName=TABLE_NAME,
            Key={
                "PK": {"S": document["PK"]},
                "SK": {"S": document["SK"]},
            },
            ConsistentRead=True,
        )["Item"],
        handler_module.get_document_hygiene_shard(
            DOCUMENT_ID,
            SHARD_COUNT,
        ),
        SHARD_COUNT,
        now,
    )

    dynamodb_local.Table(TABLE_NAME).update_item(
        Key={
            "PK": document["PK"],
            "SK": document["SK"],
        },
        UpdateExpression="SET object_key = :changed",
        ExpressionAttributeValues={
            ":changed": document["object_key"] + "-changed",
        },
    )

    result = handler_module.remove_hygiene_index(
        make_low_level_client(),
        TABLE_NAME,
        candidate,
    )

    assert result is False

    stored = read_document(dynamodb_local)

    assert stored["object_key"] == document["object_key"] + "-changed"
    assert stored["GSI3PK"] == document["GSI3PK"]
    assert stored["GSI3SK"] == document["GSI3SK"]


def test_invalid_uploaded_document_is_not_modified(
    dynamodb_local,
):
    document = make_uploaded_document()
    document["version_id"] = "null"

    seed_document(dynamodb_local, document)

    wait_for_hygiene_index(
        make_low_level_client(),
        document,
    )

    result = handler_module.run_document_version_hygiene(
        make_low_level_client(),
        FakeS3(),
        CONFIG,
        datetime.now(UTC).replace(microsecond=0),
    )

    assert result["processed"] == 1
    assert result["invalid"] == 1
    assert result["cleaned"] == 0

    stored = read_document(dynamodb_local)

    assert stored["version_id"] == "null"
    assert stored["GSI3PK"] == document["GSI3PK"]
    assert stored["GSI3SK"] == document["GSI3SK"]
