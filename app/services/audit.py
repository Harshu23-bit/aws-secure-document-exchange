import base64
import binascii
import json
from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.core.authorization import TenantMembership, TenantRole
from app.repositories.audit import (
    AuditRepository,
    DynamoDBAuditRepository,
)
from app.repositories.submission import SubmissionRepository
from app.schemas.workflow import (
    AuditEventListResponse,
    AuditEventResponse,
    TenantAuditEventListResponse,
)
from app.services.submissions import get_authorized_submission


def get_audit_repository() -> AuditRepository:
    from app.core.config import get_settings

    return DynamoDBAuditRepository(get_settings())


def _expected_partition(
    tenant_id: str,
    submission_id: str,
) -> str:
    return f"TENANT#{tenant_id}#SUBMISSION#{submission_id}"


def _validate_audit_key(
    key: object,
    tenant_id: str,
    submission_id: str,
) -> dict[str, Any]:
    """Validate a DynamoDB audit event key against its expected scope."""

    if not isinstance(key, dict) or set(key) != {"PK", "SK"}:
        raise ValueError("Invalid audit key shape")

    expected_pk = _expected_partition(tenant_id, submission_id)
    pk = key["PK"]
    sk = key["SK"]

    if not isinstance(pk, str) or pk != expected_pk:
        raise ValueError("Invalid audit partition key")

    if not isinstance(sk, str):
        raise TypeError("Invalid audit sort key")

    parts = sk.split("#", 2)

    if len(parts) != 3 or parts[0] != "EVENT" or not parts[1] or not parts[2]:
        raise TypeError("Invalid audit sort key")

    return key


def encode_audit_cursor(
    last_evaluated_key: dict[str, Any],
) -> str:
    serialized = json.dumps(
        last_evaluated_key,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    return base64.urlsafe_b64encode(serialized).decode("ascii").rstrip("=")


def decode_audit_cursor(
    cursor: str,
    tenant_id: str,
    submission_id: str,
) -> dict[str, Any]:
    try:
        if not isinstance(cursor, str) or not cursor or len(cursor) > 4096:
            raise ValueError

        padded = cursor + "=" * (-len(cursor) % 4)

        decoded = base64.b64decode(
            padded,
            altchars=b"-_",
            validate=True,
        )

        last_key = json.loads(decoded)

        return _validate_audit_key(
            last_key,
            tenant_id,
            submission_id,
        )

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
            detail="Invalid audit pagination cursor",
        )


def _validate_audit_event(
    item: object,
    tenant_id: str,
    submission_id: str,
) -> AuditEventResponse:
    """Validate event identity, key consistency, and response fields."""

    if not isinstance(item, dict):
        raise TypeError("Audit event is not an object")

    if (
        item.get("tenant_id") != tenant_id
        or item.get("submission_id") != submission_id
        or item.get("entity_type") != "AUDIT_EVENT"
    ):
        raise ValueError("Audit event scope mismatch")

    _validate_audit_key(
        {"PK": item.get("PK"), "SK": item.get("SK")},
        tenant_id,
        submission_id,
    )

    event_id = item.get("event_id")
    timestamp = item.get("timestamp")

    if (
        not isinstance(event_id, str)
        or not event_id
        or not isinstance(timestamp, str)
        or not timestamp
    ):
        raise ValueError("Invalid audit event identity")

    expected_sk = f"EVENT#{timestamp}#{event_id}"

    if item["SK"] != expected_sk:
        raise ValueError("Audit event key does not match event identity")

    return AuditEventResponse.model_validate(item)


async def get_submission_audit_history(
    tenant_id: str,
    submission_id: str,
    membership: TenantMembership,
    submission_repository: SubmissionRepository,
    audit_repository: AuditRepository,
    limit: int = 20,
    cursor: str | None = None,
) -> AuditEventListResponse:

    if membership.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant access denied",
        )

    if type(limit) is not int or not 1 <= limit <= 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid audit history limit",
        )

    await get_authorized_submission(
        submission_id=submission_id,
        membership=membership,
        repository=submission_repository,
    )

    last_evaluated_key = None

    if cursor is not None:
        last_evaluated_key = decode_audit_cursor(
            cursor,
            tenant_id,
            submission_id,
        )

    result = await run_in_threadpool(
        audit_repository.list_submission_events,
        tenant_id,
        submission_id,
        limit,
        last_evaluated_key,
    )

    if not isinstance(result, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid audit repository response",
        )

    items = result.get("Items", [])

    if not isinstance(items, list):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid audit repository response",
        )

    validated_items = []

    try:
        for item in items:
            validated_items.append(
                _validate_audit_event(
                    item,
                    tenant_id,
                    submission_id,
                )
            )

        next_key = result.get("LastEvaluatedKey")

        if next_key is not None:
            _validate_audit_key(
                next_key,
                tenant_id,
                submission_id,
            )

    except (ValueError, TypeError, KeyError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid audit event data",
        )

    return AuditEventListResponse(
        items=validated_items,
        next_cursor=(encode_audit_cursor(next_key) if next_key else None),
    )


def _validate_tenant_audit_key(
    key: object,
    tenant_id: str,
) -> dict[str, Any]:
    """Validate a GSI pagination key against the requested tenant."""

    expected_gsi_pk = f"TENANT#{tenant_id}"

    if not isinstance(key, dict):
        raise TypeError("Invalid tenant audit key")

    if set(key) != {"PK", "SK", "GSI1PK", "GSI1SK"}:
        raise ValueError("Invalid tenant audit key shape")

    pk = key["PK"]
    sk = key["SK"]
    gsi_pk = key["GSI1PK"]
    gsi_sk = key["GSI1SK"]

    if not all(isinstance(value, str) for value in (pk, sk, gsi_pk, gsi_sk)):
        raise ValueError("Invalid tenant audit key values")

    if gsi_pk != expected_gsi_pk:
        raise ValueError("Tenant audit partition mismatch")

    if gsi_sk != sk:
        raise ValueError("Tenant audit sort key mismatch")

    valid_prefixes = (
        f"TENANT#{tenant_id}#SUBMISSION#",
        f"TENANT#{tenant_id}#MEMBERSHIP#",
    )

    if not any(
        pk.startswith(prefix) and len(pk) > len(prefix) for prefix in valid_prefixes
    ):
        raise ValueError("Invalid tenant audit entity partition")

    parts = sk.split("#", 2)

    if len(parts) != 3 or parts[0] != "EVENT" or not parts[1] or not parts[2]:
        raise ValueError("Invalid tenant audit sort key")

    return key


def decode_tenant_audit_cursor(
    cursor: str,
    tenant_id: str,
) -> dict[str, Any]:
    """Decode and validate a tenant-wide audit pagination cursor."""

    try:
        if not isinstance(cursor, str) or not cursor or len(cursor) > 4096:
            raise ValueError

        padded = cursor + "=" * (-len(cursor) % 4)

        decoded = base64.b64decode(
            padded,
            altchars=b"-_",
            validate=True,
        )

        last_key = json.loads(decoded)

        return _validate_tenant_audit_key(last_key, tenant_id)

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
            detail="Invalid audit pagination cursor",
        )


def _validate_tenant_audit_event(
    item: object,
    tenant_id: str,
) -> dict[str, Any]:
    """Validate tenant scope and key consistency for a tenant audit event."""

    if not isinstance(item, dict):
        raise TypeError("Audit event is not an object")

    if item.get("tenant_id") != tenant_id or item.get("entity_type") != "AUDIT_EVENT":
        raise ValueError("Audit event scope mismatch")

    event_id = item.get("event_id")
    timestamp = item.get("timestamp")
    event_type = item.get("event_type")

    if (
        not isinstance(event_id, str)
        or not event_id
        or not isinstance(timestamp, str)
        or not timestamp
    ):
        raise ValueError("Invalid audit event identity")

    expected_sk = f"EVENT#{timestamp}#{event_id}"

    if item.get("SK") != expected_sk:
        raise ValueError("Audit event sort key mismatch")

    if item.get("GSI1PK") != f"TENANT#{tenant_id}":
        raise ValueError("Audit event tenant index mismatch")

    if item.get("GSI1SK") != expected_sk:
        raise ValueError("Audit event index sort key mismatch")

    if event_type == "SUBMISSION_STATUS_CHANGED":
        submission_id = item.get("submission_id")

        if not isinstance(submission_id, str) or not submission_id:
            raise ValueError("Invalid submission audit identity")

        expected_pk = f"TENANT#{tenant_id}#SUBMISSION#{submission_id}"

    elif event_type in (
        "MEMBERSHIP_ROLE_CHANGED",
        "MEMBERSHIP_DEACTIVATED",
    ):
        target_user_id = item.get("target_user_id")

        if not isinstance(target_user_id, str) or not target_user_id:
            raise ValueError("Invalid membership audit identity")

        expected_pk = f"TENANT#{tenant_id}#MEMBERSHIP#{target_user_id}"

    else:
        raise ValueError("Unsupported tenant audit event type")

    if item.get("PK") != expected_pk:
        raise ValueError("Audit event partition key mismatch")

    return item


async def get_tenant_audit_history(
    tenant_id: str,
    membership: TenantMembership,
    audit_repository: AuditRepository,
    limit: int = 20,
    cursor: str | None = None,
) -> TenantAuditEventListResponse:
    """Retrieve tenant-wide audit history for tenant administrators."""

    if (
        membership.tenant_id != tenant_id
        or membership.role != TenantRole.TENANT_ADMIN
        or membership.status != "ACTIVE"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant administrator privileges required",
        )

    if type(limit) is not int or not 1 <= limit <= 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid audit history limit",
        )

    last_evaluated_key = None

    if cursor is not None:
        last_evaluated_key = decode_tenant_audit_cursor(
            cursor,
            tenant_id,
        )

    result = await run_in_threadpool(
        audit_repository.list_tenant_events,
        tenant_id,
        limit,
        last_evaluated_key,
    )

    if not isinstance(result, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid audit repository response",
        )

    items = result.get("Items", [])

    if not isinstance(items, list):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid audit repository response",
        )

    try:
        validated_items = [
            _validate_tenant_audit_event(item, tenant_id) for item in items
        ]

        next_key = result.get("LastEvaluatedKey")

        if next_key is not None:
            _validate_tenant_audit_key(next_key, tenant_id)

        return TenantAuditEventListResponse(
            items=validated_items,
            next_cursor=(encode_audit_cursor(next_key) if next_key else None),
        )

    except (ValueError, TypeError, KeyError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid audit event data",
        )
