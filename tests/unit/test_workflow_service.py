import asyncio
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.authorization import TenantMembership, TenantRole
from app.core.logging import request_id_context
from app.repositories.submission import (
    SubmissionActorAuthorizationError,
    SubmissionStateConflictError,
)
from app.schemas.workflow import (
    SubmissionStatus,
    SubmissionTransitionRequest,
)
from app.services import workflow


@pytest.fixture
def submitter():
    return TenantMembership(
        user_id="user-a",
        tenant_id="tenant-a",
        role=TenantRole.SUBMITTER,
        status="ACTIVE",
    )


@pytest.fixture
def reviewer():
    return TenantMembership(
        user_id="reviewer-a",
        tenant_id="tenant-a",
        role=TenantRole.REVIEWER,
        status="ACTIVE",
    )


@pytest.fixture
def repository():
    repo = MagicMock()
    repo.get_submission.return_value = {
        "PK": "TENANT#tenant-a",
        "SK": "SUBMISSION#submission-123",
        "tenant_id": "tenant-a",
        "submission_id": "submission-123",
        "owner_id": "user-a",
        "status": "DRAFT",
        "version": 1,
        "pending_document_count": 0,
        "uploaded_document_count": 1,
    }
    return repo


def run_async(coroutine):
    return asyncio.run(coroutine)


def test_submitter_can_submit_own_draft(
    submitter,
    repository,
    monkeypatch,
):
    monkeypatch.setattr(
        workflow,
        "get_timestamp",
        lambda: "2026-11-12T12:00:00Z",
    )

    monkeypatch.setattr(
        workflow,
        "uuid4",
        lambda: "event-123",
    )

    token = request_id_context.set("request-123")

    try:
        result = run_async(
            workflow.transition_submission(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=SubmissionTransitionRequest(
                    target_status=SubmissionStatus.SUBMITTED,
                    expected_version=1,
                ),
                membership=submitter,
                repository=repository,
            )
        )
    finally:
        request_id_context.reset(token)

    assert result.status == SubmissionStatus.SUBMITTED
    assert result.previous_status == SubmissionStatus.DRAFT
    assert result.version == 2

    args = repository.transition_submission.call_args.args

    assert args[0] == "tenant-a"
    assert args[1] == "submission-123"
    assert args[2] == "DRAFT"
    assert args[3] == "SUBMITTED"
    assert args[4] == 1
    assert args[7] == "user-a"
    assert args[8] is True
    kwargs = repository.transition_submission.call_args.kwargs

    assert kwargs["actor_id"] == "user-a"
    assert kwargs["actor_role"] == "SUBMITTER"

    audit_event = args[6]

    assert audit_event["GSI1PK"] == "TENANT#tenant-a"
    assert audit_event["GSI1SK"].startswith("EVENT#")
    assert audit_event["actor_id"] == "user-a"
    assert audit_event["actor_role"] == "SUBMITTER"
    assert audit_event["previous_version"] == 1
    assert audit_event["new_version"] == 2
    assert audit_event["request_id"] == "request-123"
    assert audit_event["event_type"] == "SUBMISSION_STATUS_CHANGED"


def test_reviewer_can_start_review(
    reviewer,
    repository,
):
    repository.get_submission.return_value["status"] = "SUBMITTED"

    result = run_async(
        workflow.transition_submission(
            tenant_id="tenant-a",
            submission_id="submission-123",
            request=SubmissionTransitionRequest(
                target_status=SubmissionStatus.IN_REVIEW,
                expected_version=1,
            ),
            membership=reviewer,
            repository=repository,
        )
    )

    assert result.status == SubmissionStatus.IN_REVIEW

    args = repository.transition_submission.call_args.args

    assert args[7] is None
    assert args[8] is False
    kwargs = repository.transition_submission.call_args.kwargs

    assert kwargs["actor_id"] == "reviewer-a"
    assert kwargs["actor_role"] == "REVIEWER"


def test_revoked_reviewer_membership_becomes_http_403(
    reviewer,
    repository,
):
    repository.get_submission.return_value["status"] = "SUBMITTED"

    repository.transition_submission.side_effect = SubmissionActorAuthorizationError

    with pytest.raises(HTTPException) as exc:
        run_async(
            workflow.transition_submission(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=SubmissionTransitionRequest(
                    target_status=SubmissionStatus.IN_REVIEW,
                    expected_version=1,
                ),
                membership=reviewer,
                repository=repository,
            )
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == ("Tenant membership is no longer authorized")


@pytest.mark.parametrize(
    ("current_status", "target_status"),
    [
        ("DRAFT", SubmissionStatus.APPROVED),
        ("SUBMITTED", SubmissionStatus.CLOSED),
        ("APPROVED", SubmissionStatus.REJECTED),
        ("CLOSED", SubmissionStatus.DRAFT),
    ],
)
def test_invalid_workflow_transition_is_rejected(
    reviewer,
    repository,
    current_status,
    target_status,
):
    repository.get_submission.return_value["status"] = current_status

    with pytest.raises(HTTPException) as exc:
        run_async(
            workflow.transition_submission(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=SubmissionTransitionRequest(
                    target_status=target_status,
                    expected_version=1,
                ),
                membership=reviewer,
                repository=repository,
            )
        )

    assert exc.value.status_code == 409
    repository.transition_submission.assert_not_called()


def test_submitter_cannot_transition_another_users_submission(
    submitter,
    repository,
):
    repository.get_submission.return_value["owner_id"] = "user-b"

    with pytest.raises(HTTPException) as exc:
        run_async(
            workflow.transition_submission(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=SubmissionTransitionRequest(
                    target_status=SubmissionStatus.SUBMITTED,
                    expected_version=1,
                ),
                membership=submitter,
                repository=repository,
            )
        )

    assert exc.value.status_code == 404
    repository.transition_submission.assert_not_called()


def test_reviewer_cannot_perform_submitter_transition(
    reviewer,
    repository,
):
    with pytest.raises(HTTPException) as exc:
        run_async(
            workflow.transition_submission(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=SubmissionTransitionRequest(
                    target_status=SubmissionStatus.SUBMITTED,
                    expected_version=1,
                ),
                membership=reviewer,
                repository=repository,
            )
        )

    assert exc.value.status_code == 409
    repository.transition_submission.assert_not_called()


def test_submitter_cannot_approve_submission(
    submitter,
    repository,
):
    repository.get_submission.return_value["status"] = "IN_REVIEW"

    with pytest.raises(HTTPException) as exc:
        run_async(
            workflow.transition_submission(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=SubmissionTransitionRequest(
                    target_status=SubmissionStatus.APPROVED,
                    expected_version=1,
                ),
                membership=submitter,
                repository=repository,
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "This workflow transition is not permitted"
    repository.transition_submission.assert_not_called()


@pytest.mark.parametrize(
    "target_status",
    [
        SubmissionStatus.REJECTED,
        SubmissionStatus.NEEDS_CHANGES,
    ],
)
def test_reviewer_reason_is_required(
    reviewer,
    repository,
    target_status,
):
    repository.get_submission.return_value["status"] = "IN_REVIEW"

    with pytest.raises(HTTPException) as exc:
        run_async(
            workflow.transition_submission(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=SubmissionTransitionRequest(
                    target_status=target_status,
                    expected_version=1,
                ),
                membership=reviewer,
                repository=repository,
            )
        )

    assert exc.value.status_code == 422
    repository.transition_submission.assert_not_called()


def test_reviewer_rejection_records_reason(
    reviewer,
    repository,
):
    repository.get_submission.return_value["status"] = "IN_REVIEW"

    run_async(
        workflow.transition_submission(
            tenant_id="tenant-a",
            submission_id="submission-123",
            request=SubmissionTransitionRequest(
                target_status=SubmissionStatus.REJECTED,
                expected_version=1,
                reason="Required documents are incomplete",
            ),
            membership=reviewer,
            repository=repository,
        )
    )

    audit_event = repository.transition_submission.call_args.args[6]

    assert audit_event["reason"] == "Required documents are incomplete"


def test_stale_expected_version_is_rejected(
    submitter,
    repository,
):
    with pytest.raises(HTTPException) as exc:
        run_async(
            workflow.transition_submission(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=SubmissionTransitionRequest(
                    target_status=SubmissionStatus.SUBMITTED,
                    expected_version=5,
                ),
                membership=submitter,
                repository=repository,
            )
        )

    assert exc.value.status_code == 409
    repository.transition_submission.assert_not_called()


def test_invalid_submission_version_is_rejected(
    submitter,
    repository,
):
    repository.get_submission.return_value["version"] = 0

    with pytest.raises(HTTPException) as exc:
        run_async(
            workflow.transition_submission(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=SubmissionTransitionRequest(
                    target_status=SubmissionStatus.SUBMITTED,
                    expected_version=1,
                ),
                membership=submitter,
                repository=repository,
            )
        )

    assert exc.value.status_code == 409
    repository.transition_submission.assert_not_called()


def test_tenant_mismatch_is_rejected(
    submitter,
    repository,
):
    with pytest.raises(HTTPException) as exc:
        run_async(
            workflow.transition_submission(
                tenant_id="tenant-b",
                submission_id="submission-123",
                request=SubmissionTransitionRequest(
                    target_status=SubmissionStatus.SUBMITTED,
                    expected_version=1,
                ),
                membership=submitter,
                repository=repository,
            )
        )

    assert exc.value.status_code == 403
    repository.get_submission.assert_not_called()


def test_missing_submission_returns_404(
    submitter,
    repository,
):
    repository.get_submission.return_value = None

    with pytest.raises(HTTPException) as exc:
        run_async(
            workflow.transition_submission(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=SubmissionTransitionRequest(
                    target_status=SubmissionStatus.SUBMITTED,
                    expected_version=1,
                ),
                membership=submitter,
                repository=repository,
            )
        )

    assert exc.value.status_code == 404
    repository.transition_submission.assert_not_called()


def test_repository_state_conflict_becomes_http_409(
    submitter,
    repository,
):
    repository.transition_submission.side_effect = SubmissionStateConflictError

    with pytest.raises(HTTPException) as exc:
        run_async(
            workflow.transition_submission(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=SubmissionTransitionRequest(
                    target_status=SubmissionStatus.SUBMITTED,
                    expected_version=1,
                ),
                membership=submitter,
                repository=repository,
            )
        )

    assert exc.value.status_code == 409


def test_submit_transition_delegates_uploaded_document_invariant_to_repository(
    submitter,
    repository,
):
    repository.get_submission.return_value["uploaded_document_count"] = 0

    result = run_async(
        workflow.transition_submission(
            tenant_id="tenant-a",
            submission_id="submission-123",
            request=SubmissionTransitionRequest(
                target_status=SubmissionStatus.SUBMITTED,
                expected_version=1,
            ),
            membership=submitter,
            repository=repository,
        )
    )

    assert result.status == SubmissionStatus.SUBMITTED

    args = repository.transition_submission.call_args.args
    assert args[8] is True


@pytest.mark.parametrize(
    ("stored_version", "expected_version"),
    [
        (Decimal(1), 1),
        (Decimal(2), 2),
        (Decimal(123456789), 123456789),
    ],
)
def test_dynamodb_decimal_version_allows_valid_transition(
    submitter,
    repository,
    stored_version,
    expected_version,
):
    repository.get_submission.return_value["version"] = stored_version

    result = run_async(
        workflow.transition_submission(
            tenant_id="tenant-a",
            submission_id="submission-123",
            request=SubmissionTransitionRequest(
                target_status=SubmissionStatus.SUBMITTED,
                expected_version=expected_version,
            ),
            membership=submitter,
            repository=repository,
        )
    )

    assert result.version == expected_version + 1

    args = repository.transition_submission.call_args.args
    assert args[4] == expected_version
    assert args[6]["previous_version"] == expected_version
    assert args[6]["new_version"] == expected_version + 1


@pytest.mark.parametrize(
    "stored_version",
    [
        True,
        False,
        0,
        -1,
        1.0,
        1.5,
        "1",
        Decimal(0),
        Decimal(-1),
        Decimal("1.5"),
        Decimal("NaN"),
        Decimal("Infinity"),
        None,
        [],
        {},
    ],
)
def test_malformed_submission_version_is_rejected(
    submitter,
    repository,
    stored_version,
):
    repository.get_submission.return_value["version"] = stored_version

    with pytest.raises(HTTPException) as exc:
        run_async(
            workflow.transition_submission(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=SubmissionTransitionRequest(
                    target_status=SubmissionStatus.SUBMITTED,
                    expected_version=1,
                ),
                membership=submitter,
                repository=repository,
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Submission version is invalid"
    repository.transition_submission.assert_not_called()


@pytest.mark.parametrize(
    "stored_status",
    [
        None,
        [],
        {},
        123,
    ],
)
def test_malformed_submission_status_is_rejected(
    submitter,
    repository,
    stored_status,
):
    repository.get_submission.return_value["status"] = stored_status

    with pytest.raises(HTTPException) as exc:
        run_async(
            workflow.transition_submission(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=SubmissionTransitionRequest(
                    target_status=SubmissionStatus.SUBMITTED,
                    expected_version=1,
                ),
                membership=submitter,
                repository=repository,
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Submission has an invalid workflow state"
    repository.transition_submission.assert_not_called()


@pytest.mark.parametrize(
    "expected_version",
    [
        True,
        False,
        "1",
        1.0,
        1.5,
        0,
        -1,
    ],
)
def test_transition_request_rejects_non_strict_versions(
    expected_version,
):

    with pytest.raises(ValidationError):
        SubmissionTransitionRequest(
            target_status=SubmissionStatus.SUBMITTED,
            expected_version=expected_version,
        )
