from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class DocumentStatus(str, Enum):
    PENDING_UPLOAD = "PENDING_UPLOAD"
    UPLOADED = "UPLOADED"


class DocumentContentType(str, Enum):
    PDF = "application/pdf"
    JPEG = "image/jpeg"
    PNG = "image/png"


class DocumentUploadRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    filename: str = Field(min_length=1, max_length=255)
    content_type: DocumentContentType
    size_bytes: int = Field(strict=True, gt=0, le=10 * 1024 * 1024)


class DocumentUploadResponse(BaseModel):
    document_id: str
    upload_url: str
    upload_fields: dict[str, str]
    expires_in: int


class DocumentResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    document_id: str
    submission_id: str
    filename: str
    content_type: str
    size_bytes: int
    status: DocumentStatus
    created_at: str


class DocumentDownloadResponse(BaseModel):
    document_id: str
    download_url: str
    expires_in: int


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    next_cursor: str | None = None
