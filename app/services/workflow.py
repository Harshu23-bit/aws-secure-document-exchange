from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.core.authorization import TenantMembership, TenantRole
from app.core.logging import request_id_context
from app.repositories.submission import (
    DynamoDBSubmissionRepository,
    SubmissionActorAuthorizationError,
    SubmissionRepository,
    SubmissionStateConflictError,
)
from app.schemas.workflow import (
    SubmissionStatus,
    SubmissionTransitionRequest,
    SubmissionTransitionResponse,
)


def get_workflow_repository() -> SubmissionRepository:
    from app.core.config import get_settings

    return DynamoDBSubmissionRepository(get_settings())


def get_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_submission_version(value: object) -> int | None:
    """Accept only positive integral DynamoDB/Python integer values."""
    if type(value) is int:
        return value if value >= 1 else None

    if (
        type(value) is Decimal
        and value.is_finite()
        and value >= 1
        and value == value.to_integral_value()
    ):
        return int(value)

        return None


def validate_transition(
    current_status: str,
    target_status: SubmissionStatus,
    membership: TenantMembership,
    submission: dict,
    reason: str | None,
) -> None:

    transitions = {
        (
            TenantRole.SUBMITTER,
            SubmissionStatus.DRAFT,
            SubmissionStatus.SUBMITTED,
        ),
        (
            TenantRole.SUBMITTER,
            SubmissionStatus.NEEDS_CHANGES,
            SubmissionStatus.DRAFT,
        ),
        (
            TenantRole.REVIEWER,
            SubmissionStatus.SUBMITTED,
            SubmissionStatus.IN_REVIEW,
        ),
        (
            TenantRole.REVIEWER,
            SubmissionStatus.IN_REVIEW,
            SubmissionStatus.APPROVED,
        ),
        (
            TenantRole.REVIEWER,
            SubmissionStatus.IN_REVIEW,
            SubmissionStatus.REJECTED,
        ),
        (
            TenantRole.REVIEWER,
            SubmissionStatus.IN_REVIEW,
            SubmissionStatus.NEEDS_CHANGES,
        ),
        (
            TenantRole.REVIEWER,
            SubmissionStatus.APPROVED,
            SubmissionStatus.CLOSED,
        ),
    }

    try:
        previous_status = SubmissionStatus(current_status)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Submission has an invalid workflow state",
        )

    transition = (
        membership.role,
        previous_status,
        target_status,
    )

    if transition not in transitions:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This workflow transition is not permitted",
        )

    if (
        membership.role == TenantRole.SUBMITTER
        and submission.get("owner_id") != membership.user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the submission owner can perform this action",
        )

    if (
        target_status
        in {
            SubmissionStatus.REJECTED,
            SubmissionStatus.NEEDS_CHANGES,
        }
        and not reason
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A reason is required for this transition",
        )


async def transition_submission(
    tenant_id: str,
    submission_id: str,
    request: SubmissionTransitionRequest,
    membership: TenantMembership,
    repository: SubmissionRepository,
) -> SubmissionTransitionResponse:

    if membership.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant access denied",
        )

    if membership.role not in {
        TenantRole.SUBMITTER,
        TenantRole.REVIEWER,
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Role not permitted",
        )

    submission = await run_in_threadpool(
        repository.get_submission,
        tenant_id,
        submission_id,
    )

    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    if not isinstance(submission, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid submission data",
        )

    if (
        submission.get("tenant_id") != tenant_id
        or submission.get("submission_id") != submission_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    if (
        membership.role == TenantRole.SUBMITTER
        and submission.get("owner_id") != membership.user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    previous_status = submission.get("status")
    previous_version = normalize_submission_version(submission.get("version"))

    if previous_version is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Submission version is invalid",
        )

    if request.expected_version != previous_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Submission has changed. Refresh and retry.",
        )

    validate_transition(
        current_status=previous_status,
        target_status=request.target_status,
        membership=membership,
        submission=submission,
        reason=request.reason,
    )

    timestamp = get_timestamp()
    event_id = str(uuid4())

    audit_event = {
        "PK": f"TENANT#{tenant_id}#SUBMISSION#{submission_id}",
        "SK": f"EVENT#{timestamp}#{event_id}",
        "GSI1PK": f"TENANT#{tenant_id}",
        "GSI1SK": f"EVENT#{timestamp}#{event_id}",
        "entity_type": "AUDIT_EVENT",
        "event_id": event_id,
        "event_type": "SUBMISSION_STATUS_CHANGED",
        "tenant_id": tenant_id,
        "submission_id": submission_id,
        "actor_id": membership.user_id,
        "actor_role": membership.role.value,
        "previous_status": previous_status,
        "new_status": request.target_status.value,
        "previous_version": previous_version,
        "new_version": previous_version + 1,
        "timestamp": timestamp,
        "request_id": request_id_context.get(),
    }

    if request.reason is not None:
        audit_event["reason"] = request.reason

    owner_id = membership.user_id if membership.role == TenantRole.SUBMITTER else None

    try:
        await run_in_threadpool(
            repository.transition_submission,
            tenant_id,
            submission_id,
            previous_status,
            request.target_status.value,
            previous_version,
            timestamp,
            audit_event,
            owner_id,
            (
                previous_status == SubmissionStatus.DRAFT.value
                and request.target_status == SubmissionStatus.SUBMITTED
            ),
            actor_id=membership.user_id,
            actor_role=membership.role.value,
        )

    except SubmissionActorAuthorizationError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant membership is no longer authorized",
        )

    except SubmissionStateConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Submission state changed during the transition",
        )

    return SubmissionTransitionResponse(
        tenant_id=tenant_id,
        submission_id=submission_id,
        previous_status=previous_status,
        status=request.target_status,
        version=previous_version + 1,
        updated_at=timestamp,
    )
