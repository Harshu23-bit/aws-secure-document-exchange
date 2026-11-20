from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.repositories.submission import DynamoDBSubmissionRepository


@pytest.fixture
def repository(monkeypatch):
    table = MagicMock()
    dynamodb = SimpleNamespace(Table=MagicMock(return_value=table))

    monkeypatch.setattr(
        "app.repositories.submission.boto3.resource",
        lambda *args, **kwargs: dynamodb,
    )

    settings = Settings(
        aws_region="ap-south-1",
        submissions_table_name="cloudsec-submissions-dev",
    )

    repo = DynamoDBSubmissionRepository(settings)
    return repo, table


def test_submitter_query_uses_owner_index(repository):
    repo, table = repository
    table.query.return_value = {"Items": []}

    result = repo.list_submitter_submissions(
        tenant_id="tenant-a",
        user_id="user-123",
        limit=20,
    )

    assert result == {"Items": []}

    params = table.query.call_args.kwargs
    condition = params["KeyConditionExpression"].get_expression()

    assert params["IndexName"] == "OwnerIndex"
    assert params["Limit"] == 20
    assert params["ScanIndexForward"] is False
    assert condition["values"][1] == "TENANT#tenant-a#USER#user-123"


def test_submitter_query_uses_pagination_cursor(repository):
    repo, table = repository
    table.query.return_value = {"Items": []}

    cursor = {
        "PK": "TENANT#tenant-a",
        "SK": "SUBMISSION#submission-123",
        "GSI1PK": "TENANT#tenant-a#USER#user-123",
        "GSI1SK": (
            "CREATED#2026-11-12T10:00:00Z#TENANT#tenant-a#SUBMISSION#submission-123"
        ),
    }

    repo.list_submitter_submissions(
        tenant_id="tenant-a",
        user_id="user-123",
        limit=10,
        cursor=cursor,
    )

    params = table.query.call_args.kwargs

    assert params["ExclusiveStartKey"] == cursor
    assert params["Limit"] == 10
    assert params["IndexName"] == "OwnerIndex"


def test_reviewer_query_is_tenant_scoped(repository):
    repo, table = repository
    table.query.return_value = {"Items": []}

    result = repo.list_reviewer_submissions(
        tenant_id="tenant-a",
        limit=20,
    )

    assert result == {"Items": []}

    params = table.query.call_args.kwargs
    condition = params["KeyConditionExpression"].get_expression()

    partition_condition = condition["values"][0].get_expression()
    sort_condition = condition["values"][1].get_expression()

    assert partition_condition["values"][1] == "TENANT#tenant-a"
    assert sort_condition["values"][1] == "SUBMISSION#"
    assert params["Limit"] == 20
    assert params["ScanIndexForward"] is False
    assert "IndexName" not in params


def test_reviewer_query_uses_pagination_cursor(repository):
    repo, table = repository
    table.query.return_value = {"Items": []}

    cursor = {
        "PK": "TENANT#tenant-a",
        "SK": "SUBMISSION#submission-123",
    }

    repo.list_reviewer_submissions(
        tenant_id="tenant-a",
        limit=10,
        cursor=cursor,
    )

    params = table.query.call_args.kwargs

    assert params["ExclusiveStartKey"] == cursor
    assert params["Limit"] == 10


def test_submitter_query_returns_pagination_key(repository):
    repo, table = repository

    last_key = {
        "PK": "TENANT#tenant-a",
        "SK": "SUBMISSION#submission-123",
        "GSI1PK": "TENANT#tenant-a#USER#user-123",
        "GSI1SK": (
            "CREATED#2026-11-12T10:00:00Z#TENANT#tenant-a#SUBMISSION#submission-123"
        ),
    }

    table.query.return_value = {
        "Items": [],
        "LastEvaluatedKey": last_key,
    }

    result = repo.list_submitter_submissions(
        tenant_id="tenant-a",
        user_id="user-123",
        limit=1,
    )

    assert result["LastEvaluatedKey"] == last_key
