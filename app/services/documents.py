import base64
import binascii
import json
import logging
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.core.authorization import TenantMembership, TenantRole
from app.core.config import get_settings
from app.repositories.document import (
    DocumentAlreadyExistsError,
    DocumentNotFoundError,
    DocumentQuotaExceededError,
    DocumentRepository,
    DocumentStateConflictError,
    DynamoDBDocumentRepository,
)
from app.repositories.submission import SubmissionRepository
from app.schemas.document import (
    DocumentContentType,
    DocumentDownloadResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentStatus,
    DocumentUploadRequest,
    DocumentUploadResponse,
)
from app.services.storage import (
    S3StorageService,
    StorageObjectValidationError,
)

logger = logging.getLogger(__name__)

UPLOAD_URL_EXPIRY = 300
UPLOAD_HYGIENE_GRACE_SECONDS = 86400
DOCUMENT_RESERVATION_TTL_SECONDS = 1800
DOCUMENT_EXPIRY_SHARD_COUNT = 4
DOWNLOAD_URL_EXPIRY = 300

REVIEWER_DOWNLOADABLE_SUBMISSION_STATUSES = frozenset(
    {
        "SUBMITTED",
        "IN_REVIEW",
        "APPROVED",
        "REJECTED",
        "NEEDS_CHANGES",
        "CLOSED",
    }
)


def get_document_repository():
    return DynamoDBDocumentRepository(get_settings())


def get_storage_service():
    return S3StorageService(get_settings())


def format_utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("A timezone-aware UTC datetime is required")
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_canonical_utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    if format_utc_timestamp(parsed) != value:
        return None
    return parsed


def get_document_expiry_shard(document_id: str) -> int:
    digest = sha256(document_id.encode("utf-8")).digest()
    return digest[0] % DOCUMENT_EXPIRY_SHARD_COUNT


def get_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def sanitize_filename(filename: str) -> str:
    filename = filename.replace("\\", "/").split("/")[-1]

    filename = "".join(
        char
        for char in filename
        if char.isprintable() and char not in {'"', "\r", "\n"}
    ).strip()

    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid document filename",
        )

    return filename[:255]


def expected_document_object_key(
    tenant_id: str,
    submission_id: str,
    document_id: str,
) -> str:
    return f"tenants/{tenant_id}/submissions/{submission_id}/{document_id}"


def validate_document_record(document: dict) -> None:
    """Reject malformed persisted document records."""

    valid_content_types = {item.value for item in DocumentContentType}
    valid_statuses = {item.value for item in DocumentStatus}

    filename = document.get("original_filename")
    content_type = document.get("content_type")
    size_bytes = document.get("size_bytes")
    owner_id = document.get("owner_id")
    created_at = document.get("created_at")
    document_status = document.get("status")

    if (
        not isinstance(owner_id, str)
        or not owner_id.strip()
        or not isinstance(filename, str)
        or not filename.strip()
        or len(filename) > 255
        or not isinstance(content_type, str)
        or content_type not in valid_content_types
        or type(size_bytes) is not int
        or size_bytes <= 0
        or parse_canonical_utc_timestamp(created_at) is None
        or not isinstance(document_status, str)
        or document_status not in valid_statuses
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document record is invalid",
        )

    if document_status == DocumentStatus.UPLOADED.value:
        version_id = document.get("version_id")

        if (
            not isinstance(version_id, str)
            or not version_id.strip()
            or version_id == "null"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Document record is invalid",
            )


async def get_authorized_submission_record(
    tenant_id: str,
    submission_id: str,
    membership: TenantMembership,
    submission_repository: SubmissionRepository,
) -> dict:
    if membership.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant access denied",
        )

    submission = await run_in_threadpool(
        submission_repository.get_submission,
        tenant_id,
        submission_id,
    )

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    if not isinstance(submission, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    if (
        submission.get("tenant_id") != tenant_id
        or submission.get("submission_id") != submission_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    if membership.role == TenantRole.SUBMITTER:
        if submission.get("owner_id") != membership.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Submission access denied",
            )

    elif membership.role != TenantRole.REVIEWER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Role not permitted",
        )

    return submission


async def create_document_upload(
    tenant_id: str,
    submission_id: str,
    request: DocumentUploadRequest,
    membership: TenantMembership,
    submission_repository: SubmissionRepository,
    document_repository=None,
    storage=None,
) -> DocumentUploadResponse:
    if membership.role != TenantRole.SUBMITTER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only submitters can upload documents",
        )

    submission = await get_authorized_submission_record(
        tenant_id,
        submission_id,
        membership,
        submission_repository,
    )

    if submission.get("status") != "DRAFT":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Documents can only be uploaded to draft submissions",
        )

    document_repository = document_repository or get_document_repository()
    storage = storage or get_storage_service()

    document_id = str(uuid4())
    filename = sanitize_filename(request.filename)

    object_key = expected_document_object_key(
        tenant_id,
        submission_id,
        document_id,
    )

    now = datetime.now(UTC).replace(microsecond=0)

    timestamp = format_utc_timestamp(now)

    expires_at = format_utc_timestamp(
        now + timedelta(seconds=DOCUMENT_RESERVATION_TTL_SECONDS)
    )

    upload_url_expires_at = format_utc_timestamp(
        now + timedelta(seconds=UPLOAD_URL_EXPIRY)
    )

    upload_hygiene_after = format_utc_timestamp(
        now
        + timedelta(seconds=UPLOAD_URL_EXPIRY)
        + timedelta(seconds=UPLOAD_HYGIENE_GRACE_SECONDS)
    )

    expiry_shard = get_document_expiry_shard(document_id)

    document = {
        "PK": f"TENANT#{tenant_id}#SUBMISSION#{submission_id}",
        "SK": f"DOCUMENT#{document_id}",
        "entity_type": "DOCUMENT",
        "tenant_id": tenant_id,
        "submission_id": submission_id,
        "document_id": document_id,
        "owner_id": membership.user_id,
        "original_filename": filename,
        "content_type": request.content_type.value,
        "size_bytes": request.size_bytes,
        "object_key": object_key,
        "status": DocumentStatus.PENDING_UPLOAD.value,
        "created_at": timestamp,
        "expires_at": expires_at,
        "GSI3PK": f"PENDING_UPLOAD#{expiry_shard:02d}",
        "GSI3SK": f"{expires_at}#{document_id}",
        "upload_url_expires_at": upload_url_expires_at,
        "upload_hygiene_after": upload_hygiene_after,
    }

    # Generate the presigned upload request.
    try:
        upload_request = await run_in_threadpool(
            storage.generate_upload_request,
            object_key,
            request.content_type.value,
            request.size_bytes,
        )

    except (ClientError, BotoCoreError) as exc:
        logger.exception(
            "Failed to generate document upload URL",
            extra={
                "event": "document_upload_url_generation_failed",
            },
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to prepare document upload",
        ) from exc

    # Create the document reservation in DynamoDB.
    try:
        await run_in_threadpool(
            document_repository.create_document,
            document,
        )

    except DocumentAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document already exists",
        )

    except DocumentStateConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Submission is no longer available for document uploads",
        )

    except DocumentQuotaExceededError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Submission document quota exceeded",
        )

    return DocumentUploadResponse(
        document_id=document_id,
        upload_url=upload_request["url"],
        upload_fields=upload_request["fields"],
        expires_in=UPLOAD_URL_EXPIRY,
    )


async def complete_document_upload(
    tenant_id: str,
    submission_id: str,
    document_id: str,
    membership: TenantMembership,
    submission_repository: SubmissionRepository,
    document_repository=None,
    storage=None,
) -> DocumentResponse:
    if membership.role != TenantRole.SUBMITTER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only submitters can complete uploads",
        )

    submission = await get_authorized_submission_record(
        tenant_id,
        submission_id,
        membership,
        submission_repository,
    )

    if submission.get("status") != "DRAFT":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Submission is no longer accepting uploads",
        )

    document_repository = document_repository or get_document_repository()
    storage = storage or get_storage_service()

    document = await run_in_threadpool(
        document_repository.get_document,
        tenant_id,
        submission_id,
        document_id,
    )

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if not isinstance(document, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if (
        document.get("tenant_id") != tenant_id
        or document.get("submission_id") != submission_id
        or document.get("document_id") != document_id
        or document.get("owner_id") != membership.user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    expected_key = expected_document_object_key(
        tenant_id,
        submission_id,
        document_id,
    )

    if document.get("object_key") != expected_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    validate_document_record(document)

    if document.get("status") != DocumentStatus.PENDING_UPLOAD.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document is not awaiting upload",
        )

    expires_at = parse_canonical_utc_timestamp(document.get("expires_at"))

    if expires_at is None or expires_at <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document upload reservation has expired",
        )

    upload_url_expires_at = parse_canonical_utc_timestamp(
        document.get("upload_url_expires_at")
    )

    upload_hygiene_after = parse_canonical_utc_timestamp(
        document.get("upload_hygiene_after")
    )

    if (
        upload_url_expires_at is None
        or upload_hygiene_after is None
        or upload_url_expires_at >= expires_at
        or upload_hygiene_after
        != upload_url_expires_at + timedelta(seconds=UPLOAD_HYGIENE_GRACE_SECONDS)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document upload hygiene metadata is invalid",
        )

    expiry_shard = get_document_expiry_shard(document_id)

    pending_gsi3_pk = f"PENDING_UPLOAD#{expiry_shard:02d}"
    pending_gsi3_sk = f"{document['expires_at']}#{document_id}"

    if (
        document.get("GSI3PK") != pending_gsi3_pk
        or document.get("GSI3SK") != pending_gsi3_sk
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document upload state has changed",
        )

    uploaded_gsi3_pk = f"UPLOADED#{expiry_shard:02d}"
    uploaded_gsi3_sk = f"{document['upload_hygiene_after']}#{document_id}"

    # Retrieve uploaded object metadata from S3.
    try:
        object_metadata = await run_in_threadpool(
            storage.get_object_metadata,
            document["object_key"],
        )

    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")

        if error_code in {"404", "NoSuchKey", "NotFound"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Uploaded object was not found",
            ) from exc

        logger.exception(
            "S3 document metadata verification failed",
            extra={
                "event": "document_metadata_verification_failed",
            },
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify uploaded document",
        ) from exc

    except BotoCoreError as exc:
        logger.exception(
            "S3 document metadata verification encountered an SDK error",
            extra={
                "event": "document_metadata_sdk_error",
            },
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify uploaded document",
        ) from exc

    # Validate object metadata.
    try:
        await run_in_threadpool(
            storage.validate_object_metadata,
            object_metadata,
            document["size_bytes"],
            document["content_type"],
        )

    except StorageObjectValidationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded document failed storage validation",
        )

    version_id = object_metadata.get("VersionId")

    if (
        not isinstance(version_id, str)
        or not version_id.strip()
        or version_id == "null"
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 bucket versioning is not enabled or unavailable",
        )

    # Validate the uploaded object's actual content signature.
    try:
        await run_in_threadpool(
            storage.validate_object_content,
            document["object_key"],
            version_id,
            document["content_type"],
        )

    except StorageObjectValidationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded document failed content validation",
        )

    except (ClientError, BotoCoreError) as exc:
        logger.exception(
            "S3 document content verification failed",
            extra={
                "event": "document_content_verification_failed",
            },
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify uploaded document content",
        ) from exc

    uploaded_at = get_timestamp()

    # Transition the document from PENDING_UPLOAD to UPLOADED.
    try:
        await run_in_threadpool(
            document_repository.mark_document_uploaded,
            tenant_id,
            submission_id,
            document_id,
            uploaded_at,
            version_id,
            membership.user_id,
            document["size_bytes"],
            pending_gsi3_pk,
            pending_gsi3_sk,
            uploaded_gsi3_pk,
            uploaded_gsi3_sk,
            document["upload_url_expires_at"],
            document["upload_hygiene_after"],
        )

    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    except DocumentStateConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document state has changed",
        )

    return DocumentResponse(
        document_id=document_id,
        submission_id=submission_id,
        filename=document["original_filename"],
        content_type=document["content_type"],
        size_bytes=document["size_bytes"],
        status=DocumentStatus.UPLOADED,
        created_at=document["created_at"],
    )


async def create_document_download(
    tenant_id: str,
    submission_id: str,
    document_id: str,
    membership: TenantMembership,
    submission_repository: SubmissionRepository,
    document_repository=None,
    storage=None,
) -> DocumentDownloadResponse:
    submission = await get_authorized_submission_record(
        tenant_id,
        submission_id,
        membership,
        submission_repository,
    )

    if (
        membership.role == TenantRole.REVIEWER
        and submission.get("status") not in REVIEWER_DOWNLOADABLE_SUBMISSION_STATUSES
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    document_repository = document_repository or get_document_repository()
    storage = storage or get_storage_service()

    document = await run_in_threadpool(
        document_repository.get_document,
        tenant_id,
        submission_id,
        document_id,
    )

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if not isinstance(document, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if (
        document.get("tenant_id") != tenant_id
        or document.get("submission_id") != submission_id
        or document.get("document_id") != document_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if (
        membership.role == TenantRole.SUBMITTER
        and document.get("owner_id") != membership.user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    expected_key = expected_document_object_key(
        tenant_id,
        submission_id,
        document_id,
    )

    if document.get("object_key") != expected_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    validate_document_record(document)

    if document.get("status") != DocumentStatus.UPLOADED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document is not available for download",
        )

    version_id = document.get("version_id")

    if (
        not isinstance(version_id, str)
        or not version_id.strip()
        or version_id == "null"
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Accepted document version is unavailable",
        )

    # Generate a presigned download URL for the exact accepted S3 version.
    try:
        download_url = await run_in_threadpool(
            storage.generate_download_url,
            document["object_key"],
            document["content_type"],
            document["original_filename"],
            version_id,
        )

    except (ClientError, BotoCoreError) as exc:
        logger.exception(
            "Failed to generate document download URL",
            extra={
                "event": "document_download_url_generation_failed",
            },
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to prepare document download",
        ) from exc

    return DocumentDownloadResponse(
        document_id=document_id,
        download_url=download_url,
        expires_in=DOWNLOAD_URL_EXPIRY,
    )


def _validate_document_cursor_key(
    key: object,
    tenant_id: str,
    submission_id: str,
) -> dict[str, Any]:

    if not isinstance(key, dict) or set(key) != {"PK", "SK"}:
        raise ValueError("Invalid document cursor key")

    expected_pk = f"TENANT#{tenant_id}#SUBMISSION#{submission_id}"

    pk = key["PK"]
    sk = key["SK"]

    if not isinstance(pk, str) or pk != expected_pk:
        raise ValueError("Invalid document cursor partition")

    if (
        not isinstance(sk, str)
        or not sk.startswith("DOCUMENT#")
        or not sk.removeprefix("DOCUMENT#")
    ):
        raise ValueError("Invalid document cursor sort key")

    return key


def encode_document_cursor(
    last_evaluated_key: dict[str, Any],
    membership: TenantMembership,
    submission_id: str,
) -> str:

    payload = {
        "version": 1,
        "tenant_id": membership.tenant_id,
        "submission_id": submission_id,
        "user_id": membership.user_id,
        "role": membership.role.value,
        "last_evaluated_key": _validate_document_cursor_key(
            last_evaluated_key,
            membership.tenant_id,
            submission_id,
        ),
    }

    serialized = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    return base64.urlsafe_b64encode(serialized).decode("ascii").rstrip("=")


def decode_document_cursor(
    cursor: str,
    membership: TenantMembership,
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

        payload = json.loads(decoded)

        if not isinstance(payload, dict):
            raise TypeError("Invalid cursor payload type")

        if set(payload) != {
            "version",
            "tenant_id",
            "submission_id",
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

        if payload["submission_id"] != submission_id:
            raise ValueError

        if payload["user_id"] != membership.user_id:
            raise ValueError

        if payload["role"] != membership.role.value:
            raise ValueError

        return _validate_document_cursor_key(
            payload["last_evaluated_key"],
            membership.tenant_id,
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
            detail="Invalid document pagination cursor",
        )


async def list_submission_documents(
    tenant_id: str,
    submission_id: str,
    membership: TenantMembership,
    submission_repository: SubmissionRepository,
    document_repository: DocumentRepository,
    limit: int = 20,
    cursor: str | None = None,
) -> DocumentListResponse:

    if membership.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant access denied",
        )

    if type(limit) is not int or not 1 <= limit <= 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid document listing limit",
        )

    submission = await get_authorized_submission_record(
        tenant_id,
        submission_id,
        membership,
        submission_repository,
    )

    if (
        membership.role == TenantRole.REVIEWER
        and submission.get("status") not in REVIEWER_DOWNLOADABLE_SUBMISSION_STATUSES
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    last_evaluated_key = None

    if cursor is not None:
        last_evaluated_key = decode_document_cursor(
            cursor,
            membership,
            submission_id,
        )

    result = await run_in_threadpool(
        document_repository.list_documents,
        tenant_id,
        submission_id,
        limit,
        last_evaluated_key,
    )

    if not isinstance(result, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid document repository response",
        )

    items = result.get("Items", [])

    if not isinstance(items, list):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid document repository response",
        )

    validated_items = []

    try:
        for item in items:
            if not isinstance(item, dict):
                raise TypeError("Invalid document record")

            if (
                item.get("tenant_id") != tenant_id
                or item.get("submission_id") != submission_id
                or item.get("entity_type") != "DOCUMENT"
            ):
                raise ValueError("Document scope mismatch")

            document_id = item.get("document_id")

            if (
                not isinstance(document_id, str)
                or not document_id
                or item.get("PK") != f"TENANT#{tenant_id}#SUBMISSION#{submission_id}"
                or item.get("SK") != f"DOCUMENT#{document_id}"
            ):
                raise ValueError("Document key mismatch")

            if (
                membership.role == TenantRole.SUBMITTER
                and item.get("owner_id") != membership.user_id
            ):
                raise ValueError("Document ownership mismatch")

            try:
                validate_document_record(item)
            except HTTPException as exc:
                raise ValueError("Invalid persisted document record") from exc

            validated_items.append(
                DocumentResponse(
                    document_id=document_id,
                    submission_id=submission_id,
                    filename=item["original_filename"],
                    content_type=item["content_type"],
                    size_bytes=item["size_bytes"],
                    status=item["status"],
                    created_at=item["created_at"],
                )
            )

        next_key = result.get("LastEvaluatedKey")

        if next_key is not None:
            _validate_document_cursor_key(
                next_key,
                tenant_id,
                submission_id,
            )

    except (ValueError, TypeError, KeyError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid document data",
        )

    return DocumentListResponse(
        items=validated_items,
        next_cursor=(
            encode_document_cursor(
                next_key,
                membership,
                submission_id,
            )
            if next_key
            else None
        ),
    )
