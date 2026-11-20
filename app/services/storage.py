from urllib.parse import quote

import boto3
from botocore.config import Config

from app.core.config import get_settings

MAX_DOCUMENT_SIZE = 10 * 1024 * 1024
UPLOAD_URL_EXPIRY = 300
DOWNLOAD_URL_EXPIRY = 300
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
}

FILE_SIGNATURES = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}

CONTENT_VALIDATION_RANGE = "bytes=0-1023"
CONTENT_VALIDATION_MAX_BYTES = 1024


class StorageConfigurationError(Exception):
    pass


class StorageObjectValidationError(Exception):
    pass


class S3StorageService:
    def __init__(self, settings=None, s3_client=None):
        settings = settings or get_settings()

        if not settings.documents_bucket_name:
            raise StorageConfigurationError("Document storage bucket is not configured")

        if not settings.documents_kms_key_arn:
            raise StorageConfigurationError(
                "Document storage KMS key ARN is not configured"
            )

        self.bucket_name = settings.documents_bucket_name
        self.kms_key_arn = settings.documents_kms_key_arn

        self.client = s3_client or boto3.client(
            "s3",
            region_name=settings.aws_region,
            config=Config(signature_version="s3v4"),
        )

    def generate_upload_request(
        self,
        object_key: str,
        content_type: str,
        size_bytes: int,
    ) -> dict:
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise ValueError("Unsupported document content type")

        if not 1 <= size_bytes <= MAX_DOCUMENT_SIZE:
            raise ValueError("Document size is outside the permitted range")

        fields = {
            "Content-Type": content_type,
            "x-amz-server-side-encryption": "aws:kms",
            "x-amz-server-side-encryption-aws-kms-key-id": self.kms_key_arn,
        }

        conditions = [
            {"Content-Type": content_type},
            {"key": object_key},
            {"x-amz-server-side-encryption": "aws:kms"},
            {"x-amz-server-side-encryption-aws-kms-key-id": (self.kms_key_arn)},
            ["content-length-range", size_bytes, size_bytes],
        ]

        return self.client.generate_presigned_post(
            Bucket=self.bucket_name,
            Key=object_key,
            Fields=fields,
            Conditions=conditions,
            ExpiresIn=UPLOAD_URL_EXPIRY,
        )

    def validate_object_metadata(
        self,
        metadata: dict,
        expected_size: int,
        expected_content_type: str,
    ) -> None:
        if not isinstance(metadata, dict):
            raise StorageObjectValidationError("Invalid S3 object metadata")

        content_length = metadata.get("ContentLength")

        if type(content_length) is not int or content_length != expected_size:
            raise StorageObjectValidationError(
                "Uploaded object size does not match the declared size"
            )

        if metadata.get("ContentType") != expected_content_type:
            raise StorageObjectValidationError(
                "Uploaded object content type does not match the declaration"
            )

        if metadata.get("ServerSideEncryption") != "aws:kms":
            raise StorageObjectValidationError(
                "Uploaded object does not use the required encryption"
            )

        if metadata.get("SSEKMSKeyId") != self.kms_key_arn:
            raise StorageObjectValidationError(
                "Uploaded object uses an unexpected KMS key"
            )

    def validate_object_content(
        self,
        object_key: str,
        version_id: str,
        expected_content_type: str,
    ) -> None:
        if (
            not isinstance(version_id, str)
            or not version_id.strip()
            or version_id == "null"
        ):
            raise StorageObjectValidationError("A valid S3 object version is required")

        signatures = FILE_SIGNATURES.get(expected_content_type)

        if not signatures:
            raise StorageObjectValidationError("Unsupported document content type")

        response = self.client.get_object(
            Bucket=self.bucket_name,
            Key=object_key,
            VersionId=version_id,
            Range=CONTENT_VALIDATION_RANGE,
        )

        body = response.get("Body")

        if body is None or not callable(getattr(body, "read", None)):
            raise StorageObjectValidationError(
                "Unable to read uploaded document content"
            )

        try:
            content = body.read(CONTENT_VALIDATION_MAX_BYTES)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()

        if not isinstance(content, bytes) or not content:
            raise StorageObjectValidationError(
                "Uploaded document is empty or unreadable"
            )

        if expected_content_type == "application/pdf":
            valid_signature = content.startswith(b"%PDF-")
        else:
            valid_signature = any(
                content.startswith(signature) for signature in signatures
            )

        if not valid_signature:
            raise StorageObjectValidationError(
                "Uploaded document content does not match its declared type"
            )

    def generate_download_url(
        self,
        object_key: str,
        content_type: str,
        filename: str,
        version_id: str,
    ) -> str:
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise ValueError("Unsupported document content type")

        if (
            not isinstance(version_id, str)
            or not version_id.strip()
            or version_id == "null"
        ):
            raise ValueError("A valid S3 object version is required")

        safe_filename = filename.replace("\\", "_").replace("/", "_")

        safe_filename = "".join(
            char
            for char in safe_filename
            if char.isprintable() and char not in {'"', "\r", "\n"}
        ).strip()

        if not safe_filename:
            safe_filename = "document"

        ascii_filename = (
            safe_filename.encode("ascii", "ignore").decode("ascii") or "document"
        )

        disposition = (
            f'attachment; filename="{ascii_filename}"; '
            f"filename*=UTF-8''{quote(safe_filename, safe='')}"
        )

        return self.client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": self.bucket_name,
                "Key": object_key,
                "VersionId": version_id,
                "ResponseContentType": content_type,
                "ResponseContentDisposition": disposition,
            },
            ExpiresIn=DOWNLOAD_URL_EXPIRY,
        )

    def get_object_metadata(self, object_key: str) -> dict:
        return self.client.head_object(
            Bucket=self.bucket_name,
            Key=object_key,
        )
