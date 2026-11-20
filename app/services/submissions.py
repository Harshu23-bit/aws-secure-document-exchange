import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.core.authorization import TenantMembership, TenantRole
from app.repositories.submission import (
    DynamoDBSubmissionRepository,
    SubmissionAlreadyExistsError,
    SubmissionRepository,
)
from app.schemas.submission import (
    SubmissionCreateRequest,
    SubmissionListResponse,
    SubmissionResponse,
)


def get_submission_repository() -> SubmissionRepository:
    from app.core.config import get_settings

    return DynamoDBSubmissionRepository(get_settings())


async def get_authorized_submission(
    submission_id: str,
    membership: TenantMembership,
    repository: SubmissionRepository,
) -> SubmissionResponse:

    submission = await run_in_threadpool(
        repository.get_submission,
        membership.tenant_id,
        submission_id,
    )

    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    if (
        submission.get("tenant_id") != membership.tenant_id
        or submission.get("submission_id") != submission_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    if membership.role == TenantRole.SUBMITTER:
        if submission.get("owner_id") != membership.user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Submission not found",
            )

    elif membership.role != TenantRole.REVIEWER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    return SubmissionResponse.model_validate(submission)


async def create_submission(
    request: SubmissionCreateRequest,
    membership: TenantMembership,
    repository: SubmissionRepository,
) -> SubmissionResponse:

    if membership.role != TenantRole.SUBMITTER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only submitters can create submissions",
        )

    submission_id = str(uuid4())

    timestamp = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    tenant_id = membership.tenant_id
    owner_id = membership.user_id

    submission: dict[str, Any] = {
        "PK": f"TENANT#{tenant_id}",
        "SK": f"SUBMISSION#{submission_id}",
        "GSI1PK": f"TENANT#{tenant_id}#USER#{owner_id}",
        "GSI1SK": (
            f"CREATED#{timestamp}#TENANT#{tenant_id}#SUBMISSION#{submission_id}"
        ),
        "GSI2PK": f"TENANT#{tenant_id}#STATUS#DRAFT",
        "GSI2SK": (f"CREATED#{timestamp}#SUBMISSION#{submission_id}"),
        "entity_type": "SUBMISSION",
        "tenant_id": tenant_id,
        "submission_id": submission_id,
        "owner_id": owner_id,
        "title": request.title,
        "description": request.description,
        "status": "DRAFT",
        "created_at": timestamp,
        "updated_at": timestamp,
        "version": 1,
        "total_document_count": 0,
        "total_document_bytes": 0,
        "pending_document_count": 0,
        "pending_document_bytes": 0,
        "uploaded_document_count": 0,
        "uploaded_document_bytes": 0,
    }

    try:
        await run_in_threadpool(
            repository.create_submission,
            submission,
        )
    except SubmissionAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Submission already exists",
        )

    return SubmissionResponse.model_validate(submission)


def encode_submission_cursor(
    last_evaluated_key: dict[str, Any],
    membership: TenantMembership,
) -> str:

    payload = {
        "version": 1,
        "tenant_id": membership.tenant_id,
        "user_id": membership.user_id,
        "role": membership.role.value,
        "last_evaluated_key": last_evaluated_key,
    }

    serialized = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    return base64.urlsafe_b64encode(serialized).decode("ascii").rstrip("=")


def decode_submission_cursor(
    cursor: str,
    membership: TenantMembership,
) -> dict[str, Any]:

    try:
        if not cursor or len(cursor) > 4096:
            raise ValueError

        padded_cursor = cursor + "=" * (-len(cursor) % 4)

        decoded = base64.b64decode(
            padded_cursor,
            altchars=b"-_",
            validate=True,
        )

        payload = json.loads(decoded)

        if not isinstance(payload, dict):
            raise TypeError

        if set(payload) != {
            "version",
            "tenant_id",
            "user_id",
            "role",
            "last_evaluated_key",
        }:
            raise ValueError

        if type(payload["version"]) is not int:
            raise ValueError

        if payload["version"] != 1:
            raise ValueError

        if payload["tenant_id"] != membership.tenant_id:
            raise ValueError

        if payload["user_id"] != membership.user_id:
            raise ValueError

        if payload["role"] != membership.role.value:
            raise ValueError

        last_key = payload["last_evaluated_key"]

        if not isinstance(last_key, dict):
            raise TypeError

        if membership.role == TenantRole.SUBMITTER:
            expected_keys = {
                "PK",
                "SK",
                "GSI1PK",
                "GSI1SK",
            }

            if set(last_key) != expected_keys:
                raise ValueError

            if last_key["PK"] != f"TENANT#{membership.tenant_id}":
                raise ValueError

            if last_key["GSI1PK"] != (
                f"TENANT#{membership.tenant_id}#USER#{membership.user_id}"
            ):
                raise ValueError

            if not isinstance(last_key["SK"], str):
                raise ValueError

            if not last_key["SK"].startswith("SUBMISSION#"):
                raise ValueError

            if not isinstance(last_key["GSI1SK"], str):
                raise ValueError

            if not last_key["GSI1SK"].startswith("CREATED#"):
                raise ValueError

        elif membership.role == TenantRole.REVIEWER:
            if set(last_key) != {"PK", "SK"}:
                raise ValueError

            if last_key["PK"] != f"TENANT#{membership.tenant_id}":
                raise ValueError

            if not isinstance(last_key["SK"], str):
                raise ValueError

            if not last_key["SK"].startswith("SUBMISSION#"):
                raise ValueError

        else:
            raise ValueError

        return last_key

    except (
        ValueError,
        TypeError,
        KeyError,
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination cursor",
        )


async def list_submissions(
    membership: TenantMembership,
    repository: SubmissionRepository,
    limit: int,
    cursor: str | None = None,
) -> SubmissionListResponse:

    last_evaluated_key = None

    if cursor is not None:
        last_evaluated_key = decode_submission_cursor(
            cursor,
            membership,
        )

    if membership.role == TenantRole.SUBMITTER:
        result = await run_in_threadpool(
            repository.list_submitter_submissions,
            membership.tenant_id,
            membership.user_id,
            limit,
            last_evaluated_key,
        )

    elif membership.role == TenantRole.REVIEWER:
        result = await run_in_threadpool(
            repository.list_reviewer_submissions,
            membership.tenant_id,
            limit,
            last_evaluated_key,
        )

    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    items = result.get("Items", [])

    for item in items:
        if item.get("tenant_id") != membership.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Invalid submission data",
            )

        if (
            membership.role == TenantRole.SUBMITTER
            and item.get("owner_id") != membership.user_id
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Invalid submission data",
            )

    next_key = result.get("LastEvaluatedKey")

    next_cursor = encode_submission_cursor(next_key, membership) if next_key else None

    return SubmissionListResponse(
        items=items,
        next_cursor=next_cursor,
    )
