from unittest.mock import MagicMock

import pytest

from app.repositories.audit import DynamoDBAuditRepository


@pytest.fixture
def repository():
    repo = DynamoDBAuditRepository.__new__(DynamoDBAuditRepository)

    repo.table = MagicMock()

    return repo


def test_query_uses_tenant_and_submission_partition(repository):
    repository.list_submission_events(
        tenant_id="tenant-a",
        submission_id="submission-123",
        limit=20,
    )

    repository.table.query.assert_called_once()

    params = repository.table.query.call_args.kwargs

    assert params["Limit"] == 20
    assert params["ScanIndexForward"] is False
    assert "ExclusiveStartKey" not in params

    expression = params["KeyConditionExpression"].get_expression()

    assert expression["operator"] == "AND"
    assert len(expression["values"]) == 2

    partition_condition, sort_condition = expression["values"]

    partition_expression = partition_condition.get_expression()
    sort_expression = sort_condition.get_expression()

    assert partition_expression["values"][0].name == "PK"
    assert partition_expression["values"][1] == (
        "TENANT#tenant-a#SUBMISSION#submission-123"
    )

    assert sort_expression["values"][0].name == "SK"
    assert sort_expression["values"][1] == "EVENT#"


def test_query_uses_pagination_cursor(repository):
    cursor = {
        "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
        "SK": "EVENT#2026-11-12T12:00:00Z#event-123",
    }

    repository.list_submission_events(
        tenant_id="tenant-a",
        submission_id="submission-123",
        limit=10,
        cursor=cursor,
    )

    params = repository.table.query.call_args.kwargs

    assert params["ExclusiveStartKey"] == cursor
    assert params["Limit"] == 10
    assert params["ScanIndexForward"] is False


def test_query_returns_dynamodb_response(repository):
    expected = {
        "Items": [
            {
                "event_id": "event-123",
                "event_type": "SUBMISSION_STATUS_CHANGED",
            }
        ]
    }

    repository.table.query.return_value = expected

    result = repository.list_submission_events(
        tenant_id="tenant-a",
        submission_id="submission-123",
        limit=20,
    )

    assert result == expected


def test_tenant_query_uses_tenant_audit_index(repository):
    repository.list_tenant_events(
        tenant_id="tenant-a",
        limit=20,
    )

    repository.table.query.assert_called_once()

    params = repository.table.query.call_args.kwargs

    assert params["IndexName"] == "TenantAuditIndex"
    assert params["Limit"] == 20
    assert params["ScanIndexForward"] is False
    assert "ExclusiveStartKey" not in params

    expression = params["KeyConditionExpression"].get_expression()

    assert expression["operator"] == "AND"

    partition_condition, sort_condition = expression["values"]

    partition_expression = partition_condition.get_expression()
    sort_expression = sort_condition.get_expression()

    assert partition_expression["values"][0].name == "GSI1PK"
    assert partition_expression["values"][1] == "TENANT#tenant-a"

    assert sort_expression["values"][0].name == "GSI1SK"
    assert sort_expression["values"][1] == "EVENT#"


def test_tenant_query_uses_pagination_cursor(repository):
    cursor = {
        "PK": "TENANT#tenant-a#MEMBERSHIP#user-b",
        "SK": "EVENT#2026-11-17T12:00:00Z#event-123",
        "GSI1PK": "TENANT#tenant-a",
        "GSI1SK": "EVENT#2026-11-17T12:00:00Z#event-123",
    }

    repository.list_tenant_events(
        tenant_id="tenant-a",
        limit=10,
        cursor=cursor,
    )

    params = repository.table.query.call_args.kwargs

    assert params["IndexName"] == "TenantAuditIndex"
    assert params["ExclusiveStartKey"] == cursor
    assert params["Limit"] == 10
    assert params["ScanIndexForward"] is False


def test_tenant_query_returns_dynamodb_response(repository):
    expected = {
        "Items": [
            {
                "event_id": "event-123",
                "event_type": "MEMBERSHIP_ROLE_CHANGED",
            }
        ]
    }

    repository.table.query.return_value = expected

    result = repository.list_tenant_events(
        tenant_id="tenant-a",
        limit=20,
    )

    assert result == expected
