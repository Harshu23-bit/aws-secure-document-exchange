from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.core.authorization import (
    TenantMembership,
    get_tenant_membership,
)
from app.repositories.document import (
    DocumentRepository,
)
from app.repositories.submission import SubmissionRepository
from app.schemas.document import (
    DocumentDownloadResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadRequest,
    DocumentUploadResponse,
)
from app.services.documents import (
    complete_document_upload,
    create_document_download,
    create_document_upload,
    get_document_repository,
    get_storage_service,
    list_submission_documents,
)
from app.services.storage import S3StorageService
from app.services.submissions import get_submission_repository

router = APIRouter(prefix="/tenants", tags=["Documents"])


@router.post(
    "/{tenant_id}/submissions/{submission_id}/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a document upload",
)
async def request_document_upload(
    request: DocumentUploadRequest,
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
    document_repository: Annotated[
        DocumentRepository,
        Depends(get_document_repository),
    ],
    storage: Annotated[
        S3StorageService,
        Depends(get_storage_service),
    ],
) -> DocumentUploadResponse:

    return await create_document_upload(
        tenant_id=tenant_id,
        submission_id=submission_id,
        request=request,
        membership=membership,
        submission_repository=submission_repository,
        document_repository=document_repository,
        storage=storage,
    )


@router.post(
    "/{tenant_id}/submissions/{submission_id}/documents/{document_id}/complete",
    response_model=DocumentResponse,
    summary="Verify document upload completion",
)
async def complete_document_upload_endpoint(
    tenant_id: Annotated[
        str,
        Path(min_length=1, max_length=128),
    ],
    submission_id: Annotated[
        str,
        Path(min_length=1, max_length=128),
    ],
    document_id: Annotated[
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
    document_repository: Annotated[
        DocumentRepository,
        Depends(get_document_repository),
    ],
    storage: Annotated[
        S3StorageService,
        Depends(get_storage_service),
    ],
) -> DocumentResponse:

    return await complete_document_upload(
        tenant_id=tenant_id,
        submission_id=submission_id,
        document_id=document_id,
        membership=membership,
        submission_repository=submission_repository,
        document_repository=document_repository,
        storage=storage,
    )


@router.get(
    "/{tenant_id}/submissions/{submission_id}/documents/{document_id}/download",
    response_model=DocumentDownloadResponse,
    summary="Request an authorized document download",
)
async def download_document(
    tenant_id: Annotated[
        str,
        Path(min_length=1, max_length=128),
    ],
    submission_id: Annotated[
        str,
        Path(min_length=1, max_length=128),
    ],
    document_id: Annotated[
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
    document_repository: Annotated[
        DocumentRepository,
        Depends(get_document_repository),
    ],
    storage: Annotated[
        S3StorageService,
        Depends(get_storage_service),
    ],
) -> DocumentDownloadResponse:

    return await create_document_download(
        tenant_id=tenant_id,
        submission_id=submission_id,
        document_id=document_id,
        membership=membership,
        submission_repository=submission_repository,
        document_repository=document_repository,
        storage=storage,
    )


@router.get(
    "/{tenant_id}/submissions/{submission_id}/documents",
    response_model=DocumentListResponse,
    summary="List authorized submission documents",
)
async def list_documents(
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
    document_repository: Annotated[
        DocumentRepository,
        Depends(get_document_repository),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[
        str | None,
        Query(max_length=4096),
    ] = None,
) -> DocumentListResponse:

    return await list_submission_documents(
        tenant_id=tenant_id,
        submission_id=submission_id,
        membership=membership,
        submission_repository=submission_repository,
        document_repository=document_repository,
        limit=limit,
        cursor=cursor,
    )
