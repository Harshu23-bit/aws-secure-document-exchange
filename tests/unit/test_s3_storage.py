from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.storage import (
    DOWNLOAD_URL_EXPIRY,
    MAX_DOCUMENT_SIZE,
    UPLOAD_URL_EXPIRY,
    S3StorageService,
    StorageConfigurationError,
    StorageObjectValidationError,
)

KMS_KEY_ARN = "arn:aws:kms:ap-south-1:123456789012:test-key-id"


@pytest.fixture
def s3_client():
    return MagicMock()


@pytest.fixture
def storage(s3_client):
    settings = SimpleNamespace(
        aws_region="ap-south-1",
        documents_bucket_name="cloudsec-documents-test",
        documents_kms_key_arn=KMS_KEY_ARN,
    )
    return S3StorageService(
        settings=settings,
        s3_client=s3_client,
    )


def test_storage_requires_bucket_configuration():
    settings = SimpleNamespace(
        aws_region="ap-south-1",
        documents_bucket_name=None,
        documents_kms_key_arn=KMS_KEY_ARN,
    )

    with pytest.raises(StorageConfigurationError):
        S3StorageService(settings=settings)


def test_storage_requires_kms_key_configuration():
    settings = SimpleNamespace(
        aws_region="ap-south-1",
        documents_bucket_name="cloudsec-documents-test",
        documents_kms_key_arn=None,
    )

    with pytest.raises(StorageConfigurationError):
        S3StorageService(settings=settings)


def test_generate_upload_request(storage, s3_client):
    s3_client.generate_presigned_post.return_value = {
        "url": "https://example.com",
        "fields": {"key": "test-key"},
    }

    object_key = "tenants/tenant-a/submissions/sub-1/doc-1"
    declared_size = 1024

    result = storage.generate_upload_request(
        object_key=object_key,
        content_type="application/pdf",
        size_bytes=declared_size,
    )

    assert result["url"] == "https://example.com"

    call = s3_client.generate_presigned_post.call_args.kwargs

    assert call["Bucket"] == "cloudsec-documents-test"
    assert call["Key"] == object_key
    assert call["ExpiresIn"] == UPLOAD_URL_EXPIRY

    assert call["Fields"] == {
        "Content-Type": "application/pdf",
        "x-amz-server-side-encryption": "aws:kms",
        "x-amz-server-side-encryption-aws-kms-key-id": KMS_KEY_ARN,
    }

    assert {"key": object_key} in call["Conditions"]
    assert {"Content-Type": "application/pdf"} in call["Conditions"]
    assert {"x-amz-server-side-encryption": "aws:kms"} in call["Conditions"]

    assert {"x-amz-server-side-encryption-aws-kms-key-id": KMS_KEY_ARN} in call[
        "Conditions"
    ]

    assert [
        "content-length-range",
        declared_size,
        declared_size,
    ] in call["Conditions"]


def test_upload_policy_enforces_exact_declared_size(storage, s3_client):
    storage.generate_upload_request(
        object_key="test-object",
        content_type="application/pdf",
        size_bytes=4096,
    )

    conditions = s3_client.generate_presigned_post.call_args.kwargs["Conditions"]

    size_condition = next(
        condition
        for condition in conditions
        if isinstance(condition, list) and condition[0] == "content-length-range"
    )

    assert size_condition == ["content-length-range", 4096, 4096]


@pytest.mark.parametrize(
    "content_type",
    [
        "application/x-msdownload",
        "text/html",
        "application/octet-stream",
    ],
)
def test_upload_rejects_unsupported_content_type(storage, content_type):
    with pytest.raises(ValueError):
        storage.generate_upload_request(
            object_key="test-object",
            content_type=content_type,
            size_bytes=1024,
        )


@pytest.mark.parametrize(
    "size_bytes",
    [
        0,
        -1,
        MAX_DOCUMENT_SIZE + 1,
    ],
)
def test_upload_rejects_invalid_size(storage, size_bytes):
    with pytest.raises(ValueError):
        storage.generate_upload_request(
            object_key="test-object",
            content_type="application/pdf",
            size_bytes=size_bytes,
        )


def test_validate_object_metadata_accepts_valid_metadata(storage):
    metadata = {
        "ContentLength": 1024,
        "ContentType": "application/pdf",
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": KMS_KEY_ARN,
        "VersionId": "version-123",
    }

    storage.validate_object_metadata(
        metadata,
        expected_size=1024,
        expected_content_type="application/pdf",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("ContentLength", 2048),
        ("ContentType", "image/png"),
        ("ServerSideEncryption", "AES256"),
        ("SSEKMSKeyId", "arn:aws:kms:ap-south-1:123456789012:other-key"),
    ],
)
def test_validate_object_metadata_rejects_invalid_metadata(
    storage,
    field,
    value,
):
    metadata = {
        "ContentLength": 1024,
        "ContentType": "application/pdf",
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": KMS_KEY_ARN,
        "VersionId": "version-123",
    }

    metadata[field] = value

    with pytest.raises(StorageObjectValidationError):
        storage.validate_object_metadata(
            metadata,
            expected_size=1024,
            expected_content_type="application/pdf",
        )


@pytest.mark.parametrize(
    "field",
    [
        "ContentLength",
        "ContentType",
        "ServerSideEncryption",
        "SSEKMSKeyId",
    ],
)
def test_validate_object_metadata_rejects_missing_metadata(
    storage,
    field,
):
    metadata = {
        "ContentLength": 1024,
        "ContentType": "application/pdf",
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": KMS_KEY_ARN,
        "VersionId": "version-123",
    }

    del metadata[field]

    with pytest.raises(StorageObjectValidationError):
        storage.validate_object_metadata(
            metadata,
            expected_size=1024,
            expected_content_type="application/pdf",
        )


def test_generate_download_url(storage, s3_client):
    s3_client.generate_presigned_url.return_value = "https://example.com/download"

    result = storage.generate_download_url(
        object_key="tenants/tenant-a/submissions/sub-1/doc-1",
        content_type="application/pdf",
        filename="invoice.pdf",
        version_id="version-123",
    )

    assert result == "https://example.com/download"

    call = s3_client.generate_presigned_url.call_args.kwargs

    assert call["ClientMethod"] == "get_object"
    assert call["Params"]["Bucket"] == "cloudsec-documents-test"
    assert call["Params"]["Key"] == "tenants/tenant-a/submissions/sub-1/doc-1"
    assert call["Params"]["VersionId"] == "version-123"
    assert call["ExpiresIn"] == DOWNLOAD_URL_EXPIRY


@pytest.mark.parametrize(
    "version_id",
    [
        None,
        "",
        "null",
    ],
)
def test_download_rejects_missing_or_null_version_id(storage, version_id):
    with pytest.raises(ValueError):
        storage.generate_download_url(
            object_key="test-object",
            content_type="application/pdf",
            filename="invoice.pdf",
            version_id=version_id,
        )


def test_download_filename_is_sanitized(storage, s3_client):
    s3_client.generate_presigned_url.return_value = "https://example.com"

    storage.generate_download_url(
        object_key="test-object",
        content_type="application/pdf",
        filename='../../invoice"\r\n.pdf',
        version_id="version-123",
    )

    call = s3_client.generate_presigned_url.call_args.kwargs

    disposition = call["Params"]["ResponseContentDisposition"]

    assert "\r" not in disposition
    assert "\n" not in disposition
    assert "/" not in disposition


def test_download_rejects_unsupported_content_type(storage):
    with pytest.raises(ValueError):
        storage.generate_download_url(
            object_key="test-object",
            content_type="text/html",
            filename="test.html",
            version_id="version-123",
        )


def test_get_object_metadata_calls_head_object(storage, s3_client):
    expected_metadata = {
        "ContentLength": 1024,
        "ContentType": "application/pdf",
        "VersionId": "version-123",
    }

    s3_client.head_object.return_value = expected_metadata

    result = storage.get_object_metadata("test-object")

    assert result == expected_metadata

    s3_client.head_object.assert_called_once_with(
        Bucket="cloudsec-documents-test",
        Key="test-object",
    )


@pytest.mark.parametrize(
    "content_type,content",
    [
        ("application/pdf", b"%PDF-1.7\nexample"),
        ("image/jpeg", b"\xff\xd8\xff\xe0example"),
        ("image/png", b"\x89PNG\r\n\x1a\nexample"),
    ],
)
def test_validate_object_content_accepts_valid_signatures(
    storage,
    s3_client,
    content_type,
    content,
):
    body = BytesIO(content)
    s3_client.get_object.return_value = {"Body": body}

    storage.validate_object_content(
        "tenants/tenant-a/submissions/sub-1/doc-1",
        "version-123",
        content_type,
    )

    s3_client.get_object.assert_called_once_with(
        Bucket="cloudsec-documents-test",
        Key="tenants/tenant-a/submissions/sub-1/doc-1",
        VersionId="version-123",
        Range="bytes=0-1023",
    )

    assert body.closed


@pytest.mark.parametrize(
    "content",
    [
        b"\\x00" * 20 + b"%PDF-1.7\\nexample",
        b"<html>not a PDF</html>%PDF-1.7\\nexample",
    ],
)
def test_validate_object_content_rejects_pdf_header_after_leading_bytes(
    storage,
    s3_client,
    content,
):
    s3_client.get_object.return_value = {
        "Body": BytesIO(content),
    }

    with pytest.raises(StorageObjectValidationError):
        storage.validate_object_content(
            "test-object",
            "version-123",
            "application/pdf",
        )


@pytest.mark.parametrize(
    "content_type,content",
    [
        ("application/pdf", b"<html>not a PDF"),
        ("image/jpeg", b"not a JPEG"),
        ("image/png", b"not a PNG"),
    ],
)
def test_validate_object_content_rejects_mismatched_signatures(
    storage,
    s3_client,
    content_type,
    content,
):
    s3_client.get_object.return_value = {
        "Body": BytesIO(content),
    }

    with pytest.raises(StorageObjectValidationError):
        storage.validate_object_content(
            "test-object",
            "version-123",
            content_type,
        )


@pytest.mark.parametrize(
    "version_id",
    [None, "", "null", "   ", 123],
)
def test_validate_object_content_rejects_invalid_version(
    storage,
    s3_client,
    version_id,
):
    with pytest.raises(StorageObjectValidationError):
        storage.validate_object_content(
            "test-object",
            version_id,
            "application/pdf",
        )

    s3_client.get_object.assert_not_called()


def test_validate_object_content_rejects_empty_content(
    storage,
    s3_client,
):
    s3_client.get_object.return_value = {
        "Body": BytesIO(b""),
    }

    with pytest.raises(StorageObjectValidationError):
        storage.validate_object_content(
            "test-object",
            "version-123",
            "application/pdf",
        )


def test_validate_object_content_rejects_unsupported_type(
    storage,
    s3_client,
):
    with pytest.raises(StorageObjectValidationError):
        storage.validate_object_content(
            "test-object",
            "version-123",
            "text/html",
        )

    s3_client.get_object.assert_not_called()


@pytest.mark.parametrize(
    "content_length",
    [True, 1024.0, "1024", None],
)
def test_validate_metadata_rejects_non_integer_content_length(
    storage,
    content_length,
):
    metadata = {
        "ContentLength": content_length,
        "ContentType": "application/pdf",
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": KMS_KEY_ARN,
    }

    with pytest.raises(StorageObjectValidationError):
        storage.validate_object_metadata(
            metadata,
            expected_size=1024,
            expected_content_type="application/pdf",
        )
