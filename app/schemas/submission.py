from pydantic import BaseModel, ConfigDict, Field

from app.schemas.workflow import SubmissionStatus


class SubmissionCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class SubmissionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tenant_id: str
    submission_id: str
    title: str | None = None
    description: str | None = None
    status: SubmissionStatus
    created_at: str
    updated_at: str
    version: int = Field(ge=1)
    pending_document_count: int = Field(default=0, ge=0)
    uploaded_document_count: int = Field(default=0, ge=0)


class SubmissionListItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tenant_id: str
    submission_id: str
    title: str
    status: SubmissionStatus
    created_at: str
    updated_at: str
    version: int = Field(ge=1)
    pending_document_count: int = Field(default=0, ge=0)
    uploaded_document_count: int = Field(default=0, ge=0)


class SubmissionListResponse(BaseModel):
    items: list[SubmissionListItem]
    next_cursor: str | None = None
