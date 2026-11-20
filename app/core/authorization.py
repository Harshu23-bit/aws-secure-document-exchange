import logging
from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from fastapi import Depends, HTTPException, Path, status
from starlette.concurrency import run_in_threadpool

from app.core.security import AuthenticatedUser, get_current_user
from app.repositories.membership import (
    DynamoDBMembershipRepository,
    MembershipRepository,
)

logger = logging.getLogger(__name__)


class TenantRole(str, Enum):
    SUBMITTER = "SUBMITTER"
    REVIEWER = "REVIEWER"
    TENANT_ADMIN = "TENANT_ADMIN"


@dataclass(frozen=True)
class TenantMembership:
    user_id: str
    tenant_id: str
    role: TenantRole
    status: str


def get_membership_repository() -> MembershipRepository:
    from app.core.config import get_settings

    return DynamoDBMembershipRepository(get_settings())


async def get_tenant_membership(
    tenant_id: Annotated[str, Path(min_length=1, max_length=128)],
    current_user: Annotated[
        AuthenticatedUser,
        Depends(get_current_user),
    ],
    repository: Annotated[
        MembershipRepository,
        Depends(get_membership_repository),
    ],
) -> TenantMembership:

    membership = await run_in_threadpool(
        repository.get_membership,
        current_user.sub,
        tenant_id,
    )

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this tenant",
        )

    expected_user_id = current_user.sub
    expected_tenant_id = tenant_id

    if (
        membership.get("user_id") != expected_user_id
        or membership.get("tenant_id") != expected_tenant_id
    ):
        logger.error(
            "Membership record identity mismatch",
            extra={"event": "membership_identity_mismatch"},
        )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this tenant",
        )

    if membership.get("status") != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this tenant",
        )

    try:
        role = TenantRole(membership["role"])
    except (KeyError, ValueError, TypeError):
        logger.error(
            "Invalid tenant membership role",
            extra={"event": "invalid_membership_role"},
        )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this tenant",
        )

    return TenantMembership(
        user_id=expected_user_id,
        tenant_id=expected_tenant_id,
        role=role,
        status="ACTIVE",
    )


async def require_tenant_admin(
    membership: Annotated[
        TenantMembership,
        Depends(get_tenant_membership),
    ],
) -> TenantMembership:
    if membership.role != TenantRole.TENANT_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant administrator privileges required",
        )

    return membership
