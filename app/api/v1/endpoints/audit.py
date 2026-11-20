from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.core.authorization import (
    TenantMembership,
    get_tenant_membership,
    require_tenant_admin,
)
from app.repositories.audit import AuditRepository
from app.repositories.submission import SubmissionRepository
from app.schemas.workflow import (
    AuditEventListResponse,
    TenantAuditEventListResponse,
)
from app.services.audit import (
    get_audit_repository,
    get_submission_audit_history,
    get_tenant_audit_history,
)
from app.services.submissions import get_submission_repository

router = APIRouter(prefix="/tenants", tags=["Audit History"])


@router.get(
    "/{tenant_id}/submissions/{submission_id}/audit-events",
    response_model=AuditEventListResponse,
    summary="Retrieve submission audit history",
)
async def get_submission_audit_events(
    tenant_id: Annotated[
        str,
        Path(min_length=1, max_length=128),
    ],
    submission_id: Annotated[
        str,
        Path(min_length=1, max_length=128),
    ],
    membership: Annotated[
        TenantMembership,
        Depends(get_tenant_membership),
    ],
    submission_repository: Annotated[
        SubmissionRepository,
        Depends(get_submission_repository),
    ],
    audit_repository: Annotated[
        AuditRepository,
        Depends(get_audit_repository),
    ],
    limit: Annotated[
        int,
        Query(ge=1, le=100),
    ] = 20,
    cursor: Annotated[
        str | None,
        Query(max_length=4096),
    ] = None,
) -> AuditEventListResponse:

    return await get_submission_audit_history(
        tenant_id=tenant_id,
        submission_id=submission_id,
        membership=membership,
        submission_repository=submission_repository,
        audit_repository=audit_repository,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/{tenant_id}/audit-events",
    response_model=TenantAuditEventListResponse,
    summary="Retrieve tenant-wide audit history",
)
async def get_tenant_audit_events(
    tenant_id: Annotated[
        str,
        Path(min_length=1, max_length=128),
    ],
    membership: Annotated[
        TenantMembership,
        Depends(require_tenant_admin),
    ],
    audit_repository: Annotated[
        AuditRepository,
        Depends(get_audit_repository),
    ],
    limit: Annotated[
        int,
        Query(ge=1, le=100),
    ] = 20,
    cursor: Annotated[
        str | None,
        Query(max_length=4096),
    ] = None,
) -> TenantAuditEventListResponse:

    return await get_tenant_audit_history(
        tenant_id=tenant_id,
        membership=membership,
        audit_repository=audit_repository,
        limit=limit,
        cursor=cursor,
    )
