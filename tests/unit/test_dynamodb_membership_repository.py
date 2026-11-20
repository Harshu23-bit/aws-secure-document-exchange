from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from app.repositories.membership import (
    DynamoDBMembershipRepository,
    MembershipActorAuthorizationError,
    MembershipStateConflictError,
)


@pytest.fixture
def repository(monkeypatch):
    table = MagicMock()
    table.name = "cloudsec-test-memberships"

    dynamodb = SimpleNamespace(Table=MagicMock(return_value=table))

    monkeypatch.setattr(
        "app.repositories.membership.boto3.resource",
        MagicMock(return_value=dynamodb),
    )

    settings = SimpleNamespace(
        aws_region="ap-south-1",
        memberships_table_name="cloudsec-test-memberships",
        audit_events_table_name="cloudsec-test-audit-events",
        dynamodb_endpoint_url=None,
    )

    return DynamoDBMembershipRepository(settings), table


@pytest.fixture
def audit_event():
    return {
        "PK": "TENANT#tenant-a#MEMBERSHIP#user-b",
        "SK": "EVENT#2026-11-17T12:00:00Z#event-123",
        "entity_type": "AUDIT_EVENT",
        "event_id": "event-123",
        "event_type": "MEMBERSHIP_ROLE_CHANGED",
        "tenant_id": "tenant-a",
        "target_user_id": "user-b",
        "actor_id": "admin-a",
        "actor_role": "TENANT_ADMIN",
        "previous_role": "SUBMITTER",
        "new_role": "REVIEWER",
        "timestamp": "2026-11-17T12:00:00Z",
        "request_id": "request-123",
    }


def make_client_error(code, cancellation_reasons=None):
    response = {
        "Error": {
            "Code": code,
            "Message": "Test error",
        }
    }

    if cancellation_reasons is not None:
        response["CancellationReasons"] = cancellation_reasons

    return ClientError(response, "TransactWriteItems")


def test_change_member_role_uses_atomic_transaction(
    repository,
    audit_event,
):
    repo, table = repository

    repo.change_member_role(
        tenant_id="tenant-a",
        actor_id="admin-a",
        target_user_id="user-b",
        expected_role="SUBMITTER",
        new_role="REVIEWER",
        updated_at="2026-11-17T12:00:00Z",
        audit_event=audit_event,
    )

    client = table.meta.client
    client.transact_write_items.assert_called_once()

    transactions = client.transact_write_items.call_args.kwargs["TransactItems"]

    assert len(transactions) == 3

    actor_check = transactions[0]["ConditionCheck"]

    assert actor_check["TableName"] == table.name
    assert actor_check["Key"] == {
        "PK": "USER#admin-a",
        "SK": "TENANT#tenant-a",
    }
    assert "#role = :tenant_admin" in actor_check["ConditionExpression"]
    assert "#status = :active" in actor_check["ConditionExpression"]
    assert "user_id = :actor_id" in actor_check["ConditionExpression"]
    assert "tenant_id = :tenant_id" in actor_check["ConditionExpression"]

    assert actor_check["ExpressionAttributeValues"] == {
        ":tenant_admin": "TENANT_ADMIN",
        ":active": "ACTIVE",
        ":actor_id": "admin-a",
        ":tenant_id": "tenant-a",
    }

    update = transactions[1]["Update"]

    assert update["TableName"] == table.name
    assert update["Key"] == {
        "PK": "USER#user-b",
        "SK": "TENANT#tenant-a",
    }
    assert update["UpdateExpression"] == (
        "SET #role = :new_role, updated_at = :updated_at"
    )
    assert "#role = :expected_role" in update["ConditionExpression"]
    assert "#status = :active" in update["ConditionExpression"]
    assert "user_id = :target_user_id" in update["ConditionExpression"]
    assert "tenant_id = :tenant_id" in update["ConditionExpression"]

    assert update["ExpressionAttributeValues"] == {
        ":expected_role": "SUBMITTER",
        ":active": "ACTIVE",
        ":target_user_id": "user-b",
        ":tenant_id": "tenant-a",
        ":new_role": "REVIEWER",
        ":updated_at": "2026-11-17T12:00:00Z",
    }

    put = transactions[2]["Put"]

    assert put["TableName"] == "cloudsec-test-audit-events"
    assert put["Item"] == audit_event
    assert put["ConditionExpression"] == (
        "attribute_not_exists(PK) AND attribute_not_exists(SK)"
    )


def test_deactivate_member_uses_atomic_transaction(
    repository,
    audit_event,
):
    repo, table = repository

    repo.deactivate_member(
        tenant_id="tenant-a",
        actor_id="admin-a",
        target_user_id="user-b",
        expected_role="REVIEWER",
        updated_at="2026-11-17T12:05:00Z",
        audit_event=audit_event,
    )

    transactions = table.meta.client.transact_write_items.call_args.kwargs[
        "TransactItems"
    ]

    assert len(transactions) == 3

    update = transactions[1]["Update"]

    assert update["UpdateExpression"] == (
        "SET #status = :inactive, updated_at = :updated_at"
    )

    assert update["ExpressionAttributeValues"] == {
        ":expected_role": "REVIEWER",
        ":active": "ACTIVE",
        ":target_user_id": "user-b",
        ":tenant_id": "tenant-a",
        ":inactive": "INACTIVE",
        ":updated_at": "2026-11-17T12:05:00Z",
    }


@pytest.mark.parametrize(
    ("operation", "kwargs"),
    [
        (
            "change_member_role",
            {
                "expected_role": "SUBMITTER",
                "new_role": "REVIEWER",
            },
        ),
        (
            "deactivate_member",
            {
                "expected_role": "SUBMITTER",
            },
        ),
    ],
)
def test_membership_operations_reject_self_modification(
    repository,
    audit_event,
    operation,
    kwargs,
):
    repo, table = repository

    arguments = {
        "tenant_id": "tenant-a",
        "actor_id": "same-user",
        "target_user_id": "same-user",
        "updated_at": "2026-11-17T12:00:00Z",
        "audit_event": audit_event,
        **kwargs,
    }

    with pytest.raises(MembershipActorAuthorizationError):
        getattr(repo, operation)(**arguments)

    table.meta.client.transact_write_items.assert_not_called()


@pytest.mark.parametrize(
    ("expected_role", "new_role"),
    [
        ("TENANT_ADMIN", "SUBMITTER"),
        ("SUBMITTER", "TENANT_ADMIN"),
        ("INVALID", "REVIEWER"),
        ("SUBMITTER", "INVALID"),
        ("SUBMITTER", "SUBMITTER"),
    ],
)
def test_change_member_role_rejects_invalid_role_changes(
    repository,
    audit_event,
    expected_role,
    new_role,
):
    repo, table = repository

    with pytest.raises(ValueError):
        repo.change_member_role(
            tenant_id="tenant-a",
            actor_id="admin-a",
            target_user_id="user-b",
            expected_role=expected_role,
            new_role=new_role,
            updated_at="2026-11-17T12:00:00Z",
            audit_event=audit_event,
        )

    table.meta.client.transact_write_items.assert_not_called()


def test_deactivate_member_rejects_tenant_admin_target(
    repository,
    audit_event,
):
    repo, table = repository

    with pytest.raises(ValueError):
        repo.deactivate_member(
            tenant_id="tenant-a",
            actor_id="admin-a",
            target_user_id="user-b",
            expected_role="TENANT_ADMIN",
            updated_at="2026-11-17T12:00:00Z",
            audit_event=audit_event,
        )

    table.meta.client.transact_write_items.assert_not_called()


def test_actor_condition_failure_becomes_authorization_error(
    repository,
    audit_event,
):
    repo, table = repository

    table.meta.client.transact_write_items.side_effect = make_client_error(
        "TransactionCanceledException",
        [
            {"Code": "ConditionalCheckFailed"},
            {"Code": "None"},
            {"Code": "None"},
        ],
    )

    with pytest.raises(MembershipActorAuthorizationError):
        repo.change_member_role(
            tenant_id="tenant-a",
            actor_id="admin-a",
            target_user_id="user-b",
            expected_role="SUBMITTER",
            new_role="REVIEWER",
            updated_at="2026-11-17T12:00:00Z",
            audit_event=audit_event,
        )


def test_target_condition_failure_becomes_conflict(
    repository,
    audit_event,
):
    repo, table = repository

    table.meta.client.transact_write_items.side_effect = make_client_error(
        "TransactionCanceledException",
        [
            {"Code": "None"},
            {"Code": "ConditionalCheckFailed"},
            {"Code": "None"},
        ],
    )

    with pytest.raises(MembershipStateConflictError):
        repo.change_member_role(
            tenant_id="tenant-a",
            actor_id="admin-a",
            target_user_id="user-b",
            expected_role="SUBMITTER",
            new_role="REVIEWER",
            updated_at="2026-11-17T12:00:00Z",
            audit_event=audit_event,
        )


def test_audit_condition_failure_becomes_conflict(
    repository,
    audit_event,
):
    repo, table = repository

    table.meta.client.transact_write_items.side_effect = make_client_error(
        "TransactionCanceledException",
        [
            {"Code": "None"},
            {"Code": "None"},
            {"Code": "ConditionalCheckFailed"},
        ],
    )

    with pytest.raises(MembershipStateConflictError):
        repo.change_member_role(
            tenant_id="tenant-a",
            actor_id="admin-a",
            target_user_id="user-b",
            expected_role="SUBMITTER",
            new_role="REVIEWER",
            updated_at="2026-11-17T12:00:00Z",
            audit_event=audit_event,
        )


def test_unclassified_transaction_error_propagates(
    repository,
    audit_event,
):
    repo, table = repository

    table.meta.client.transact_write_items.side_effect = make_client_error(
        "TransactionConflictException"
    )

    with pytest.raises(ClientError):
        repo.change_member_role(
            tenant_id="tenant-a",
            actor_id="admin-a",
            target_user_id="user-b",
            expected_role="SUBMITTER",
            new_role="REVIEWER",
            updated_at="2026-11-17T12:00:00Z",
            audit_event=audit_event,
        )
