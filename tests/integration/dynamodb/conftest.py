import os

import boto3
import pytest

from app.core.config import Settings
from app.repositories.audit import DynamoDBAuditRepository
from app.repositories.document import DynamoDBDocumentRepository
from app.repositories.membership import DynamoDBMembershipRepository
from app.repositories.submission import DynamoDBSubmissionRepository

DYNAMODB_ENDPOINT = "http://127.0.0.1:8000"

SUBMISSIONS_TABLE = "cloudsec-test-submissions"
MEMBERSHIPS_TABLE = "cloudsec-test-memberships"
AUDIT_TABLE = "cloudsec-test-audit-events"

TEST_TABLES = [
    SUBMISSIONS_TABLE,
    MEMBERSHIPS_TABLE,
    AUDIT_TABLE,
]


@pytest.fixture(scope="session")
def dynamodb_local():
    previous_environment = {
        key: os.environ.get(key)
        for key in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_DEFAULT_REGION",
            "AWS_EC2_METADATA_DISABLED",
        )
    }

    os.environ["AWS_ACCESS_KEY_ID"] = "local"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "local"
    os.environ["AWS_DEFAULT_REGION"] = "ap-south-1"
    os.environ["AWS_EC2_METADATA_DISABLED"] = "true"

    dynamodb = boto3.resource(
        "dynamodb",
        region_name="ap-south-1",
        endpoint_url=DYNAMODB_ENDPOINT,
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )

    client = dynamodb.meta.client

    try:
        client.list_tables()
    except Exception as exc:
        raise RuntimeError(
            "DynamoDB Local is unavailable. "
            "Start the cloudsec-dynamodb-local Docker container "
            "and verify that port 8000 is accessible."
        ) from exc

    existing_tables = client.list_tables()["TableNames"]

    for table_name in TEST_TABLES:
        if table_name in existing_tables:
            client.delete_table(TableName=table_name)
            client.get_waiter("table_not_exists").wait(TableName=table_name)

    client.create_table(
        TableName=SUBMISSIONS_TABLE,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
            {"AttributeName": "GSI2PK", "AttributeType": "S"},
            {"AttributeName": "GSI2SK", "AttributeType": "S"},
            {"AttributeName": "GSI3PK", "AttributeType": "S"},
            {"AttributeName": "GSI3SK", "AttributeType": "S"},
            {"AttributeName": "GSI4PK", "AttributeType": "S"},
            {"AttributeName": "GSI4SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "OwnerIndex",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {
                    "ProjectionType": "INCLUDE",
                    "NonKeyAttributes": [
                        "tenant_id",
                        "submission_id",
                        "owner_id",
                        "status",
                        "created_at",
                        "updated_at",
                        "version",
                        "title",
                    ],
                },
            },
            {
                "IndexName": "TenantStatusIndex",
                "KeySchema": [
                    {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                ],
                "Projection": {
                    "ProjectionType": "INCLUDE",
                    "NonKeyAttributes": [
                        "tenant_id",
                        "submission_id",
                        "owner_id",
                        "status",
                        "created_at",
                        "updated_at",
                        "version",
                        "title",
                    ],
                },
            },
            {
                "IndexName": "PendingDocumentExpiryIndex",
                "KeySchema": [
                    {"AttributeName": "GSI3PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI3SK", "KeyType": "RANGE"},
                ],
                "Projection": {
                    "ProjectionType": "INCLUDE",
                    "NonKeyAttributes": [
                        "tenant_id",
                        "entity_type",
                        "submission_id",
                        "document_id",
                        "object_key",
                        "size_bytes",
                        "expires_at",
                        "status",
                        "version_id",
                        "upload_url_expires_at",
                        "upload_hygiene_after",
                    ],
                },
            },
            {
                "IndexName": "PendingDocumentCleanupIndex",
                "KeySchema": [
                    {"AttributeName": "GSI4PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI4SK", "KeyType": "RANGE"},
                ],
                "Projection": {
                    "ProjectionType": "INCLUDE",
                    "NonKeyAttributes": [
                        "tenant_id",
                        "submission_id",
                        "document_id",
                        "object_key",
                        "expires_at",
                        "cleanup_after",
                        "cleanup_attempts",
                        "cleanup_completed_at",
                        "finalize_after",
                        "status",
                    ],
                },
            },
        ],
    )

    client.create_table(
        TableName=MEMBERSHIPS_TABLE,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "TenantMembersIndex",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {
                    "ProjectionType": "INCLUDE",
                    "NonKeyAttributes": [
                        "user_id",
                        "tenant_id",
                        "role",
                        "status",
                        "created_at",
                    ],
                },
            }
        ],
    )

    client.create_table(
        TableName=AUDIT_TABLE,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "TenantAuditIndex",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )

    for table_name in TEST_TABLES:
        client.get_waiter("table_exists").wait(TableName=table_name)

    try:
        yield dynamodb
    finally:
        for table_name in TEST_TABLES:
            try:
                client.delete_table(TableName=table_name)
            except client.exceptions.ResourceNotFoundException:
                pass

        for key, value in previous_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture(autouse=True)
def isolate_dynamodb_test_data(dynamodb_local):
    for table_name in TEST_TABLES:
        table = dynamodb_local.Table(table_name)

        scan_kwargs = {
            "ProjectionExpression": "#pk, #sk",
            "ExpressionAttributeNames": {
                "#pk": "PK",
                "#sk": "SK",
            },
        }

        while True:
            response = table.scan(**scan_kwargs)

            with table.batch_writer() as batch:
                for item in response["Items"]:
                    batch.delete_item(
                        Key={
                            "PK": item["PK"],
                            "SK": item["SK"],
                        }
                    )

            last_evaluated_key = response.get("LastEvaluatedKey")

            if not last_evaluated_key:
                break

            scan_kwargs["ExclusiveStartKey"] = last_evaluated_key

    yield


@pytest.fixture
def dynamodb_settings():
    return Settings(
        aws_region="ap-south-1",
        dynamodb_endpoint_url=DYNAMODB_ENDPOINT,
        submissions_table_name=SUBMISSIONS_TABLE,
        memberships_table_name=MEMBERSHIPS_TABLE,
        audit_events_table_name=AUDIT_TABLE,
    )


@pytest.fixture
def dynamodb_repositories(
    dynamodb_local,
    dynamodb_settings,
):
    return {
        "submissions": DynamoDBSubmissionRepository(dynamodb_settings),
        "documents": DynamoDBDocumentRepository(dynamodb_settings),
        "memberships": DynamoDBMembershipRepository(dynamodb_settings),
        "audit": DynamoDBAuditRepository(dynamodb_settings),
    }


@pytest.fixture
def submission_factory():
    def create_submission(
        tenant_id="tenant-a",
        submission_id="submission-001",
        owner_id="user-a",
        status="DRAFT",
        version=1,
        total_document_count=0,
        total_document_bytes=0,
        pending_document_count=0,
        pending_document_bytes=0,
        uploaded_document_count=0,
        uploaded_document_bytes=0,
        created_at="2026-11-12T10:00:00Z",
    ):
        return {
            "PK": f"TENANT#{tenant_id}",
            "SK": f"SUBMISSION#{submission_id}",
            "entity_type": "SUBMISSION",
            "tenant_id": tenant_id,
            "submission_id": submission_id,
            "owner_id": owner_id,
            "title": f"Assessment {submission_id}",
            "status": status,
            "created_at": created_at,
            "updated_at": created_at,
            "version": version,
            "total_document_count": total_document_count,
            "total_document_bytes": total_document_bytes,
            "pending_document_count": pending_document_count,
            "pending_document_bytes": pending_document_bytes,
            "uploaded_document_count": uploaded_document_count,
            "uploaded_document_bytes": uploaded_document_bytes,
            "GSI1PK": f"TENANT#{tenant_id}#USER#{owner_id}",
            "GSI1SK": (
                f"CREATED#{created_at}#TENANT#{tenant_id}#SUBMISSION#{submission_id}"
            ),
            "GSI2PK": f"TENANT#{tenant_id}#STATUS#{status}",
            "GSI2SK": (f"CREATED#{created_at}#SUBMISSION#{submission_id}"),
        }

    return create_submission
