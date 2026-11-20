from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.core.authorization import (
    TenantMembership,
    get_tenant_membership,
)
from app.repositories.submission import SubmissionRepository
from app.schemas.workflow import (
    SubmissionTransitionRequest,
    SubmissionTransitionResponse,
)
from app.services.workflow import (
    get_workflow_repository,
    transition_submission,
)

router = APIRouter(prefix="/tenants", tags=["Submission Workflow"])


@router.post(
    "/{tenant_id}/submissions/{submission_id}/transitions",
    response_model=SubmissionTransitionResponse,
    summary="Transition a submission to another workflow state",
)
async def transition_submission_endpoint(
    request: SubmissionTransitionRequest,
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
    repository: Annotated[
        SubmissionRepository,
        Depends(get_workflow_repository),
    ],
) -> SubmissionTransitionResponse:

    return await transition_submission(
        tenant_id=tenant_id,
        submission_id=submission_id,
        request=request,
        membership=membership,
        repository=repository,
    )
