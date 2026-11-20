import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

from app.core.authorization import TenantMembership, TenantRole
from app.schemas.document import (
    DocumentContentType,
    DocumentStatus,
    DocumentUploadRequest,
)
from app.services.documents import (
    complete_document_upload,
    create_document_download,
    create_document_upload,
    decode_document_cursor,
    encode_document_cursor,
    list_submission_documents,
)
from app.services.storage import StorageObjectValidationError


@pytest.fixture
def submitter():
    return TenantMembership(
        user_id="user-a",
        tenant_id="tenant-a",
        role=TenantRole.SUBMITTER,
        status="ACTIVE",
    )


@pytest.fixture
def reviewer():
    return TenantMembership(
        user_id="reviewer-a",
        tenant_id="tenant-a",
        role=TenantRole.REVIEWER,
        status="ACTIVE",
    )


@pytest.fixture
def submission_repository():
    repository = MagicMock()
    repository.get_submission.return_value = {
        "PK": "TENANT#tenant-a",
        "SK": "SUBMISSION#submission-123",
        "tenant_id": "tenant-a",
        "submission_id": "submission-123",
        "owner_id": "user-a",
        "status": "DRAFT",
    }
    return repository


@pytest.fixture
def document_repository():
    return MagicMock()


@pytest.fixture
def storage():
    service = MagicMock()

    service.generate_upload_request.return_value = {
        "url": "https://example.com/upload",
        "fields": {"key": "test-object"},
    }

    service.get_object_metadata.return_value = {
        "ContentLength": 1024,
        "ContentType": "application/pdf",
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": ("arn:aws:kms:ap-south-1:123456789012:test-key-id"),
        "VersionId": "version-123",
    }

    service.generate_download_url.return_value = "https://example.com/download"

    return service


@pytest.fixture
def upload_request():
    return DocumentUploadRequest(
        filename="invoice.pdf",
        content_type=DocumentContentType.PDF,
        size_bytes=1024,
    )


def run_async(coroutine):
    return asyncio.run(coroutine)


def pending_document():
    now = datetime.now(UTC).replace(microsecond=0)

    expires_at = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    upload_url_expires_at = (now + timedelta(seconds=300)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    upload_hygiene_after = (
        now + timedelta(seconds=300) + timedelta(hours=24)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "tenant_id": "tenant-a",
        "submission_id": "submission-123",
        "document_id": "document-456",
        "owner_id": "user-a",
        "object_key": ("tenants/tenant-a/submissions/submission-123/document-456"),
        "original_filename": "invoice.pdf",
        "content_type": "application/pdf",
        "size_bytes": 1024,
        "status": "PENDING_UPLOAD",
        "expires_at": expires_at,
        "GSI3PK": "PENDING_UPLOAD#02",
        "GSI3SK": f"{expires_at}#document-456",
        "upload_url_expires_at": upload_url_expires_at,
        "upload_hygiene_after": upload_hygiene_after,
        "created_at": "2026-11-12T12:00:00Z",
    }


def uploaded_document():
    document = pending_document()
    document["status"] = "UPLOADED"
    document["version_id"] = "version-123"
    return document


def test_submitter_can_request_document_upload(
    submitter,
    submission_repository,
    document_repository,
    storage,
    upload_request,
):
    result = run_async(
        create_document_upload(
            tenant_id="tenant-a",
            submission_id="submission-123",
            request=upload_request,
            membership=submitter,
            submission_repository=submission_repository,
            document_repository=document_repository,
            storage=storage,
        )
    )

    assert result.document_id
    assert result.upload_url == "https://example.com/upload"
    assert result.expires_in == 300

    document = document_repository.create_document.call_args.args[0]

    assert document["tenant_id"] == "tenant-a"
    assert document["submission_id"] == "submission-123"
    assert document["owner_id"] == "user-a"
    assert document["status"] == "PENDING_UPLOAD"
    assert document["expires_at"]
    assert document["upload_url_expires_at"]
    assert document["upload_hygiene_after"]

    upload_url_expiry = datetime.strptime(
        document["upload_url_expires_at"],
        "%Y-%m-%dT%H:%M:%SZ",
    ).replace(tzinfo=UTC)

    hygiene_after = datetime.strptime(
        document["upload_hygiene_after"],
        "%Y-%m-%dT%H:%M:%SZ",
    ).replace(tzinfo=UTC)

    assert hygiene_after == (upload_url_expiry + timedelta(hours=24))
    assert document["GSI3PK"].startswith("PENDING_UPLOAD#")
    assert document["GSI3SK"] == (f"{document['expires_at']}#{document['document_id']}")
    assert document["GSI3PK"][-2:].isdigit()
    assert 0 <= int(document["GSI3PK"][-2:]) < 4
    assert document["object_key"] == (
        f"tenants/tenant-a/submissions/submission-123/{document['document_id']}"
    )


def test_reviewer_cannot_request_upload(
    reviewer,
    submission_repository,
    document_repository,
    storage,
    upload_request,
):
    with pytest.raises(HTTPException) as exc:
        run_async(
            create_document_upload(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=upload_request,
                membership=reviewer,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 403
    submission_repository.get_submission.assert_not_called()
    document_repository.create_document.assert_not_called()
    storage.generate_upload_request.assert_not_called()


def test_submitter_cannot_upload_to_another_users_submission(
    submitter,
    submission_repository,
    document_repository,
    storage,
    upload_request,
):
    submission_repository.get_submission.return_value["owner_id"] = "user-b"

    with pytest.raises(HTTPException) as exc:
        run_async(
            create_document_upload(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=upload_request,
                membership=submitter,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 403
    document_repository.create_document.assert_not_called()
    storage.generate_upload_request.assert_not_called()


def test_submitter_cannot_upload_to_non_draft_submission(
    submitter,
    submission_repository,
    document_repository,
    storage,
    upload_request,
):
    submission_repository.get_submission.return_value["status"] = "SUBMITTED"

    with pytest.raises(HTTPException) as exc:
        run_async(
            create_document_upload(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=upload_request,
                membership=submitter,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 409
    document_repository.create_document.assert_not_called()
    storage.generate_upload_request.assert_not_called()


def test_submitter_can_complete_verified_upload(
    submitter,
    submission_repository,
    document_repository,
    storage,
):
    document = pending_document()
    document_repository.get_document.return_value = document

    result = run_async(
        complete_document_upload(
            tenant_id="tenant-a",
            submission_id="submission-123",
            document_id="document-456",
            membership=submitter,
            submission_repository=submission_repository,
            document_repository=document_repository,
            storage=storage,
        )
    )

    assert result.status == DocumentStatus.UPLOADED
    assert result.document_id == "document-456"

    storage.get_object_metadata.assert_called_once_with(
        "tenants/tenant-a/submissions/submission-123/document-456"
    )

    storage.validate_object_metadata.assert_called_once_with(
        storage.get_object_metadata.return_value,
        1024,
        "application/pdf",
    )

    storage.validate_object_content.assert_called_once_with(
        "tenants/tenant-a/submissions/submission-123/document-456",
        "version-123",
        "application/pdf",
    )

    document_repository.mark_document_uploaded.assert_called_once()

    call_args = document_repository.mark_document_uploaded.call_args.args

    assert call_args[0] == "tenant-a"
    assert call_args[1] == "submission-123"
    assert call_args[2] == "document-456"
    assert call_args[4] == "version-123"
    assert call_args[5] == "user-a"
    assert call_args[6] == 1024

    assert call_args[7] == "PENDING_UPLOAD#02"
    assert call_args[8].endswith("#document-456")

    assert call_args[9] == "UPLOADED#02"
    assert call_args[10].endswith("#document-456")

    assert call_args[11] == document["upload_url_expires_at"]
    assert call_args[12] == document["upload_hygiene_after"]


def test_upload_completion_rejects_invalid_document_signature(
    submitter,
    submission_repository,
    document_repository,
    storage,
):
    document_repository.get_document.return_value = pending_document()

    storage.validate_object_content.side_effect = StorageObjectValidationError(
        "Invalid PDF signature"
    )

    with pytest.raises(HTTPException) as exc:
        run_async(
            complete_document_upload(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=submitter,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 400

    storage.validate_object_content.assert_called_once_with(
        "tenants/tenant-a/submissions/submission-123/document-456",
        "version-123",
        "application/pdf",
    )

    document_repository.mark_document_uploaded.assert_not_called()


@pytest.mark.parametrize(
    "expiry",
    [
        None,
        "",
        "not-a-timestamp",
        "2026-11-14T12:00:00+05:30",
        "2026-11-14T12:00:00.123Z",
        "2020-01-01T00:00:00Z",
    ],
)
def test_upload_completion_rejects_invalid_or_expired_reservation(
    submitter,
    submission_repository,
    document_repository,
    storage,
    expiry,
):
    document = pending_document()

    if expiry is None:
        document.pop("expires_at")
    else:
        document["expires_at"] = expiry

    document_repository.get_document.return_value = document

    with pytest.raises(HTTPException) as exc:
        run_async(
            complete_document_upload(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=submitter,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 409
    storage.get_object_metadata.assert_not_called()
    storage.validate_object_metadata.assert_not_called()
    document_repository.mark_document_uploaded.assert_not_called()


def test_upload_completion_rejects_size_mismatch(
    submitter,
    submission_repository,
    document_repository,
    storage,
):
    document_repository.get_document.return_value = pending_document()

    storage.validate_object_metadata.side_effect = StorageObjectValidationError(
        "Size mismatch"
    )

    with pytest.raises(HTTPException) as exc:
        run_async(
            complete_document_upload(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=submitter,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 400
    document_repository.mark_document_uploaded.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        "Content type mismatch",
        "Incorrect encryption algorithm",
        "Incorrect KMS key",
    ],
)
def test_upload_completion_rejects_storage_validation_failures(
    submitter,
    submission_repository,
    document_repository,
    storage,
    failure,
):
    document_repository.get_document.return_value = pending_document()

    storage.validate_object_metadata.side_effect = StorageObjectValidationError(failure)

    with pytest.raises(HTTPException) as exc:
        run_async(
            complete_document_upload(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=submitter,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 400
    document_repository.mark_document_uploaded.assert_not_called()


def test_upload_completion_rejects_missing_object(
    submitter,
    submission_repository,
    document_repository,
    storage,
):
    document_repository.get_document.return_value = pending_document()

    storage.get_object_metadata.side_effect = ClientError(
        {
            "Error": {
                "Code": "404",
                "Message": "Not Found",
            }
        },
        "HeadObject",
    )

    with pytest.raises(HTTPException) as exc:
        run_async(
            complete_document_upload(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=submitter,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 409
    document_repository.mark_document_uploaded.assert_not_called()


def test_upload_completion_rejects_unexpected_storage_error(
    submitter,
    submission_repository,
    document_repository,
    storage,
):
    document_repository.get_document.return_value = pending_document()

    storage.get_object_metadata.side_effect = ClientError(
        {
            "Error": {
                "Code": "InternalError",
                "Message": "Internal error",
            }
        },
        "HeadObject",
    )

    with pytest.raises(HTTPException) as exc:
        run_async(
            complete_document_upload(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=submitter,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 503
    document_repository.mark_document_uploaded.assert_not_called()


def test_upload_completion_rejects_missing_version_id(
    submitter,
    submission_repository,
    document_repository,
    storage,
):
    document_repository.get_document.return_value = pending_document()

    storage.get_object_metadata.return_value["VersionId"] = "null"

    with pytest.raises(HTTPException) as exc:
        run_async(
            complete_document_upload(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=submitter,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 503
    document_repository.mark_document_uploaded.assert_not_called()


def test_upload_completion_rejects_wrong_document_object_key(
    submitter,
    submission_repository,
    document_repository,
    storage,
):
    document = pending_document()
    document["object_key"] = "tenants/tenant-b/submissions/submission-123/document-456"
    document_repository.get_document.return_value = document

    with pytest.raises(HTTPException) as exc:
        run_async(
            complete_document_upload(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=submitter,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 404
    storage.get_object_metadata.assert_not_called()
    document_repository.mark_document_uploaded.assert_not_called()


@pytest.mark.parametrize(
    "submission_status",
    [
        "SUBMITTED",
        "IN_REVIEW",
        "APPROVED",
        "REJECTED",
        "NEEDS_CHANGES",
        "CLOSED",
    ],
)
def test_reviewer_can_download_uploaded_document(
    reviewer,
    submission_repository,
    document_repository,
    storage,
    submission_status,
):
    submission_repository.get_submission.return_value["status"] = submission_status
    document_repository.get_document.return_value = uploaded_document()

    result = run_async(
        create_document_download(
            tenant_id="tenant-a",
            submission_id="submission-123",
            document_id="document-456",
            membership=reviewer,
            submission_repository=submission_repository,
            document_repository=document_repository,
            storage=storage,
        )
    )

    assert result.document_id == "document-456"
    assert result.download_url == "https://example.com/download"

    storage.generate_download_url.assert_called_once_with(
        "tenants/tenant-a/submissions/submission-123/document-456",
        "application/pdf",
        "invoice.pdf",
        "version-123",
    )


def test_reviewer_cannot_download_document_from_draft_submission(
    reviewer,
    submission_repository,
    document_repository,
    storage,
):
    submission_repository.get_submission.return_value["status"] = "DRAFT"

    with pytest.raises(HTTPException) as exc:
        run_async(
            create_document_download(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=reviewer,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Document not found"
    document_repository.get_document.assert_not_called()
    storage.generate_download_url.assert_not_called()


@pytest.mark.parametrize(
    "submission_status",
    [
        None,
        "",
        "UNKNOWN",
        "DRAFT",
    ],
)
def test_reviewer_download_fails_closed_for_unapproved_submission_status(
    reviewer,
    submission_repository,
    document_repository,
    storage,
    submission_status,
):
    submission_repository.get_submission.return_value["status"] = submission_status

    with pytest.raises(HTTPException) as exc:
        run_async(
            create_document_download(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=reviewer,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 404
    document_repository.get_document.assert_not_called()
    storage.generate_download_url.assert_not_called()


def test_submitter_cannot_download_another_users_document(
    submitter,
    submission_repository,
    document_repository,
    storage,
):
    submission_repository.get_submission.return_value["owner_id"] = "user-b"

    with pytest.raises(HTTPException) as exc:
        run_async(
            create_document_download(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=submitter,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 403
    document_repository.get_document.assert_not_called()
    storage.generate_download_url.assert_not_called()


def test_submitter_can_download_own_uploaded_document(
    submitter,
    submission_repository,
    document_repository,
    storage,
):
    document_repository.get_document.return_value = uploaded_document()

    result = run_async(
        create_document_download(
            tenant_id="tenant-a",
            submission_id="submission-123",
            document_id="document-456",
            membership=submitter,
            submission_repository=submission_repository,
            document_repository=document_repository,
            storage=storage,
        )
    )

    assert result.document_id == "document-456"
    assert result.download_url == "https://example.com/download"

    storage.generate_download_url.assert_called_once_with(
        "tenants/tenant-a/submissions/submission-123/document-456",
        "application/pdf",
        "invoice.pdf",
        "version-123",
    )


@pytest.mark.parametrize(
    "owner_id",
    [
        "user-b",
        None,
        "",
        123,
    ],
)
def test_submitter_cannot_download_document_not_owned_by_them(
    submitter,
    submission_repository,
    document_repository,
    storage,
    owner_id,
):
    document = uploaded_document()
    document["owner_id"] = owner_id
    document_repository.get_document.return_value = document

    with pytest.raises(HTTPException) as exc:
        run_async(
            create_document_download(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=submitter,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Document not found"
    storage.generate_download_url.assert_not_called()


def test_pending_document_cannot_be_downloaded(
    submitter,
    submission_repository,
    document_repository,
    storage,
):
    document_repository.get_document.return_value = pending_document()

    with pytest.raises(HTTPException) as exc:
        run_async(
            create_document_download(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=submitter,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 409
    storage.generate_download_url.assert_not_called()


def test_download_rejects_wrong_document_object_key(
    reviewer,
    submission_repository,
    document_repository,
    storage,
):
    document = uploaded_document()
    document["object_key"] = "tenants/tenant-b/submissions/submission-123/document-456"
    document_repository.get_document.return_value = document

    with pytest.raises(HTTPException) as exc:
        run_async(
            create_document_download(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=reviewer,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 404
    storage.generate_download_url.assert_not_called()


def test_download_rejects_missing_version_id(
    reviewer,
    submission_repository,
    document_repository,
    storage,
):
    submission_repository.get_submission.return_value["status"] = "SUBMITTED"

    document = uploaded_document()
    document["version_id"] = "null"
    document_repository.get_document.return_value = document

    with pytest.raises(HTTPException) as exc:
        run_async(
            create_document_download(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=reviewer,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 409
    storage.generate_download_url.assert_not_called()


def test_upload_request_maps_document_quota_to_conflict(
    submitter,
    submission_repository,
    document_repository,
    storage,
    upload_request,
):
    from app.repositories.document import DocumentQuotaExceededError

    document_repository.create_document.side_effect = DocumentQuotaExceededError

    with pytest.raises(HTTPException) as exc:
        run_async(
            create_document_upload(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=upload_request,
                membership=submitter,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Submission document quota exceeded"


@pytest.mark.parametrize(
    "aws_error",
    [
        ClientError(
            {
                "Error": {
                    "Code": "InternalError",
                    "Message": "S3 internal error",
                }
            },
            "GeneratePresignedPost",
        ),
        BotoCoreError(
            error_msg="Credential resolution failed",
        ),
    ],
)
def test_upload_url_generation_aws_errors_return_503(
    submitter,
    submission_repository,
    document_repository,
    storage,
    upload_request,
    aws_error,
):
    storage.generate_upload_request.side_effect = aws_error

    with pytest.raises(HTTPException) as exc:
        run_async(
            create_document_upload(
                tenant_id="tenant-a",
                submission_id="submission-123",
                request=upload_request,
                membership=submitter,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "Unable to prepare document upload"

    document_repository.create_document.assert_not_called()


@pytest.mark.parametrize(
    "aws_error",
    [
        ClientError(
            {
                "Error": {
                    "Code": "InternalError",
                    "Message": "S3 internal error",
                }
            },
            "GeneratePresignedUrl",
        ),
        BotoCoreError(
            error_msg="Credential resolution failed",
        ),
    ],
)
def test_download_url_generation_aws_errors_return_503(
    submitter,
    submission_repository,
    document_repository,
    storage,
    aws_error,
):
    document_repository.get_document.return_value = uploaded_document()
    storage.generate_download_url.side_effect = aws_error

    with pytest.raises(HTTPException) as exc:
        run_async(
            create_document_download(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=submitter,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "Unable to prepare document download"


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("original_filename", ""),
        ("original_filename", None),
        ("content_type", "application/octet-stream"),
        ("content_type", ["application/pdf"]),
        ("size_bytes", 0),
        ("size_bytes", -1),
        ("size_bytes", True),
        ("size_bytes", "1024"),
        ("created_at", "invalid-timestamp"),
        ("status", "UNKNOWN"),
        ("status", ["UPLOADED"]),
    ],
)
def test_upload_completion_rejects_malformed_document_record(
    submitter,
    submission_repository,
    document_repository,
    storage,
    field,
    invalid_value,
):
    document = pending_document()
    document[field] = invalid_value
    document_repository.get_document.return_value = document

    with pytest.raises(HTTPException) as exc_info:
        run_async(
            complete_document_upload(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=submitter,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc_info.value.status_code == 409
    storage.get_object_metadata.assert_not_called()
    document_repository.mark_document_uploaded.assert_not_called()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("original_filename", ""),
        ("original_filename", None),
        ("content_type", "application/octet-stream"),
        ("content_type", ["application/pdf"]),
        ("size_bytes", 0),
        ("size_bytes", True),
        ("size_bytes", "1024"),
        ("created_at", "invalid-timestamp"),
        ("status", "UNKNOWN"),
        ("status", ["UPLOADED"]),
        ("version_id", None),
        ("version_id", ""),
        ("version_id", "null"),
    ],
)
def test_download_rejects_malformed_document_record(
    reviewer,
    submission_repository,
    document_repository,
    storage,
    field,
    invalid_value,
):
    submission_repository.get_submission.return_value["status"] = "SUBMITTED"
    document = uploaded_document()
    document[field] = invalid_value
    document_repository.get_document.return_value = document

    with pytest.raises(HTTPException) as exc_info:
        run_async(
            create_document_download(
                tenant_id="tenant-a",
                submission_id="submission-123",
                document_id="document-456",
                membership=reviewer,
                submission_repository=submission_repository,
                document_repository=document_repository,
                storage=storage,
            )
        )

    assert exc_info.value.status_code == 409
    storage.generate_download_url.assert_not_called()


def document_listing_record():
    document = pending_document()

    document.update(
        {
            "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
            "SK": "DOCUMENT#document-456",
            "entity_type": "DOCUMENT",
        }
    )

    return document


def run_document_listing(
    membership,
    submission_repository,
    document_repository,
    cursor=None,
    limit=20,
):
    return run_async(
        list_submission_documents(
            tenant_id="tenant-a",
            submission_id="submission-123",
            membership=membership,
            submission_repository=submission_repository,
            document_repository=document_repository,
            limit=limit,
            cursor=cursor,
        )
    )


def test_submitter_can_list_own_submission_documents(
    submitter,
    submission_repository,
    document_repository,
):
    document_repository.list_documents.return_value = {
        "Items": [document_listing_record()],
    }

    result = run_document_listing(
        submitter,
        submission_repository,
        document_repository,
    )

    assert len(result.items) == 1

    document = result.items[0]

    assert document.document_id == "document-456"
    assert document.submission_id == "submission-123"
    assert document.filename == "invoice.pdf"
    assert document.content_type == "application/pdf"
    assert document.size_bytes == 1024
    assert document.status == DocumentStatus.PENDING_UPLOAD

    document_repository.list_documents.assert_called_once_with(
        "tenant-a",
        "submission-123",
        20,
        None,
    )


def test_document_listing_does_not_expose_internal_metadata(
    submitter,
    submission_repository,
    document_repository,
):
    document_repository.list_documents.return_value = {
        "Items": [document_listing_record()],
    }

    result = run_document_listing(
        submitter,
        submission_repository,
        document_repository,
    )

    response_document = result.items[0].model_dump()

    forbidden_fields = {
        "owner_id",
        "object_key",
        "version_id",
        "expires_at",
        "upload_url_expires_at",
        "upload_hygiene_after",
        "GSI3PK",
        "GSI3SK",
        "PK",
        "SK",
        "entity_type",
    }

    assert forbidden_fields.isdisjoint(response_document)


def test_submitter_cannot_list_another_users_submission_documents(
    submitter,
    submission_repository,
    document_repository,
):
    submission_repository.get_submission.return_value["owner_id"] = "user-b"

    with pytest.raises(HTTPException) as exc:
        run_document_listing(
            submitter,
            submission_repository,
            document_repository,
        )

    assert exc.value.status_code == 403
    document_repository.list_documents.assert_not_called()


def test_reviewer_cannot_list_documents_from_draft_submission(
    reviewer,
    submission_repository,
    document_repository,
):
    submission_repository.get_submission.return_value["status"] = "DRAFT"

    with pytest.raises(HTTPException) as exc:
        run_document_listing(
            reviewer,
            submission_repository,
            document_repository,
        )

    assert exc.value.status_code == 404
    document_repository.list_documents.assert_not_called()


def test_reviewer_can_list_documents_from_submitted_submission(
    reviewer,
    submission_repository,
    document_repository,
):
    submission_repository.get_submission.return_value["status"] = "SUBMITTED"
    document_repository.list_documents.return_value = {
        "Items": [document_listing_record()],
    }

    result = run_document_listing(
        reviewer,
        submission_repository,
        document_repository,
    )

    assert len(result.items) == 1
    assert result.items[0].document_id == "document-456"


def test_document_listing_rejects_invalid_limit(
    submitter,
    submission_repository,
    document_repository,
):
    with pytest.raises(HTTPException) as exc:
        run_document_listing(
            submitter,
            submission_repository,
            document_repository,
            limit=101,
        )

    assert exc.value.status_code == 422
    document_repository.list_documents.assert_not_called()


def test_document_listing_rejects_oversized_cursor(
    submitter,
    submission_repository,
    document_repository,
):
    with pytest.raises(HTTPException) as exc:
        run_document_listing(
            submitter,
            submission_repository,
            document_repository,
            cursor="a" * 4097,
        )

    assert exc.value.status_code == 400
    document_repository.list_documents.assert_not_called()


def test_document_listing_rejects_malformed_cursor(
    submitter,
    submission_repository,
    document_repository,
):
    with pytest.raises(HTTPException) as exc:
        run_document_listing(
            submitter,
            submission_repository,
            document_repository,
            cursor="not-a-valid-cursor",
        )

    assert exc.value.status_code == 400
    document_repository.list_documents.assert_not_called()


def test_document_cursor_is_bound_to_user_and_role(submitter):
    cursor = encode_document_cursor(
        {
            "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
            "SK": "DOCUMENT#document-456",
        },
        submitter,
        "submission-123",
    )

    different_user = TenantMembership(
        user_id="user-b",
        tenant_id="tenant-a",
        role=TenantRole.SUBMITTER,
        status="ACTIVE",
    )

    with pytest.raises(HTTPException) as exc:
        decode_document_cursor(
            cursor,
            different_user,
            "submission-123",
        )

    assert exc.value.status_code == 400


def test_document_cursor_rejects_another_submission_partition(submitter):
    with pytest.raises(ValueError):
        encode_document_cursor(
            {
                "PK": "TENANT#tenant-a#SUBMISSION#another-submission",
                "SK": "DOCUMENT#document-456",
            },
            submitter,
            "submission-123",
        )


def test_document_listing_rejects_wrong_document_owner(
    submitter,
    submission_repository,
    document_repository,
):
    document = document_listing_record()
    document["owner_id"] = "user-b"

    document_repository.list_documents.return_value = {
        "Items": [document],
    }

    with pytest.raises(HTTPException) as exc:
        run_document_listing(
            submitter,
            submission_repository,
            document_repository,
        )

    assert exc.value.status_code == 500


def test_document_listing_rejects_wrong_document_partition(
    submitter,
    submission_repository,
    document_repository,
):
    document = document_listing_record()
    document["PK"] = "TENANT#tenant-b#SUBMISSION#submission-123"

    document_repository.list_documents.return_value = {
        "Items": [document],
    }

    with pytest.raises(HTTPException) as exc:
        run_document_listing(
            submitter,
            submission_repository,
            document_repository,
        )

    assert exc.value.status_code == 500


def test_document_listing_returns_next_cursor(
    submitter,
    submission_repository,
    document_repository,
):
    next_key = {
        "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
        "SK": "DOCUMENT#document-456",
    }

    document_repository.list_documents.return_value = {
        "Items": [document_listing_record()],
        "LastEvaluatedKey": next_key,
    }

    result = run_document_listing(
        submitter,
        submission_repository,
        document_repository,
    )

    assert result.next_cursor is not None

    decoded = decode_document_cursor(
        result.next_cursor,
        submitter,
        "submission-123",
    )

    assert decoded == next_key


def test_document_listing_uses_supplied_cursor(
    submitter,
    submission_repository,
    document_repository,
):
    key = {
        "PK": "TENANT#tenant-a#SUBMISSION#submission-123",
        "SK": "DOCUMENT#document-456",
    }

    cursor = encode_document_cursor(
        key,
        submitter,
        "submission-123",
    )

    document_repository.list_documents.return_value = {
        "Items": [],
    }

    run_document_listing(
        submitter,
        submission_repository,
        document_repository,
        cursor=cursor,
    )

    document_repository.list_documents.assert_called_once_with(
        "tenant-a",
        "submission-123",
        20,
        key,
    )
