from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from app.repositories.submission import (
    DynamoDBSubmissionRepository,
    SubmissionActorAuthorizationError,
    SubmissionStateConflictError,
)


@pytest.fixture
def repository():
    repo = DynamoDBSubmissionRepository.__new__(DynamoDBSubmissionRepository)

    repo.table = MagicMock()
    repo.table.name = "cloudsec-submissions-dev"

    repo.client = repo.table.meta.client
    repo.audit_table_name = "cloudsec-audit-events-dev"
    repo.memberships_table_name = "cloudsec-tenant-memberships-dev"

    return repo


@pytest.fixture
def audit_event():
    return {
        "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
        "SK": "EVENT#2026-11-12T12:00:00Z#event-123",
        "GSI1PK": "TENANT#tenant-a",
        "GSI1SK": "EVENT#2026-11-12T10:00:00Z#event-123",
        "entity_type": "AUDIT_EVENT",
        "event_id": "event-123",
        "event_type": "SUBMISSION_STATUS_CHANGED",
        "tenant_id": "tenant-a",
        "submission_id": "submission-123",
        "actor_id": "user-a",
        "actor_role": "SUBMITTER",
        "previous_status": "DRAFT",
        "new_status": "SUBMITTED",
        "previous_version": 1,
        "new_version": 2,
        "timestamp": "2026-11-12T12:00:00Z",
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


def test_transition_writes_submission_and_audit_atomically(
    repository,
    audit_event,
):
    repository.transition_submission(
        tenant_id="tenant-a",
        submission_id="submission-123",
        previous_status="DRAFT",
        new_status="SUBMITTED",
        expected_version=1,
        updated_at="2026-11-12T12:00:00Z",
        audit_event=audit_event,
        owner_id="user-a",
        require_uploaded_documents=True,
        actor_id="user-a",
        actor_role="SUBMITTER",
    )

    repository.client.transact_write_items.assert_called_once()

    transactions = repository.client.transact_write_items.call_args.kwargs[
        "TransactItems"
    ]

    assert len(transactions) == 3

    update = transactions[0]["Update"]

    assert update["TableName"] == "cloudsec-submissions-dev"

    assert update["Key"] == {
        "PK": "TENANT#tenant-a",
        "SK": "SUBMISSION#submission-123",
    }

    assert update["ExpressionAttributeValues"] == {
        ":previous_status": "DRAFT",
        ":new_status": "SUBMITTED",
        ":expected_version": 1,
        ":next_version": 2,
        ":updated_at": "2026-11-12T12:00:00Z",
        ":gsi2pk": "TENANT#tenant-a#STATUS#SUBMITTED",
        ":owner_id": "user-a",
        ":zero": 0,
        ":one": 1,
    }

    condition = update["ConditionExpression"]

    assert "#status = :previous_status" in condition
    assert "#version = :expected_version" in condition
    assert "owner_id = :owner_id" in condition
    assert "pending_document_count = :zero" in condition
    assert "uploaded_document_count >= :one" in condition

    put = transactions[1]["Put"]

    membership_check = transactions[2]["ConditionCheck"]

    assert membership_check["TableName"] == ("cloudsec-tenant-memberships-dev")

    assert membership_check["Key"] == {
        "PK": "USER#user-a",
        "SK": "TENANT#tenant-a",
    }

    assert membership_check["ExpressionAttributeValues"] == {
        ":actor_role": "SUBMITTER",
        ":active": "ACTIVE",
        ":actor_id": "user-a",
        ":tenant_id": "tenant-a",
    }

    assert put["TableName"] == "cloudsec-audit-events-dev"
    assert put["Item"] == audit_event

    assert put["ConditionExpression"] == (
        "attribute_not_exists(PK) AND attribute_not_exists(SK)"
    )


def test_reviewer_transition_does_not_require_owner(
    repository,
    audit_event,
):
    repository.transition_submission(
        tenant_id="tenant-a",
        submission_id="submission-123",
        previous_status="SUBMITTED",
        new_status="IN_REVIEW",
        expected_version=1,
        updated_at="2026-11-12T12:00:00Z",
        audit_event=audit_event,
        actor_id="reviewer-a",
        actor_role="REVIEWER",
    )

    update = repository.client.transact_write_items.call_args.kwargs["TransactItems"][
        0
    ]["Update"]

    condition = update["ConditionExpression"]
    values = update["ExpressionAttributeValues"]

    assert "owner_id" not in condition
    assert "pending_document_count" not in condition
    assert "uploaded_document_count" not in condition

    assert ":owner_id" not in values
    assert ":zero" not in values
    assert ":one" not in values


def test_conditional_submission_failure_becomes_conflict(
    repository,
    audit_event,
):
    repository.client.transact_write_items.side_effect = make_client_error(
        "TransactionCanceledException",
        [
            {"Code": "ConditionalCheckFailed"},
            {"Code": "None"},
            {"Code": "None"},
        ],
    )

    with pytest.raises(SubmissionStateConflictError):
        repository.transition_submission(
            tenant_id="tenant-a",
            submission_id="submission-123",
            previous_status="DRAFT",
            new_status="SUBMITTED",
            expected_version=1,
            updated_at="2026-11-12T12:00:00Z",
            audit_event=audit_event,
            actor_id="user-a",
            actor_role="SUBMITTER",
        )


def test_audit_event_conditional_failure_becomes_conflict(
    repository,
    audit_event,
):
    repository.client.transact_write_items.side_effect = make_client_error(
        "TransactionCanceledException",
        [
            {"Code": "None"},
            {"Code": "ConditionalCheckFailed"},
            {"Code": "None"},
        ],
    )

    with pytest.raises(SubmissionStateConflictError):
        repository.transition_submission(
            tenant_id="tenant-a",
            submission_id="submission-123",
            previous_status="DRAFT",
            new_status="SUBMITTED",
            expected_version=1,
            updated_at="2026-11-12T12:00:00Z",
            audit_event=audit_event,
            actor_id="user-a",
            actor_role="SUBMITTER",
        )


def test_unclassified_transaction_error_propagates(
    repository,
    audit_event,
):
    repository.client.transact_write_items.side_effect = make_client_error(
        "TransactionConflictException"
    )

    with pytest.raises(ClientError):
        repository.transition_submission(
            tenant_id="tenant-a",
            submission_id="submission-123",
            previous_status="DRAFT",
            new_status="SUBMITTED",
            expected_version=1,
            updated_at="2026-11-12T12:00:00Z",
            audit_event=audit_event,
            actor_id="user-a",
            actor_role="SUBMITTER",
        )


def test_reviewer_transition_checks_active_membership_atomically(
    repository,
    audit_event,
):
    repository.transition_submission(
        tenant_id="tenant-a",
        submission_id="submission-123",
        previous_status="SUBMITTED",
        new_status="IN_REVIEW",
        expected_version=1,
        updated_at="2026-11-12T12:00:00Z",
        audit_event=audit_event,
        actor_id="reviewer-a",
        actor_role="REVIEWER",
    )

    transactions = repository.client.transact_write_items.call_args.kwargs[
        "TransactItems"
    ]

    assert len(transactions) == 3

    check = transactions[2]["ConditionCheck"]

    assert check["TableName"] == "cloudsec-tenant-memberships-dev"
    assert check["Key"] == {
        "PK": "USER#reviewer-a",
        "SK": "TENANT#tenant-a",
    }

    assert check["ExpressionAttributeValues"] == {
        ":actor_role": "REVIEWER",
        ":active": "ACTIVE",
        ":actor_id": "reviewer-a",
        ":tenant_id": "tenant-a",
    }


def test_inactive_reviewer_membership_rejects_transition(
    repository,
    audit_event,
):
    repository.client.transact_write_items.side_effect = make_client_error(
        "TransactionCanceledException",
        [
            {"Code": "None"},
            {"Code": "None"},
            {"Code": "ConditionalCheckFailed"},
        ],
    )

    with pytest.raises(SubmissionActorAuthorizationError):
        repository.transition_submission(
            tenant_id="tenant-a",
            submission_id="submission-123",
            previous_status="SUBMITTED",
            new_status="IN_REVIEW",
            expected_version=1,
            updated_at="2026-11-12T12:00:00Z",
            audit_event=audit_event,
            actor_id="reviewer-a",
            actor_role="REVIEWER",
        )
