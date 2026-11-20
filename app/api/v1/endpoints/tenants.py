from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.core.authorization import (
    TenantMembership,
    TenantRole,
    get_membership_repository,
    get_tenant_membership,
    require_tenant_admin,
)
from app.core.security import AuthenticatedUser, get_current_user
from app.repositories.membership import MembershipRepository
from app.schemas.membership import (
    ChangeMemberRoleRequest,
    DeactivateMemberRequest,
    MembershipMutationResponse,
)
from app.services.memberships import (
    change_member_role as change_member_role_service,
)
from app.services.memberships import (
    deactivate_member as deactivate_member_service,
)

router = APIRouter(prefix="/tenants", tags=["Tenants"])


@router.get("/{tenant_id}/context")
async def get_tenant_context(
    membership: Annotated[
        TenantMembership,
        Depends(get_tenant_membership),
    ],
) -> dict[str, str]:
    return {
        "tenant_id": membership.tenant_id,
        "user_id": membership.user_id,
        "role": membership.role.value,
    }


@router.get("/{tenant_id}/members")
async def list_tenant_members(
    membership: Annotated[
        TenantMembership,
        Depends(require_tenant_admin),
    ],
    repository: Annotated[
        MembershipRepository,
        Depends(get_membership_repository),
    ],
) -> list[dict[str, str | None]]:
    records = await run_in_threadpool(
        repository.list_tenant_members,
        membership.tenant_id,
    )

    members = []

    valid_roles = {role.value for role in TenantRole}
    valid_statuses = {"ACTIVE", "INACTIVE"}

    for record in records:
        user_id = record.get("user_id")
        tenant_id = record.get("tenant_id")
        role = record.get("role")
        status = record.get("status")
        created_at = record.get("created_at")

        if (
            not isinstance(user_id, str)
            or not user_id
            or tenant_id != membership.tenant_id
            or not isinstance(role, str)
            or role not in valid_roles
            or not isinstance(status, str)
            or status not in valid_statuses
        ):
            continue

        members.append(
            {
                "user_id": user_id,
                "tenant_id": membership.tenant_id,
                "role": role,
                "status": status,
                "created_at": (created_at if isinstance(created_at, str) else None),
            }
        )

    return members


@router.patch(
    "/{tenant_id}/members/{user_id}/role",
    response_model=MembershipMutationResponse,
)
async def change_tenant_member_role(
    tenant_id: str,
    user_id: str,
    request: ChangeMemberRoleRequest,
    membership: Annotated[
        TenantMembership,
        Depends(require_tenant_admin),
    ],
    repository: Annotated[
        MembershipRepository,
        Depends(get_membership_repository),
    ],
) -> MembershipMutationResponse:
    return await change_member_role_service(
        tenant_id=tenant_id,
        target_user_id=user_id,
        request=request,
        membership=membership,
        repository=repository,
    )


@router.post(
    "/{tenant_id}/members/{user_id}/deactivate",
    response_model=MembershipMutationResponse,
)
async def deactivate_tenant_member(
    tenant_id: str,
    user_id: str,
    request: DeactivateMemberRequest,
    membership: Annotated[
        TenantMembership,
        Depends(require_tenant_admin),
    ],
    repository: Annotated[
        MembershipRepository,
        Depends(get_membership_repository),
    ],
) -> MembershipMutationResponse:
    return await deactivate_member_service(
        tenant_id=tenant_id,
        target_user_id=user_id,
        request=request,
        membership=membership,
        repository=repository,
    )


@router.get("")
async def list_user_tenants(
    current_user: Annotated[
        AuthenticatedUser,
        Depends(get_current_user),
    ],
    repository: Annotated[
        MembershipRepository,
        Depends(get_membership_repository),
    ],
) -> list[dict[str, str]]:

    memberships = await run_in_threadpool(
        repository.list_memberships,
        current_user.sub,
    )

    tenants = []

    for membership in memberships:
        if (
            membership.get("user_id") != current_user.sub
            or membership.get("status") != "ACTIVE"
        ):
            continue

        tenant_id = membership.get("tenant_id")
        role = membership.get("role")

        if not isinstance(tenant_id, str) or not tenant_id:
            continue

        if not isinstance(role, str) or role not in {
            tenant_role.value for tenant_role in TenantRole
        }:
            continue

        tenants.append(
            {
                "tenant_id": tenant_id,
                "role": role,
            }
        )

    return tenants
