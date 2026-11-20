from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.core.authorization import (
    TenantMembership,
    get_tenant_membership,
)
from app.repositories.submission import SubmissionRepository
from app.schemas.submission import (
    SubmissionCreateRequest,
    SubmissionListResponse,
    SubmissionResponse,
)
from app.services.submissions import (
    create_submission,
    get_authorized_submission,
    get_submission_repository,
    list_submissions,
)

router = APIRouter(prefix="/tenants", tags=["Submissions"])


@router.post(
    "/{tenant_id}/submissions",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft submission",
)
async def create_submission_endpoint(
    request: SubmissionCreateRequest,
    membership: Annotated[
        TenantMembership,
        Depends(get_tenant_membership),
    ],
    repository: Annotated[
        SubmissionRepository,
        Depends(get_submission_repository),
    ],
) -> SubmissionResponse:

    return await create_submission(
        request=request,
        membership=membership,
        repository=repository,
    )


@router.get(
    "/{tenant_id}/submissions/{submission_id}",
    response_model=SubmissionResponse,
    summary="Retrieve an authorized submission",
)
async def get_submission(
    submission_id: Annotated[
        str,
        Path(min_length=1, max_length=128),
    ],
    membership: Annotated[
        TenantMembership,
        Depends(get_tenant_membership),
    ],
    repository: Annotated[
        SubmissionRepository,
        Depends(get_submission_repository),
    ],
) -> SubmissionResponse:

    return await get_authorized_submission(
        submission_id=submission_id,
        membership=membership,
        repository=repository,
    )


@router.get(
    "/{tenant_id}/submissions",
    response_model=SubmissionListResponse,
    summary="List authorized submissions",
)
async def list_submissions_endpoint(
    membership: Annotated[
        TenantMembership,
        Depends(get_tenant_membership),
    ],
    repository: Annotated[
        SubmissionRepository,
        Depends(get_submission_repository),
    ],
    limit: Annotated[
        int,
        Query(ge=1, le=100),
    ] = 20,
    cursor: Annotated[
        str | None,
        Query(max_length=4096),
    ] = None,
) -> SubmissionListResponse:

    return await list_submissions(
        membership=membership,
        repository=repository,
        limit=limit,
        cursor=cursor,
    )
