import boto3
import pytest
from botocore.stub import Stubber

from app.core.config import Settings
from app.repositories.submission import (
    DynamoDBSubmissionRepository,
    SubmissionAlreadyExistsError,
)


@pytest.fixture
def dynamodb_stubber(monkeypatch):
    session = boto3.Session(
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        region_name="ap-south-1",
    )

    dynamodb = session.resource("dynamodb")
    client = dynamodb.meta.client

    stubber = Stubber(client)
    stubber.activate()

    monkeypatch.setattr(
        "app.repositories.submission.boto3.resource",
        lambda *service_name, **kwargs: dynamodb,
    )

    yield stubber

    stubber.deactivate()


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        aws_region="ap-south-1",
        submissions_table_name="cloudsec-submissions-dev",
    )


@pytest.fixture
def submission():
    return {
        "PK": "TENANT#tenant-a",
        "SK": "SUBMISSION#submission-123",
        "GSI1PK": "TENANT#tenant-a#USER#user-123",
        "GSI1SK": (
            "CREATED#2026-11-12T10:00:00Z#TENANT#tenant-a#SUBMISSION#submission-123"
        ),
        "GSI2PK": "TENANT#tenant-a#STATUS#DRAFT",
        "GSI2SK": ("CREATED#2026-11-12T10:00:00Z#SUBMISSION#submission-123"),
        "entity_type": "SUBMISSION",
        "tenant_id": "tenant-a",
        "submission_id": "submission-123",
        "owner_id": "user-123",
        "title": "Vendor Onboarding",
        "description": None,
        "status": "DRAFT",
        "created_at": "2026-11-12T10:00:00Z",
        "updated_at": "2026-11-12T10:00:00Z",
        "version": 1,
    }


def expected_put_params(submission):
    return {
        "TableName": "cloudsec-submissions-dev",
        "Item": submission,
        "ConditionExpression": (
            "attribute_not_exists(PK) AND attribute_not_exists(SK)"
        ),
    }


def test_create_submission_writes_expected_item(
    dynamodb_stubber,
    settings,
    submission,
):
    repository = DynamoDBSubmissionRepository(settings)

    dynamodb_stubber.add_response(
        "put_item",
        {},
        expected_put_params(submission),
    )

    repository.create_submission(submission)

    dynamodb_stubber.assert_no_pending_responses()


def test_create_submission_rejects_existing_record(
    dynamodb_stubber,
    settings,
    submission,
):
    repository = DynamoDBSubmissionRepository(settings)

    dynamodb_stubber.add_client_error(
        "put_item",
        service_error_code="ConditionalCheckFailedException",
        service_message="The conditional request failed",
        expected_params=expected_put_params(submission),
    )

    with pytest.raises(SubmissionAlreadyExistsError):
        repository.create_submission(submission)

    dynamodb_stubber.assert_no_pending_responses()
