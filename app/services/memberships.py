from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.core.authorization import TenantMembership, TenantRole
from app.core.logging import request_id_context
from app.repositories.membership import (
    MembershipActorAuthorizationError,
    MembershipRepository,
    MembershipStateConflictError,
)
from app.schemas.membership import (
    ChangeMemberRoleRequest,
    DeactivateMemberRequest,
    MembershipMutationResponse,
)


def get_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_admin_membership(
    tenant_id: str,
    membership: TenantMembership,
) -> None:
    if (
        membership.tenant_id != tenant_id
        or membership.role != TenantRole.TENANT_ADMIN
        or membership.status != "ACTIVE"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant administrator privileges required",
        )


def _build_membership_audit_event(
    tenant_id: str,
    target_user_id: str,
    membership: TenantMembership,
    event_type: str,
    timestamp: str,
    **changes: str,
) -> dict:
    event_id = str(uuid4())

    return {
        "PK": (f"TENANT#{tenant_id}#MEMBERSHIP#{target_user_id}"),
        "SK": f"EVENT#{timestamp}#{event_id}",
        "GSI1PK": f"TENANT#{tenant_id}",
        "GSI1SK": f"EVENT#{timestamp}#{event_id}",
        "entity_type": "AUDIT_EVENT",
        "event_id": event_id,
        "event_type": event_type,
        "tenant_id": tenant_id,
        "target_user_id": target_user_id,
        "actor_id": membership.user_id,
        "actor_role": membership.role.value,
        "timestamp": timestamp,
        "request_id": request_id_context.get(),
        **changes,
    }


def _raise_membership_http_error(
    error: Exception,
) -> None:
    if isinstance(error, MembershipActorAuthorizationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant administrator privileges required",
        ) from error

    if isinstance(error, MembershipStateConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Membership state changed. Refresh and retry.",
        ) from error

    raise error


async def change_member_role(
    tenant_id: str,
    target_user_id: str,
    request: ChangeMemberRoleRequest,
    membership: TenantMembership,
    repository: MembershipRepository,
) -> MembershipMutationResponse:
    _validate_admin_membership(tenant_id, membership)

    timestamp = get_timestamp()

    audit_event = _build_membership_audit_event(
        tenant_id=tenant_id,
        target_user_id=target_user_id,
        membership=membership,
        event_type="MEMBERSHIP_ROLE_CHANGED",
        timestamp=timestamp,
        previous_role=request.expected_role,
        new_role=request.new_role,
    )

    try:
        await run_in_threadpool(
            repository.change_member_role,
            tenant_id,
            membership.user_id,
            target_user_id,
            request.expected_role,
            request.new_role,
            timestamp,
            audit_event,
        )
    except (
        MembershipActorAuthorizationError,
        MembershipStateConflictError,
    ) as error:
        _raise_membership_http_error(error)

    return MembershipMutationResponse(
        user_id=target_user_id,
        tenant_id=tenant_id,
        role=request.new_role,
        status="ACTIVE",
        updated_at=timestamp,
    )


async def deactivate_member(
    tenant_id: str,
    target_user_id: str,
    request: DeactivateMemberRequest,
    membership: TenantMembership,
    repository: MembershipRepository,
) -> MembershipMutationResponse:
    _validate_admin_membership(tenant_id, membership)

    timestamp = get_timestamp()

    audit_event = _build_membership_audit_event(
        tenant_id=tenant_id,
        target_user_id=target_user_id,
        membership=membership,
        event_type="MEMBERSHIP_DEACTIVATED",
        timestamp=timestamp,
        previous_status="ACTIVE",
        new_status="INACTIVE",
    )

    try:
        await run_in_threadpool(
            repository.deactivate_member,
            tenant_id,
            membership.user_id,
            target_user_id,
            request.expected_role,
            timestamp,
            audit_event,
        )
    except (
        MembershipActorAuthorizationError,
        MembershipStateConflictError,
    ) as error:
        _raise_membership_http_error(error)

    return MembershipMutationResponse(
        user_id=target_user_id,
        tenant_id=tenant_id,
        role=request.expected_role,
        status="INACTIVE",
        updated_at=timestamp,
    )
